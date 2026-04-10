"""
Building blocks used by the FB_Module_* code generator.

This file contains reusable blocks for generating FB_Module_<class>.
The resolved model is consumed here; raw JSON must not be parsed again.

Design notes
------------
- This file formats Structured Text only.
- Structural applicability is decided earlier in the resolve layer.
- Customised parameters and customised commands are already resolved and exposed
  through the generic resolved model, so this emitter should not try to infer
  them again from raw config.
"""

from __future__ import annotations

import re

from codegen.resolve.types import (
    ResolvedCustomParameter,
    ResolvedModuleClass,
)
from codegen.tasklist import TaskList


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _to_string_func_for_plc_type(plc_type: str) -> str:
    """
    Return the ST function used to convert a scalar PLC value to STRING.

    Supported conversions:
    - LREAL -> LREAL_TO_STRING
    - DINT  -> DINT_TO_STRING
    - INT   -> INT_TO_STRING
    """
    if plc_type == "LREAL":
        return "LREAL_TO_STRING"
    if plc_type == "DINT":
        return "DINT_TO_STRING"
    if plc_type == "INT":
        return "INT_TO_STRING"
    raise ValueError(f"Unsupported plc_type for TO_STRING conversion: {plc_type}")


def _value_to_string_expr(resolved: ResolvedModuleClass, var_ref: str) -> str:
    """
    Build the ST expression that converts a value-like variable to STRING.

    Rules:
    - numeric LREAL -> LREAL_TO_STRING(var)
    - numeric DINT  -> DINT_TO_STRING(var)
    - enum          -> INT_TO_STRING(var)
    - string        -> handled elsewhere through JSON string encoding
    """
    if resolved.value.is_enum:
        return f"INT_TO_STRING({var_ref})"
    if resolved.value.is_numeric:
        return f"{_to_string_func_for_plc_type(resolved.value.plc_type)}({var_ref})"
    raise ValueError("value_to_string_expr only supports numeric/enum values")


def _string_max_len(plc_type: str) -> int:
    """
    Extract the declared max length from a STRING plc_type, e.g. STRING(30) → 30.
    Falls back to 255 if the format is not recognised.
    """
    m = re.search(r'\((\d+)\)', plc_type)
    return int(m.group(1)) if m else 255


def _target_temp_var_name(resolved: ResolvedModuleClass) -> str:
    """
    Name of the temporary variable used to parse a requested target value.

    Rules:
    - enum -> iTargetNewVal
    - numeric/string -> <var_prefix>TargetNewVal
    """
    if resolved.value.is_enum:
        return "iTargetNewVal"
    return f"{resolved.value.var_prefix}TargetNewVal"


def _target_temp_var_type(resolved: ResolvedModuleClass) -> str:
    """
    PLC type of the temporary variable used to parse a requested target value.
    """
    if resolved.value.is_enum:
        return "INT"
    return resolved.value.plc_type


def _emit_status_data_report(action_expr: str, accessible_expr: str) -> list[str]:
    """
    Emit the standard status data-report sequence.
    """
    return [
        "  A_GenerateStatusDataReport(); // Generate status data report and store it in sBuiltDataReport",
        f"  M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action_expr}, i_sAccessible := {accessible_expr}, i_sDataReport:= sBuiltDataReport); // Status",
    ]


def _emit_numeric_or_enum_data_report(
    action_expr: str,
    accessible_literal: str,
    data_expr: str,
) -> list[str]:
    """
    Emit M_AddDataReportToReplyMessage for numeric or enum data.
    """
    return [
        f"  M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action_expr}, i_sAccessible := '{accessible_literal}', i_sDataReport:= {data_expr}); // {accessible_literal}"
    ]


def _emit_string_data_report(
    action_expr: str,
    accessible_literal: str,
    raw_var_ref: str,
) -> list[str]:
    """
    Emit JSON string encoding followed by a reply message.
    """
    return [
        f"  M_JsonEncodeString(i_sRawString:= {raw_var_ref}, q_sJsonString => sBuiltDataReport); // Json-encode string and store it in sBuiltDataReport",
        f"  M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action_expr}, i_sAccessible := '{accessible_literal}', i_sDataReport:= sBuiltDataReport); // {accessible_literal}",
    ]


def _emit_value_report_lines(action_expr: str, resolved: ResolvedModuleClass, tasklist: TaskList, context: str = "") -> list[str]:
    """
    Emit report lines for accessibles.value.

    For array/tuple value types a task comment is emitted instead of automatic
    mapping code because the internal structure is open-ended.
    context is used to distinguish between activate / read / update task entries.
    """
    if resolved.value.is_array or resolved.value.is_tuple:
        secop_type = "array" if resolved.value.is_array else "tuple"
        suffix = f".{context}" if context else ""
        return [
            "  " + tasklist.make_st_comment(
                plc_path=f"FB_Module_{resolved.name}.value_report{suffix}",
                message=f"report 'value' — type '{secop_type}' has open-ended structure; implement encoding manually",
            )
        ]

    value_var = f"iq_{resolved.value.var_prefix}Value"

    if resolved.value.is_string:
        return _emit_string_data_report(action_expr, "value", value_var)

    return _emit_numeric_or_enum_data_report(
        action_expr=action_expr,
        accessible_literal="value",
        data_expr=_value_to_string_expr(resolved, value_var),
    )


