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

from typing import List

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
    ResolvedRealCustomParameterPlc,
)
from codegen.resolve.types import ResolvedModuleClasses, ResolvedCustomParameter
from codegen.tasklist import TaskList


def _module_prefix(module_name: str) -> str:
    """
    Build the GVL prefix for one real module.
    """
    return f"GVL_SecNode.G_st_{module_name}"


def _emit_program_header() -> List[str]:
    """
    Emit the PROGRAM header and internal initialisation flag.
    """
    lines: List[str] = []

    lines.append("PROGRAM SecopMapFromPlc")
    lines.append("VAR")
    lines.append(" xSecopInitDone: BOOL := FALSE;")
    lines.append("END_VAR")
    lines.append("")

    return lines


def _emit_call_secop_init() -> List[str]:
    """
    Emit the one-time SecopInit() call.
    """
    lines: List[str] = []

    lines.append("// Initialise SECoP variables on CPU's first cycle")
    lines.append("IF NOT xSecopInitDone THEN")
    lines.append(" SecopInit();")
    lines.append("END_IF")
    lines.append("xSecopInitDone := TRUE;")
    lines.append("")
    lines.append("// Map PLC process data to SECoP layer")
    lines.append("")

    return lines


def _resolved_enum_members(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> list[tuple[str, int]]:
    """
    Return enum members for a real module using its resolved module class.

    Returned format:
        [(member_name, member_value), ...]
    """
    resolved_class = resolved_classes.classes[module.module_class_name]
    if not resolved_class.value.members:
        return []
    return list(resolved_class.value.members.items())


def _custom_parameter_enum_members(
    cp: ResolvedCustomParameter,
) -> list[tuple[str, int]]:
    """
    Return enum members for one resolved customised parameter.
    """
    if not cp.members:
        return []
    return list(cp.members.items())


def _emit_sec_node_mapping(
    resolved: ResolvedRealModules,
    tasklist: TaskList,
) -> List[str]:
    """
    Emit SEC node timestamp and interface-ready mapping.

    These concepts always apply in this project. Missing configured tags are
    turned into task comments and task-list entries.
    """
    lines: List[str] = []
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
    resolved_classes: ResolvedModuleClasses,
    tasklist: TaskList,
) -> List[str]:
    """
    Emit mapping for the standard SECoP accessible 'value'.

    Supported patterns:
    - numeric / string value -> x-plc.value.read_expr
    - enum value             -> x-plc.value.enum_tag
    """
    lines: List[str] = []
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
                        f"Configure automatic PLC-to-SECoP value mapping for module "
                        f"{module.module_name} (missing x-plc.value.read_expr)."
                    ),
                )
            )
        lines.append("")
        return lines

    if module.value_is_enum:
        enum_tag = module.x_plc_value.enum_tag if module.x_plc_value else None
        members = _resolved_enum_members(module, resolved_classes)

        if enum_tag and members:
            lines.append(f"CASE {enum_tag} OF")
            for member_name, member_value in members:
                lines.append(
                    f" {member_value}: {pfx}.etValue := ET_Module_{module.module_class_name}_value.{member_name};"
                )
            lines.append("END_CASE")
        else:
            lines.append(
                tasklist.make_st_comment(
                    plc_path=f"SecopMapFromPlc.{module.module_name}.value",
                    message=(
                        f"Configure automatic enum PLC-to-SECoP value mapping for "
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
) -> List[str]:
    """
    Emit mapping for the xPossible interlock used by Writable / Drivable target
    changes.
    """
    lines: List[str] = []

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
) -> List[str]:
    """
    Emit module timestamp mapping.

    Module timestamp mapping always applies conceptually in this project.
    Missing configuration becomes a task comment plus one task-list entry.
    """
    lines: List[str] = []

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


def _emit_clear_errors_reset(module: ResolvedRealModule) -> List[str]:
    """
    Emit the reset of standard command flags that must be pulsed from PLC to
    SECoP side.
    """
    lines: List[str] = []

    if module.has_clear_errors_command:
        lines.append("// Reset commands")
        lines.append(f"{_module_prefix(module.module_name)}.xClearErrors := FALSE;")
        lines.append("")

    return lines


def _emit_status_block(module: ResolvedRealModule) -> List[str]:
    """
    Emit the status-and-error evaluation block.

    Priority order:
    1) Disabled
    2) Communication error
    3) Hardware error
    4) Normal state logic
    """
    lines: List[str] = []
    pfx = _module_prefix(module.module_name)

    lines.append("// Status and errors")

    branches_started = 0

    if module.status_has_disabled and module.x_plc_status:
        lines.append(f"IF {module.x_plc_status.disabled_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Disabled;")
        lines.append(f" {pfx}.stStatus.sDescription := 'DISABLED';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'DISABLED';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '{module.x_plc_status.disabled_description}';")
        branches_started += 1

    if module.status_has_comm_error and module.x_plc_status:
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {module.x_plc_status.comm_error_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Error;")
        lines.append(f" {pfx}.stStatus.sDescription := '{module.x_plc_status.comm_error_description}';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'CommunicationFailed';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '{module.x_plc_status.comm_error_description}';")
        branches_started += 1

    if module.status_has_hw_error and module.x_plc_status:
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {module.x_plc_status.hw_error_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Error;")
        lines.append(f" {pfx}.stStatus.sDescription := '{module.x_plc_status.hw_error_description}';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE;")
        lines.append(f" {pfx}.stErrorReport.sClass := 'HardwareError';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '{module.x_plc_status.hw_error_description}';")
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
) -> List[str]:
    """
    Emit mapping for one customised parameter.

    Supported patterns:
    - numeric / string custom parameter -> read_expr
    - enum custom parameter             -> enum_tag
    """
    lines: List[str] = []
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
        members = _custom_parameter_enum_members(cp)

        if enum_tag and members:
            lines.append(f"CASE {enum_tag} OF")
            for member_name, member_value in members:
                lines.append(f" {member_value}: {lhs} := {cp.plc_type}.{member_name};")
            lines.append("END_CASE")
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
) -> List[str]:
    """
    Emit mappings for all resolved customised parameters of one real module.
    """
    lines: List[str] = []

    for cp in module.custom_parameters:
        cp_plc = module.x_plc_custom_parameters.get(cp.secop_name)
        lines.extend(_emit_one_custom_parameter_mapping(module, cp, cp_plc, tasklist))

    return lines


def _emit_module_mapping(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
    tasklist: TaskList,
) -> List[str]:
    """
    Emit the full PLC-to-SECoP mapping block for one real module.
    """
    lines: List[str] = []

    lines.append(f"// {module.module_name}")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")

    lines.extend(_emit_value_mapping(module, resolved_classes, tasklist))
    lines.extend(_emit_target_change_interlock(module, tasklist))
    lines.extend(_emit_timestamp_mapping(module, tasklist))
    lines.extend(_emit_clear_errors_reset(module))
    lines.extend(_emit_status_block(module))
    lines.extend(_emit_custom_parameters(module, tasklist))

    return lines


def emit_prg_secop_map_from_plc(
    resolved_real_modules: ResolvedRealModules,
    resolved_module_classes: ResolvedModuleClasses,
    tasklist: TaskList,
) -> str:
    """
    Emit full ST source for PROGRAM SecopMapFromPlc.
    """
    lines: List[str] = []

    lines.extend(_emit_program_header())
    lines.extend(_emit_call_secop_init())
    lines.extend(_emit_sec_node_mapping(resolved_real_modules, tasklist))

    for module_name in resolved_real_modules.sec_node.module_names_in_order:
        lines.extend(
            _emit_module_mapping(
                resolved_real_modules.modules[module_name],
                resolved_module_classes,
                tasklist,
            )
        )

    return "\n".join(lines) + "\n"