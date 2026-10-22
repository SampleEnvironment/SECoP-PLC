"""
ST generator for PROGRAM SecopMapFromPlc.

This PRG:
- calls SecopInit on the first CPU cycle
- maps PLC process data to the SECoP layer
- updates SEC node timestamp / interface-ready flag
- updates each real module

Inputs
------
- resolved_real_modules:
    module-instance data + x-plc concrete values
- resolved_module_classes:
    class-level data, especially enum members

Design notes
------------
- This emitter only formats Structured Text.
- Structural applicability is decided earlier in the resolve layer.
- For project fields that always apply conceptually but are missing in the
  configuration, this emitter generates TASK comments and adds an entry to the
  task list instead of emitting invalid ST.
"""

from __future__ import annotations

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
    ResolvedRealCustomParameterPlc,
)
from codegen.resolve.types import ResolvedCustomParameter
from codegen.tasklist import TaskList
from codegen.generators.st.st_utils import format_st_string_literal


def _module_prefix(module_name: str) -> str:
    """
    Build the GVL prefix for one real module.
    """
    return f"GVL_SecNode.G_st_{module_name}"


def _emit_program_header(resolved: ResolvedRealModules) -> list[str]:
    """
    Emit the PROGRAM header and internal initialisation flag.

    When the structure report is dynamic (modules with x-plc.exclude_condition),
    the variables used to rebuild it are declared too.
    """
    lines: list[str] = []

    lines.append("PROGRAM SecopMapFromPlc")
    lines.append("VAR")
    lines.append(" xSecopInitDone: BOOL := FALSE;")
    if resolved.sec_node.structure_report_dynamic:
        n = len(_excludable_modules(resolved))
        lines.append(" // Dynamic SEC node structure report")
        lines.append(" xStructReportRebuild: BOOL := TRUE; // Rebuild request (TRUE: build on first cycle)")
        lines.append(" xStructReportBuilt: BOOL := FALSE; // Structure report built at least once")
        lines.append(f" axExcludedPrev: ARRAY[1..{n}] OF BOOL; // Previous xExcluded flags of the excludable modules")
        lines.append(" sStructReportSep: STRING(1); // Separator between modules")
    lines.append("END_VAR")
    lines.append("")

    return lines


def _emit_call_secop_init() -> list[str]:
    """
    Emit the one-time SecopInit() call.
    """
    lines: list[str] = []

    lines.append("// Initialise SECoP variables on CPU's first cycle")
    lines.append("IF NOT xSecopInitDone THEN")
    lines.append(" SecopInit();")
    lines.append("END_IF")
    lines.append("xSecopInitDone := TRUE;")
    lines.append("")
    lines.append("// Map PLC process data to SECoP layer")
    lines.append("")

    return lines



