"""
ST generator for GVL_SecNode based on the resolved model.

This emitter generates the global variable list:
- one G_st_<module> : ST_Module_<moduleclass> per real module
- one G_SecopProcessModules : FB_SecopProcessModules
- one constant block with the maximum compatible SECoP library version

Important design rule
---------------------
This emitter must not inspect raw or normalized JSON directly.
It consumes the resolved model only.

Example output
--------------
    {attribute 'qualified_only'}
    VAR_GLOBAL
     // SEC node modules
     G_st_mf : ST_Module_mf;
     G_st_tc1 : ST_Module_tc;
     G_st_tc2 : ST_Module_tc;
     ...
     G_SecopProcessModules : FB_SecopProcessModules;
    END_VAR

    VAR_GLOBAL CONSTANT
     // Max. SECoP library version compatible with the code generator
     Gc_dwMaxLibVersion : DWORD := 10777200;
     // Version warning
     xCodeGenNotUpToDate : BOOL := SECOP.GCL.Gc_dwLibVersionNumber > Gc_dwMaxLibVersion;
    END_VAR
"""

from __future__ import annotations

from codegen.resolve.real_modules import ResolvedRealModules
from codegen.resolve.types import ResolvedModuleClasses
from codegen.utils.constants import GC_DW_MAX_LIB_VERSION
from codegen.generators.st.st_utils import format_st_string_literal


def _format_st_string_literal(value: str) -> str:
    """
    Format a string as an ST literal (same escaping as SecopInit).
    """
    return format_st_string_literal(value)


def _emit_structure_report_constants(resolved_real: ResolvedRealModules) -> list[str]:
    """
    Emit the constants used to build the dynamic SEC node structure report.

    Only when at least one module has x-plc.exclude_condition. Each STRING is
    sized to its exact length.
    """
    sec_node = resolved_real.sec_node
    if not sec_node.structure_report_dynamic:
        return []

    def decl(name: str, value: str) -> str:
        size = max(len(value), 1)
        return f" {name} : STRING({size}) := {_format_st_string_literal(value)};"

    lines: list[str] = []
    lines.append("")
    lines.append("VAR_GLOBAL CONSTANT")
    lines.append(" // SEC node structure report, built at runtime from the non-excluded modules (SecopMapFromPlc)")
    lines.append(decl("Gc_sStructReportHead", sec_node.structure_report_head))
    for name in sec_node.module_names_in_order:
        lines.append(decl(f"Gc_sStructReport_{name}", sec_node.structure_report_fragments[name]))
    lines.append(decl("Gc_sStructReportTail", sec_node.structure_report_tail))
    lines.append("END_VAR")
    return lines


def emit_gvl_secnode(
    resolved: ResolvedModuleClasses,
    resolved_real: ResolvedRealModules | None = None,
) -> str:
    """
    Emit ST for GVL_SecNode from the resolved model.

    Order policy
    ------------
    Module declaration order follows resolved.module_to_class insertion order,
    which in practice preserves the normalized-config module order.

    Notes
    -----
    - The actual ST_Module_<class> and ET_Module_<class>_... type declarations
      are generated separately into st/modules/.
    - This GVL only references those types.
    """
    lines: list[str] = []

    lines.append("{attribute 'qualified_only'}")
    lines.append("VAR_GLOBAL")
    lines.append(" // SEC node modules")

    for modname, modclass in resolved.module_to_class.items():
        lines.append(f" G_st_{modname} : ST_Module_{modclass};")

    lines.append(" G_SecopProcessModules : FB_SecopProcessModules;")
    lines.append("END_VAR")
    lines.append("")

    lines.append("VAR_GLOBAL CONSTANT")
    lines.append(" // Max. SECoP library version compatible with the code generator")
    lines.append(f" Gc_dwMaxLibVersion : DWORD := {GC_DW_MAX_LIB_VERSION};")
    lines.append(" // Version warning")
    lines.append(" xCodeGenNotUpToDate : BOOL := SECOP.GCL.Gc_dwLibVersionNumber > Gc_dwMaxLibVersion;")
    lines.append("END_VAR")

    if resolved_real is not None:
        lines.extend(_emit_structure_report_constants(resolved_real))

    return "\n".join(lines) + "\n"