def _emit_target_report_lines(action_expr: str, resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit report lines for accessibles.target.

    Only valid when target exists.
    """
    if resolved.target is None:
        return []

    target_var = f"iq_{resolved.value.var_prefix}Target"

    if resolved.value.is_string:
        return _emit_string_data_report(action_expr, "target", target_var)

    return _emit_numeric_or_enum_data_report(
        action_expr=action_expr,
        accessible_literal="target",
        data_expr=_value_to_string_expr(resolved, target_var),
    )


def _target_data_report_lines(
    resolved: ResolvedModuleClass,
    target_var: str,
    action: str,
    accessible_expr: str,
    indent: str,
) -> list[str]:
    """
    Return ST lines for a target data-report with a caller-supplied indent.

    Handles both cases:
    - string value  -> M_JsonEncodeString + M_AddDataReportToReplyMessage
    - numeric/enum  -> M_AddDataReportToReplyMessage with inline conversion

    action:          ST expression for the action, e.g. "'changed'" or "'update'"
    accessible_expr: ST expression for the accessible, e.g. "'target'" or
                     "i_sAccessible" (in places where it is a run-time variable)
    indent:          whitespace prefix prepended to every emitted line
    """
    if resolved.value.is_string:
        return [
            f"{indent}M_JsonEncodeString(i_sRawString:= {target_var}, q_sJsonString => sBuiltDataReport); // Json-encode string and store it in sBuiltDataReport",
            f"{indent}M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action}, i_sAccessible := {accessible_expr}, i_sDataReport:= sBuiltDataReport); // target",
        ]
    data_expr = _value_to_string_expr(resolved, target_var)
    return [
        f"{indent}M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action}, i_sAccessible := {accessible_expr}, i_sDataReport:= {data_expr}); // target"
    ]


def _value_data_report_lines(
    resolved: ResolvedModuleClass,
    action: str,
    indent: str,
) -> list[str]:
    """
    Return ST lines for a value data-report with a caller-supplied indent.

    Handles both cases:
    - string value  -> M_JsonEncodeString + M_AddDataReportToReplyMessage
    - numeric/enum  -> M_AddDataReportToReplyMessage with inline conversion

    action: ST expression for the action, e.g. "'change'" or "'update'"
    indent: whitespace prefix prepended to every emitted line
    """
    value_var = f"iq_{resolved.value.var_prefix}Value"
    if resolved.value.is_string:
        return [
            f"{indent}M_JsonEncodeString(i_sRawString:= {value_var}, q_sJsonString => sBuiltDataReport); // Json-encode string and store it in sBuiltDataReport",
            f"{indent}M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action}, i_sAccessible := 'value', i_sDataReport:= sBuiltDataReport); // value",
        ]
    data_expr = _value_to_string_expr(resolved, value_var)
    return [
        f"{indent}M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action}, i_sAccessible := 'value', i_sDataReport:= {data_expr}); // value"
    ]


def _emit_custom_parameter_report_lines(
    action_expr: str,
    cp: ResolvedCustomParameter,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit report lines for one customised parameter.
    """
    raw_var = f"iq_{cp.plc_var_name}"

    if cp.is_string:
        return _emit_string_data_report(action_expr, cp.secop_name, raw_var)

    if cp.is_enum:
        return _emit_numeric_or_enum_data_report(
            action_expr=action_expr,
            accessible_literal=cp.secop_name,
            data_expr=f"INT_TO_STRING({raw_var})",
        )

    if cp.is_numeric:
        return _emit_numeric_or_enum_data_report(
            action_expr=action_expr,
            accessible_literal=cp.secop_name,
            data_expr=f"{_to_string_func_for_plc_type(cp.plc_type)}({raw_var})",
        )

    if cp.is_array or cp.is_tuple:
        secop_type = "array" if cp.is_array else "tuple"
        return [
            "  " + tasklist.make_st_comment(
                plc_path=f"FB_Module.{cp.secop_name}_report",
                message=f"report '{cp.secop_name}' — type '{secop_type}' has open-ended structure; implement encoding manually",
            )
        ]

    raise ValueError(f"Unsupported custom parameter type for {cp.secop_name}")


def _emit_pollinterval_report_lines(action_expr: str) -> list[str]:
    """
    Emit report lines for accessibles.pollinterval.
    """
    return [
        f"  M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := {action_expr}, i_sAccessible := 'pollinterval', i_sDataReport:= LREAL_TO_STRING(iq_stPollInterval.lrValue)); // pollinterval"
    ]


def _emit_all_parameter_reports(action_expr: str, resolved: ResolvedModuleClass, tasklist: TaskList, context: str = "") -> list[str]:
    """
    Emit report lines for all readable parameters of the module.

    Included:
    - status
    - value
    - target (if it exists)
    - customised parameters
    - pollinterval

    Not included:
    - commands
    - target_limits
    """
    lines: list[str] = []

    lines.extend(_emit_status_data_report(action_expr, "'status'"))
    lines.extend(_emit_value_report_lines(action_expr, resolved, tasklist, context=context))

    if resolved.target is not None:
        lines.extend(_emit_target_report_lines(action_expr, resolved))

    for cp in resolved.custom_parameters:
        lines.extend(_emit_custom_parameter_report_lines(action_expr, cp, tasklist))

    lines.extend(_emit_pollinterval_report_lines(action_expr))

    return lines


def _emit_read_parameter_chain(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit the IF / ELSIF chain used inside 'read'.

    Included:
    - status
    - value
    - target (if it exists)
    - customised parameters
    - pollinterval
    """
    lines: list[str] = []

    lines.append("  // Prepare reply message: reply <module>:<parameter> <data-report>")
    lines.append("  IF i_sAccessible = 'status' THEN")
    lines.extend(_indent(_emit_status_data_report("i_sAction", "i_sAccessible"), 1))

    lines.append("  ELSIF i_sAccessible = 'value' THEN")
    lines.extend(_indent(_emit_value_report_lines("i_sAction", resolved, tasklist, context="read"), 1))

    if resolved.target is not None:
        lines.append("  ELSIF i_sAccessible = 'target' THEN")
        lines.extend(_indent(_emit_target_report_lines("i_sAction", resolved), 1))

    for cp in resolved.custom_parameters:
        lines.append(f"  ELSIF i_sAccessible = '{cp.secop_name}' THEN")
        lines.extend(_indent(_emit_custom_parameter_report_lines("i_sAction", cp, tasklist), 1))

    lines.append("  ELSIF i_sAccessible = 'pollinterval' THEN")
    lines.extend(_indent(_emit_pollinterval_report_lines("i_sAction"), 1))

    lines.append("  ELSE")
    lines.append('   A_ReturnErrorNoSuchParameter(); // Return "NoSuchParameter" error')
    lines.append("  END_IF")

    return lines


def _indent(lines: list[str], level: int = 1) -> list[str]:
    """
    Light indentation helper used to keep generated code readable.
    """
    prefix = " " * (level * 1)
    return [prefix + line if line else "" for line in lines]


def _build_target_range_condition(resolved: ResolvedModuleClass, temp_var: str) -> str | None:
    """
    Build the IF condition that detects whether a requested target is out of range.

    Returns None if no target-range restrictions apply.
    """
    checks: list[str] = []
    p = resolved.value.var_prefix

    if resolved.target is None:
        return None

    if resolved.target.has_min_max:
        checks.append(f"{temp_var} > iq_{p}TargetMax")
        checks.append(f"{temp_var} < iq_{p}TargetMin")

    if resolved.target.has_limits:
        checks.append(f"{temp_var} > iq_{p}TargetLimitsMax")
        checks.append(f"{temp_var} < iq_{p}TargetLimitsMin")

    if not checks:
        return None

    return " OR ".join(checks)


def _build_restrictive_min_expr(resolved: ResolvedModuleClass) -> str:
    """
    Build the ST expression for the most restrictive minimum target bound.
    """
    p = resolved.value.var_prefix
    if resolved.target is None:
        raise ValueError("target is None")

    if resolved.target.has_min_max and resolved.target.has_limits:
        return f"MAX(iq_{p}TargetMin, iq_{p}TargetLimitsMin)"
    if resolved.target.has_min_max:
        return f"iq_{p}TargetMin"
    if resolved.target.has_limits:
        return f"iq_{p}TargetLimitsMin"

    raise ValueError("No restrictive min available")


def _build_restrictive_max_expr(resolved: ResolvedModuleClass) -> str:
    """
    Build the ST expression for the most restrictive maximum target bound.
    """
    p = resolved.value.var_prefix
    if resolved.target is None:
        raise ValueError("target is None")

    if resolved.target.has_min_max and resolved.target.has_limits:
        return f"MIN(iq_{p}TargetMax, iq_{p}TargetLimitsMax)"
    if resolved.target.has_min_max:
        return f"iq_{p}TargetMax"
    if resolved.target.has_limits:
        return f"iq_{p}TargetLimitsMax"

    raise ValueError("No restrictive max available")


def _build_limit_expr(resolved: ResolvedModuleClass, source_expr: str) -> str:
    """
    Build the LIMIT(...) expression used when applying a new target.

    If there are no target bounds, return source_expr directly.
    """
    if resolved.target is None:
        return source_expr

    if resolved.target.has_min_max or resolved.target.has_limits:
        return (
            f"LIMIT({_build_restrictive_min_expr(resolved)}, "
            f"{source_expr}, {_build_restrictive_max_expr(resolved)})"
        )

    return source_expr


# ---------------------------------------------------------
# Header
# ---------------------------------------------------------

def emit_header_comments(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit the function-block structure comment header.
    """
    lines: list[str] = []

    lines.append("// ============================================================================")
    lines.append("// Function block structure:")

    if resolved.value.has_min_max or resolved.value.has_out_of_range or resolved.value.is_enum:
        lines.append("//  0 - Monitor value to generate out of range warning/error if configured")

    lines.append("//  1 - Sync mode. Process client request")

    if resolved.interface_class == "Drivable":
        lines.append("//  2 - Async. mode.")
        lines.append("//  2.1 - State machine for handling target drive and stop command")
        lines.append("//  2.2 - Handle module updates for subscribed clients")
        lines.append("//  3 - Monitor target drive while status is BUSY, and update status when done")
    else:
        lines.append("//  2 - Async. mode. Handle module updates for subscribed clients")

    lines.append("// ============================================================================")
    lines.append("")

    return lines


def emit_fb_header(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit the FB header line including the correct base class.
    """
    lines: list[str] = []

    if resolved.interface_class == "Readable":
        base = "SECOP.FB_BaseModuleReadable"
    elif resolved.interface_class == "Writable":
        base = "SECOP.FB_BaseModuleWritable"
    elif resolved.interface_class == "Drivable":
        base = "SECOP.FB_BaseModuleDrivable"
    else:
        raise ValueError(f"Unsupported interface class: {resolved.interface_class}")

    lines.append(f"FUNCTION_BLOCK FB_Module_{resolved.name} EXTENDS {base}")
    lines.append("")

    return lines


# ---------------------------------------------------------
# VAR_IN_OUT
# ---------------------------------------------------------

def emit_var_in_out(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit VAR_IN_OUT block for module-specific variables.

    For open-ended types (array, tuple) no PLC type can be generated automatically.
    A task comment is emitted instead, and the task is registered in the task list.
    """
    lines: list[str] = []

    lines.append("VAR_IN_OUT")
    for var in resolved.module_variables:
        if "(*TODO:" in var.plc_type:
            lines.append(
                " " + tasklist.make_st_comment(
                    plc_path=f"FB_Module_{resolved.name}.{var.name}",
                    message=f"declare variable for '{var.name[1:]}' — value type has open-ended structure (array or tuple); no automatic PLC type can be generated",
                )
            )
        else:
            lines.append(f" iq_{var.name}: {var.plc_type};")
    lines.append("END_VAR")
    lines.append("")

    return lines


# ---------------------------------------------------------
# VAR
# ---------------------------------------------------------

def emit_var_internal(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit internal VAR block for FB_Module_<class>.
    """
    lines: list[str] = []

    lines.append("VAR")

    if resolved.value.is_numeric:
        lines.append(" sMin: STRING;")
        lines.append(" sMax: STRING;")

    if resolved.interface_class in ("Writable", "Drivable"):
        lines.append(f" {_target_temp_var_name(resolved)}: {_target_temp_var_type(resolved)};")

    lines.append(" fbBlinkPollInterval: BLINK;")
    lines.append(" fbRtrigPollInterval: R_TRIG;")
    lines.append(" fbRtrigIsFirstClient: R_TRIG;")
    lines.append(" fbRtrigAllClientsDone: R_TRIG;")
    lines.append(" xUpdateAllSubscribers: BOOL;")
    lines.append(" xPollIntervalDone: BOOL;")

    if resolved.interface_class == "Drivable":
        if resolved.value.is_enum:
            drive_prefix = "i"
        elif resolved.value.is_string:
            drive_prefix = "s"
        else:
            drive_prefix = resolved.value.var_prefix

        lines.append(f" fbTargetDriveMonitor : SECOP.FB_{drive_prefix}TargetDrive;")

    lines.append("END_VAR")
    lines.append("")

    return lines


# ---------------------------------------------------------
# Common first block
# ---------------------------------------------------------

def emit_monitor_clients_round_block() -> list[str]:
    """
    Emit the block that monitors the start and end of a client round.
    """
    lines: list[str] = []

    lines.append("// Monitor client round start and finish")
    lines.append("fbRtrigIsFirstClient(CLK:= i_xFirstSecopClient);")
    lines.append("fbRtrigAllClientsDone(CLK:= i_xAllSecopClientsDone);")
    lines.append("")

    return lines


# ---------------------------------------------------------
# Out-of-range block
# ---------------------------------------------------------

def _emit_numeric_out_of_range_block(resolved: ResolvedModuleClass) -> list[str]:
    lines: list[str] = []

    value_prefix = resolved.value.var_prefix
    to_string_func = _to_string_func_for_plc_type(resolved.value.plc_type)

    has_oor = bool(resolved.value.has_out_of_range)
    has_minmax = bool(resolved.value.has_min_max)

    if not (has_oor or has_minmax):
        return lines

    lines.append("//  0 - Monitor value to generate out of range warning/error if configured")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("// Update module status when value goes out of range if module is in IDLE (keep current status otherwise)")
    lines.append("IF fbRtrigIsFirstClient.Q AND NOT iq_stErrorReport.xActive AND iq_stStatus.etCode = SECOP.ET_StatusCode.Idle THEN")

    if has_oor:
        lines.append("")
        lines.append(' // Return "OutOfRange" error')
        lines.append(
            f" IF (iq_{value_prefix}Value < iq_{value_prefix}ValueOutOfRangeL OR iq_{value_prefix}Value > iq_{value_prefix}ValueOutOfRangeH) THEN"
        )
        lines.append("  iq_stStatus.etCode := SECOP.ET_StatusCode.Error;")
        lines.append("  iq_stStatus.sDescription := 'Measure fault';")
        lines.append("  iq_stErrorReport.xActive := TRUE;")
        lines.append("  iq_stErrorReport.sClass := 'OutOfRange';")
        lines.append("  iq_stErrorReport.sDescription := 'Sensor or calibration range is between ';")
        lines.append(f"  sMin := {to_string_func}(iq_{value_prefix}ValueMin);")
        lines.append("  StrConcatA(pstFrom:= ADR(sMin), pstTo:= ADR(iq_stErrorReport.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append("  StrConcatA(pstFrom:= ADR(' and '), pstTo:= ADR(iq_stErrorReport.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append(f"  sMax := {to_string_func}(iq_{value_prefix}ValueMax);")
        lines.append("  StrConcatA(pstFrom:= ADR(sMax), pstTo:= ADR(iq_stErrorReport.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")

    if has_minmax:
        lines.append("")
        lines.append(' // Return "OutOfRange" warning')
        keyword = " ELSIF" if has_oor else " IF"
        lines.append(
            f"{keyword} (iq_{value_prefix}Value < iq_{value_prefix}ValueMin OR iq_{value_prefix}Value > iq_{value_prefix}ValueMax) THEN"
        )
        lines.append("  iq_stStatus.etCode := SECOP.ET_StatusCode.Warn;")
        lines.append("  iq_stStatus.sDescription := 'Value read from hardware out of range. Sensor or calibration range is between ';")
        lines.append(f"  sMin := {to_string_func}(iq_{value_prefix}ValueMin);")
        lines.append("  StrConcatA(pstFrom:= ADR(sMin), pstTo:= ADR(iq_stStatus.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append("  StrConcatA(pstFrom:= ADR(' and '), pstTo:= ADR(iq_stStatus.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append(f"  sMax := {to_string_func}(iq_{value_prefix}ValueMax);")
        lines.append("  StrConcatA(pstFrom:= ADR(sMax), pstTo:= ADR(iq_stStatus.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")

    lines.append(" END_IF")
    lines.append("END_IF")
    lines.append("")

    return lines


def _emit_enum_out_of_range_block(resolved: ResolvedModuleClass) -> list[str]:
    lines: list[str] = []

    if not resolved.value.is_enum or not resolved.value.members:
        return lines

    lines.append("//  0 - Monitor value to generate out of range warning/error if configured")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("// Update module status when value goes out of range if module is in IDLE (keep current status otherwise)")
    lines.append("IF fbRtrigIsFirstClient.Q AND NOT iq_stErrorReport.xActive AND iq_stStatus.etCode = SECOP.ET_StatusCode.Idle THEN")
    lines.append("")
    lines.append(' // Return "OutOfRange" error')

    members = list(resolved.value.members.keys())
    for idx, member_name in enumerate(members):
        prefix = " IF" if idx == 0 else "  AND"
        suffix = " THEN" if idx == len(members) - 1 else ""
        lines.append(f"{prefix} iq_etValue <> ET_Module_{resolved.name}_value.{member_name}{suffix}")

    lines.append("  iq_stStatus.etCode := SECOP.ET_StatusCode.Error;")
    lines.append("  iq_stStatus.sDescription := 'Value set to unspecified enum variant';")
    lines.append("  iq_stErrorReport.xActive := TRUE;")
    lines.append("  iq_stErrorReport.sClass := 'OutOfRange';")
    lines.append("  iq_stErrorReport.sDescription := 'Value set to unspecified enum variant';")
    lines.append(" END_IF")
    lines.append("END_IF")
    lines.append("")

    return lines


def emit_out_of_range_block(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit full out-of-range block when applicable.
    """
    if resolved.value.is_enum:
        return _emit_enum_out_of_range_block(resolved)

    if resolved.value.is_numeric and (resolved.value.has_min_max or resolved.value.has_out_of_range):
        return _emit_numeric_out_of_range_block(resolved)

    return []


# ---------------------------------------------------------
# SYNC block
# ---------------------------------------------------------

def _emit_sync_activate(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    lines: list[str] = []

    lines.append(" // Activate updates: activate <module>")
    lines.append(" IF i_sAction = 'activate' THEN")
    lines.append("  ")
    lines.append("  // Update subscriber list")
    lines.append("  M_UpdateSubscriberList(i_stClient:= i_stClientMonitored);")
    lines.append("  ")
    lines.append("  // Build reply message. Include all module accessibles")
    lines.extend(_emit_all_parameter_reports("i_sAction", resolved, tasklist, context="activate"))
    lines.append("  IF i_sModuleRequested = iq_sName THEN M_AddUpdatesEndMessage(i_sAction := i_sAction); END_IF // End message")

    return lines


def _emit_sync_deactivate() -> list[str]:
    lines: list[str] = []

    lines.append("")
    lines.append(" // Deactivate updates: deactivate <module>")
    lines.append(" ELSIF i_sAction = 'deactivate' THEN")
    lines.append("  ")
    lines.append("  M_RemoveSubscribedClientFromList(i_stClient:= i_stClientMonitored); // Unsubscribe client")
    lines.append("  IF i_sModuleRequested = iq_sName THEN M_AddUpdatesEndMessage(i_sAction := i_sAction); END_IF // End message")

    return lines


def _emit_sync_read(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    lines: list[str] = []

    lines.append("")
    lines.append(" // Read request: read <module>:<parameter>")
    lines.append(" ELSIF i_sAction = 'read' THEN")
    lines.append("  ")
    lines.extend(_emit_read_parameter_chain(resolved, tasklist))

    return lines


def _emit_numeric_change_target(resolved: ResolvedModuleClass) -> list[str]:
    lines: list[str] = []

    p = resolved.value.var_prefix
    temp_var = _target_temp_var_name(resolved)
    integer_required = "TRUE" if resolved.value.plc_type == "DINT" else "FALSE"

    lines.append(f"    IF NOT M_CheckIfDataIsNumeric(i_sDataToParse:= i_sData, i_xMustBeInteger:= {integer_required}) THEN // Unexpected data type")
    lines.append('     A_ReturnErrorWrongType(); // Return "WrongType" error')
    lines.append("    ")
    lines.append("    ELSE")
    lines.append(f"     {temp_var} := STRING_TO_{resolved.value.plc_type}(i_sData);")

    range_cond = _build_target_range_condition(resolved, temp_var)
    if range_cond:
        lines.append(f"     IF {range_cond} THEN // Target out of range")
        lines.append("      iq_stErrorReport.sClass := 'RangeError';")
        lines.append("      iq_stErrorReport.sDescription := 'Value must be between ';")
        min_expr = _build_restrictive_min_expr(resolved)
        max_expr = _build_restrictive_max_expr(resolved)
        to_string_func = _to_string_func_for_plc_type(resolved.value.plc_type)
        lines.append(f"      sMin := {to_string_func}({min_expr});")
        lines.append("      StrConcatA(pstFrom:= ADR(sMin), pstTo:= ADR(iq_stErrorReport.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append("      StrConcatA(pstFrom:= ADR(' and '), pstTo:= ADR(iq_stErrorReport.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append(f"      sMax := {to_string_func}({max_expr});")
        lines.append("      StrConcatA(pstFrom:= ADR(sMax), pstTo:= ADR(iq_stErrorReport.sDescription), iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeDescription));")
        lines.append("      M_ReplyWithErrorStraightAway(i_xErrorLatched:= FALSE);")
        lines.append("     ")
        lines.append("     ELSE // Apply new target value")
        limit_expr = _build_limit_expr(resolved, temp_var)
    else:
        limit_expr = temp_var
        lines.append("     // Apply new target value")

    if resolved.interface_class == "Drivable":
        lines.append(f"      iq_{p}TargetChangeNewVal := {limit_expr};")
        lines.append("      M_UpdateTargetDriveClientList(i_stClient:= i_stClientMonitored);")
        lines.append("      iq_stTargetDrive.uiState := 1;")
    else:
        lines.append(f"      iq_{p}Target := {limit_expr};")
        lines.extend(
            _target_data_report_lines(
                resolved=resolved,
                target_var=f"iq_{p}Target",
                action="'changed'",
                accessible_expr="i_sAccessible",
                indent="      ",
            )
        )
        lines.append("      xTargetChanged := TRUE;")
        lines.append("      iq_stTargetWrite.stTargetChangeClient.sIp := i_stClientMonitored.sIp;")
        lines.append("      iq_stTargetWrite.stTargetChangeClient.uiPort := i_stClientMonitored.uiPort;")

    if range_cond:
        lines.append("     END_IF")

    lines.append("    END_IF")
    lines.append("   END_IF")

    return lines


def _emit_enum_change_target(resolved: ResolvedModuleClass) -> list[str]:
    lines: list[str] = []

    lines.append("    IF NOT M_CheckIfDataIsNumeric(i_sDataToParse:= i_sData, i_xMustBeInteger:= TRUE) THEN // Unexpected data type")
    lines.append('     A_ReturnErrorWrongType(); // Return "WrongType" error')
    lines.append("    ")
    lines.append("    ELSE")
    lines.append("     iTargetNewVal := STRING_TO_INT(i_sData);")
    lines.append("")

    members = list(resolved.value.members.items()) if resolved.value.members else []

    if members:
        conds = [f"iTargetNewVal <> ET_Module_{resolved.name}_value.{name}" for name, _value in members]
        joined = " \n      AND ".join(conds)
        lines.append(f"     IF ({joined}) THEN // Target out of range")
    else:
        lines.append("     IF TRUE THEN // Target out of range")

    lines.append("      iq_stErrorReport.sClass := 'RangeError';")
    lines.append("      iq_stErrorReport.sDescription := 'Unspecified enum variant';")
    lines.append("      M_ReplyWithErrorStraightAway(i_xErrorLatched:= FALSE);")
    lines.append("     ")
    lines.append("     ELSE // Apply requested value")

    lines.append("      CASE iTargetNewVal OF")
    for name, member_value in members:
        if resolved.interface_class == "Drivable":
            lines.append(f"       {member_value}: iq_etTargetChangeNewVal := ET_Module_{resolved.name}_value.{name};")
        else:
            lines.append(f"       {member_value}: iq_etTarget := ET_Module_{resolved.name}_value.{name};")
    lines.append("      END_CASE")

    if resolved.interface_class == "Drivable":
        lines.append("      M_UpdateTargetDriveClientList(i_stClient:= i_stClientMonitored);")
        lines.append("      iq_stTargetDrive.uiState := 1;")
    else:
        lines.append("      M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := 'changed', i_sAccessible := i_sAccessible, i_sDataReport:= INT_TO_STRING(iq_etTarget));")
        lines.append("      xTargetChanged := TRUE;")
        lines.append("      iq_stTargetWrite.stTargetChangeClient.sIp := i_stClientMonitored.sIp;")
        lines.append("      iq_stTargetWrite.stTargetChangeClient.uiPort := i_stClientMonitored.uiPort;")

    lines.append("     END_IF")
    lines.append("    END_IF")
    lines.append("   END_IF")

    return lines


def _emit_string_change_target(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit the target-change inner block for a string-valued Writable or Drivable module.

    Validation: reject if the incoming data looks like a number, or if it
    exceeds the declared STRING max length.
    Apply (Writable):  decode JSON string from i_sData into iq_sTarget via
                       M_JsonDecodeString; report i_sData (already JSON) back to client.
    Apply (Drivable):  store raw JSON in iq_sTargetChangeNewVal; the drive state
                       machine will decode it when the target is actually applied.
    """
    lines: list[str] = []

    max_len = _string_max_len(resolved.value.plc_type)

    lines.append(f"    IF M_CheckIfDataIsNumeric(i_sDataToParse:= i_sData, i_xMustBeInteger:= FALSE) OR StrLenA(pstData:= ADR(i_sData)) > {max_len} THEN // Unexpected data type")
    lines.append('     A_ReturnErrorWrongType(); // Return "WrongType" error')
    lines.append("    ")
    lines.append("    ELSE // Apply new target value")
    if resolved.interface_class == "Drivable":
        lines.append("     M_JsonDecodeString(i_sJsonString:= i_sData, q_sRawString=> iq_sTargetChangeNewVal);")
        lines.append("     M_UpdateTargetDriveClientList(i_stClient:= i_stClientMonitored);")
        lines.append("     iq_stTargetDrive.uiState := 1;")
    else:
        lines.append("     M_JsonDecodeString(i_sJsonString:= i_sData, q_sRawString=> iq_sTarget);")
        lines.append("     M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := 'changed', i_sAccessible := i_sAccessible, i_sDataReport:= i_sData); // target")
        lines.append("     xTargetChanged := TRUE;")
        lines.append("     iq_stTargetWrite.stTargetChangeClient.sIp := i_stClientMonitored.sIp;")
        lines.append("     iq_stTargetWrite.stTargetChangeClient.uiPort := i_stClientMonitored.uiPort;")
    lines.append("    END_IF")
    lines.append("   END_IF")

    return lines


def _emit_sync_change(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    lines: list[str] = []

    lines.append("")
    lines.append(" // Change value: change <module>:<parameter> <value>")
    lines.append(" ELSIF i_sAction = 'change' THEN")
    lines.append("")

    first_branch_started = False

    if resolved.target is not None:
        lines.append("  // target")
        lines.append("  IF i_sAccessible = 'target' THEN")
        lines.append("   ")
        lines.append('   A_CheckTargetChangeInterlocks(); // Check target change interlocks. Return error if there is: "Impossible", "Disabled", "IsError", "BadJSON"...')
        lines.append("   ")
        lines.append("   IF xTargetChangeInterlock THEN // Target change interlocks healthy")

        if resolved.value.is_numeric:
            lines.extend(_emit_numeric_change_target(resolved))
        elif resolved.value.is_enum:
            lines.extend(_emit_enum_change_target(resolved))
        elif resolved.value.is_string:
            lines.extend(_emit_string_change_target(resolved))
        else:
            lines.append(
                "    " + tasklist.make_st_comment(
                    plc_path=f"FB_Module_{resolved.name}.change_target",
                    message="implement target change — value type has open-ended structure (array or tuple); no automatic mapping generated",
                )
            )
            lines.append("   END_IF")

        first_branch_started = True

    if resolved.pollinterval_changeable:
        keyword = "  ELSIF" if first_branch_started else "  IF"
        lines.append("")
        lines.append("  // pollinterval")
        lines.append(f"{keyword} i_sAccessible = 'pollinterval' THEN")
        lines.append("   A_HandlePollintervalChange(); // Handle polling interval change request")
        first_branch_started = True

    readonly_names: list[str] = ["value", "status"]
    readonly_names.extend(cp.secop_name for cp in resolved.custom_parameters)

    if resolved.target is not None and resolved.target.has_limits:
        readonly_names.append("target_limits")

    if not resolved.pollinterval_changeable:
        readonly_names.append("pollinterval")

    if readonly_names:
        cond = " OR ".join([f"i_sAccessible = '{name}'" for name in readonly_names])
        keyword = "  ELSIF" if first_branch_started else "  IF"
        lines.append("")
        lines.append("  // read-only accessible")
        lines.append(f"{keyword} {cond} THEN")
        lines.append('   A_ReturnErrorReadOnly(); // Return "ReadOnly" error')
        first_branch_started = True

    keyword = "  ELSE" if first_branch_started else "  IF TRUE THEN"
    lines.append("")
    lines.append("  // unknown parameter")
    lines.append(f"{keyword}")
    lines.append('   A_ReturnErrorNoSuchParameter(); // Return "NoSuchParameter" error')
    lines.append("  END_IF")

    return lines


def _emit_stop_apply_new_target(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit the expression that applies the stop command target.
    """
    lines: list[str] = []

    p = resolved.value.var_prefix

    if resolved.value.is_numeric:
        limit_expr = _build_limit_expr(resolved, f"iq_{p}Value")
        lines.append(f"     iq_{p}TargetChangeNewVal := {limit_expr};")
        return lines

    if resolved.value.is_enum and resolved.value.members:
        lines.append("     CASE iq_etValue OF")
        for member_name, member_value in resolved.value.members.items():
            lines.append(f"      {member_value}: iq_etTargetChangeNewVal := ET_Module_{resolved.name}_value.{member_name};")
        lines.append("     END_CASE")
        return lines

    if resolved.value.is_string:
        lines.append("     iq_sTargetChangeNewVal := iq_sValue; // Stop: revert target to current value")
        return lines

    lines.append(
        "     " + tasklist.make_st_comment(
            plc_path=f"FB_Module_{resolved.name}.stop_target",
            message="implement stop command target apply — value type has open-ended structure (array or tuple); no automatic mapping generated",
        )
    )
    return lines


def _emit_sync_do(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    lines: list[str] = []

    lines.append("")
    lines.append(" // Execute command: do <module>:<command> <value> (where <value> is optional)")
    lines.append(" ELSIF i_sAction = 'do' THEN")

    first_branch_started = False

    if resolved.interface_class == "Drivable":
        lines.append("  ")
        lines.append("  // stop")
        lines.append("  IF i_sAccessible = 'stop' THEN")
        lines.append("   ")
        lines.append('   A_CheckTargetChangeInterlocks(); // Check target change interlocks. Return error if there is: "Impossible", "Disabled", "IsError", "BadJSON"...')
        lines.append("   ")
        lines.append("   IF xTargetChangeInterlock THEN // Target change interlocks healthy")
        lines.append("    ")
        lines.append("    IF iq_stTargetDrive.uiState = 0 OR iq_stTargetDrive.uiState >= 4 THEN // No target change is underway")
        lines.append("     ; // Ignore request")
        lines.append("    ")
        lines.append("    ELSIF iq_stTargetDrive.xStopCmd THEN // A stop command is already ongoing")
        lines.append("     ; // Ignore request")
        lines.append("    ")
        lines.append("    ELSE // Execute stop command (target updated to current process value). Register client that made request. Initiates target drive state machine")
        lines.append("     iq_stTargetDrive.xStopCmd := TRUE;")
        lines.extend(_emit_stop_apply_new_target(resolved, tasklist))
        lines.append("     iq_stTargetDrive.stStopCmdClient.sIp := i_stClientMonitored.sIp;")
        lines.append("     iq_stTargetDrive.stStopCmdClient.uiPort := i_stClientMonitored.uiPort;")
        lines.append("     iq_stTargetDrive.uiState := 1;")
        lines.append("    END_IF")
        lines.append("   END_IF")
        first_branch_started = True

    if resolved.has_clear_errors_command:
        keyword = "  ELSIF" if first_branch_started else "  IF"
        lines.append("  ")
        lines.append("  // clear_errors")
        lines.append(f"{keyword} i_sAccessible = 'clear_errors' THEN")
        lines.append("   iq_xClearErrors := TRUE; // Apply command")
        lines.append("   M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction:= i_sAction, i_sAccessible:= i_sAccessible, i_sDataReport:= 'null'); // Prepare reply message: done <module>:<command> <data-report>")
        first_branch_started = True

    for cc in resolved.custom_commands:
        keyword = "  ELSIF" if first_branch_started else "  IF"
        lines.append(f"{keyword} i_sAccessible = '{cc.secop_name}' THEN")
        lines.append(f"   iq_{cc.plc_var_name} := TRUE; // Apply customised command")
        lines.append(
            "   " + tasklist.make_st_comment(
                plc_path=f"FB_Module_{resolved.name}.do_{cc.secop_name}",
                message=f"implement behaviour for custom command '{cc.secop_name}'",
            )
        )
        lines.append("   M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction:= i_sAction, i_sAccessible:= i_sAccessible, i_sDataReport:= 'null');")
        first_branch_started = True

    if first_branch_started:
        # At least one command branch was opened — close with ELSE for unknown commands
        lines.append("  ELSE")
        lines.append('   A_ReturnErrorNoSuchCommand();')
        lines.append("  END_IF")
    else:
        # No commands at all — no IF was opened, so no ELSE/END_IF needed
        lines.append('  A_ReturnErrorNoSuchCommand();')

    return lines


def emit_sync_block(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit the full synchronous request-processing block.

    Implemented:
    - activate
    - deactivate
    - read
    - change
    - do

    Not implemented:
    - check
    """
    lines: list[str] = []

    lines.append("// 1 - Sync mode. Process client request")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("IF i_xSyncModeRequest AND (i_sModuleRequested = iq_sName OR (StrIsNullOrEmptyA(ADR(i_sModuleRequested)) AND (i_sAction = 'activate' OR i_sAction = 'deactivate'))) THEN")
    lines.append(" ")

    lines.extend(_emit_sync_activate(resolved, tasklist))
    lines.extend(_emit_sync_deactivate())
    lines.extend(_emit_sync_read(resolved, tasklist))
    lines.extend(_emit_sync_change(resolved, tasklist))
    lines.extend(_emit_sync_do(resolved, tasklist))

    lines.append(" END_IF")  # closes IF i_sAction = 'activate' / ELSIF chain
    lines.append("END_IF")  # closes IF i_xSyncModeRequest AND ...
    lines.append("")

    return lines


def _emit_async_target_drive_state_machine(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit the target-drive state machine.

    Only applies to Drivable modules.
    """
    lines: list[str] = []

    if resolved.interface_class != "Drivable":
        return lines

    target_var = f"iq_{resolved.value.var_prefix}Target"

    lines.append("// Target drive state machine")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("CASE iq_stTargetDrive.uiState OF")
    lines.append(" ")
    lines.append(" 0: // Idle")
    lines.append("  ;")
    lines.append("  ")
    lines.append(" 1: // Target value change requested. Awaiting possibility of applying it to controlled hardware")
    lines.append("  ;")
    lines.append("  ")
    lines.append(" 2: // Target value change accepted and applied in hardware. Send updates to concerned clients")
    lines.append("  ")
    lines.append("  // Check if current client is concerned")
    lines.append("  M_CheckIfClientIsSubscribed(i_stClient:= i_stClientMonitored);")
    lines.append("  M_CheckIfClientChangedTarget(i_stClient:= i_stClientMonitored);")
    lines.append("  IF xClientIsSubscribed OR xClientChangedTarget")
    lines.append("   OR (i_stClientMonitored.sIp <> '' AND iq_stTargetDrive.stStopCmdClient.sIp = i_stClientMonitored.sIp")
    lines.append("    AND i_stClientMonitored.uiPort > 0 AND iq_stTargetDrive.stStopCmdClient.uiPort = i_stClientMonitored.uiPort) THEN")
    lines.append("    ")
    lines.append("    // Send update messages")
    lines.append("    A_GenerateStatusDataReport();")
    lines.append("    M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := 'change', i_sAccessible := 'status', i_sDataReport:= sBuiltDataReport); // Status")
    lines.extend(_value_data_report_lines(resolved, "'change'", "    "))
    lines.append("")
    lines.append('    // Target data is sent through a "changed" message to the client that sent the last target change request')
    lines.append('    // or through a "change" message to the rest of concerned clients')
    lines.append("    IF iq_stTargetWrite.stTargetChangeClient.sIp = i_stClientMonitored.sIp AND iq_stTargetWrite.stTargetChangeClient.uiPort = i_stClientMonitored.uiPort AND NOT iq_stTargetDrive.xStopCmd THEN")
    lines.extend(_target_data_report_lines(resolved, target_var, "'changed'", "'target'", "     "))
    lines.append("    ELSE")
    lines.extend(_target_data_report_lines(resolved, target_var, "'change'", "'target'", "     "))
    lines.append("    END_IF")
    lines.append("")
    lines.append('    // A "done" message is sent to the client that sent the stop command')
    lines.append("    IF iq_stTargetDrive.xStopCmd AND iq_stTargetDrive.stStopCmdClient.sIp = i_stClientMonitored.sIp AND iq_stTargetDrive.stStopCmdClient.uiPort = i_stClientMonitored.uiPort THEN")
    lines.append("     M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction:= 'do', i_sAccessible:= 'stop', i_sDataReport:= 'null');")
    lines.append("    END_IF")
    lines.append("  END_IF")
    lines.append("  ")
    lines.append("  // Go to next state when client round is done")
    lines.append("  IF i_xAllSecopClientsDone THEN")
    lines.append("   iq_stTargetDrive.uiState := 3;")
    lines.append("  END_IF")
    lines.append(" ")
    lines.append(" 3: // Waiting for the new target value to be reached")
    lines.append("  ;")
    lines.append("  ")
    lines.append(" 4: // Target value reached or failed (timeout elapsed). Send updates for concerned clients")
    lines.append(" ")
    lines.append("  M_CheckIfClientIsSubscribed(i_stClient:= i_stClientMonitored);")
    lines.append("  M_CheckIfClientChangedTarget(i_stClient:= i_stClientMonitored);")
    lines.append("  IF xClientIsSubscribed OR xClientChangedTarget")
    lines.append("   OR (i_stClientMonitored.sIp <> '' AND iq_stTargetDrive.stStopCmdClient.sIp = i_stClientMonitored.sIp")
    lines.append("    AND i_stClientMonitored.uiPort > 0 AND iq_stTargetDrive.stStopCmdClient.uiPort = i_stClientMonitored.uiPort) THEN")
    lines.append("   ")
    lines.append("   // Return module status")
    lines.append("   A_GenerateStatusDataReport();")
    lines.append("   M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := 'change', i_sAccessible := 'status', i_sDataReport:= sBuiltDataReport); // Status")
    lines.append("   IF NOT iq_stErrorReport.xActive THEN")
    lines.extend(_value_data_report_lines(resolved, "'change'", "    "))
    lines.extend(_target_data_report_lines(resolved, target_var, "'change'", "'target'", "    "))
    lines.append("   END_IF")
    lines.append(" ")
    lines.append("  END_IF")
    lines.append("  ")
    lines.append("  // Reset list of clients that made a target change request when client round is done, and back to Idle")
    lines.append("  IF i_xAllSecopClientsDone THEN")
    lines.append("   A_ResetTargetDriveClientList();")
    lines.append("   iq_stTargetDrive.uiState := 0;")
    lines.append("  END_IF")
    lines.append("  ")
    lines.append("END_CASE")
    lines.append("")

    return lines


def _emit_async_handle_updates(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit the async update-handling block.

    Applies to all modules.
    """
    lines: list[str] = []

    lines.append("// Handle module updates for subscribed clients")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("")
    lines.append("// Remove disconnected clients from subscriber list")
    lines.append("IF i_xClientDisconnectedFlag THEN")
    lines.append(" M_RemoveSubscribedClientFromList(i_stClient:= i_stClientDisconnected);")
    lines.append("END_IF")
    lines.append("")
    lines.append("// Monitor poll interval. New updates are due when poll interval is done")
    lines.append("fbBlinkPollInterval(ENABLE:= TRUE, TIMELOW:= LREAL_TO_TIME(iq_stPollInterval.lrValue/2*1000), TIMEHIGH:= LREAL_TO_TIME(iq_stPollInterval.lrValue/2*1000));")
    lines.append("fbRtrigPollInterval(CLK:= fbBlinkPollInterval.OUT);")
    lines.append("IF fbRtrigPollInterval.Q THEN xPollIntervalDone := TRUE; END_IF")
    lines.append("")
    lines.append("// When new updates are due, trigger update messages for subscribers when starting a new client's round")
    if resolved.interface_class == "Readable":
        lines.append("IF fbRtrigIsFirstClient.Q AND")
        lines.append(" (xPollIntervalDone OR xPollIntervalChanged) THEN")
    else:
        lines.append("IF fbRtrigIsFirstClient.Q AND")
        lines.append(" ((xPollIntervalDone OR xPollIntervalChanged)")
        lines.append("  OR xTargetChanged) THEN")
    lines.append("  xUpdateAllSubscribers := TRUE;")
    lines.append("END_IF")
    lines.append("")
    lines.append("// Update subscribers")
    lines.append("IF xUpdateAllSubscribers THEN")
    lines.append(" M_CheckIfClientIsSubscribed(i_stClient:= i_stClientMonitored); // Set xClientIsSubscribed to TRUE if monitored client is on the subscriber list")
    lines.append(" IF xClientIsSubscribed THEN")
    lines.append("  ")
    lines.append("  // Update subscribers on all module parameters when new updates are due (poll interval done)")
    lines.append("  IF xPollIntervalDone THEN")

    lines.extend(_indent(_emit_all_parameter_reports("'update'", resolved, tasklist, context="update"), 2))

    lines.append("  ELSE")
    lines.append("   // Update subscribers when changing the polling interval")
    lines.append("   IF xPollIntervalChanged AND NOT (iq_stPollInterval.stPollintervalChangeClient.sIp = i_stClientMonitored.sIp AND iq_stPollInterval.stPollintervalChangeClient.uiPort = i_stClientMonitored.uiPort) THEN")
    lines.append("    M_AddDataReportToReplyMessage(i_xReturnError := FALSE, i_sAction := 'update', i_sAccessible := 'pollinterval', i_sDataReport:= LREAL_TO_STRING(iq_stPollInterval.lrValue)); // Poll interval")
    lines.append("   END_IF")

    if resolved.interface_class == "Writable":
        target_expr = f"iq_{resolved.value.var_prefix}Target"
        lines.append("   // Update subscribers when changing the target")
        lines.append("   IF xTargetChanged AND NOT (iq_stTargetWrite.stTargetChangeClient.sIp = i_stClientMonitored.sIp AND iq_stTargetWrite.stTargetChangeClient.uiPort = i_stClientMonitored.uiPort) THEN")
        lines.extend(
            _target_data_report_lines(
                resolved=resolved,
                target_var=target_expr,
                action="'update'",
                accessible_expr="'target'",
                indent="    ",
            )
        )
        lines.append("   END_IF")

    lines.append("  END_IF")
    lines.append(" END_IF")
    lines.append("END_IF")
    lines.append("")
    lines.append("// Reset all flags and pollinterval handling variables when the client round is done")
    lines.append("IF xUpdateAllSubscribers AND fbRtrigAllClientsDone.Q THEN")
    lines.append(" xPollIntervalDone := FALSE;")
    lines.append(" xUpdateAllSubscribers := FALSE;")
    lines.append(" IF xPollIntervalChanged THEN")
    lines.append("  xPollIntervalChanged := FALSE;")
    lines.append("  iq_stPollInterval.stPollintervalChangeClient.sIp := '';")
    lines.append("  iq_stPollInterval.stPollintervalChangeClient.uiPort := 0;")
    lines.append(" END_IF")

    if resolved.interface_class == "Writable":
        lines.append(" IF xTargetChanged THEN")
        lines.append("  xTargetChanged := FALSE;")
        lines.append("  iq_stTargetWrite.stTargetChangeClient.sIp := '';")
        lines.append("  iq_stTargetWrite.stTargetChangeClient.uiPort := 0;")
        lines.append(" END_IF")

    lines.append("END_IF")
    lines.append("")

    return lines


def emit_async_block(resolved: ResolvedModuleClass, tasklist: TaskList) -> list[str]:
    """
    Emit the complete async block.

    For Drivable:
    - target drive state machine
    - handle updates

    For Readable / Writable:
    - handle updates only
    """
    lines: list[str] = []

    lines.append("// 2 - Asynchronous mode")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("")

    if resolved.interface_class == "Drivable":
        lines.extend(_emit_async_target_drive_state_machine(resolved))

    lines.extend(_emit_async_handle_updates(resolved, tasklist))

    return lines


def emit_target_drive_monitor_block(resolved: ResolvedModuleClass) -> list[str]:
    """
    Emit the final block that monitors target driving and updates status when done.

    Only applies to Drivable modules.

    Rules:
    - numeric LREAL -> lr, uses tolerance
    - numeric DINT  -> di, uses tolerance
    - enum          -> i,  tolerance fixed to 0
    - string        -> s,  uses ADR() pointers, no tolerance
    """
    lines: list[str] = []

    if resolved.interface_class != "Drivable":
        return lines

    lines.append("//  3 - Monitor target driving and update module status when done")
    lines.append("// ----------------------------------------------------------------------------")
    lines.append("")
    lines.append("// Monitor process value and target value. Set q_xSpReached to TRUE if target is reached on time. Set q_xSpFail to TRUE otherwise")

    if resolved.value.is_string:
        lines.append("fbTargetDriveMonitor(i_xEnable:= iq_stTargetDrive.uiState = 3,")
        lines.append("      i_pbPv:= ADR(iq_sValue),")
        lines.append("      i_pbSp:= ADR(iq_sTarget),")
        lines.append("      i_timTimeout:= iq_stTargetDrive.timTimeout);")
    else:
        if resolved.value.is_enum:
            mon_prefix = "i"
            pv_expr = "iq_etValue"
            sp_expr = "iq_etTarget"
            tol_expr = "0"
        else:
            mon_prefix = resolved.value.var_prefix
            pv_expr = f"iq_{resolved.value.var_prefix}Value"
            sp_expr = f"iq_{resolved.value.var_prefix}Target"
            tol_expr = f"iq_{resolved.value.var_prefix}TargetDriveTolerance"

        lines.append("fbTargetDriveMonitor(i_xEnable:= iq_stTargetDrive.uiState = 3,")
        lines.append(f"      i_{mon_prefix}Pv:= {pv_expr},")
        lines.append(f"      i_{mon_prefix}Sp:= {sp_expr},")
        lines.append(f"      i_{mon_prefix}Tolerance:= {tol_expr},")
        lines.append("      i_timTimeout:= iq_stTargetDrive.timTimeout);")

    lines.append("")
    lines.append('// Set module status to Idle if target is reached on time. Generate a "TimeoutError" error otherwise')
    lines.append("M_UpdateStatusWhenDriveDone(i_xDone:= fbTargetDriveMonitor.q_xDone AND fbRtrigAllClientsDone.Q,")
    lines.append("       i_xSpReached:= fbTargetDriveMonitor.q_xSpReached,")
    lines.append("       i_xTimeOutElapsed:= fbTargetDriveMonitor.q_xSpFail);")
    lines.append("")

    return lines