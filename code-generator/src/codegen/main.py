"""
Main entry point for the SECoP PLC code generator.

What this file does
-------------------
This module orchestrates the full code-generation pipeline for a PLC that will
act as a SECoP node.

The pipeline starts from a JSON configuration file and performs the following:
1. Parse command-line arguments
2. Load the raw JSON input
3. Validate and normalise it with Pydantic
4. Run business-rule validation
5. Resolve module-class level information
6. Resolve real-module / node-instance information
7. Generate Structured Text (ST) artefacts
8. Generate a task list for manual PLC-side follow-up work
9. Convert the generated ST artefacts into one PLCOpenXML file that can be
   imported into the PLC IDE

Design intent
-------------
The generator deliberately keeps two resolved views of the configuration:

- resolved module classes:
    Used for artefacts that exist once per module class, such as:
    * ST_Module_<class>
    * FB_Module_<class>
    * enum DUTs
    * FB_SecopProcessModules

- resolved real modules:
    Used for artefacts that depend on the actual modules present in the node,
    such as:
    * GVL_SecNode
    * SecopInit
    * SecopMapFromPlc
    * SecopMapToPlc

Why PLCOpenXML is generated from ST
-----------------------------------
The PLCOpenXML export is intentionally generated from the already-emitted ST
files rather than directly from the resolved models.

This keeps one clear source of truth for the final PLC code content:
- the ST files define the exact code that the PLC developer would see
- the PLCOpenXML layer wraps that ST into an IDE-importable project format

That approach also helps us keep the XML exporter aligned with the real output
of the ST emitters and avoids duplicating code-generation rules in two places.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codegen.version import __version__

from pydantic import ValidationError

from codegen.model.secnode import SecNodeConfig
from codegen.tasklist import TaskList
from codegen.validators.validate_config import validate_config, build_report, has_errors

# ST code emitters
from codegen.generators.st.emit_gvl import emit_gvl_secnode
from codegen.generators.st.emit_types import emit_all_module_types
from codegen.generators.st.emit_fb_process_modules import emit_fb_process_modules
from codegen.generators.st.emit_fb_module import emit_all_fb_modules
from codegen.generators.st.emit_prg_secop_init import emit_prg_secop_init
from codegen.generators.st.emit_prg_secop_map_from_plc import emit_prg_secop_map_from_plc
from codegen.generators.st.emit_prg_secop_map_to_plc import emit_prg_secop_map_to_plc

# PLCOpenXML exporter
from codegen.generators.plcopenxml.emit_plcopenxml import emit_plcopenxml

# Resolve layer
from codegen.resolve.module_classes import resolve_module_classes
from codegen.resolve.real_modules import resolve_real_modules

def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments.

    Why this exists:
    - it allows running the tool from terminal or IDE with explicit parameters
    - it avoids hard-coded file paths
    - it keeps the same entry point reusable for different configs and outputs

    Example:
        python -m codegen.main --config inputs/secnodeplc_demo_config.json --out outputs/runs/dev
    """
    parser = argparse.ArgumentParser(
        prog="secop-plc-codegen",
        description=(
            f"SECoP PLC Code Generator v{__version__} — "
            "Load and validate a SECoP node config (JSON), produce a normalised "
            "version, generate PLC Structured Text artefacts, and generate one "
            "PLCOpenXML file importable by the PLC IDE."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to the SECoP node config JSON file (input).",
    )

    parser.add_argument(
        "--out",
        default="outputs/runs/dev",
        help="Output folder where the tool writes results (default: outputs/runs/dev).",
    )

    return parser.parse_args()


def main() -> int:
    """
    Main code generation pipeline.

    Pipeline overview:
    0) Parse CLI arguments
    1) Load the input JSON file into a raw Python dict
    2) Validate + normalise it with Pydantic
    3) Run business-rule validation and write a validation report
    4) Resolve module-class data
    5) Resolve real-module / SECoP-node data
    6) Generate PLC Structured Text files from resolve models
    7) Generate a task list for manual PLC integration work
    8) Convert the generated Structured Text files into one PLCOpenXML file

    Important implementation note:
    - ST generation is still model-driven from the resolved data
    - PLCOpenXML generation is then performed from the emitted ST files
    - this keeps the final XML content aligned with the exact ST output

    Return codes:
    - 0: success
    - 2: validation / input / generation failure
    """
    args = parse_args()

    config_path = Path(args.config)
    out_dir = Path(args.out)

    # Create the output folder early so every later stage can write artefacts
    # without repeatedly checking whether the directory already exists.
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1) Load JSON input file -> raw dict
    # ------------------------------------------------------------------
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        return 2

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print("ERROR: invalid JSON in config file")
        print(e)
        return 2
    except OSError as e:
        print("ERROR: could not read config file")
        print(e)
        return 2

    # Write raw input for traceability/debugging.
    # This helps compare:
    # - the original config provided by the user
    # - the normalised config after Pydantic validation
    # - the resolved models used for code generation
    (out_dir / "raw_config.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # 2) Validate + normalise with Pydantic
    # ------------------------------------------------------------------
    try:
        cfg = SecNodeConfig.model_validate(raw)
    except ValidationError as e:
        print("ERROR: config validation failed")
        print(e)
        return 2

    # Store the normalised config so that downstream debugging always has a
    # stable and explicit view of what the schema accepted.
    (out_dir / "normalized_config.json").write_text(
        cfg.model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # 3) Run business-rule validation
    # ------------------------------------------------------------------
    findings = validate_config(cfg)
    report = build_report(findings)

    (out_dir / "validation_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Validation summary:", report["summary"])
    print("wrote:", str(out_dir / "validation_report.json"))

    # Stop here if the config is structurally valid but violates business rules.
    if has_errors(findings):
        print("ERROR: Business-rule validation failed. Cannot proceed.")
        return 2

    # Keep a plain dict version of the validated config because the resolve
    # layer currently consumes dictionary-like data.
    normalized_dict = cfg.model_dump(by_alias=True)

    # ------------------------------------------------------------------
    # 4) Resolve module classes
    # ------------------------------------------------------------------
    # This resolved view is used for artefacts that exist once per module class:
    # - ST_Module_<class>
    # - FB_Module_<class>
    # - enum DUTs
    # - FB_SecopProcessModules
    try:
        resolved = resolve_module_classes(normalized_dict)
    except ValueError as e:
        print("ERROR: failed to resolve module classes for code generation")
        print(e)
        return 2

    (out_dir / "resolved_module_classes.json").write_text(
        json.dumps(resolved.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Resolved module classes.")
    print("wrote:", str(out_dir / "resolved_module_classes.json"))

    # ------------------------------------------------------------------
    # 5) Resolve real modules
    # ------------------------------------------------------------------
    # This resolved view is used for artefacts that depend on the actual set
    # of modules instantiated in the SECoP node:
    # - SecopInit
    # - SecopMapFromPlc
    # - SecopMapToPlc
    # - node-level initialisation / mapping logic
    try:
        resolved_real_modules = resolve_real_modules(
            raw_cfg=raw,
            normalized_cfg=normalized_dict,
            resolved_classes=resolved,
        )
    except ValueError as e:
        print("ERROR: failed to resolve real-module data")
        print(e)
        return 2

    (out_dir / "resolved_real_modules.json").write_text(
        json.dumps(resolved_real_modules.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Resolved real modules.")
    print("wrote:", str(out_dir / "resolved_real_modules.json"))

    # ------------------------------------------------------------------
    # 6) Generate PLC Structured Text artefacts
    # ------------------------------------------------------------------
    # The task list is filled while emitters generate TODO_CODEGEN markers.
    # This keeps the generated ST and the manual follow-up list aligned.
    tasklist = TaskList()

    # Emit the core ST artefacts that are always present in the generated
    # PLC SECoP node project.
    st_gvl = emit_gvl_secnode(resolved)
    st_fb_process_modules = emit_fb_process_modules(resolved, tasklist)
    st_secop_init = emit_prg_secop_init(resolved_real_modules, tasklist)
    st_secop_map_from_plc = emit_prg_secop_map_from_plc(
        resolved_real_modules,
        resolved,
        tasklist,
    )
    st_secop_map_to_plc = emit_prg_secop_map_to_plc(
        resolved_real_modules,
        resolved,
        tasklist,
    )

    # All ST artefacts are written to a dedicated subfolder.
    # This serves two purposes:
    # 1) the developer can inspect the generated ST directly
    # 2) the PLCOpenXML exporter can consume those files afterwards
    out_st_dir = out_dir / "st"
    out_st_dir.mkdir(parents=True, exist_ok=True)

    (out_st_dir / "GVL_SecNode.st").write_text(st_gvl, encoding="utf-8")
    (out_st_dir / "FB_SecopProcessModules.st").write_text(
        st_fb_process_modules,
        encoding="utf-8",
    )
    (out_st_dir / "SecopInit.st").write_text(st_secop_init, encoding="utf-8")
    (out_st_dir / "SecopMapFromPlc.st").write_text(
        st_secop_map_from_plc,
        encoding="utf-8",
    )
    (out_st_dir / "SecopMapToPlc.st").write_text(
        st_secop_map_to_plc,
        encoding="utf-8",
    )

    # Generate one ST type file per resolved module class and per enum DUT.
    emit_all_module_types(resolved.classes, out_st_dir, tasklist)

    # Generate one FB_Module_<class>.st file per resolved module class.
    emit_all_fb_modules(resolved.classes, out_st_dir, tasklist)

    # ------------------------------------------------------------------
    # 7) Write task list
    # ------------------------------------------------------------------
    (out_dir / "tasklist.json").write_text(
        json.dumps(tasklist.to_list(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("ST generation done.")
    print("wrote:", str(out_st_dir / "GVL_SecNode.st"))
    print("wrote:", str(out_st_dir / "FB_SecopProcessModules.st"))
    print("wrote:", str(out_st_dir / "SecopInit.st"))
    print("wrote:", str(out_st_dir / "SecopMapFromPlc.st"))
    print("wrote:", str(out_st_dir / "SecopMapToPlc.st"))
    print("wrote:", str(out_st_dir / "modules"))
    print("wrote:", str(out_dir / "tasklist.json"))

    # ------------------------------------------------------------------
    # 8) Convert generated ST to PLCOpenXML
    # ------------------------------------------------------------------
    # The exporter reads the ST files already on disk (from step 7) and
    # wraps each one in the appropriate PLCOpenXML structure.  One single
    # .xml file is produced — importable by Codesys-based IDE.
    out_xml = emit_plcopenxml(
        st_dir=out_st_dir,
        out_dir=out_dir,
    )

    print("PLCOpenXML generation done.")
    print("wrote:", str(out_xml))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())