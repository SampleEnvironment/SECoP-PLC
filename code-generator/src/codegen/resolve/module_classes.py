"""
Resolve module classes for PLC code generation.

This module performs the "semantic resolution" step between:
- normalized SECoP config (plain dict / Pydantic output)
and
- ST / PLCopenXML generators

Main responsibilities:
1) Group equal modules into one "module class"
   Example:
       tc1 + tc2 -> module class "tc"
2) Resolve PLC-relevant information for each module class:
   - interface class
   - value PLC type
   - enum members (if value is enum)
   - target capabilities
   - clear_errors existence
   - custom parameters
   - final list of module-specific PLC variables
3) Return a clean resolved model that generators can consume without
   re-parsing the original JSON structure.

Important design principle:
- Parsing / checks / decisions happen here once.
- Generators should not re-implement this logic.

Current supported value types:
- double
- int
- string
- enum

Future extensions:
- array
- other SECoP datainfo types if needed later
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List
import copy

from codegen.resolve.types import (
    ResolvedCustomParameter,
    ResolvedModuleClass,
    ResolvedModuleClasses,
    ResolvedModuleVariable,
    ResolvedTarget,
    ResolvedValue,
)
from codegen.utils.codesys_naming import (
    custom_param_var_name,
    make_var_name,
    prefix_for_scalar_type,
    secop_type_to_iec,
)

# ---------------------------------------------------------------------------
# Grouping helpers reused from previous IR layer
# ---------------------------------------------------------------------------

"""
1) Group modules into "module classes" when their SECoP structure is identical.
2) Ignore x-plc entirely EXCEPT x-plc.value.outofrange_min/max (these affect class equality).
3) Pick a deterministic module-class name:
   - if class has one module => class name is module name
   - if class has multiple modules => use common name heuristic, fallback to moduleclassN

Example grouping:
    modules: tc1, tc2 (identical) -> class name "tc"
    modules: mf (unique) -> class name "mf"

Signature rule:
- remove 'x-plc' completely
- but include outofrange config under synthetic key "__xplc_outofrange__"
So if module A has outofrange and module B does not, they won't group.
"""

@dataclass(frozen=True)
class ModuleClassInfo:
    """Information about a module class derived from grouping."""
    modclass: str
    interface_class: str  # "Readable" | "Writable" | "Drivable"
    # you can extend this later (value type, etc.) but not needed yet


def _get_interface_class(module_dict: Dict[str, Any]) -> str:
    """
    Decide module interface class from normalized config.

    In your normalized config: "interface_classes": ["Drivable"] etc.
    We assume there is exactly one, which matches your examples.

    Raises ValueError if missing/invalid.
    """
    ic = module_dict.get("interface_classes")
    if not ic or not isinstance(ic, list):
        raise ValueError("module.interface_classes missing or invalid")
    if len(ic) != 1:
        raise ValueError(f"Expected exactly 1 interface class, got: {ic}")
    if ic[0] not in ("Readable", "Writable", "Drivable"):
        raise ValueError(f"Unknown interface class: {ic[0]}")
    return ic[0]


def module_signature(module_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create the module signature used to decide class equality.

    Rules:
    - deep-copy module
    - remove full 'x-plc'
    - include only x-plc.value.outofrange_min/max under synthetic key
      '__xplc_outofrange__'

    This makes equality checks explicit and easy to reason about.
    """
    m = copy.deepcopy(module_dict)

    # Extract outofrange (if any)
    out = None
    xplc = m.get("x-plc")
    if isinstance(xplc, dict):
        v = xplc.get("value")
        if isinstance(v, dict):
            omin = v.get("outofrange_min")
            omax = v.get("outofrange_max")
            # include only if BOTH exist (min/max). If one is None it still counts as "not configured".
            if omin is not None and omax is not None:
                out = {"outofrange_min": omin, "outofrange_max": omax}

    # Remove full x-plc from signature
    if "x-plc" in m:
        del m["x-plc"]

    if out is not None:
        m["__xplc_outofrange__"] = out

    return m


