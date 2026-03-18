from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from codegen.model.secnode import SecNodeConfig
from codegen.validators.validate_config import validate_config, build_report, has_errors

# ST code emitters
from codegen.generators.st.emit_gvl import emit_gvl_secnode
from codegen.generators.st.emit_types import emit_all_module_types
from codegen.generators.st.emit_fb_process_modules import emit_fb_process_modules
from codegen.generators.st.emit_fb_module import emit_all_fb_modules
from codegen.generators.st.emit_prg_secop_init import emit_prg_secop_init
from codegen.generators.st.emit_prg_secop_map_from_plc import emit_prg_secop_map_from_plc
from codegen.generators.st.emit_prg_secop_map_to_plc import emit_prg_secop_map_to_plc

# Resolve layer
from codegen.resolve.module_classes import resolve_module_classes
from codegen.resolve.real_modules import resolve_real_modules


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments.

    Why this exists:
    - the tool can be run from terminal or from an IDE with parameters,
    - the program stays independent from hard-coded file paths,
    - the same entry point can be reused for different input configs and output
      folders.

    Example:
        python -m codegen.main --config inputs/secnodeplc_demo_config.json --out outputs/runs/dev
    """
    parser = argparse.ArgumentParser(
        prog="secop-plc-codegen",
        description=(
            "Load and validate a SECoP node config (JSON), produce a normalised "
            "version, resolve PLC-oriented intermediate models, and generate "
            "PLC Structured Text artefacts if no validation errors exist."
        ),
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


def _build_structure_report_json_from_raw(raw_cfg: dict) -> str:
    """
    Build the structure report JSON that will later be exposed by the SEC node
    in response to the SECoP 'describe' command.

    Important design choice:
    - this report is built from the raw configuration,
    - not from the normalised Pydantic dump.

    Reason:
    the protocol-facing describe structure should reflect the user-provided
    SECoP structure without extra optional fields introduced by normalization
    with null values.
    """
    def _deep_remove_x_plc(obj):
        if isinstance(obj, dict):
            return {
                key: _deep_remove_x_plc(value)
                for key, value in obj.items()
                if key != "x-plc"
            }
        if isinstance(obj, list):
            return [_deep_remove_x_plc(item) for item in obj]
        return obj

    without_x_plc = _deep_remove_x_plc(raw_cfg)
    return json.dumps(without_x_plc, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    """
    Main code-generation pipeline.

    Current pipeline
    ----------------
    0) Parse CLI arguments
    1) Load the input JSON file into a raw Python dict
    2) Validate and normalise it with Pydantic
    3) Run business-rule validation and write a validation report
    4) Resolve module-class data used by class-based ST artefacts
    5) Resolve real-module / SEC-node data used mainly by PRGs
    6) Generate PLC Structured Text files

    Architectural note
    ------------------
    Two resolved views of the configuration are kept:

    - module classes:
        used for ST types, enum DUTs, FB_Module_<class>, FB_SecopProcessModules

    - real modules:
        used for PRGs such as SecopInit, SecopMapFromPlc and SecopMapToPlc

    Scope note
    ----------
    At this stage the tool generates Structured Text only.
    PLCopenXML generation will come later from the same validated/resolved data.
    """
    args = parse_args()

    config_path = Path(args.config)
    out_dir = Path(args.out)

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

    (out_dir / "raw_config.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Build the protocol-facing structure report from the raw config before
    # any normalization adds explicit null-valued optional fields.
    structure_report_json = _build_structure_report_json_from_raw(raw)

    # ------------------------------------------------------------------
    # 2) Validate + normalise with Pydantic
    # ------------------------------------------------------------------
    try:
        cfg = SecNodeConfig.model_validate(raw)
    except ValidationError as e:
        print("ERROR: config validation failed")
        print(e)
        return 2

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

    if has_errors(findings):
        print("ERROR: Business-rule validation failed. Cannot proceed.")
        return 2

    normalized_dict = cfg.model_dump(by_alias=True)

    # ------------------------------------------------------------------
    # 4) Resolve module classes
    # ------------------------------------------------------------------
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
    try:
        resolved_real_modules = resolve_real_modules(
            normalized_cfg=normalized_dict,
            resolved_classes=resolved,
            structure_report_json=structure_report_json,
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
    # Current generated artefacts:
    # - GVL_SecNode.st
    # - ST_Module_<class>.st and ET_Module_<class>_... .st inside st/modules/
    # - FB_SecopProcessModules.st
    # - one FB_Module_<class>.st per module class inside st/modules/
    # - SecopInit.st
    # - SecopMapFromPlc.st
    # - SecopMapToPlc.st
    st_gvl = emit_gvl_secnode(resolved)
    st_fb_process_modules = emit_fb_process_modules(resolved)
    st_secop_init = emit_prg_secop_init(resolved_real_modules)
    st_secop_map_from_plc = emit_prg_secop_map_from_plc(
        resolved_real_modules,
        resolved,
    )
    st_secop_map_to_plc = emit_prg_secop_map_to_plc(
        resolved_real_modules,
        resolved,
    )

    out_st_dir = out_dir / "st"
    out_st_dir.mkdir(parents=True, exist_ok=True)

    (out_st_dir / "GVL_SecNode.st").write_text(st_gvl, encoding="utf-8")
    (out_st_dir / "FB_SecopProcessModules.st").write_text(st_fb_process_modules, encoding="utf-8")
    (out_st_dir / "SecopInit.st").write_text(st_secop_init, encoding="utf-8")
    (out_st_dir / "SecopMapFromPlc.st").write_text(st_secop_map_from_plc, encoding="utf-8")
    (out_st_dir / "SecopMapToPlc.st").write_text(st_secop_map_to_plc, encoding="utf-8")

    # Generate one ST type file per module class and enum DUT file when needed.
    emit_all_module_types(resolved.classes, out_st_dir)

    # Generate one FB_Module_<class>.st file per resolved module class.
    emit_all_fb_modules(resolved.classes, out_st_dir)

    print("ST generation done.")
    print("wrote:", str(out_st_dir / "GVL_SecNode.st"))
    print("wrote:", str(out_st_dir / "FB_SecopProcessModules.st"))
    print("wrote:", str(out_st_dir / "SecopInit.st"))
    print("wrote:", str(out_st_dir / "SecopMapFromPlc.st"))
    print("wrote:", str(out_st_dir / "SecopMapToPlc.st"))
    print("wrote:", str(out_st_dir / "modules"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())