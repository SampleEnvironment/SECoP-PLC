"""
Resolve module classes for PLC code generation.

This module performs the semantic resolution step between:
- normalized SECoP config (plain dict / Pydantic output),
and
- code generators (Structured Text now, PLCopenXML later).

Main responsibilities
---------------------
1) group equal real modules into one module class
2) resolve PLC-relevant information for each module class:
   - interface class
   - value PLC type
   - enum members (if value is enum)
   - target capabilities
   - clear_errors existence
   - custom parameters
   - custom commands
   - final ordered list of module-specific PLC variables
3) return a clean resolved model that generators can consume without
   re-parsing the original JSON structure

Important design principle
--------------------------
Parsing, interpretation and design decisions happen here once.
Emitters should not re-implement this logic.

Current supported value/custom-parameter types
----------------------------------------------
- double
- int
- string
- enum

Future extensions may add further SECoP datatypes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import copy

from codegen.resolve.types import (
    ResolvedCustomCommand,
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
# Grouping helpers
# ---------------------------------------------------------------------------

"""
Grouping policy
---------------
1) Group real modules into module classes when their SECoP structure is equal.
2) Ignore x-plc entirely EXCEPT x-plc.value.outofrange_min/max, because those
   fields affect the generated class-level variable set.
3) Pick a deterministic module-class name:
   - if class has one module => class name is module name
   - if class has multiple modules => use the common-name heuristic, otherwise
     fallback to moduleclassN

Signature rule
--------------
- remove the whole 'x-plc' block,
- but include x-plc.value.outofrange_min/max under a synthetic key
  '__xplc_outofrange__'

This ensures that modules differing only in x-plc out-of-range configuration do
not collapse into the same module class.
"""


@dataclass(frozen=True)
class ModuleClassInfo:
    """
    Lightweight information derived from grouping before full resolution.
    """
    modclass: str
    interface_class: str


def _get_interface_class(module_dict: dict[str, Any]) -> str:
    """
    Extract and validate the module interface class from normalized config.

    Expected shape:
        "interface_classes": ["Readable"]
        "interface_classes": ["Writable"]
        "interface_classes": ["Drivable"]

    This remains strict because the rest of the code generator depends on the
    simplified one-class-per-module policy.
    """
    interface_classes = module_dict.get("interface_classes")
    if not isinstance(interface_classes, list) or len(interface_classes) != 1:
        raise ValueError(
            f"Expected exactly one interface class, got: {interface_classes}"
        )

    ic = interface_classes[0]
    if ic not in ("Readable", "Writable", "Drivable"):
        raise ValueError(f"Unsupported interface class: {ic}")

    return ic


def module_signature(module_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Create the module signature used to decide class equality.

    Rules:
    - deep-copy the module dict
    - remove full 'x-plc'
    - include only x-plc.value.outofrange_min/max under synthetic key
      '__xplc_outofrange__' if both are configured

    This makes equality checks explicit and easy to reason about.
    """
    m = copy.deepcopy(module_dict)

    out = None
    xplc = m.get("x-plc")
    if isinstance(xplc, dict):
        v = xplc.get("value")
        if isinstance(v, dict):
            omin = v.get("outofrange_min")
            omax = v.get("outofrange_max")
            if omin is not None and omax is not None:
                out = {"outofrange_min": omin, "outofrange_max": omax}

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


def _common_name_heuristic(names: list[str]) -> Optional[str]:
    """
    Heuristic for naming a shared module class.

    Examples:
      tempabcdef1x + temp567 -> "temp"  (common prefix)
      abcdef1x + tempdef1x   -> "def1x" (common suffix)
      abc + temp             -> None    (fallback to moduleclassN)

    Policy:
    - if common prefix length >= 2 -> use it
    - else if common suffix length >= 2 -> use it
    - else return None
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


def group_modules_into_classes(
    modules: dict[str, dict[str, Any]]
) -> tuple[dict[str, str], dict[str, ModuleClassInfo]]:
    """
    Group real modules into module classes.

    Returns:
        module_to_class: dict[module_name] = modclass_name
        classes: dict[modclass_name] = ModuleClassInfo

    Steps:
    1) build signatures
    2) group by deep equality of signature
    3) name each group
    4) ensure uniqueness of generated class names

    Determinism:
    - modules are processed in sorted order for grouping
    """
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

        modclass = base_name
        suffix = 2
        while modclass in used_names:
            modclass = f"{base_name}_{suffix}"
            suffix += 1

        used_names.add(modclass)

        ic = _get_interface_class(modules[names[0]])
        classes[modclass] = ModuleClassInfo(modclass=modclass, interface_class=ic)

        for n in names:
            module_to_class[n] = modclass

    return module_to_class, classes


# ---------------------------------------------------------------------------
# Small helpers to read normalized config safely
# ---------------------------------------------------------------------------

def _get_accessible(module: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
    """
    Return accessibles.<name> if it exists and is a dict, else None.
    """
    acc = module.get("accessibles") or {}
    value = acc.get(name)
    return value if isinstance(value, dict) else None


def _get_datainfo(accessible: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Return accessible.datainfo if it exists and is a dict, else None.
    """
    di = accessible.get("datainfo")
    return di if isinstance(di, dict) else None


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

