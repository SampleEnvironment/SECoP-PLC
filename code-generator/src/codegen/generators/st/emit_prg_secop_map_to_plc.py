"""
ST generator for PROGRAM SecopMapToPlc.

This PRG:
- applies SECoP target values to PLC hardware
- applies clear_errors commands
- clears the SEC node error report when any module clear_errors command is active

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
- Missing PLC mapping details do not generate invalid ST. When a concept applies
  but its configuration is missing, the emitter writes TODO_CODEGEN comments.
"""

from __future__ import annotations

from typing import List

from codegen.resolve.real_modules import (
    ResolvedRealModule,
    ResolvedRealModules,
)
from codegen.resolve.types import ResolvedModuleClasses


def _module_prefix(module_name: str) -> str:
    """
    Build the GVL prefix for one real module.
    """
    return f"GVL_SecNode.G_st_{module_name}"


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


def _is_drivable(module: ResolvedRealModule) -> bool:
    """
    Return True when the real module belongs to the Drivable interface class.
    """
    return module.interface_class == "Drivable"


def _is_writable_not_drivable(module: ResolvedRealModule) -> bool:
    """
    Return True for Writable modules that are not Drivable.
    """
    return module.interface_class == "Writable"


def _needs_rtrig(module: ResolvedRealModule) -> bool:
    """
    Drivable modules use a rising-edge trigger to start target application.
    """
    return _is_drivable(module)


def _needs_num_monitor(module: ResolvedRealModule) -> bool:
    """
    Writable non-Drivable numeric/enum targets use FB_MonitorNumValue to detect
    target changes.
    """
    return _is_writable_not_drivable(module) and (
        module.value_is_numeric or module.value_is_enum
    )


def _needs_small_string_monitor(module: ResolvedRealModule) -> bool:
    """
    Writable non-Drivable string targets use FB_MonitorSmallString to detect
    target changes.
    """
    return _is_writable_not_drivable(module) and module.value_is_string


def _emit_var_block(resolved_real_modules: ResolvedRealModules) -> List[str]:
    """
    Emit the PROGRAM header and internal helper FB instances.
    """
    lines: List[str] = []

    lines.append("PROGRAM SecopMapToPlc")
    lines.append("VAR")

    for module_name in resolved_real_modules.sec_node.module_names_in_order:
        module = resolved_real_modules.modules[module_name]

        if _needs_rtrig(module):
            lines.append(f" fbRtrigApplyTarget_{module_name} : R_TRIG;")

        if _needs_num_monitor(module):
            lines.append(f" fbMonitorNumValue_{module_name} : SECOP.FB_MonitorNumValue;")

        if _needs_small_string_monitor(module):
            lines.append(f" fbMonitorSmallString_{module_name} : SECOP.FB_MonitorSmallString;")

    lines.append("END_VAR")
    lines.append("")

    return lines


def _target_monitor_input_expr(module: ResolvedRealModule) -> str:
    """
    Build the i_rVar expression for FB_MonitorNumValue.

    Conversion rules:
    - enum  -> INT_TO_REAL(...)
    - LREAL -> LREAL_TO_REAL(...)
    - DINT  -> DINT_TO_REAL(...)
    """
    pfx = _module_prefix(module.module_name)

    if module.value_is_enum:
        return f"INT_TO_REAL({pfx}.etTarget)"

    if module.value_plc_type == "LREAL":
        return f"LREAL_TO_REAL({pfx}.{module.value_var_prefix}Target)"

    if module.value_plc_type == "DINT":
        return f"DINT_TO_REAL({pfx}.{module.value_var_prefix}Target)"

    raise ValueError(
        f"Unsupported numeric target monitor conversion for module {module.module_name} "
        f"with PLC type {module.value_plc_type}"
    )


