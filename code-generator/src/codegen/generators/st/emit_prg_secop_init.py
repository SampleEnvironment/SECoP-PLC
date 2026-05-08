"""
ST generator for PROGRAM SecopInit.

This PRG performs:
- version warning
- assignment of FB_SecopProcessModules to the library interface
- SEC node initialization
- per-module initialization

Input:
- resolved model produced by codegen.resolve.real_modules.resolve_real_modules

Design notes
------------
- This emitter only formats Structured Text.
- All structural decisions about what applies to each module should already have
  been resolved before reaching this stage.
- For project fields that always apply conceptually but are missing in the
  configuration, this emitter generates TASK comments and adds an entry to the
  task list so the PLC integrator can complete them later.
"""

from __future__ import annotations

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
)
from codegen.tasklist import TaskList


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
    - strings are single-quoted
    - floats with no fractional part are emitted as integers (e.g. 10000.0 -> 10000)
      so that the literal is compatible with both DINT and LREAL variables.
    - other numbers are emitted as-is
    """
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _format_server_ip(value: str) -> str:
    """
    Format the tcp.server_ip value for a ST assignment.

    If the value contains exactly 3 dots it is treated as a literal IP address
    and emitted as a single-quoted string.
    Otherwise it is treated as a PLC variable / tag reference and emitted
    without quotes.

    Examples:
        "192.168.1.10"  ->  "'192.168.1.10'"
        "sPlcAddress2"  ->  "sPlcAddress2"
    """
    if value.count(".") == 3:
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return value


def _emit_optional_scalar_assignment_with_task(
    st_lhs: str,
    value: float | int | str | None,
    plc_path: str,
    task_message: str,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit one scalar ST assignment when the value exists.

    If the value is missing, emit a task comment and register one task.

    This helper is used for project fields that always apply conceptually.
    """
    if value is None:
        return [tasklist.make_st_comment(plc_path=plc_path, message=task_message)]

    return [f"{st_lhs} := {_format_st_scalar(value)};"]


# ---------------------------------------------------------------------------
# Fixed header
# ---------------------------------------------------------------------------

def _emit_fixed_header() -> list[str]:
    """
    Emit the fixed first block of SecopInit.
    """
    lines: list[str] = []

    lines.append("PROGRAM SecopInit")
    lines.append("")
    lines.append("// Warning - SECoP library version newer than supported by the code generator")
    lines.append("{IF hasconstantvalue(GVL_SecNode.xCodeGenNotUpToDate, TRUE, =)}")
    lines.append("{warning 'SECOP library is newer than supported by the code generator.'}")
    lines.append("{END_IF}")
    lines.append("")
    lines.append("// Detect if JSON Utilities SL library is installed")
    lines.append("{IF defined(variable:JSON.GParams.g_diMaxDepth)}")
    lines.append(" SECOP.GVL.G_xJsonLibInstalled := TRUE;")
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

