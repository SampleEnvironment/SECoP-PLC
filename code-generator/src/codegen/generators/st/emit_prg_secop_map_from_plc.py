"""
ST generator for PRG SecopMapFromPlc.

This PRG:
- calls SecopInit on first CPU cycle
- maps PLC process data to the SECoP layer
- updates SEC node timestamp / interface-ready flag
- updates each real module

Inputs:
- resolved_real_modules: module-instance data + x-plc
- resolved_module_classes: class-level data (especially enum members)
"""

from __future__ import annotations

from typing import List

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
)
from codegen.resolve.types import ResolvedModuleClasses


def _module_prefix(module_name: str) -> str:
    return f"GVL_SecNode.G_st_{module_name}"


def _emit_program_header() -> List[str]:
    lines: List[str] = []

    lines.append("PROGRAM SecopMapFromPlc")
    lines.append("VAR ")
    lines.append(" xSecopInitDone: BOOL := FALSE;")
    lines.append("END_VAR")
    lines.append("")

    return lines


def _emit_call_secop_init() -> List[str]:
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


def _emit_sec_node_mapping(resolved: ResolvedRealModules) -> List[str]:
    lines: List[str] = []
    sec_node = resolved.sec_node

    lines.append("// SEC node")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")
    lines.append("// Timestamp")
    lines.append(f"SECOP.GVL.G_st_SecNode.sTimestamp := {sec_node.plc_timestamp_tag};")
    lines.append("")
    lines.append("// Interface ready")
    lines.append(
        f"SECOP.GVL.G_st_SecNode.xTcpServerInterfaceReady := {sec_node.tcp_server_interface_healthy_tag};"
    )
    lines.append("")

    return lines


