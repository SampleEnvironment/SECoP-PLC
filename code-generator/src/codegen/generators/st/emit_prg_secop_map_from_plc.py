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
  configuration, this emitter generates TODO_CODEGEN comments instead of invalid
  ST.
"""

from __future__ import annotations

from typing import List

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
    ResolvedRealCustomParameterPlc,
)
from codegen.resolve.types import ResolvedModuleClasses, ResolvedCustomParameter


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


def _emit_optional_assignment(
    lhs: str,
    rhs_expr: str | None,
    todo_message: str,
) -> List[str]:
    """
    Emit one ST assignment if the right-hand-side expression is available.

    Otherwise emit a TODO_CODEGEN comment.
    """
    if rhs_expr is None:
        return [f"// TODO_CODEGEN: {todo_message}"]
    return [f"{lhs} := {rhs_expr};"]


def _emit_sec_node_mapping(resolved: ResolvedRealModules) -> List[str]:
    """
    Emit SEC node timestamp and interface-ready mapping.

    These concepts always apply in this project. Missing configured tags are
    turned into TODO_CODEGEN comments.
    """
    lines: List[str] = []
    sec_node = resolved.sec_node

    lines.append("// SEC node")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")
    lines.append("// Timestamp")
    lines.extend(
        _emit_optional_assignment(
            "SECOP.GVL.G_st_SecNode.sTimestamp",
            sec_node.plc_timestamp_tag,
            "configure SEC node PLC timestamp tag",
        )
    )
    lines.append("")
    lines.append("// Interface ready")
    lines.extend(
        _emit_optional_assignment(
            "SECOP.GVL.G_st_SecNode.xTcpServerInterfaceReady",
            sec_node.tcp_server_interface_healthy_tag,
            "configure SEC node TCP interface healthy tag",
        )
    )
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


def _emit_value_mapping(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
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
            lines.append("// TODO_CODEGEN: configure value mapping (missing x-plc.value.read_expr)")
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
            lines.append("// TODO_CODEGEN: configure enum value mapping (missing x-plc.value.enum_tag)")
        lines.append("")
        return lines

    lines.append("// TODO_CODEGEN: manual implementation required for unsupported value type")
    lines.append("")
    return lines


def _emit_target_change_interlock(module: ResolvedRealModule) -> List[str]:
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
        lines.append("// TODO_CODEGEN: configure target interlock (missing x-plc.target.change_possible_expr)")
    lines.append("")

    return lines


def _emit_timestamp_mapping(module: ResolvedRealModule) -> List[str]:
    """
    Emit module timestamp mapping.

    The module timestamp concept always applies in this project. Missing
    configuration therefore becomes TODO_CODEGEN instead of invalid ST.
    """
    lines: List[str] = []

    lines.append("// Timestamp")
    tag = module.x_plc_value.timestamp_tag if module.x_plc_value else None
    if tag:
        lines.append(f"{_module_prefix(module.module_name)}.sTimestamp := {tag};")
    else:
        lines.append("// TODO_CODEGEN: configure module timestamp tag")
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
                f"// TODO_CODEGEN: configure mapping for customised parameter {cp.secop_name} "
                f"(missing x-plc.custom_parameters.{cp.secop_name}.read_expr)"
            )
        lines.append("")
        return lines

    if cp.is_enum:
        enum_tag = cp_plc.enum_tag if cp_plc else None
        members = _custom_parameter_enum_members(cp)

        if enum_tag and members:
            lines.append(f"CASE {enum_tag} OF")
            for member_name, member_value in members:
                lines.append(
                    f" {member_value}: {lhs} := {cp.plc_type}.{member_name};"
                )
            lines.append("END_CASE")
        else:
            lines.append(
                f"// TODO_CODEGEN: configure enum mapping for customised parameter {cp.secop_name} "
                f"(missing x-plc.custom_parameters.{cp.secop_name}.enum_tag)"
            )
        lines.append("")
        return lines

    lines.append(
        f"// TODO_CODEGEN: manual implementation required for customised parameter {cp.secop_name}"
    )
    lines.append("")
    return lines


def _emit_custom_parameters(module: ResolvedRealModule) -> List[str]:
    """
    Emit mappings for all resolved customised parameters of one real module.
    """
    lines: List[str] = []

    for cp in module.custom_parameters:
        cp_plc = module.x_plc_custom_parameters.get(cp.secop_name)
        lines.extend(_emit_one_custom_parameter_mapping(module, cp, cp_plc))

    return lines


def _emit_module_mapping(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> List[str]:
    """
    Emit the full PLC-to-SECoP mapping block for one real module.
    """
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