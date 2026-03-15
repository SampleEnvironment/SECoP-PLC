"""
Generator for FB_Module_<class>.

One FB is generated per module class.
Example:

    FB_Module_mf
    FB_Module_ts
    FB_Module_tc

The FB implements the SECoP behaviour for a module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from codegen.resolve.types import ResolvedModuleClass
from codegen.generators.st.emit_fb_module_blocks import (
    emit_fb_header,
    emit_var_in_out,
    emit_var_internal,
    emit_header_comments,
    emit_monitor_clients_round_block,
    emit_out_of_range_block,
    emit_sync_block,
    emit_async_block,
    emit_target_drive_monitor_block,
)


def emit_fb_module(resolved: ResolvedModuleClass) -> str:
    """
    Generate the full ST source for one FB_Module_<class>.
    """
    lines: list[str] = []

    lines.extend(emit_header_comments(resolved))
    lines.extend(emit_fb_header(resolved))
    lines.extend(emit_var_in_out(resolved))
    lines.extend(emit_var_internal(resolved))

    # Common first blocks
    lines.extend(emit_monitor_clients_round_block())
    lines.extend(emit_out_of_range_block(resolved))

    # Sync mode
    lines.extend(emit_sync_block(resolved))

    # Async mode
    lines.extend(emit_async_block(resolved))

    # Final target drive monitor (Drivable only)
    lines.extend(emit_target_drive_monitor_block(resolved))

    lines.append("END_FUNCTION_BLOCK")

    return "\n".join(lines)


def emit_all_fb_modules(
    classes: Dict[str, ResolvedModuleClass],
    out_dir: Path,
) -> None:
    """
    Generate one ST file per module class.
    """

    modules_dir = out_dir / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    for name, resolved in classes.items():
        source = emit_fb_module(resolved)

        path = modules_dir / f"FB_Module_{name}.st"
        path.write_text(source, encoding="utf-8")