def _emit_drivable_apply_target_block(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> List[str]:
    """
    Emit target application logic for Drivable modules.

    Supported patterns:
    - numeric / string target -> x-plc.target.write_stmt
    - enum target             -> x-plc.target.enum_tag
    """
    lines: List[str] = []
    pfx = _module_prefix(module.module_name)

    if not _is_drivable(module):
        return lines

    lines.append("// Apply new target value in hardware")
    lines.append(
        f"fbRtrigApplyTarget_{module.module_name}(CLK:= {pfx}.stTargetDrive.uiState = 1);"
    )
    lines.append(f"IF fbRtrigApplyTarget_{module.module_name}.Q THEN")

    if module.value_is_numeric or module.value_is_string:
        write_stmt = module.x_plc_target.write_stmt if module.x_plc_target else None
        if write_stmt:
            lines.append(f" {write_stmt};")
        else:
            lines.append(" // TODO_CODEGEN: configure target write statement (missing x-plc.target.write_stmt)")

    elif module.value_is_enum:
        enum_tag = module.x_plc_target.enum_tag if module.x_plc_target else None
        members = _resolved_enum_members(module, resolved_classes)

        if enum_tag and members:
            lines.append(f" CASE {pfx}.etTargetChangeNewVal OF")
            for member_name, member_value in members:
                lines.append(
                    f"  {member_value}: {enum_tag} := ET_Module_{module.module_class_name}_value.{member_name};"
                )
            lines.append(" END_CASE")
        else:
            lines.append(" // TODO_CODEGEN: configure enum target write mapping (missing x-plc.target.enum_tag)")

    else:
        lines.append(" // TODO_CODEGEN: manual implementation required for unsupported Drivable target type")

    lines.append(f" {pfx}.stStatus.etCode := SECOP.ET_StatusCode.Busy;")
    lines.append(f" {pfx}.stStatus.sDescription := 'BUSY';")
    lines.append(f" {pfx}.stErrorReport.sClass := '';")
    lines.append(f" {pfx}.stErrorReport.sDescription := '';")
    lines.append(f" {pfx}.{module.value_var_prefix}Target := {pfx}.{module.value_var_prefix}TargetChangeNewVal;")
    lines.append(f" {pfx}.stTargetDrive.uiState := 2;")
    lines.append("END_IF")
    lines.append("")

    return lines


def _emit_writable_apply_target_block(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> List[str]:
    """
    Emit target application logic for Writable non-Drivable modules.

    Supported patterns:
    - numeric target -> x-plc.target.write_stmt
    - string target  -> x-plc.target.write_stmt
    - enum target    -> x-plc.target.enum_tag
    """
    lines: List[str] = []
    pfx = _module_prefix(module.module_name)

    if not _is_writable_not_drivable(module):
        return lines

    lines.append("// Apply new target value in hardware")

    if _needs_num_monitor(module):
        lines.append(
            f"fbMonitorNumValue_{module.module_name}(i_rVar:= {_target_monitor_input_expr(module)});"
        )
        lines.append(f"IF fbMonitorNumValue_{module.module_name}.q_xHasChanged THEN")

        if module.value_is_numeric:
            write_stmt = module.x_plc_target.write_stmt if module.x_plc_target else None
            if write_stmt:
                lines.append(f" {write_stmt};")
            else:
                lines.append(" // TODO_CODEGEN: configure target write statement (missing x-plc.target.write_stmt)")

        elif module.value_is_enum:
            enum_tag = module.x_plc_target.enum_tag if module.x_plc_target else None
            members = _resolved_enum_members(module, resolved_classes)

            if enum_tag and members:
                lines.append(f" CASE {pfx}.etTarget OF")
                for member_name, member_value in members:
                    lines.append(
                        f"  {member_value}: {enum_tag} := ET_Module_{module.module_class_name}_value.{member_name};"
                    )
                lines.append(" END_CASE")
            else:
                lines.append(" // TODO_CODEGEN: configure enum target write mapping (missing x-plc.target.enum_tag)")

        lines.append("END_IF")
        lines.append("")
        return lines

    if _needs_small_string_monitor(module):
        lines.append(
            f"fbMonitorSmallString_{module.module_name}(i_sVar:= {pfx}.sTarget);"
        )
        lines.append(f"IF fbMonitorSmallString_{module.module_name}.q_xHasChanged THEN")

        write_stmt = module.x_plc_target.write_stmt if module.x_plc_target else None
        if write_stmt:
            lines.append(f" {write_stmt};")
        else:
            lines.append(" // TODO_CODEGEN: configure target write statement (missing x-plc.target.write_stmt)")

        lines.append("END_IF")
        lines.append("")
        return lines

    lines.append("// TODO_CODEGEN: manual implementation required for Writable target monitoring")
    lines.append("")
    return lines


def _emit_apply_clear_errors_block(module: ResolvedRealModule) -> List[str]:
    """
    Emit application of the standard clear_errors command.

    Even when no extra PLC command statement is configured, the SECoP-side
    error-report fields are still cleared.
    """
    lines: List[str] = []
    pfx = _module_prefix(module.module_name)

    if not module.has_clear_errors_command:
        return lines

    lines.append('// Apply "clear_errors" command')
    lines.append(f"IF {pfx}.xClearErrors THEN")
    lines.append(f" {pfx}.stErrorReport.xActive := FALSE;")
    lines.append(f" {pfx}.stErrorReport.sClass := '';")
    lines.append(f" {pfx}.stErrorReport.sDescription := '';")

    cmd_stmt = module.x_plc_clear_errors.cmd_stmt if module.x_plc_clear_errors else None
    if cmd_stmt:
        lines.append(f" {cmd_stmt};")

    lines.append("END_IF")
    lines.append("")

    return lines


def _emit_module_block(
    module: ResolvedRealModule,
    resolved_classes: ResolvedModuleClasses,
) -> List[str]:
    """
    Emit the full SECoP-to-PLC mapping block for one real module.
    """
    lines: List[str] = []

    lines.append(f"// {module.module_name}")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")

    lines.extend(_emit_drivable_apply_target_block(module, resolved_classes))
    lines.extend(_emit_writable_apply_target_block(module, resolved_classes))
    lines.extend(_emit_apply_clear_errors_block(module))

    return lines


def _emit_sec_node_clear_errors_block(
    resolved_real_modules: ResolvedRealModules,
) -> List[str]:
    """
    Emit the SEC node error-report reset when any module clear_errors command is
    active.
    """
    lines: List[str] = []

    modules_with_clear = [
        m.module_name
        for m in resolved_real_modules.modules.values()
        if m.has_clear_errors_command
    ]

    lines.append("// SEC Node")
    lines.append("// -----------------------------------------------------------------")
    lines.append("")

    if not modules_with_clear:
        lines.append("// No clear_errors commands configured in any module")
        lines.append("")
        return lines

    or_expr = " OR ".join(
        [
            f"GVL_SecNode.G_st_{name}.xClearErrors"
            for name in resolved_real_modules.sec_node.module_names_in_order
            if name in modules_with_clear
        ]
    )

    lines.append(f"IF {or_expr} THEN")
    lines.append(" SECOP.GVL.G_st_SecNode.stErrorReport.xActive := FALSE;")
    lines.append(" SECOP.GVL.G_st_SecNode.stErrorReport.sClass := '';")
    lines.append(" SECOP.GVL.G_st_SecNode.stErrorReport.sDescription := '';")
    lines.append("END_IF")
    lines.append("")

    return lines


def emit_prg_secop_map_to_plc(
    resolved_real_modules: ResolvedRealModules,
    resolved_module_classes: ResolvedModuleClasses,
) -> str:
    """
    Emit full ST source for PROGRAM SecopMapToPlc.
    """
    lines: List[str] = []

    lines.extend(_emit_var_block(resolved_real_modules))

    for module_name in resolved_real_modules.sec_node.module_names_in_order:
        lines.extend(
            _emit_module_block(
                resolved_real_modules.modules[module_name],
                resolved_module_classes,
            )
        )

    lines.extend(_emit_sec_node_clear_errors_block(resolved_real_modules))

    return "\n".join(lines) + "\n"