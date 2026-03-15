"""
ST generator for module TYPES based on the resolved model.

This emitter generates:
- ET_Module_<modclass>_value   (only when value is enum)
- ST_Module_<modclass>

Important design rule:
- This file must NOT inspect the raw / normalized JSON structure anymore.
- All parsing, checks and decisions must already have been done by the resolve layer.
- This emitter only consumes the resolved model and formats ST output.

Current sources:
- codegen.resolve.types.ResolvedModuleClasses
- codegen.resolve.types.ResolvedModuleClass
- codegen.resolve.types.ResolvedModuleVariable

Example:
    For a resolved class "mf", this emitter generates:

        TYPE ST_Module_mf EXTENDS SECOP.ST_BaseModuleDrivable :
        STRUCT
         /// Current value of the module
         lrValue: LREAL;
         lrValueMin: LREAL ;
         ...
        END_STRUCT
        END_TYPE
"""

from __future__ import annotations

from typing import List

from codegen.resolve.types import (
    ResolvedModuleClass,
    ResolvedModuleClasses,
    ResolvedModuleVariable,
)


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


def _emit_enum_type(resolved_class: ResolvedModuleClass) -> str:
    """
    Emit enum TYPE for a resolved module class whose value is enum.

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
    if not resolved_class.value.is_enum or not resolved_class.value.members:
        raise ValueError(
            f"_emit_enum_type called for non-enum class: {resolved_class.name}"
        )

    lines: list[str] = []
    lines.append("{attribute 'qualified_only' := ''}")
    lines.append("{attribute 'strict' := ''}")
    lines.append(f"TYPE ET_Module_{resolved_class.name}_value :")
    lines.append("(")

    items = list(resolved_class.value.members.items())
    for idx, (member_name, member_value) in enumerate(items):
        comma = "," if idx < len(items) - 1 else ""
        lines.append(f" {member_name} := {member_value}{comma}")

    lines.append(");")
    lines.append("END_TYPE")

    return "\n".join(lines) + "\n\n"


def _find_var(module_variables: List[ResolvedModuleVariable], name: str) -> ResolvedModuleVariable | None:
    """
    Find a resolved module variable by exact name.

    Returns None if not found.
    """
    for var in module_variables:
        if var.name == name:
            return var
    return None


def _emit_value_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit the "value" block of ST_Module_<class> using resolved module variables.

    Expected order:
    - Value
    - ValueMin / ValueMax (if any)
    - ValueOutOfRangeL / H (if any)

    This relies on the resolved model and does not inspect JSON.
    """
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
        lines.append(f" {value_min.name}: {value_min.plc_type} ;")
        lines.append(f" {value_max.name}: {value_max.plc_type} ;")

    value_oor_l = _find_var(vars_, f"{value_prefix}ValueOutOfRangeL")
    value_oor_h = _find_var(vars_, f"{value_prefix}ValueOutOfRangeH")
    if value_oor_l and value_oor_h:
        lines.append(f" {value_oor_l.name}: {value_oor_l.plc_type} ;")
        lines.append(f" {value_oor_h.name}: {value_oor_h.plc_type} ;")

    return lines


def _emit_target_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit the "target" block of ST_Module_<class> using resolved module variables.

    Expected order:
    - Target
    - TargetMin / TargetMax (if any)
    - TargetLimitsMin / TargetLimitsMax (if any)
    - TargetChangeNewVal
    - TargetDriveTolerance (if any)

    If the class has no target (Readable), returns an empty list.
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
        lines.append(f" {target_min.name}: {target_min.plc_type} ;")
        lines.append(f" {target_max.name}: {target_max.plc_type} ;")

    target_limits_min = _find_var(vars_, f"{value_prefix}TargetLimitsMin")
    target_limits_max = _find_var(vars_, f"{value_prefix}TargetLimitsMax")
    if target_limits_min and target_limits_max:
        lines.append(f" {target_limits_min.name}: {target_limits_min.plc_type} ;")
        lines.append(f" {target_limits_max.name}: {target_limits_max.plc_type} ;")

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
    Emit xClearErrors if the resolved class includes it.
    """
    lines: list[str] = []

    var = _find_var(resolved_class.module_variables, "xClearErrors")
    if var:
        lines.append(" /// Try to clear error state command")
        lines.append(f" {var.name}: {var.plc_type};")

    return lines


def _emit_custom_parameters_block(resolved_class: ResolvedModuleClass) -> list[str]:
    """
    Emit custom parameters in the order they were resolved.

    """
    lines: list[str] = []

    # Build a quick map from variable name to resolved module variable
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


def _emit_struct_type(resolved_class: ResolvedModuleClass) -> str:
    """
    Emit one ST_Module_<modclass> TYPE from one resolved module class.
    """
    extends = _extends_for_interface(resolved_class.interface_class)

    lines: list[str] = []
    lines.append(f"TYPE ST_Module_{resolved_class.name} EXTENDS {extends} :")
    lines.append("STRUCT")

    # Ordered blocks
    lines.extend(_emit_value_block(resolved_class))
    lines.extend(_emit_target_block(resolved_class))
    lines.extend(_emit_clear_errors_block(resolved_class))
    lines.extend(_emit_custom_parameters_block(resolved_class))

    lines.append("END_STRUCT")
    lines.append("END_TYPE")

    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def emit_module_types(resolved: ResolvedModuleClasses) -> str:
    """
    Emit all enum types and ST_Module_<class> types from the resolved model.

    Output order:
    - classes in insertion order of resolved.classes
    - enum TYPE first (only when needed)
    - then ST_Module_<class>

    This order is convenient because struct declarations may reference enum types.
    """
    out: list[str] = []

    for resolved_class in resolved.classes.values():
        if resolved_class.value.is_enum:
            out.append(_emit_enum_type(resolved_class))

    for resolved_class in resolved.classes.values():
        out.append(_emit_struct_type(resolved_class))

    return "".join(out)