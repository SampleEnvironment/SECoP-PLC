"""
ST generator for FB_SecopProcessModules based on the resolved model.

This emitter generates:
1) FUNCTION_BLOCK FB_SecopProcessModules IMPLEMENTS SECOP.I_ProcessModules
2) one internal FB_Module_<moduleclass> instance per real module
3) METHOD Run : BOOL
4) the body of Run, which calls each module FB and maps:
   - common readable signals
   - writable / drivable common signals
   - all module-specific variables from GVL_SecNode

Important design rule
---------------------
This emitter must not parse raw or normalized JSON structures.
It consumes only the resolved model.

Order policy
------------
- module declaration order follows resolved.module_to_class insertion order
- METHOD Run processes modules in that same order

Design note
-----------
This emitter does not need to know whether a module-specific variable comes
from:
- standard value/target logic,
- a customised parameter,
- a customised command.

It simply maps all resolved module variables from:
    GVL_SecNode.G_st_<module>.<var>
to:
    iq_<var>

That keeps the wiring generic and stable even as the resolve layer evolves.
"""

from __future__ import annotations

from codegen.resolve.types import ResolvedModuleClass, ResolvedModuleClasses
from codegen.tasklist import TaskList


def _pascal_case_module_name(modname: str) -> str:
    """
    Convert a module name to a readable PascalCase suffix for FB instance names.

    Examples:
        tc1         -> Tc1
        heatswitch  -> Heatswitch
        current_sp  -> CurrentSp
    """
    parts = modname.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _emit_common_interface_block() -> list[str]:
    """
    Emit the common interface declaration shared by:
    - FUNCTION_BLOCK FB_SecopProcessModules
    - METHOD Run

    This avoids duplicating the same VAR_INPUT / VAR_IN_OUT block twice.

    Important:
    - variable names must match the SECOP library interface
    - i_sModuleRequested is used consistently throughout the generated code
    """
    lines: list[str] = []

    lines.append("VAR_INPUT")
    lines.append(" // Action")
    lines.append(" i_sAction: STRING;")
    lines.append(" // Module requested")
    lines.append(" i_sModuleRequested: STRING(SECOP.GCL.Gc_uiMaxSizeIdentifier);")
    lines.append(" // Accessible (parameter, property or command)")
    lines.append(" i_sAccessibleName: STRING(SECOP.GCL.Gc_uiMaxSizeIdentifier);")
    lines.append(" // Data")
    lines.append(" i_sData: STRING(SECOP.GPL.Gc_uiMaxSizeMessage);")
    lines.append(" // Monitored client")
    lines.append(" i_stClientMonitored: SECOP.ST_Subscriber;")
    lines.append(" // Disconnected client")
    lines.append(" i_stClientDisconnected: SECOP.ST_Subscriber;")
    lines.append(" // (Flag) 'i_stClientDisconnected' just disconnected")
    lines.append(" i_xClientDisconnectedFlag: BOOL;")
    lines.append(" // (Flag) 'i_stClientMonitored' sent a new request that needs processing")
    lines.append(" i_xSyncModeRequest: BOOL;")
    lines.append(" // (Flag) 'i_stClientMonitored' is the first in server's list")
    lines.append(" i_xFirstSecopClient: BOOL;")
    lines.append(" // (Flag) all clients in server's list were processed")
    lines.append(" i_xAllSecopClientsDone: BOOL;")
    lines.append("END_VAR")

    lines.append("VAR_IN_OUT")
    lines.append(" // Reply message")
    lines.append(" iq_sReplyMessage: STRING(SECOP.GPL.Gc_uiMaxSizeMessage);")
    lines.append("END_VAR")

    return lines


def _emit_fb_header() -> list[str]:
    """
    Emit the FUNCTION_BLOCK declaration and shared interface.
    """
    lines: list[str] = []
    lines.append("FUNCTION_BLOCK FB_SecopProcessModules IMPLEMENTS SECOP.I_ProcessModules")
    lines.extend(_emit_common_interface_block())
    return lines


def _emit_fb_var_instances(resolved: ResolvedModuleClasses) -> list[str]:
    """
    Emit internal FB_Module_<moduleclass> instances, one per real module.

    Example:
        fbModuleTc1: FB_Module_tc;
        fbModuleTc2: FB_Module_tc;
        fbModuleMf: FB_Module_mf;
    """
    lines: list[str] = []
    lines.append("VAR")
    lines.append(" // Module FB instances")

    for modname, modclass in resolved.module_to_class.items():
        instance_suffix = _pascal_case_module_name(modname)
        lines.append(f" fbModule{instance_suffix}: FB_Module_{modclass};")

    lines.append("END_VAR")
    return lines


def _emit_run_header() -> list[str]:
    """
    Emit METHOD Run declaration and shared interface.
    """
    lines: list[str] = []
    lines.append("METHOD Run : BOOL")
    lines.extend(_emit_common_interface_block())
    return lines


def _emit_common_readable_mappings(modname: str) -> list[str]:
    """
    Emit mappings that always apply because Readable is implicit in all
    supported interface classes.
    """
    return [
        " // Common from readable class",
        f"    iq_sName                 := GVL_SecNode.G_st_{modname}.sName,",
        f"    iq_stErrorReport         := GVL_SecNode.G_st_{modname}.stErrorReport,",
        f"    iq_sTimestamp            := GVL_SecNode.G_st_{modname}.sTimestamp,",
        f"    iq_stStatus              := GVL_SecNode.G_st_{modname}.stStatus,",
        f"    iq_stPollInterval        := GVL_SecNode.G_st_{modname}.stPollInterval,",
        f"    iq_astSubscriberList     := GVL_SecNode.G_st_{modname}.astSubscriberList,",
        "",
    ]