def _resolve_value(modclass: str, module: dict[str, Any]) -> ResolvedValue:
    """
    Resolve the PLC-oriented representation of accessibles.value.

    Structural tri-state policy:
    - numeric values:
        has_min_max:
            True  if min/max configured
            False if concept applies but min/max missing
            None  never used here
        has_out_of_range:
            True  if x-plc out-of-range configured
            False if concept applies but fields missing
            None  never used here
    - string / enum values:
        has_min_max = None
        has_out_of_range = None
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

    # Numeric values
    if secop_type in ("double", "int"):
        iec_type = secop_type_to_iec(secop_type, maxchars=None)
        var_prefix = prefix_for_scalar_type(iec_type)

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
            is_array=False,
            is_tuple=False,
            has_min_max=has_min_max,
            has_out_of_range=has_out_of_range,
            members=None,
        )

    # String values
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
            is_array=False,
            is_tuple=False,
            has_min_max=None,
            has_out_of_range=None,
            members=None,
        )

    # Enum values
    if secop_type == "enum":
        members = di.get("members")
        if not isinstance(members, dict) or not members:
            raise ValueError("ENUM value requires datainfo.members dict")

        enum_members = {str(k): int(v) for k, v in members.items()}

        return ResolvedValue(
            plc_type=f"ET_Module_{modclass}_value",
            var_prefix=prefix_for_scalar_type("ENUM"),
            is_numeric=False,
            is_enum=True,
            is_string=False,
            is_array=False,
            is_tuple=False,
            has_min_max=None,
            has_out_of_range=None,
            members=enum_members,
        )

    # Array and tuple value types are accepted by the generator but their
    # internal structure is open-ended. Automatic PLC mapping cannot be produced.
    # A placeholder resolved value is returned; generators will emit task markers.
    if secop_type in ("array", "tuple"):
        return ResolvedValue(
            plc_type=f"(*TODO: {secop_type} value — manual implementation required*)",
            var_prefix="x",
            is_numeric=False,
            is_enum=False,
            is_string=False,
            is_array=(secop_type == "array"),
            is_tuple=(secop_type == "tuple"),
            has_min_max=None,
            has_out_of_range=None,
            members=None,
        )

    raise ValueError(
        f"Unsupported value.datainfo.type for code generation: {secop_type}"
    )


# ---------------------------------------------------------------------------
# Resolve target block
# ---------------------------------------------------------------------------

def _resolve_target(
    interface_class: str,
    value: ResolvedValue,
    module: dict[str, Any]
) -> Optional[ResolvedTarget]:
    """
    Resolve target-related structural behaviour.

    Tri-state policy:
    - numeric target min/max:
        True  -> applies and configured
        False -> applies but not configured
        None  -> does not apply conceptually
    - target_limits:
        same policy
    - drive tolerance:
        True  -> Drivable numeric target and configured
        False -> Drivable numeric target but not configured
        None  -> does not apply conceptually
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

    if value.is_enum and target_secop_type != "enum":
        raise ValueError("Target type must match enum value type")

    if value.is_numeric:
        expected = "double" if value_plc_type == "LREAL" else "int"
        if target_secop_type != expected:
            raise ValueError("Target type must match numeric value type")

    if value.is_string:
        if target_secop_type != "string":
            raise ValueError("Target type must match string value type")

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
            # conceptually applicable for numeric targets, but not configured
            has_limits = False
    else:
        has_min_max = None
        has_limits = None

    if _is_drivable(interface_class) and value.is_numeric:
        xplc = module.get("x-plc") or {}
        xplc_target = xplc.get("target") if isinstance(xplc, dict) else None
        if isinstance(xplc_target, dict):
            has_drive_tolerance = xplc_target.get("reach_abs_tolerance") is not None
        else:
            has_drive_tolerance = False
    else:
        has_drive_tolerance = None

    return ResolvedTarget(
        has_min_max=has_min_max,
        has_limits=has_limits,
        has_drive_tolerance=has_drive_tolerance,
    )


# ---------------------------------------------------------------------------
# Resolve clear_errors + custom parameters + custom commands
# ---------------------------------------------------------------------------

