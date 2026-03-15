"""
ST generator for PRG SecopInit.

This PRG performs:
- version warning
- assignment of FB_SecopProcessModules to the library interface
- SEC node initialization
- per-module initialization

Input:
- resolved model produced by codegen.resolve.real_modules.resolve_real_modules

Design notes:
- This emitter only formats ST.
- All decisions about what applies to each module should already have been resolved.
"""

from __future__ import annotations

from typing import List

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _interface_class_literal(interface_class: str) -> str:
    """
    Map interface class to SECOP.ET_BaseClass literal.
    """
    if interface_class == "Readable":
        return "SECOP.ET_BaseClass.readable"
    if interface_class == "Writable":
        return "SECOP.ET_BaseClass.writable"
    if interface_class == "Drivable":
        return "SECOP.ET_BaseClass.drivable"
    raise ValueError(f"Unsupported interface class: {interface_class}")


def _bool_literal(value: bool) -> str:
    """
    Convert Python bool to ST BOOL literal.
    """
    return "TRUE" if value else "FALSE"


def _secop_gvl_module_prefix(module_name: str) -> str:
    """
    Build the GVL prefix for one module.

    Example:
        mf -> GVL_SecNode.G_st_mf
    """
    return f"GVL_SecNode.G_st_{module_name}"


def _format_st_scalar(value: float | int | str) -> str:
    """
    Format a scalar for ST assignment.

    Notes:
    - Strings are single-quoted
    - Numbers are emitted as-is
    """
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return str(value)


# ---------------------------------------------------------------------------
# Fixed header
# ---------------------------------------------------------------------------


def _emit_fixed_header() -> List[str]:
    """
    Emit the fixed first block of SecopInit.
    """
    lines: List[str] = []

    lines.append("PROGRAM SecopInit")
    lines.append("")
    lines.append("// Warning - SECoP library version newer than supported by the code generator")
    lines.append("{IF hasconstantvalue(GVL_SecNode.xCodeGenNotUpToDate, TRUE, =)}")
    lines.append("{warning 'SECOP library is newer than supported by the code generator.'}")
    lines.append("{END_IF}")
    lines.append("")
    lines.append("// Assign FB_SecopProcessModules instance to library's interface")
    lines.append("SECOP.GVL.G_ProcessModules := GVL_SecNode.G_SecopProcessModules;")
    lines.append("SECOP.GVL.G_xProcessModulesAssigned := TRUE;")
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# SEC node init
# ---------------------------------------------------------------------------


def _emit_init_sec_node(resolved: ResolvedRealModules) -> List[str]:
    """
    Emit the SEC node initialization block.
    """
    lines: List[str] = []
    sec_node = resolved.sec_node

    lines.append("// SEC node")
    lines.append("// ----------------------------------------------------------------")
    lines.append("")
    lines.append(f"SECOP.GVL.G_st_SecNode.sFirmware := {_format_st_scalar(sec_node.firmware)};")
    lines.append(f"SECOP.GVL.G_st_SecNode.sSecopVersion := {_format_st_scalar(sec_node.secop_version)};")
    lines.append(f"SECOP.GVL.G_st_SecNode.sTcpServerIp := {_format_st_scalar(sec_node.tcp_server_ip)};")
    lines.append(f"SECOP.GVL.G_st_SecNode.uiTcpServerPort := {sec_node.tcp_server_port};")

    for idx, module_name in enumerate(sec_node.module_names_in_order, start=1):
        lines.append(f"SECOP.GVL.G_st_SecNode.asModule[{idx}] := {_format_st_scalar(module_name)};")

    lines.append(
        f"SECOP.GVL.G_st_SecNode.sStructureReport := {_format_st_scalar(sec_node.structure_report_json)};"
    )
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Per-module init
# ---------------------------------------------------------------------------


def _emit_module_init(module: ResolvedRealModule) -> List[str]:
    """
    Emit initialization lines for one real module.
    """
    lines: List[str] = []
    pfx = _secop_gvl_module_prefix(module.module_name)

    lines.append(f"// {module.module_name}")
    lines.append("// ----------------------------------------------------------------")
    lines.append("")
    lines.append(f"{pfx}.etInterfaceClass := {_interface_class_literal(module.interface_class)};")
    lines.append(f"{pfx}.sName := {_format_st_scalar(module.module_name)};")
    lines.append(f"{pfx}.sDescription := {_format_st_scalar(module.description)};")

    # target min/max
    if module.target_has_min_max:
        lines.append(f"{pfx}.{module.value_var_prefix}TargetMin := {module.target_min};")
        lines.append(f"{pfx}.{module.value_var_prefix}TargetMax := {module.target_max};")

    # target drive tolerance
    if module.target_has_drive_tolerance:
        lines.append(f"{pfx}.{module.value_var_prefix}TargetDriveTolerance := {module.target_drive_tolerance};")

    # value min/max
    if module.value_has_min_max:
        lines.append(f"{pfx}.{module.value_var_prefix}ValueMin := {module.value_min};")
        lines.append(f"{pfx}.{module.value_var_prefix}ValueMax := {module.value_max};")

    # value out-of-range
    if module.value_has_out_of_range:
        lines.append(f"{pfx}.{module.value_var_prefix}ValueOutOfRangeL := {module.value_out_of_range_l};")
        lines.append(f"{pfx}.{module.value_var_prefix}ValueOutOfRangeH := {module.value_out_of_range_h};")

    # target limits
    if module.target_has_limits:
        lines.append(f"{pfx}.{module.value_var_prefix}TargetLimitsMin := {module.target_limits_min};")
        lines.append(f"{pfx}.{module.value_var_prefix}TargetLimitsMax := {module.target_limits_max};")

    # pollinterval
    lines.append(f"{pfx}.stPollInterval.lrValue := 5;")
    lines.append(f"{pfx}.stPollInterval.lrMin := {module.pollinterval_min};")
    lines.append(f"{pfx}.stPollInterval.lrMax := {module.pollinterval_max};")
    lines.append(f"{pfx}.stPollInterval.xReadOnly := {_bool_literal(module.pollinterval_readonly)};")

    # target drive timeout
    if module.interface_class == "Drivable" and module.x_plc_target and module.x_plc_target.reach_timeout_s is not None:
        lines.append(f"{pfx}.stTargetDrive.timTimeout := T#{module.x_plc_target.reach_timeout_s}S;")

    # custom parameters
    for cp in module.custom_parameters:
        lines.append(
            f"// TODO_CODEGEN: initialize custom parameter {cp.secop_name} for module {module.module_name} if needed"
        )

    lines.append("")

    return lines


def _emit_init_modules(resolved: ResolvedRealModules) -> List[str]:
    """
    Emit initialization blocks for all real modules in config order.
    """
    lines: List[str] = []

    for module_name in resolved.sec_node.module_names_in_order:
        lines.extend(_emit_module_init(resolved.modules[module_name]))

    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def emit_prg_secop_init(resolved: ResolvedRealModules) -> str:
    """
    Emit the full ST source for PROGRAM SecopInit.
    """
    lines: List[str] = []

    lines.extend(_emit_fixed_header())
    lines.extend(_emit_init_sec_node(resolved))
    lines.extend(_emit_init_modules(resolved))

    return "\n".join(lines) + "\n"