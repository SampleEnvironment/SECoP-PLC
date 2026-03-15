"""
ST generator for GVL_SecNode based on the resolved model.

This emitter generates the global variable list:
- one G_st_<module> : ST_Module_<modclass> per actual module
- one G_SecopProcessModules : FB_SecopProcessModules
- one constant block with the max compatible library version

Important design rule:
- This emitter must not inspect raw / normalized JSON directly.
- It consumes the resolved model only.

Example output:

    {attribute 'qualified_only'}
    VAR_GLOBAL
     // SEC node Modules - Demo
     G_st_mf : ST_Module_mf;
     G_st_tc1 : ST_Module_tc;
     G_st_tc2 : ST_Module_tc;
     ...
     G_SecopProcessModules : FB_SecopProcessModules;
    END_VAR
    VAR_GLOBAL CONSTANT
     // Max. SECoP library version compatible with the code generator
     Gc_dwMaxLibVersion : DWORD := 10777200;
     // Version Warning
     xCodeGenNotUpToDate : BOOL := SECOP.GCL.Gc_dwLibVersionNumber>Gc_dwMaxLibVersion;
    END_VAR
"""

from __future__ import annotations

from codegen.resolve.types import ResolvedModuleClasses
from codegen.utils.constants import GC_DW_MAX_LIB_VERSION


def emit_gvl_secnode(resolved: ResolvedModuleClasses) -> str:
    """
    Emit ST for GVL_SecNode from the resolved model.

    Order policy:
    - We preserve the insertion order of resolved.module_to_class.
    - This means module declaration order follows the original normalized config order.

    Notes:
    - The comment line "SEC node Modules - Demo" is still fixed for now,
      matching your current expected output.
    - If later you want this derived from equipment_id or another resolved field,
      we can extend the resolved model.
    """
    lines: list[str] = []

    lines.append("{attribute 'qualified_only'}")
    lines.append("VAR_GLOBAL")
    lines.append(" // SEC node Modules - Demo")

    for modname, modclass in resolved.module_to_class.items():
        lines.append(f" G_st_{modname} : ST_Module_{modclass};")

    lines.append(" G_SecopProcessModules : FB_SecopProcessModules;")
    lines.append("END_VAR")

    lines.append("VAR_GLOBAL CONSTANT")
    lines.append(" // Max. SECoP library version compatible with the code generator")
    lines.append(f" Gc_dwMaxLibVersion : DWORD := {GC_DW_MAX_LIB_VERSION};")
    lines.append(" // Version Warning")
    lines.append(" xCodeGenNotUpToDate : BOOL := SECOP.GCL.Gc_dwLibVersionNumber>Gc_dwMaxLibVersion;")
    lines.append("END_VAR")

    return "\n".join(lines) + "\n"