def _emit_sec_node_mapping(
    resolved: ResolvedRealModules,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit SEC node timestamp and interface-ready mapping.

    These concepts always apply in this project. Missing configured tags are
    turned into task comments and task-list entries.
    """
    lines: list[str] = []
    sec_node = resolved.sec_node

    lines.append("// SEC node")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")
    lines.append("// Timestamp")
    if sec_node.plc_timestamp_tag:
        lines.append(f"SECOP.GVL.G_st_SecNode.sTimestamp := {sec_node.plc_timestamp_tag};")
    else:
        lines.append(
            tasklist.make_st_comment(
                plc_path="SecopMapFromPlc.sec_node.timestamp",
                message=(
                    "Configure SEC node PLC timestamp tag and map it to "
                    "SECOP.GVL.G_st_SecNode.sTimestamp."
                ),
            )
        )
    lines.append("")
    lines.append("// Interface ready")
    if sec_node.tcp_server_interface_healthy_tag:
        lines.append(
            "SECOP.GVL.G_st_SecNode.xTcpServerInterfaceReady := "
            f"{sec_node.tcp_server_interface_healthy_tag};"
        )
    else:
        lines.append(
            tasklist.make_st_comment(
                plc_path="SecopMapFromPlc.sec_node.interface_ready",
                message=(
                    "Configure SEC node TCP interface healthy tag and map it to "
                    "SECOP.GVL.G_st_SecNode.xTcpServerInterfaceReady."
                ),
            )
        )
    lines.append("")

    return lines


def _emit_value_mapping(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit mapping for the standard SECoP accessible 'value'.

    Supported patterns:
    - numeric / string value -> x-plc.value.read_expr
    - enum value             -> x-plc.value.enum_tag (direct assignment; range
                                checking is handled in FB_Module_* at runtime).
                                BOOL_TO_INT(enum_tag) when
                                x-plc.value.enum_tag_is_bool is TRUE
    """
    lines: list[str] = []
    pfx = _module_prefix(module.module_name)

    lines.append("// Value")

    if module.value_is_numeric or module.value_is_string:
        expr = module.x_plc_value.read_expr if module.x_plc_value else None
        if expr:
            lines.append(f"{pfx}.{module.value_var_prefix}Value := {expr};")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.value",
                    message=(
                        f"Configure PLC-to-SECoP value mapping for module "
                        f"{module.module_name} (missing x-plc.value.read_expr)."
                    ),
                )
            )
        lines.append("")
        return lines

    if module.value_is_enum:
        enum_tag = module.x_plc_value.enum_tag if module.x_plc_value else None

        if enum_tag:
            if module.x_plc_value.enum_tag_is_bool:
                lines.append(f"{pfx}.etValue := BOOL_TO_INT({enum_tag});")
            else:
                lines.append(f"{pfx}.etValue := {enum_tag};")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.value",
                    message=(
                        f"Configure enum PLC-to-SECoP value mapping for "
                        f"module {module.module_name} (missing x-plc.value.enum_tag)."
                    ),
                )
            )
        lines.append("")
        return lines

    lines.append(
        tasklist.make_st_comment(
            plc_path=f"SecopMapFromPlc.{module.module_name}.value",
            message=(
                f"Manual PLC-to-SECoP value mapping is required for module "
                f"{module.module_name} because the value type is not supported "
                "by automatic generation."
            ),
        )
    )
    lines.append("")
    return lines