def _emit_writable_mappings(modname: str) -> list[str]:
    """
    Emit mappings common to Writable and Drivable modules.
    """
    return [
        " // Common from writable class",
        f"    iq_stTargetWrite         := GVL_SecNode.G_st_{modname}.stTargetWrite,",
        "",
    ]


def _emit_drivable_mappings(modname: str) -> list[str]:
    """
    Emit mappings specific to Drivable modules.
    """
    return [
        " // Specific from drivable class",
        f"    iq_stTargetDrive         := GVL_SecNode.G_st_{modname}.stTargetDrive,",
        "",
    ]


def _emit_module_specific_mappings(
    modname: str,
    resolved_class: ResolvedModuleClass,
    tasklist: TaskList,
) -> list[str]:
    """
    Emit mappings for all module-specific variables from the resolved model.

    For each resolved module variable '<var>', generate:
        iq_<var> := GVL_SecNode.G_st_<module>.<var>

    This includes, transparently:
    - value variables
    - target-related variables
    - xClearErrors
    - customised parameters
    - customised commands

    Variables with open-ended types (array, tuple) are skipped — no automatic
    PLC variable exists for them. A task comment is emitted instead.
    """
    lines: list[str] = []
    lines.append(" // Module-specific")

    # Filter out vars with open-ended types so we can determine the last
    # mappable variable (needed to place the closing ");" correctly).
    mappable = [v for v in resolved_class.module_variables if "(*TODO:" not in v.plc_type]
    manual   = [v for v in resolved_class.module_variables if "(*TODO:" in v.plc_type]

    for idx, var in enumerate(mappable):
        is_last = idx == len(mappable) - 1 and not manual
        suffix = ");" if is_last else ","
        lines.append(
            f"    iq_{var.name:<26} := GVL_SecNode.G_st_{modname}.{var.name}{suffix}"
        )

    if manual:
        # Close the FB call before the task comments
        if mappable:
            # Remove trailing comma from last mappable line and add ");"
            lines[-1] = lines[-1].rstrip(",") + ");"
        else:
            # No mappable vars at all — close the call now
            lines.append(");")

        for var in manual:
            task_comment = tasklist.make_st_comment(
                plc_path=f"FB_SecopProcessModules.Run.{modname}",
                message=(
                    f"Manual FB-to-GVL_SecNode value mapping is required for "
                    f"module '{modname}' because the value type is not supported "
                    "by automatic generation."
                ),
            )
            lines.append(f"    {task_comment}")

    return lines


def _emit_run_body(resolved: ResolvedModuleClasses, tasklist: TaskList) -> list[str]:
    """
    Emit the body of METHOD Run.

    One FB call is generated per real module, in module order.
    """
    lines: list[str] = []
    lines.append("// Calls to module FBs")
    lines.append("")

    for modname, modclass in resolved.module_to_class.items():
        resolved_class = resolved.classes[modclass]
        instance_suffix = _pascal_case_module_name(modname)
        fb_inst = f"fbModule{instance_suffix}"

        lines.append(f"// Process module {modname}")
        lines.append("// ====================================================")
        lines.append(f"{fb_inst}(")

        # Fixed inputs
        lines.extend([
            "    i_sAction                 := i_sAction,",
            "    i_sModuleRequested        := i_sModuleRequested,",
            "    i_sAccessible             := i_sAccessibleName,",
            "    i_sData                   := i_sData,",
            "    i_stClientMonitored       := i_stClientMonitored,",
            "    i_stClientDisconnected    := i_stClientDisconnected,",
            "    i_xClientDisconnectedFlag := i_xClientDisconnectedFlag,",
            "    i_xSyncModeRequest        := i_xSyncModeRequest,",
            "    i_xFirstSecopClient       := i_xFirstSecopClient,",
            "    i_xAllSecopClientsDone    := i_xAllSecopClientsDone,",
            "",
            "    iq_sReplyMessage          := iq_sReplyMessage,",
            "",
        ])

        # Common readable
        lines.extend(_emit_common_readable_mappings(modname))

        # Writable / Drivable common
        if resolved_class.interface_class in ("Writable", "Drivable"):
            lines.extend(_emit_writable_mappings(modname))

        if resolved_class.interface_class == "Drivable":
            lines.extend(_emit_drivable_mappings(modname))

        # Module-specific
        lines.extend(_emit_module_specific_mappings(modname, resolved_class, tasklist))
        lines.append("")

    return lines


def emit_fb_process_modules(resolved: ResolvedModuleClasses, tasklist: TaskList) -> str:
    """
    Emit the full ST source for FB_SecopProcessModules.

    Output structure:
    - FUNCTION_BLOCK declaration
    - shared interface
    - VAR with module FB instances
    - METHOD Run declaration
    - shared interface
    - Run body with one FB call per real module
    """
    lines: list[str] = []

    lines.extend(_emit_fb_header())
    lines.extend(_emit_fb_var_instances(resolved))
    lines.append("")
    lines.extend(_emit_run_header())
    lines.append("")
    lines.extend(_emit_run_body(resolved, tasklist))

    return "\n".join(lines) + "\n"