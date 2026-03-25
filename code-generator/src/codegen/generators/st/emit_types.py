"""
ST generators for module type declarations based on the resolved model.

This file generates independent type files inside the output folder:
- ET_Module_<modclass>_value.st                (only when value is enum)
- ET_Module_<modclass>_<customparameter>.st    (for customised enum parameters)
- ST_Module_<modclass>.st

Important design rule
---------------------
This generator must not inspect raw or normalized JSON directly.
All parsing, checks and decisions must already have been done by the resolve
layer.

Current sources
---------------
- codegen.resolve.types.ResolvedModuleClasses
- codegen.resolve.types.ResolvedModuleClass
- codegen.resolve.types.ResolvedModuleVariable
- codegen.resolve.types.ResolvedCustomParameter

Output layout
-------------
Files are written under:
    <out_st_dir>/modules/

This matches the existing strategy already used for:
    FB_Module_<class>.st
"""

from __future__ import annotations

from pathlib import Path

from codegen.resolve.types import (
    ResolvedCustomCommand,
    ResolvedCustomParameter,
    ResolvedModuleClass,
    ResolvedModuleClasses,
    ResolvedModuleVariable,
)
from codegen.tasklist import TaskList


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _extends_for_interface(interface_class: str) -> str:
    """
    Map resolved interface class to the corresponding SECOP base struct.

    Example:
        Readable -> SECOP.ST_BaseModuleReadable
        Writable -> SECOP.ST_BaseModuleWritable
        Drivable -> SECOP.ST_BaseModuleDrivable
    """
    if interface_class == "Readable":
        return "SECOP.ST_BaseModuleReadable"
    if interface_class == "Writable":
        return "SECOP.ST_BaseModuleWritable"
    if interface_class == "Drivable":
        return "SECOP.ST_BaseModuleDrivable"
    raise ValueError(f"Unknown interface class: {interface_class}")


def _find_var(
    module_variables: list[ResolvedModuleVariable],
    name: str,
) -> ResolvedModuleVariable | None:
    """
    Find a resolved module variable by exact name.

    Returns None if not found.
    """
    for var in module_variables:
        if var.name == name:
            return var
    return None


def _enum_type_filename(enum_type_name: str) -> str:
    """
    Return the output filename for one enum DUT.

    Example:
        ET_Module_mf_value -> ET_Module_mf_value.st
    """
    return f"{enum_type_name}.st"


# ---------------------------------------------------------------------------
# Enum DUT emitters
# ---------------------------------------------------------------------------

def _emit_enum_type(type_name: str, members: dict[str, int]) -> str:
    """
    Emit one enum DUT.

    Example:
        {attribute 'qualified_only' := ''}
        {attribute 'strict' := ''}
        TYPE ET_Module_heatswitch_value :
        (
         off := 0,
         on := 1
        );
        END_TYPE
    """
    if not members:
        raise ValueError(f"_emit_enum_type called with empty members for {type_name}")

    lines: list[str] = []
    lines.append("{attribute 'qualified_only' := ''}")
    lines.append("{attribute 'strict' := ''}")
    lines.append(f"TYPE {type_name} :")
    lines.append("(")

    items = list(members.items())
    for idx, (member_name, member_value) in enumerate(items):
        comma = "," if idx < len(items) - 1 else ""
        lines.append(f" {member_name} := {member_value}{comma}")

    lines.append(");")
    lines.append("END_TYPE")

    return "\n".join(lines) + "\n"


def _emit_value_enum_type(resolved_class: ResolvedModuleClass) -> tuple[str, str] | None:
    """
    Emit the enum DUT for accessibles.value when value is enum.

    Returns:
        (filename, source)
    or:
        None when value is not enum
    """
    if not resolved_class.value.is_enum or not resolved_class.value.members:
        return None

    type_name = f"ET_Module_{resolved_class.name}_value"
    source = _emit_enum_type(type_name, resolved_class.value.members)
    return _enum_type_filename(type_name), source


def _emit_custom_parameter_enum_types(
    resolved_class: ResolvedModuleClass,
) -> list[tuple[str, str]]:
    """
    Emit enum DUT files for customised parameters of enum type.

    Returns a list of:
        (filename, source)
    """
    out: list[tuple[str, str]] = []

    for cp in resolved_class.custom_parameters:
        if not cp.is_enum or not cp.members:
            continue

        type_name = cp.plc_type
        source = _emit_enum_type(type_name, cp.members)
        out.append((_enum_type_filename(type_name), source))

    return out