def _emit_target_change_interlock(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit mapping for the xPossible interlock used by Writable / Drivable target
    changes.
    """
    lines: list[str] = []

    if module.interface_class not in ("Writable", "Drivable"):
        return lines

    expr = module.x_plc_target.change_possible_expr if module.x_plc_target else None
    lines.append("// Target change interlock")
    if expr:
        lines.append(f"{_module_prefix(module.module_name)}.stTargetWrite.xPossible := {expr};")
    else:
        lines.append(
            tasklist.make_st_comment(
                plc_path=f"SecopMapFromPlc.{module.module_name}.target_change_interlock",
                message=(
                    f"Configure target interlock for module {module.module_name} "
                    f"(missing x-plc.target.change_possible_expr)."
                ),
            )
        )
    lines.append("")

    return lines


def _emit_timestamp_mapping(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit module timestamp mapping.

    Module timestamp mapping always applies conceptually in this project.
    Missing configuration becomes a task comment plus one task-list entry.
    """
    lines: list[str] = []

    lines.append("// Timestamp")
    tag = module.x_plc_value.timestamp_tag if module.x_plc_value else None
    if tag:
        lines.append(f"{_module_prefix(module.module_name)}.sTimestamp := {tag};")
    else:
        lines.append(
            tasklist.make_st_comment(
                plc_path=f"SecopMapFromPlc.{module.module_name}.timestamp",
                message=f"Configure module timestamp mapping for {module.module_name}.",
            )
        )
    lines.append("")

    return lines


def _emit_clear_errors_reset(module: ResolvedRealModule) -> list[str]:
    """
    Emit the reset of standard command flags that must be pulsed from PLC to
    SECoP side.
    """
    lines: list[str] = []

    if module.has_clear_errors_command:
        lines.append("// Reset commands")
        lines.append(f"{_module_prefix(module.module_name)}.xClearErrors := FALSE;")
        lines.append("")

    return lines


def _emit_status_block(module: ResolvedRealModule) -> list[str]:
    """
    Emit the status-and-error evaluation block.

    Priority order (SECoP does not define one; only one status can be shown):
    1) Disabled
    2) Communication error
    3) Hardware error
    4) Value is NaN (x-plc.value.handle_nan)
    5) Normal state logic
    """
    lines: list[str] = []
    pfx = _module_prefix(module.module_name)

    lines.append("// Status and errors")

    branches_started = 0

    disabled_expr = module.x_plc_status.disabled_expr if module.x_plc_status else None
    disabled_desc = module.x_plc_status.disabled_description if module.x_plc_status else None
    if module.status_has_disabled and disabled_expr and disabled_desc:
        lines.append(f"IF {disabled_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Disabled;")
        lines.append(f" {pfx}.stStatus.sDescription := 'DISABLED';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'Disabled';") # SECoP error class (not the status enum name)
        lines.append(f" {pfx}.stErrorReport.sDescription := {format_st_string_literal(disabled_desc)};")
        branches_started += 1

    if module.status_has_comm_error and module.x_plc_status:
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {module.x_plc_status.comm_error_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Error;")
        lines.append(f" {pfx}.stStatus.sDescription := {format_st_string_literal(module.x_plc_status.comm_error_description)};")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'CommunicationFailed';")
        lines.append(f" {pfx}.stErrorReport.sDescription := {format_st_string_literal(module.x_plc_status.comm_error_description)};")
        branches_started += 1

    if module.status_has_hw_error and module.x_plc_status:
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {module.x_plc_status.hw_error_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Error;")
        lines.append(f" {pfx}.stStatus.sDescription := {format_st_string_literal(module.x_plc_status.hw_error_description)};")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'HardwareError';")
        lines.append(f" {pfx}.stErrorReport.sDescription := {format_st_string_literal(module.x_plc_status.hw_error_description)};")
        branches_started += 1

    if module.x_plc_value and module.x_plc_value.handle_nan:
        # NaN is the only value not equal to itself. JSON can not carry NaN,
        # so an error report is sent instead of the value.
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {pfx}.lrValue <> {pfx}.lrValue THEN // NaN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Error;")
        lines.append(f" {pfx}.stStatus.sDescription := 'Value is NaN';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'ReadFailed';")
        lines.append(f" {pfx}.stErrorReport.sDescription := 'Value is NaN';")
        branches_started += 1

    if module.interface_class == "Drivable":
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {pfx}.stTargetDrive.uiState = 0 THEN // No target change is ongoing")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Idle;")
        lines.append(f" {pfx}.stStatus.sDescription := 'IDLE';")
        lines.append(f" {pfx}.stErrorReport.xActive := FALSE;")
        lines.append(f" {pfx}.stErrorReport.sClass := '';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '';")
        lines.append("END_IF")
    else:
        if branches_started:
            lines.append("ELSE")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Idle;")
        lines.append(f" {pfx}.stStatus.sDescription := 'IDLE';")
        lines.append(f" {pfx}.stErrorReport.xActive := FALSE;")
        lines.append(f" {pfx}.stErrorReport.sClass := '';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '';")
        if branches_started:
            lines.append("END_IF")

    lines.append("")
    return lines


def _emit_one_custom_parameter_mapping(
    module: ResolvedRealModule,
    cp: ResolvedCustomParameter,
    cp_plc: ResolvedRealCustomParameterPlc | None,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit mapping for one customised parameter.

    Supported patterns:
    - numeric / string custom parameter -> read_expr
    - enum custom parameter             -> enum_tag
    """
    lines: list[str] = []
    pfx = _module_prefix(module.module_name)
    lhs = f"{pfx}.{cp.plc_var_name}"

    lines.append(f"// {cp.secop_name}")

    if cp.is_numeric or cp.is_string:
        expr = cp_plc.read_expr if cp_plc else None
        if expr:
            lines.append(f"{lhs} := {expr};")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.{cp.secop_name}",
                    message=(
                        f"Configure mapping for customised parameter {cp.secop_name} "
                        f"of module {module.module_name} "
                        f"(missing x-plc.custom_parameters.{cp.secop_name}.read_expr)."
                    ),
                )
            )
        lines.append("")
        return lines

    if cp.is_enum:
        enum_tag = cp_plc.enum_tag if cp_plc else None

        if enum_tag:
            if cp_plc.enum_tag_is_bool:
                lines.append(f"{lhs} := BOOL_TO_INT({enum_tag});")
            else:
                lines.append(f"{lhs} := {enum_tag};")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.{cp.secop_name}",
                    message=(
                        f"Configure enum mapping for customised parameter "
                        f"{cp.secop_name} of module {module.module_name} "
                        f"(missing x-plc.custom_parameters.{cp.secop_name}.enum_tag)."
                    ),
                )
            )
        lines.append("")
        return lines

    lines.append(
        tasklist.make_st_comment(
            plc_path=f"SecopMapFromPlc.{module.module_name}.{cp.secop_name}",
            message=(
                f"Manual mapping is required for customised parameter {cp.secop_name} "
                f"of module {module.module_name} because its type is not supported "
                "by automatic generation."
            ),
        )
    )
    lines.append("")
    return lines


def _emit_custom_parameters(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit mappings for all resolved customised parameters of one real module.
    """
    lines: list[str] = []

    for cp in module.custom_parameters:
        cp_plc = module.x_plc_custom_parameters.get(cp.secop_name)
        lines.extend(_emit_one_custom_parameter_mapping(module, cp, cp_plc, tasklist))

    return lines


def _emit_target_limits_plc_mapping(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit PLC-driven readonly target limits mapping.

    When a limit accessible is readonly (PLC-driven rather than SECoP-client-driven),
    the live PLC process value must be assigned to lrTargetLimitsMin / lrTargetLimitsMax
    every CPU cycle.  The expression comes from x-plc.target.limit_min/max_expr.

    Called for:
    - target_min  with readonly=true  -> assign lrTargetLimitsMin from limit_min_expr
    - target_max  with readonly=true  -> assign lrTargetLimitsMax from limit_max_expr
    - target_limits with readonly=true -> assign both
    """
    lines: list[str] = []

    # Determine which sides need PLC-driven assignment
    need_min = (
        (bool(module.target_has_limits_min)   and bool(module.target_has_limits_min_readonly)) or
        (bool(module.target_has_limits_tuple) and bool(module.target_has_limits_tuple_readonly))
    )
    need_max = (
        (bool(module.target_has_limits_max)   and bool(module.target_has_limits_max_readonly)) or
        (bool(module.target_has_limits_tuple) and bool(module.target_has_limits_tuple_readonly))
    )

    if not need_min and not need_max:
        return lines

    pfx = _module_prefix(module.module_name)
    vp  = module.value_var_prefix

    if need_min:
        lines.append("// Target limit min")
        expr = module.x_plc_target.limit_min_expr if module.x_plc_target else None
        if expr:
            lines.append(f"{pfx}.{vp}TargetLimitsMin := {expr};")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.target_limits_min",
                    message=(
                        f"Map PLC process expression to {vp}TargetLimitsMin for module "
                        f"{module.module_name} (missing x-plc.target.limit_min_expr)."
                    ),
                )
            )
        lines.append("")

    if need_max:
        lines.append("// Target limit max")
        expr = module.x_plc_target.limit_max_expr if module.x_plc_target else None
        if expr:
            lines.append(f"{pfx}.{vp}TargetLimitsMax := {expr};")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.target_limits_max",
                    message=(
                        f"Map PLC process expression to {vp}TargetLimitsMax for module "
                        f"{module.module_name} (missing x-plc.target.limit_max_expr)."
                    ),
                )
            )
        lines.append("")

    return lines


def _emit_target_drive_tolerance_mapping(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit PLC-driven drive tolerance mapping for Drivable numeric modules.

    The tolerance is assigned every CPU cycle from a PLC expression so that it
    can track a live process variable rather than a fixed constant at init time.
    """
    lines: list[str] = []

    if module.interface_class != "Drivable" or not module.value_is_numeric:
        return lines

    pfx = _module_prefix(module.module_name)
    vp  = module.value_var_prefix

    lines.append("// Target drive - absolute tolerance to consider target reached")
    expr = module.x_plc_target.reach_abs_tolerance_expr if module.x_plc_target else None
    if expr:
        lines.append(f"{pfx}.{vp}TargetDriveTolerance := {expr};")
    else:
        lines.append(
            tasklist.make_st_comment(
                plc_path=f"SecopMapFromPlc.{module.module_name}.target_drive_tolerance",
                message=(
                    f"Configure target drive absolute tolerance mapping for module "
                    f"{module.module_name} "
                    f"(missing x-plc.target.reach_abs_tolerance_expr)."
                ),
            )
        )
    lines.append("")

    return lines


def _emit_exclude_condition(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit the optional module exclusion condition.

    x-plc.exclude_condition is a PLC boolean expression. When configured, its
    value is assigned to xExcluded every CPU cycle; while it holds, the module
    is left out of the SEC node structure report and the module FB replies
    "NoSuchModule" to clients.

    Three cases (see ResolvedRealModule.exclude_condition_raw):
    - absent           -> nothing is emitted (module always included)
    - configured       -> assign the expression
    - present but empty -> emit a task marker
    """
    raw = module.exclude_condition_raw
    if raw is None:
        return []

    lines: list[str] = []
    lines.append("// Exclude condition")

    expr = raw.strip()
    if expr:
        lines.append(f"{_module_prefix(module.module_name)}.xExcluded := {expr};")
    else:
        lines.append(
            tasklist.make_st_comment(
                plc_path=f"SecopMapFromPlc.{module.module_name}.exclude_condition",
                message=(
                    f"Configure module exclusion condition for "
                    f"{module.module_name} (x-plc.exclude_condition is present "
                    "but empty)."
                ),
            )
        )
    lines.append("")

    return lines


def _excludable_modules(resolved: ResolvedRealModules) -> list[str]:
    """
    Modules (in config order) that have the x-plc.exclude_condition key.
    """
    return [
        name
        for name in resolved.sec_node.module_names_in_order
        if resolved.modules[name].exclude_condition_raw is not None
    ]


def _emit_structure_report_rebuild(resolved: ResolvedRealModules) -> list[str]:
    """
    Emit the dynamic SEC node structure report block.

    Only emitted when at least one module has x-plc.exclude_condition. The
    structure report is rebuilt from the constants in GVL_SecNode
    (Gc_sStructReportHead, Gc_sStructReport_<module>, Gc_sStructReportTail),
    including only the non-excluded modules:
    - on the first cycle;
    - whenever the xExcluded flag of any excludable module changes. In that case
      all SECoP clients are also disconnected, so that they get the new
      structure report (describe) on reconnection.

    It is placed at the end of SecopMapFromPlc, after all xExcluded flags have
    been updated.
    """
    sec_node = resolved.sec_node
    if not sec_node.structure_report_dynamic:
        return []

    excludable = _excludable_modules(resolved)
    report = "SECOP.GVL.G_st_SecNode.sStructureReport"
    concat_tail = (
        f"pstTo:= ADR({report}), "
        "iBufferSize:= UINT_TO_INT(SECOP.GPL.Gc_uiMaxSizeMessage));"
    )

    lines: list[str] = []
    lines.append("// SEC node structure report")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")
    lines.append("// Detect equipment configuration changes (excluded modules)")
    for idx, name in enumerate(excludable, start=1):
        lines.append(
            f"IF {_module_prefix(name)}.xExcluded <> axExcludedPrev[{idx}] THEN "
            "xStructReportRebuild := TRUE; END_IF"
        )
    lines.append("")
    lines.append("// Rebuild the structure report with the non-excluded modules")
    lines.append("IF xStructReportRebuild THEN")
    lines.append(" xStructReportRebuild := FALSE;")
    lines.append("")
    lines.append(" // Disconnect all clients (except on first build) so they get the new structure on reconnection")
    lines.append(" IF xStructReportBuilt THEN")
    lines.append("  SECOP.Server.xCmdDisconnectAll := TRUE;")
    lines.append(" END_IF")
    lines.append(" xStructReportBuilt := TRUE;")
    lines.append("")
    lines.append(" // Store current exclusion flags")
    for idx, name in enumerate(excludable, start=1):
        lines.append(f" axExcludedPrev[{idx}] := {_module_prefix(name)}.xExcluded;")
    lines.append("")
    lines.append(" // Head (SEC node properties)")
    lines.append(f" {report} := GVL_SecNode.Gc_sStructReportHead;")
    lines.append(" sStructReportSep := '';")
    lines.append("")
    lines.append(" // Modules")
    for name in sec_node.module_names_in_order:
        if name in excludable:
            lines.append(f" IF NOT {_module_prefix(name)}.xExcluded THEN")
            ind = "  "
        else:
            ind = " "
        lines.append(f"{ind}StrConcatA(pstFrom:= ADR(sStructReportSep), {concat_tail}")
        lines.append(f"{ind}StrConcatA(pstFrom:= ADR(GVL_SecNode.Gc_sStructReport_{name}), {concat_tail}")
        lines.append(f"{ind}sStructReportSep := ',';")
        if name in excludable:
            lines.append(" END_IF")
    lines.append("")
    lines.append(" // Tail")
    lines.append(f" StrConcatA(pstFrom:= ADR(GVL_SecNode.Gc_sStructReportTail), {concat_tail}")
    lines.append("END_IF")
    lines.append("")

    return lines


def _emit_module_mapping(
    module: ResolvedRealModule,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit the full PLC-to-SECoP mapping block for one real module.
    """
    lines: list[str] = []

    lines.append(f"// {module.module_name}")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")

    lines.extend(_emit_exclude_condition(module, tasklist))
    lines.extend(_emit_value_mapping(module, tasklist))
    lines.extend(_emit_target_change_interlock(module, tasklist))
    lines.extend(_emit_target_limits_plc_mapping(module, tasklist))
    lines.extend(_emit_target_drive_tolerance_mapping(module, tasklist))
    lines.extend(_emit_timestamp_mapping(module, tasklist))
    lines.extend(_emit_clear_errors_reset(module))
    lines.extend(_emit_status_block(module))
    lines.extend(_emit_custom_parameters(module, tasklist))

    return lines


def emit_prg_secop_map_from_plc(
    resolved_real_modules: ResolvedRealModules,
    tasklist: TaskList,
) -> str:
    """
    Emit full ST source for PROGRAM SecopMapFromPlc.
    """
    lines: list[str] = []

    lines.extend(_emit_program_header(resolved_real_modules))
    lines.extend(_emit_call_secop_init())
    lines.extend(_emit_sec_node_mapping(resolved_real_modules, tasklist))

    for module_name in resolved_real_modules.sec_node.module_names_in_order:
        lines.extend(
            _emit_module_mapping(
                resolved_real_modules.modules[module_name],
                tasklist,
            )
        )

    lines.extend(_emit_structure_report_rebuild(resolved_real_modules))

    return "\n".join(lines) + "\n"