def _longest_common_prefix(a: str, b: str) -> str:
    i = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        i += 1
    return a[:i]


def _longest_common_suffix(a: str, b: str) -> str:
    ra, rb = a[::-1], b[::-1]
    pref = _longest_common_prefix(ra, rb)
    return pref[::-1]


def _common_name_heuristic(names: List[str]) -> Optional[str]:
    """
    Heuristic requested by user.

    Examples:
      tempabcdef1x + temp567 -> "temp" (common prefix)
      abcdef1x + tempdef1x   -> "def1x" (common suffix)
      abc + temp             -> None (fallback to moduleclassN)

    Implementation:
    - if common prefix len >= 2 -> use it
    - else if common suffix len >= 2 -> use it
    - else None
    """
    if not names:
        return None
    if len(names) == 1:
        return names[0]

    cp = names[0]
    cs = names[0]
    for n in names[1:]:
        cp = _longest_common_prefix(cp, n)
        cs = _longest_common_suffix(cs, n)

    cp = cp.strip("_-")
    cs = cs.strip("_-")

    if len(cp) >= 2:
        return cp
    if len(cs) >= 2:
        return cs
    return None


def group_modules_into_classes(modules: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, ModuleClassInfo]]:
    """
    Group modules into module classes.

    Returns:
        module_to_class: dict[module_name] = modclass_name
        classes: dict[modclass_name] = ModuleClassInfo

    Steps:
    1) build signatures
    2) group by deep-equality of signature
    3) name each group:
       - if size==1 => name is module name
       - else => common heuristic, else moduleclassN
    4) ensure uniqueness of modclass names

    Deterministic:
    - process modules in sorted order
    """
    # Build groups: list of (signature, [module_names])
    groups: list[tuple[dict[str, Any], list[str]]] = []

    for modname in sorted(modules.keys()):
        sig = module_signature(modules[modname])

        matched = False
        for existing_sig, names in groups:
            if sig == existing_sig:
                names.append(modname)
                matched = True
                break

        if not matched:
            groups.append((sig, [modname]))

    # Name groups
    used_names: set[str] = set()
    module_to_class: dict[str, str] = {}
    classes: dict[str, ModuleClassInfo] = {}

    moduleclass_counter = 1

    for sig, names in groups:
        if len(names) == 1:
            base_name = names[0]
        else:
            candidate = _common_name_heuristic(names)
            if candidate:
                base_name = candidate
            else:
                base_name = f"moduleclass{moduleclass_counter}"
                moduleclass_counter += 1

        # enforce uniqueness
        modclass = base_name
        suffix = 2
        while modclass in used_names:
            modclass = f"{base_name}_{suffix}"
            suffix += 1

        used_names.add(modclass)

        # interface class comes from any module in the group (they are identical by signature,
        # so interface_classes must match; if it does not, rules should have caught it earlier).
        ic = _get_interface_class(modules[names[0]])

        classes[modclass] = ModuleClassInfo(modclass=modclass, interface_class=ic)

        for n in names:
            module_to_class[n] = modclass

    return module_to_class, classes

# ---------------------------------------------------------------------------
# Small helpers to read normalized config safely
# ---------------------------------------------------------------------------

