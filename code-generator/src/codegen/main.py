from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError
from codegen.model.secnode import SecNodeConfig

from codegen.validators.validate_config import validate_config, build_report, has_errors

def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments.

    Why we do this:
    - It allows running the tool from terminal or from PyCharm with parameters.
    - It keeps the code independent from hardcoded file paths.
    """
    parser = argparse.ArgumentParser(
        prog="secop-plc-codegen",
        description=(
            "Load and validate a SECoP node config (JSON) and "
            "produce a normalized version (same data, consistent types/defaults)."
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


def main() -> int:
    """
    0) Parse CLI (config_path and out_dir)
    1) Parse input config file (JSON) -> obtain 'raw' Python dict
    2) Validate + normalize (structure, data, format, types, defaults...) using a Pydantic model -> obtain 'cfg' model instance
    3) Validate business rules and write a report
    """
    args = parse_args()

    # Convert CLI strings to Path objects (safer and cross-platform)
    config_path = Path(args.config)
    out_dir = Path(args.out)

    # Ensure output folder exists
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Load JSON from file -> "raw" dict
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

    # Write a raw copy for traceability/debugging
    (out_dir / "raw_config.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 2) Validate + normalize using Pydantic
    # Pydantic will:
    # - validate types (e.g., server_port must be int)
    # - apply defaults (e.g., missing optional fields)
    # - produce a consistent internal representation (cfg)
    try:
        cfg = SecNodeConfig.model_validate(raw)
    except ValidationError as e:
        print("ERROR: config validation failed")
        # Pydantic error output is very informative (paths + reasons)
        print(e)
        return 2

    # Write the normalized config (same meaning, consistent formatting/types/defaults)
    (out_dir / "normalized_config.json").write_text(
        cfg.model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )

    # 3) Run business-rule validation and write a report
    findings = validate_config(cfg)
    report = build_report(findings)

    (out_dir / "validation_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Validation summary:", report["summary"])
    print("wrote:", str(out_dir / "validation_report.json"))

    # Stop if any ERROR exists (default mode)
    if has_errors(findings):
        print("ERROR: Business-rule validation failed. Cannot proceed.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