def _resolved_enum_members(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> list[tuple[str, int]]:
    """
    Return enum members for a real module using its module class.
    """
    resolved_class = resolved_classes.classes[module.module_class_name]
    if not resolved_class.value.members:
        return []
    return list(resolved_class.value.members.items())


def _emit_value_mapping(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> List[str]:
    lines: List[str] = []
    pfx = _module_prefix(module.module_name)

    lines.append("// Value")

    if module.value_is_numeric or module.value_is_string:
        expr = module.x_plc_value.read_expr if module.x_plc_value else None
        if expr:
            lines.append(f"{pfx}.{module.value_var_prefix}Value := {expr};")
        else:
            lines.append("// TODO_CODEGEN: manual implementation required for value mapping (missing read_expr)")
        lines.append("")
        return lines

    if module.value_is_enum:
        enum_tag = module.x_plc_value.enum_tag if module.x_plc_value else None
        members = _resolved_enum_members(module, resolved_classes)

        if enum_tag and members:
            lines.append(f"CASE {enum_tag} OF ")
            for member_name, member_value in members:
                lines.append(
                    f" {member_value}: {pfx}.etValue := ET_Module_{module.module_class_name}_value.{member_name};"
                )
            lines.append("END_CASE")
        else:
            lines.append("// TODO_CODEGEN: manual implementation required for enum value mapping")
        lines.append("")
        return lines

    lines.append("// TODO_CODEGEN: manual implementation required for unsupported value type")
    lines.append("")
    return lines


def _emit_target_change_interlock(module: ResolvedRealModule) -> List[str]:
    lines: List[str] = []

    if module.interface_class not in ("Writable", "Drivable"):
        return lines

    expr = module.x_plc_target.change_possible_expr if module.x_plc_target else None
    lines.append("// Target change interlock")
    if expr:
        lines.append(f"{_module_prefix(module.module_name)}.stTargetWrite.xPossible := {expr}")
    else:
        lines.append("// TODO_CODEGEN: manual implementation required for target interlock (missing change_possible_expr)")
    lines.append("")

    return lines


def _emit_timestamp_mapping(module: ResolvedRealModule) -> List[str]:
    lines: List[str] = []
    tag = module.x_plc_value.timestamp_tag if module.x_plc_value else ""
    lines.append("// Timestamp")
    lines.append(f"{_module_prefix(module.module_name)}.sTimestamp := {tag};")
    lines.append("")
    return lines


def _emit_clear_errors_reset(module: ResolvedRealModule) -> List[str]:
    lines: List[str] = []

    if module.has_clear_errors_command:
        lines.append("// Reset commands")
        lines.append(f"{_module_prefix(module.module_name)}.xClearErrors := FALSE;")
        lines.append("")

    return lines


def _emit_status_block(module: ResolvedRealModule) -> List[str]:
    lines: List[str] = []
    pfx = _module_prefix(module.module_name)

    lines.append("// Status and errors")

    branches_started = 0

    if module.status_has_disabled and module.x_plc_status:
        lines.append(f"IF {module.x_plc_status.disabled_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.et_StatusCode.Disabled;")
        lines.append(f" {pfx}.stStatus.sDescription := 'DISABLED';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE; ")
        lines.append(f" {pfx}.stErrorReport.sClass := 'DISABLED';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '{module.x_plc_status.disabled_description}';")
        branches_started += 1

    if module.status_has_hw_error and module.x_plc_status:
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {module.x_plc_status.hw_error_expr} THEN")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.et_StatusCode.Error;")
        lines.append(f" {pfx}.stStatus.sDescription := '{module.x_plc_status.hw_error_description}';")
        lines.append(f" {pfx}.stErrorReport.xActive := TRUE; ")
        lines.append(f" {pfx}.stErrorReport.sClass := 'HardwareError';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '{module.x_plc_status.hw_error_description}';")
        branches_started += 1

    if module.interface_class == "Drivable":
        kw = "ELSIF" if branches_started else "IF"
        lines.append(f"{kw} {pfx}.stTargetDrive.uiState=0 THEN // No target change is ongoing")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.et_StatusCode.Idle;")
        lines.append(f" {pfx}.stStatus.sDescription := 'IDLE';")
        lines.append(f" {pfx}.stErrorReport.xActive := FALSE; ")
        lines.append(f" {pfx}.stErrorReport.sClass := '';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '';")
        lines.append("END_IF")
    else:
        if branches_started:
            lines.append("ELSE")
        lines.append(f" {pfx}.stStatus.etCode := SECOP.et_StatusCode.Idle;")
        lines.append(f" {pfx}.stStatus.sDescription := 'IDLE';")
        lines.append(f" {pfx}.stErrorReport.xActive := FALSE; ")
        lines.append(f" {pfx}.stErrorReport.sClass := '';")
        lines.append(f" {pfx}.stErrorReport.sDescription := '';")
        if branches_started:
            lines.append("END_IF")

    lines.append("")
    return lines


def _emit_custom_parameters(module: ResolvedRealModule) -> List[str]:
    lines: List[str] = []

    for cp in module.custom_parameters:
        lines.append(f"// {cp.secop_name}")
        lines.append(
            f"// TODO_CODEGEN: map custom parameter {cp.secop_name} to {_module_prefix(module.module_name)}.{cp.plc_var_name}"
        )
        lines.append("")

    return lines


def _emit_module_mapping(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> List[str]:
    lines: List[str] = []

    lines.append(f"// {module.module_name}")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")

    lines.extend(_emit_value_mapping(module, resolved_classes))
    lines.extend(_emit_target_change_interlock(module))
    lines.extend(_emit_timestamp_mapping(module))
    lines.extend(_emit_clear_errors_reset(module))
    lines.extend(_emit_status_block(module))
    lines.extend(_emit_custom_parameters(module))

    return lines


def emit_prg_secop_map_from_plc(
    resolved_real_modules: ResolvedRealModules,
    resolved_module_classes: ResolvedModuleClasses,
) -> str:
    """
    Emit full ST source for PROGRAM SecopMapFromPlc.
    """
    lines: List[str] = []

    lines.extend(_emit_program_header())
    lines.extend(_emit_call_secop_init())
    lines.extend(_emit_sec_node_mapping(resolved_real_modules))

    for module_name in resolved_real_modules.sec_node.module_names_in_order:
        lines.extend(
            _emit_module_mapping(
                resolved_real_modules.modules[module_name],
                resolved_module_classes,
            )
        )

    return "\n".join(lines) + "\n"