def _emit_init_sec_node(
    resolved: ResolvedRealModules,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit the SEC node initialization block.

    Several node-level PLC/tooling fields always apply conceptually in this
    project. If they are not configured, task comments are emitted instead of
    invalid ST.
    """
    lines: list[str] = []
    sec_node = resolved.sec_node

    lines.append("// SEC node")
    lines.append("// ----------------------------------------------------------------")
    lines.append("")
    lines.append(f"SECOP.GVL.G_st_SecNode.sFirmware := {_format_st_scalar(sec_node.firmware)};")

    lines.extend(
        _emit_optional_scalar_assignment_with_task(
            "SECOP.GVL.G_st_SecNode.sSecopVersion",
            sec_node.secop_version,
            "SecopInit.sec_node.secop_version",
            "Configure SEC node SECoP version.",
            tasklist,
        )
    )

    if sec_node.tcp_server_ip is None:
        lines.append(
            tasklist.make_st_comment(
                plc_path="SecopInit.sec_node.tcp.server_ip",
                message="Configure SEC node TCP server IP.",
            )
        )
    else:
        lines.append(
            f"SECOP.GVL.G_st_SecNode.sTcpServerIp := {_format_server_ip(sec_node.tcp_server_ip)};"
        )

    lines.extend(
        _emit_optional_scalar_assignment_with_task(
            "SECOP.GVL.G_st_SecNode.uiTcpServerPort",
            sec_node.tcp_server_port,
            "SecopInit.sec_node.tcp.server_port",
            "Configure SEC node TCP server port.",
            tasklist,
        )
    )

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

def _emit_module_init(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit initialization lines for one real module.

    Class-level applicability has already been resolved elsewhere. This emitter
    therefore generates only the variables that are structurally present in the
    corresponding ST_Module_<class>.
    """
    lines: list[str] = []
    pfx = _secop_gvl_module_prefix(module.module_name)

    lines.append(f"// {module.module_name}")
    lines.append("// ----------------------------------------------------------------")
    lines.append("")
    lines.append(f"{pfx}.etInterfaceClass := {_interface_class_literal(module.interface_class)};")
    lines.append(f"{pfx}.sName := {_format_st_scalar(module.module_name)};")
    lines.append(f"{pfx}.sDescription := {_format_st_scalar(module.description)};")

    if module.target_has_min_max:
        lines.append(f"{pfx}.{module.value_var_prefix}TargetMin := {_format_st_scalar(module.target_min)};")
        lines.append(f"{pfx}.{module.value_var_prefix}TargetMax := {_format_st_scalar(module.target_max)};")

    if module.value_has_min_max:
        lines.append(f"{pfx}.{module.value_var_prefix}ValueMin := {_format_st_scalar(module.value_min)};")
        lines.append(f"{pfx}.{module.value_var_prefix}ValueMax := {_format_st_scalar(module.value_max)};")

    if module.value_has_out_of_range:
        lines.append(f"{pfx}.{module.value_var_prefix}ValueOutOfRangeL := {_format_st_scalar(module.value_out_of_range_l)};")
        lines.append(f"{pfx}.{module.value_var_prefix}ValueOutOfRangeH := {_format_st_scalar(module.value_out_of_range_h)};")

    if module.target_has_limits_tuple or module.target_has_limits_min or module.target_has_limits_max:
        vp = module.value_var_prefix
        # lrTargetLimitsMin / lrTargetLimitsMax: current lower/upper limit values
        # lrTargetLimitsMin_Min/Max: allowed range for the min-limit parameter
        # lrTargetLimitsMax_Min/Max: allowed range for the max-limit parameter
        lines.append(f"{pfx}.{vp}TargetLimitsMin     := {_format_st_scalar(module.target_limits_min_min)};")
        lines.append(f"{pfx}.{vp}TargetLimitsMax     := {_format_st_scalar(module.target_limits_max_max)};")
        lines.append(f"{pfx}.{vp}TargetLimitsMin_Min := {_format_st_scalar(module.target_limits_min_min)};")
        lines.append(f"{pfx}.{vp}TargetLimitsMin_Max := {_format_st_scalar(module.target_limits_min_max)};")
        lines.append(f"{pfx}.{vp}TargetLimitsMax_Min := {_format_st_scalar(module.target_limits_max_min)};")
        lines.append(f"{pfx}.{vp}TargetLimitsMax_Max := {_format_st_scalar(module.target_limits_max_max)};")

    lines.append(f"{pfx}.stPollInterval.lrValue := 5;")
    lines.append(f"{pfx}.stPollInterval.lrMin := {_format_st_scalar(module.pollinterval_min)};")
    lines.append(f"{pfx}.stPollInterval.lrMax := {_format_st_scalar(module.pollinterval_max)};")
    lines.append(f"{pfx}.stPollInterval.xReadOnly := {_bool_literal(module.pollinterval_readonly)};")

    if module.interface_class == "Drivable":
        if module.x_plc_target and module.x_plc_target.reach_timeout_s is not None:
            lines.append(f"{pfx}.stTargetDrive.timTimeout := T#{module.x_plc_target.reach_timeout_s}S;")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopInit.{module.module_name}.target_drive_timeout",
                    message=f"Configure target drive timeout for module {module.module_name}.",
                )
            )

    lines.append("")

    return lines


def _emit_init_modules(
    resolved: ResolvedRealModules,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit initialization blocks for all real modules in config order.
    """
    lines: list[str] = []

    for module_name in resolved.sec_node.module_names_in_order:
        lines.extend(_emit_module_init(resolved.modules[module_name], tasklist))

    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def emit_prg_secop_init(
    resolved: ResolvedRealModules,
    tasklist: TaskList,
) -> str:
    """
    Emit the full ST source for PROGRAM SecopInit.
    """
    lines: list[str] = []

    lines.extend(_emit_fixed_header())
    lines.extend(_emit_init_sec_node(resolved, tasklist))
    lines.extend(_emit_init_modules(resolved, tasklist))

    return "\n".join(lines) + "\n"