def _get_accessible(module: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """
    Return accessibles.<name> if it exists and is a dict, else None.

    Example:
        module["accessibles"]["value"] -> {...}
    """
    acc = module.get("accessibles") or {}
    value = acc.get(name)
    return value if isinstance(value, dict) else None


def _get_datainfo(accessible: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Return accessible.datainfo if it exists and is a dict, else None.
    """
    di = accessible.get("datainfo")
    return di if isinstance(di, dict) else None


def _get_interface_class(module: Dict[str, Any]) -> str:
    """
    Extract the module interface class from normalized config.

    Expected shape:
        "interface_classes": ["Readable"] / ["Writable"] / ["Drivable"]

    We keep this strict because the rest of the code generator relies on it.

    Raises:
        ValueError if the config is malformed.
    """
    interface_classes = module.get("interface_classes")
    if not isinstance(interface_classes, list) or len(interface_classes) != 1:
        raise ValueError(
            f"Expected exactly one interface class, got: {interface_classes}"
        )

    ic = interface_classes[0]
    if ic not in ("Readable", "Writable", "Drivable"):
        raise ValueError(f"Unsupported interface class: {ic}")

    return ic


def _is_writable(interface_class: str) -> bool:
    """
    Writable is explicit for Writable, and implicit for Drivable.
    """
    return interface_class in ("Writable", "Drivable")


def _is_drivable(interface_class: str) -> bool:
    """
    Drivable is only explicit for Drivable.
    """
    return interface_class == "Drivable"


# ---------------------------------------------------------------------------
# Resolve value block
# ---------------------------------------------------------------------------

def _resolve_value(modclass: str, module: Dict[str, Any]) -> ResolvedValue:
    """
    Resolve the PLC-oriented representation of accessibles.value.

    Rules:
    - double -> LREAL / lr
    - int    -> DINT / di
    - string -> STRING(n) / s
    - enum   -> ET_Module_<modclass>_value / et

    Flags:
    - has_min_max:
        * True/False for numeric values
        * None for non-numeric values
    - has_out_of_range:
        * True/False for numeric values
        * None for non-numeric values
    - members:
        * dict for enum values
        * None otherwise

    Raises:
        ValueError if value is missing or unsupported.
    """
    acc_value = _get_accessible(module, "value")
    if not acc_value:
        raise ValueError("Module is missing accessibles.value")

    di = _get_datainfo(acc_value)
    if not di:
        raise ValueError("accessibles.value is missing datainfo")

    secop_type = (di.get("type") or "").lower()
    if not secop_type:
        raise ValueError("accessibles.value.datainfo.type is missing")

    # -------------------------
    # Numeric values
    # -------------------------
    if secop_type in ("double", "int"):
        iec_type = secop_type_to_iec(secop_type, maxchars=None)
        var_prefix = prefix_for_scalar_type(iec_type)

        # In numeric values these flags conceptually apply, so we use True/False (not None).
        has_min_max = (di.get("min") is not None and di.get("max") is not None)

        xplc = module.get("x-plc") or {}
        xplc_value = xplc.get("value") if isinstance(xplc, dict) else None
        if isinstance(xplc_value, dict):
            has_out_of_range = (
                xplc_value.get("outofrange_min") is not None
                and xplc_value.get("outofrange_max") is not None
            )
        else:
            has_out_of_range = False

        return ResolvedValue(
            plc_type=iec_type,
            var_prefix=var_prefix,
            is_numeric=True,
            is_enum=False,
            is_string=False,
            has_min_max=has_min_max,
            has_out_of_range=has_out_of_range,
            members=None,
        )

    # -------------------------
    # String values
    # -------------------------
    if secop_type == "string":
        maxchars = di.get("maxchars")
        if maxchars is None:
            raise ValueError("STRING value requires datainfo.maxchars")

        return ResolvedValue(
            plc_type=f"STRING({int(maxchars)})",
            var_prefix=prefix_for_scalar_type("STRING"),
            is_numeric=False,
            is_enum=False,
            is_string=True,
            has_min_max=None,
            has_out_of_range=None,
            members=None,
        )

    # -------------------------
    # Enum values
    # -------------------------
    if secop_type == "enum":
        members = di.get("members")
        if not isinstance(members, dict) or not members:
            raise ValueError("ENUM value requires datainfo.members dict")

        # Keep enum member names exactly as they appear in JSON.
        enum_members = {str(k): int(v) for k, v in members.items()}

        return ResolvedValue(
            plc_type=f"ET_Module_{modclass}_value",
            var_prefix=prefix_for_scalar_type("ENUM"),
            is_numeric=False,
            is_enum=True,
            is_string=False,
            has_min_max=None,
            has_out_of_range=None,
            members=enum_members,
        )

    # -------------------------
    # Future types
    # -------------------------
    if secop_type == "array":
        raise ValueError(
            "SECoP array values are not resolved yet in module_classes.py"
        )

    raise ValueError(f"Unsupported value.datainfo.type for code generation: {secop_type}")


# ---------------------------------------------------------------------------
# Resolve target block
# ---------------------------------------------------------------------------

def _resolve_target(interface_class: str, value: ResolvedValue, module: Dict[str, Any]) -> Optional[ResolvedTarget]:
    """
    Resolve target-related behaviour.

    Rules:
    - Readable modules do not have target -> return None
    - Writable / Drivable modules have target -> resolve flags
    - has_drive_tolerance is True only for Drivable modules with numeric value type

    We intentionally do not repeat PLC type here because target uses the same PLC type as value.
    """
    if not _is_writable(interface_class):
        return None

    acc_target = _get_accessible(module, "target")
    if not acc_target:
        raise ValueError(
            f"Module with interface class '{interface_class}' is missing accessibles.target"
        )

    di_target = _get_datainfo(acc_target)
    if not di_target:
        raise ValueError("accessibles.target is missing datainfo")

    target_secop_type = (di_target.get("type") or "").lower()
    value_plc_type = value.plc_type

    # We want target to follow value type semantically.
    # Example:
    #   if value is LREAL, target should also come from SECoP 'double'
    #
    # We do not overcomplicate this yet. We do a simple consistency check for supported types.
    if value.is_enum and target_secop_type != "enum":
        raise ValueError("Target type must match enum value type")
    if value.is_numeric:
        expected = "double" if value_plc_type == "LREAL" else "int"
        if target_secop_type != expected:
            raise ValueError("Target type must match numeric value type")
    if (not value.is_enum) and (not value.is_numeric) and value_plc_type.startswith("STRING("):
        if target_secop_type != "string":
            raise ValueError("Target type must match string value type")

    has_min_max: Optional[bool]
    has_limits: Optional[bool]

    # Target exists, so these fields conceptually apply.
    # For numeric targets: True/False makes sense.
    # For enum/string: min/max and limits do not conceptually apply -> None.
    if value.is_numeric:
        has_min_max = (
            di_target.get("min") is not None and di_target.get("max") is not None
        )

        acc_target_limits = _get_accessible(module, "target_limits")
        if acc_target_limits:
            di_tl = _get_datainfo(acc_target_limits)
            if not di_tl:
                raise ValueError("accessibles.target_limits is missing datainfo")

            has_limits = (
                di_tl.get("min") is not None and di_tl.get("max") is not None
            )
        else:
            has_limits = False

    else:
        has_min_max = None
        has_limits = None

    # Drive tolerance only conceptually applies to Drivable modules with numeric values.
    # In all other cases we use None (not applicable), not False.
    if _is_drivable(interface_class) and value.is_numeric:
        has_drive_tolerance: Optional[bool] = True
    else:
        has_drive_tolerance = None

    return ResolvedTarget(
        has_min_max=has_min_max,
        has_limits=has_limits,
        has_drive_tolerance=has_drive_tolerance,
    )


# ---------------------------------------------------------------------------
# Resolve clear_errors + custom parameters
# ---------------------------------------------------------------------------

def _resolve_has_clear_errors_command(module: Dict[str, Any]) -> bool:
    """
    A module has clear_errors support if accessibles.clear_errors exists in config.

    We do NOT care here whether x-plc.clear_errors.cmd_stmt is empty or not.
    That is an implementation detail handled elsewhere (warning/tasklist/default logic).
    """
    return _get_accessible(module, "clear_errors") is not None


def _resolve_custom_parameters(module: Dict[str, Any]) -> list[ResolvedCustomParameter]:
    """
    Resolve all custom parameters (SECoP names starting with '_').

    Current supported custom parameter types:
    - string
    - double
    - int
    - enum
    """
    result: list[ResolvedCustomParameter] = []

    accessibles = module.get("accessibles") or {}
    if not isinstance(accessibles, dict):
        return result

    for acc_name, acc in accessibles.items():
        if not isinstance(acc_name, str) or not acc_name.startswith("_"):
            continue
        if not isinstance(acc, dict):
            continue

        di = _get_datainfo(acc)
        if not di:
            raise ValueError(f"Custom parameter {acc_name} is missing datainfo")

        secop_type = (di.get("type") or "").lower()
        if not secop_type:
            raise ValueError(f"Custom parameter {acc_name} is missing datainfo.type")

        description = str(acc.get("description") or "")

        if secop_type == "string":
            maxchars = di.get("maxchars")
            if maxchars is None:
                raise ValueError(
                    f"Custom parameter {acc_name} of type string requires maxchars"
                )

            result.append(
                ResolvedCustomParameter(
                    secop_name=acc_name,
                    description=description,
                    plc_var_name=custom_param_var_name("string", acc_name),
                    plc_type=f"STRING({int(maxchars)})",
                    var_prefix=prefix_for_scalar_type("STRING"),
                    is_numeric=False,
                    is_enum=False,
                    is_string=True,
                    members=None,
                )
            )
            continue

        if secop_type in ("double", "int"):
            iec_type = secop_type_to_iec(secop_type, maxchars=None)
            var_prefix = prefix_for_scalar_type(iec_type)
            stem = acc_name[1:]
            if not stem:
                raise ValueError("Custom parameter name cannot be just '_'")
            nice = stem[0].upper() + stem[1:]

            result.append(
                ResolvedCustomParameter(
                    secop_name=acc_name,
                    description=description,
                    plc_var_name=f"{var_prefix}_{nice}",
                    plc_type=iec_type,
                    var_prefix=var_prefix,
                    is_numeric=True,
                    is_enum=False,
                    is_string=False,
                    members=None,
                )
            )
            continue

        if secop_type == "enum":
            members = di.get("members")
            if not isinstance(members, dict) or not members:
                raise ValueError(f"Custom enum parameter {acc_name} requires members")

            enum_members = {str(k): int(v) for k, v in members.items()}
            stem = acc_name[1:]
            if not stem:
                raise ValueError("Custom parameter name cannot be just '_'")
            nice = stem[0].upper() + stem[1:]

            result.append(
                ResolvedCustomParameter(
                    secop_name=acc_name,
                    description=description,
                    plc_var_name=f"et_{nice}",
                    plc_type=f"ET_ModuleCustom_{nice}",
                    var_prefix="et",
                    is_numeric=False,
                    is_enum=True,
                    is_string=False,
                    members=enum_members,
                )
            )
            continue

        raise ValueError(
            f"Unsupported custom parameter type for {acc_name}: {secop_type}"
        )

    return result


def _resolve_custom_commands(module: Dict[str, Any]) -> list[ResolvedCustomCommand]:
    """
    Resolve custom commands other than 'stop' and 'clear_errors'.

    These commands are allowed, but automatic implementation is not provided yet.
    We still resolve them so that:
    - TYPES can declare x_<Command>
    - FBs can expose them
    - future tasklist can reference them
    """
    result: list[ResolvedCustomCommand] = []

    accessibles = module.get("accessibles") or {}
    if not isinstance(accessibles, dict):
        return result

    for acc_name, acc in accessibles.items():
        if acc_name in ("stop", "clear_errors"):
            continue
        if not isinstance(acc, dict):
            continue

        di = _get_datainfo(acc)
        if not di:
            continue

        if (di.get("type") or "").lower() != "command":
            continue

        nice = acc_name[:1].upper() + acc_name[1:]
        result.append(
            ResolvedCustomCommand(
                secop_name=acc_name,
                description=str(acc.get("description") or ""),
                plc_var_name=f"x_{nice}",
            )
        )

    return result



def _resolve_pollinterval_changeable(module: Dict[str, Any]) -> bool:
    """
    Resolve whether pollinterval is changeable.

    Rule:
    - pollinterval exists on all your current modules
    - it is changeable when readonly == False
    """
    acc = _get_accessible(module, "pollinterval")
    if not acc:
        return False
    return not bool(acc.get("readonly", False))


# ---------------------------------------------------------------------------
# Build the final list of module-specific variables
# ---------------------------------------------------------------------------

def _build_module_variables(
    interface_class: str,
    value: ResolvedValue,
    target: Optional[ResolvedTarget],
    has_clear_errors_command: bool,
    custom_parameters: list[ResolvedCustomParameter],
    custom_commands: list[ResolvedCustomCommand],
) -> list[ResolvedModuleVariable]:
    """
    Build the final ordered list of module-specific PLC variables for one module class.

    Order policy:
    - value block first
    - target block second
    - clear_errors command after target
    - custom parameters
    - custom commands last
    """
    vars_out: list[ResolvedModuleVariable] = []

    # Value
    vars_out.append(
        ResolvedModuleVariable(
            name=make_var_name(value.var_prefix, "Value"),
            plc_type=value.plc_type,
            category="value",
        )
    )

    if value.has_min_max:
        vars_out.append(
            ResolvedModuleVariable(
                name=make_var_name(value.var_prefix, "ValueMin"),
                plc_type=value.plc_type,
                category="value",
            )
        )
        vars_out.append(
            ResolvedModuleVariable(
                name=make_var_name(value.var_prefix, "ValueMax"),
                plc_type=value.plc_type,
                category="value",
            )
        )

    if value.has_out_of_range:
        vars_out.append(
            ResolvedModuleVariable(
                name=make_var_name(value.var_prefix, "ValueOutOfRangeL"),
                plc_type=value.plc_type,
                category="value",
            )
        )
        vars_out.append(
            ResolvedModuleVariable(
                name=make_var_name(value.var_prefix, "ValueOutOfRangeH"),
                plc_type=value.plc_type,
                category="value",
            )
        )

    # Target
    if target is not None:
        vars_out.append(
            ResolvedModuleVariable(
                name=make_var_name(value.var_prefix, "Target"),
                plc_type=value.plc_type,
                category="target",
            )
        )

        if target.has_min_max:
            vars_out.append(
                ResolvedModuleVariable(
                    name=make_var_name(value.var_prefix, "TargetMin"),
                    plc_type=value.plc_type,
                    category="target",
                )
            )
            vars_out.append(
                ResolvedModuleVariable(
                    name=make_var_name(value.var_prefix, "TargetMax"),
                    plc_type=value.plc_type,
                    category="target",
                )
            )

        if target.has_limits:
            vars_out.append(
                ResolvedModuleVariable(
                    name=make_var_name(value.var_prefix, "TargetLimitsMin"),
                    plc_type=value.plc_type,
                    category="target",
                )
            )
            vars_out.append(
                ResolvedModuleVariable(
                    name=make_var_name(value.var_prefix, "TargetLimitsMax"),
                    plc_type=value.plc_type,
                    category="target",
                )
            )

        # Only Drivable modules need TargetChangeNewVal
        if interface_class == "Drivable":
            vars_out.append(
                ResolvedModuleVariable(
                    name=make_var_name(value.var_prefix, "TargetChangeNewVal"),
                    plc_type=value.plc_type,
                    category="target",
                )
            )

        if target.has_drive_tolerance:
            vars_out.append(
                ResolvedModuleVariable(
                    name=make_var_name(value.var_prefix, "TargetDriveTolerance"),
                    plc_type=value.plc_type,
                    category="target",
                )
            )

    # Clear errors command
    if has_clear_errors_command:
        vars_out.append(
            ResolvedModuleVariable(
                name="xClearErrors",
                plc_type="BOOL",
                category="command",
            )
        )

    # Custom parameters
    for cp in custom_parameters:
        vars_out.append(
            ResolvedModuleVariable(
                name=cp.plc_var_name,
                plc_type=cp.plc_type,
                category="custom",
            )
        )

    # Custom commands
    for cc in custom_commands:
        vars_out.append(
            ResolvedModuleVariable(
                name=cc.plc_var_name,
                plc_type="BOOL",
                category="command",
            )
        )

    return vars_out


# ---------------------------------------------------------------------------
# Resolve one module class
# ---------------------------------------------------------------------------

def _resolve_one_module_class(modclass: str, module: Dict[str, Any]) -> ResolvedModuleClass:
    """
    Resolve one module class from one representative module.

    Assumption:
    - all modules inside the same class are structurally identical for the parts
      that matter to PLC code generation (that was ensured by grouping logic)
    """
    interface_class = _get_interface_class(module)
    value = _resolve_value(modclass=modclass, module=module)
    target = _resolve_target(interface_class=interface_class, value=value, module=module)
    has_clear_errors_command = _resolve_has_clear_errors_command(module)
    pollinterval_changeable = _resolve_pollinterval_changeable(module)
    custom_parameters = _resolve_custom_parameters(module)
    custom_commands = _resolve_custom_commands(module)
    module_variables = _build_module_variables(
        interface_class=interface_class,
        value=value,
        target=target,
        has_clear_errors_command=has_clear_errors_command,
        custom_parameters=custom_parameters,
        custom_commands=custom_commands,
    )

    return ResolvedModuleClass(
        name=modclass,
        interface_class=interface_class,
        value=value,
        target=target,
        has_clear_errors_command=has_clear_errors_command,
        pollinterval_changeable=pollinterval_changeable,
        custom_parameters=custom_parameters,
        custom_commands=custom_commands,
        module_variables=module_variables,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def resolve_module_classes(normalized_cfg: Dict[str, Any]) -> ResolvedModuleClasses:
    """
    Resolve all module classes from normalized config.

    Input:
        normalized_cfg = cfg.model_dump(by_alias=True)

    Output:
        ResolvedModuleClasses(
            module_to_class={...},
            classes={...}
        )

    Processing steps:
    1) group actual modules into module classes
    2) pick one representative module per class
    3) resolve each class once
    4) return the final resolved model

    Example:
        >>> resolved = resolve_module_classes(normalized_cfg)
        >>> resolved.module_to_class["tc1"]
        'tc'
        >>> resolved.classes["tc"].interface_class
        'Readable'
    """
    modules = normalized_cfg.get("modules") or {}
    if not isinstance(modules, dict):
        raise ValueError("normalized_cfg.modules must be a dict")

    # Reuse the grouping logic already implemented.
    # We may later move this fully into resolve/, but for now this avoids changing too much at once.
    module_to_class, _raw_classes = group_modules_into_classes(modules)

    # Pick one representative module per class.
    # We preserve module order from normalized config (no alphabetical sorting).
    example_module_by_class: dict[str, str] = {}
    for modname in modules.keys():
        modclass = module_to_class[modname]
        example_module_by_class.setdefault(modclass, modname)

    resolved_classes: dict[str, ResolvedModuleClass] = {}
    for modclass, example_modname in example_module_by_class.items():
        resolved_classes[modclass] = _resolve_one_module_class(
            modclass=modclass,
            module=modules[example_modname],
        )

    return ResolvedModuleClasses(
        module_to_class=module_to_class,
        classes=resolved_classes,
    )