def _resolve_has_clear_errors_command(module: dict[str, Any]) -> bool:
    """
    A module has clear_errors support if accessibles.clear_errors exists.

    This function only resolves existence of the standard SECoP command, not the
    completeness of x-plc.clear_errors.
    """
    return _get_accessible(module, "clear_errors") is not None


def _custom_enum_type_name(modclass: str, secop_name: str) -> str:
    """
    Build the enum DUT name for a customised parameter of enum type.

    Example:
        modclass='tc', secop_name='_sensor'
        -> ET_Module_tc__sensor
    """
    return f"ET_Module_{modclass}_{secop_name}"


def _resolve_custom_parameters(
    modclass: str,
    module: dict[str, Any]
) -> list[ResolvedCustomParameter]:
    """
    Resolve all customised parameters (SECoP names starting with '_').

    Supported current custom-parameter types:
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

        if secop_type == "command":
            continue

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
                    plc_type=_custom_enum_type_name(modclass, acc_name),
                    var_prefix="et",
                    is_numeric=False,
                    is_enum=True,
                    is_string=False,
                    members=enum_members,
                )
            )
            continue

        # Array and tuple custom parameters: accepted but require manual implementation.
        if secop_type in ("array", "tuple"):
            stem = acc_name[1:] or acc_name
            nice = stem[0].upper() + stem[1:]

            result.append(
                ResolvedCustomParameter(
                    secop_name=acc_name,
                    description=description,
                    plc_var_name=f"x_{nice}",
                    plc_type=f"(*TODO: {secop_type} — manual implementation required*)",
                    var_prefix="x",
                    is_numeric=False,
                    is_enum=False,
                    is_string=False,
                    is_array=(secop_type == "array"),
                    is_tuple=(secop_type == "tuple"),
                    members=None,
                )
            )
            continue

        raise ValueError(
            f"Unsupported custom parameter type for {acc_name}: {secop_type}"
        )

    return result


def _resolve_custom_commands(module: dict[str, Any]) -> list[ResolvedCustomCommand]:
    """
    Resolve customised commands other than the standard stop and clear_errors.

    These commands are allowed, but automatic implementation is not generated
    yet. We still resolve them so that:
    - ST types can declare the corresponding PLC variables
    - FB interfaces can expose them
    - later TODO/task-list generation can reference them
    """
    result: list[ResolvedCustomCommand] = []

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
            continue

        if (di.get("type") or "").lower() != "command":
            continue

        stem = acc_name[1:]
        if not stem:
            raise ValueError("Custom command name cannot be just '_'")

        nice = stem[:1].upper() + stem[1:]

        result.append(
            ResolvedCustomCommand(
                secop_name=acc_name,
                description=str(acc.get("description") or ""),
                plc_var_name=f"x_{nice}",
            )
        )

    return result


def _resolve_pollinterval_changeable(module: dict[str, Any]) -> bool:
    """
    Resolve whether pollinterval is changeable.

    Current project policy:
    - pollinterval exists on current modules
    - it is changeable when readonly == False
    """
    acc = _get_accessible(module, "pollinterval")
    if not acc:
        return False
    return not bool(acc.get("readonly", False))


# ---------------------------------------------------------------------------
# Build final module-specific PLC variables
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
    Build the final ordered list of module-specific PLC variables for one module
    class.

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

    # Standard clear_errors command
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

def _resolve_one_module_class(
    modclass: str,
    module: dict[str, Any]
) -> ResolvedModuleClass:
    """
    Resolve one module class from one representative real module.

    Assumption:
    all real modules inside the same class are structurally identical for the
    parts that matter to PLC code generation.
    """
    interface_class = _get_interface_class(module)
    value = _resolve_value(modclass=modclass, module=module)
    target = _resolve_target(
        interface_class=interface_class,
        value=value,
        module=module,
    )
    has_clear_errors_command = _resolve_has_clear_errors_command(module)
    pollinterval_changeable = _resolve_pollinterval_changeable(module)
    custom_parameters = _resolve_custom_parameters(modclass=modclass, module=module)
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

def resolve_module_classes(normalized_cfg: dict[str, Any]) -> ResolvedModuleClasses:
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
    1) group real modules into module classes
    2) pick one representative real module per class
    3) resolve each class once
    4) return the final resolved model

    Module order note:
    - grouping itself uses sorted names for deterministic grouping
    - representative selection preserves the original normalized-config order
    """
    modules = normalized_cfg.get("modules") or {}
    if not isinstance(modules, dict):
        raise ValueError("normalized_cfg.modules must be a dict")

    module_to_class, _raw_classes = group_modules_into_classes(modules)

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