# ---------------------------------------------------------------------------
# ST_Module_<class> building blocks
# ---------------------------------------------------------------------------

def _emit_value_block(resolved_class: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit the "value" block of ST_Module_<class> using resolved module variables.

    Expected order:
    - Value
    - ValueMin / ValueMax (if configured)
    - ValueOutOfRangeL / H (if configured)

    For array/tuple value types, a task comment is emitted instead of a typed
    variable declaration because the internal structure is open-ended.
    """
    # Array/tuple: no automatic variable declaration possible.
    if resolved_class.value.is_array or resolved_class.value.is_tuple:
        secop_type = "array" if resolved_class.value.is_array else "tuple"
        return [
            " " + tasklist.make_st_comment(
                plc_path=f"ST_Module_{resolved_class.name}.value",
                message=f"declare value variable(s) — type '{secop_type}' has open-ended structure; define appropriate PLC variable(s) and implement mapping manually",
            )
        ]

    lines: list[str] = []

    value_prefix = resolved_class.value.var_prefix
    vars_ = resolved_class.module_variables

    value_var = _find_var(vars_, f"{value_prefix}Value")
    if not value_var:
        raise ValueError(
            f"Resolved class '{resolved_class.name}' is missing main value variable"
        )

    lines.append(" /// Current value of the module")
    lines.append(f" {value_var.name}: {value_var.plc_type};")

    value_min = _find_var(vars_, f"{value_prefix}ValueMin")
    value_max = _find_var(vars_, f"{value_prefix}ValueMax")
    if value_min and value_max:
        lines.append(f" {value_min.name}: {value_min.plc_type};")
        lines.append(f" {value_max.name}: {value_max.plc_type};")

    value_oor_l = _find_var(vars_, f"{value_prefix}ValueOutOfRangeL")
    value_oor_h = _find_var(vars_, f"{value_prefix}ValueOutOfRangeH")
    if value_oor_l and value_oor_h:
        lines.append(f" {value_oor_l.name}: {value_oor_l.plc_type};")
        lines.append(f" {value_oor_h.name}: {value_oor_h.plc_type};")

    return lines


def _emit_target_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit the "target" block of ST_Module_<class> using resolved module variables.

    Expected order:
    - Target
    - TargetMin / TargetMax (if configured)
    - TargetLimitsMin / TargetLimitsMax (if configured)
    - TargetChangeNewVal (Drivable only)
    - TargetDriveTolerance (if configured)
    """
    if resolved_class.target is None:
        return []

    lines: list[str] = []
    value_prefix = resolved_class.value.var_prefix
    vars_ = resolved_class.module_variables

    target_var = _find_var(vars_, f"{value_prefix}Target")
    if not target_var:
        raise ValueError(
            f"Resolved class '{resolved_class.name}' has target but is missing main target variable"
        )

    lines.append(" /// Target value of the module")
    lines.append(f" {target_var.name}: {target_var.plc_type};")

    target_min = _find_var(vars_, f"{value_prefix}TargetMin")
    target_max = _find_var(vars_, f"{value_prefix}TargetMax")
    if target_min and target_max:
        lines.append(f" {target_min.name}: {target_min.plc_type};")
        lines.append(f" {target_max.name}: {target_max.plc_type};")

    target_limits_min = _find_var(vars_, f"{value_prefix}TargetLimitsMin")
    target_limits_max = _find_var(vars_, f"{value_prefix}TargetLimitsMax")
    if target_limits_min and target_limits_max:
        lines.append(f" {target_limits_min.name}: {target_limits_min.plc_type};")
        lines.append(f" {target_limits_max.name}: {target_limits_max.plc_type};")

    target_change = _find_var(vars_, f"{value_prefix}TargetChangeNewVal")
    if target_change:
        lines.append(' /// Target change - New value sent by a client through the "change" request')
        lines.append(f" {target_change.name}: {target_change.plc_type};")

    target_tol = _find_var(vars_, f"{value_prefix}TargetDriveTolerance")
    if target_tol:
        lines.append(" /// Target drive - Setpoint reached absolute tolerance")
        lines.append(f" {target_tol.name}: {target_tol.plc_type};")

    return lines


def _emit_clear_errors_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit xClearErrors if the resolved class includes the standard clear_errors
    command.
    """
    lines: list[str] = []

    var = _find_var(resolved_class.module_variables, "xClearErrors")
    if var:
        lines.append(" /// Try to clear error state command")
        lines.append(f" {var.name}: {var.plc_type};")

    return lines


def _emit_custom_parameters_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit customised parameters in resolved order.
    """
    lines: list[str] = []

    var_map = {v.name: v for v in resolved_class.module_variables}

    for cp in resolved_class.custom_parameters:
        var = var_map.get(cp.plc_var_name)
        if not var:
            raise ValueError(
                f"Resolved custom parameter '{cp.secop_name}' is missing module variable '{cp.plc_var_name}'"
            )

        comment = cp.description.strip() or f"Custom parameter {cp.secop_name}"
        lines.append(f" /// {comment}")
        lines.append(f" {var.name}: {var.plc_type};")

    return lines


def _emit_custom_commands_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit customised commands as BOOL variables in ST_Module_<class>.

    This mirrors the existing handling of clear_errors: the variable expresses
    the command request at PLC data level, while the actual behaviour is handled
    elsewhere or left for manual implementation.
    """
    lines: list[str] = []

    var_map = {v.name: v for v in resolved_class.module_variables}

    for cc in resolved_class.custom_commands:
        var = var_map.get(cc.plc_var_name)
        if not var:
            raise ValueError(
                f"Resolved custom command '{cc.secop_name}' is missing module variable '{cc.plc_var_name}'"
            )

        comment = cc.description.strip() or f"Custom command {cc.secop_name}"
        lines.append(f" /// {comment}")
        lines.append(f" {var.name}: {var.plc_type};")

    return lines


def _emit_struct_type(resolved_class: ResolvedModuleClass, tasklist: TaskList) -> str:
    """
    Emit one ST_Module_<modclass> TYPE from one resolved module class.
    """
    extends = _extends_for_interface(resolved_class.interface_class)

    lines: list[str] = []
    lines.append(f"TYPE ST_Module_{resolved_class.name} EXTENDS {extends} :")
    lines.append("STRUCT")

    lines.extend(_emit_value_block(resolved_class, tasklist))
    lines.extend(_emit_target_block(resolved_class))
    lines.extend(_emit_clear_errors_block(resolved_class))
    lines.extend(_emit_custom_parameters_block(resolved_class))
    lines.extend(_emit_custom_commands_block(resolved_class))

    lines.append("END_STRUCT")
    lines.append("END_TYPE")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public file emitters
# ---------------------------------------------------------------------------

def emit_module_type_files(
    resolved_class: ResolvedModuleClass,
    tasklist: TaskList,
) -> list[tuple[str, str]]:
    """
    Build all type files required for one resolved module class.

    Returned items:
        (filename, source)

    Output files may include:
    - ET_Module_<class>_value.st
    - ET_Module_<class>_<customparameter>.st
    - ST_Module_<class>.st
    """
    out: list[tuple[str, str]] = []

    value_enum = _emit_value_enum_type(resolved_class)
    if value_enum is not None:
        out.append(value_enum)

    out.extend(_emit_custom_parameter_enum_types(resolved_class))

    st_filename = f"ST_Module_{resolved_class.name}.st"
    st_source = _emit_struct_type(resolved_class, tasklist)
    out.append((st_filename, st_source))

    return out


def emit_all_module_types(
    classes: dict[str, ResolvedModuleClass],
    out_dir: Path,
    tasklist: TaskList,
) -> None:
    """
    Generate all type files for all resolved module classes.

    Files are written to:
        <out_dir>/modules/
    """
    modules_dir = out_dir / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    for resolved_class in classes.values():
        for filename, source in emit_module_type_files(resolved_class, tasklist):
            path = modules_dir / filename
            path.write_text(source, encoding="utf-8")


# ---------------------------------------------------------------------------
# Legacy compatibility helper
# ---------------------------------------------------------------------------

def emit_module_types(resolved: ResolvedModuleClasses) -> str:
    """
    Legacy helper kept temporarily for compatibility.

    It concatenates all generated type sources into one string in memory.
    The current preferred strategy is emit_all_module_types(...), which writes
    one file per type into st/modules/.

    This function may be removed later once no caller relies on it.
    """
    chunks: list[str] = []

    for resolved_class in resolved.classes.values():
        value_enum = _emit_value_enum_type(resolved_class)
        if value_enum is not None:
            chunks.append(value_enum[1] + "\n")

        for _filename, source in _emit_custom_parameter_enum_types(resolved_class):
            chunks.append(source + "\n")

        chunks.append(_emit_struct_type(resolved_class) + "\n")

    return "".join(chunks)