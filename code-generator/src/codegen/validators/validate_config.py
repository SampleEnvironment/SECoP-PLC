from __future__ import annotations

"""
Validation orchestrator.

This module runs all business rules and returns:
- a list of findings (errors/warnings)
- a summary

Default mode only:
- If errors exist -> stop generation
- Warnings -> continue, but generate placeholders and report them
"""

from typing import Any, Dict, List

from codegen.model.secnode import SecNodeConfig
from codegen.rules.types import Finding, Severity
from codegen.rules.secop_rules import (
    rule_non_empty_modules,
    rule_interface_classes_single,
    rule_features_and_offset_not_supported_on_plc,
    rule_required_accessibles,
    rule_forbidden_accessibles_by_class,
    rule_custom_command_accessibles_warn,
    rule_accessible_members_by_type,
    rule_command_datainfo_shape,
    rule_numeric_ranges_coherent,
    rule_target_limits_within_target,
    rule_string_requires_maxchars,
    rule_array_requires_maxlen,
    rule_standard_accessible_readonly_policy,
    rule_target_datainfo_type_matches_value,
    rule_checkable_requires_manual_plc,
    rule_datainfo_type_supported,
    rule_status_structure_and_codes,
)
from codegen.rules.plc_rules import (
    rule_xplc_keys_exist_in_secop_accessibles,
    rule_xplc_node_fields_configured,
    rule_xplc_module_timestamp_tag_configured,
    rule_xplc_status_hw_error_fields_configured,
    rule_xplc_status_disabled_fields_coherent,
    rule_xplc_target_change_possible_expr_configured,
    rule_xplc_target_reach_fields,
    rule_xplc_value_mapping_by_type,
    rule_xplc_target_mapping_by_type,
    rule_xplc_clear_errors_cmd_stmt_optional,
)


def validate_config(cfg: SecNodeConfig) -> List[Finding]:
    """
    Run all business rules and return a flat list of findings.
    """
    findings: List[Finding] = []

    # --- SECoP rules ---
    findings.extend(rule_non_empty_modules(cfg))                # R-NODE-001
    findings.extend(rule_interface_classes_single(cfg))         # R-MOD-001
    findings.extend(rule_features_and_offset_not_supported_on_plc(cfg))  # R-MOD-002
    findings.extend(rule_required_accessibles(cfg))             # R-CLS-001/002/003
    findings.extend(rule_forbidden_accessibles_by_class(cfg))   # R-CLS-004
    findings.extend(rule_custom_command_accessibles_warn(cfg))  # R-ACC-001
    findings.extend(rule_accessible_members_by_type(cfg))       # R-ACC-002
    findings.extend(rule_numeric_ranges_coherent(cfg))          # R-ACC-003
    findings.extend(rule_target_limits_within_target(cfg))      # R-ACC-004
    findings.extend(rule_string_requires_maxchars(cfg))         # R-ACC-005
    findings.extend(rule_array_requires_maxlen(cfg))            # R-ACC-006
    findings.extend(rule_standard_accessible_readonly_policy(cfg))  # R-ACC-007
    findings.extend(rule_target_datainfo_type_matches_value(cfg))   # R-ACC-008
    findings.extend(rule_checkable_requires_manual_plc(cfg))    # R-ACC-009
    findings.extend(rule_command_datainfo_shape(cfg))           # R-ACC-010
    findings.extend(rule_datainfo_type_supported(cfg))          # R-DI-001
    findings.extend(rule_status_structure_and_codes(cfg))       # R-STAT-001/002/003/004/005

    # --- PLC/tooling rules ---
    findings.extend(rule_xplc_keys_exist_in_secop_accessibles(cfg))     # R-PLC-001
    findings.extend(rule_xplc_node_fields_configured(cfg))              # R-PLC-010
    findings.extend(rule_xplc_module_timestamp_tag_configured(cfg))     # R-PLC-020
    findings.extend(rule_xplc_status_hw_error_fields_configured(cfg))   # R-PLC-021
    findings.extend(rule_xplc_status_disabled_fields_coherent(cfg))     # R-PLC-022/023
    findings.extend(rule_xplc_target_change_possible_expr_configured(cfg))  # R-PLC-026
    findings.extend(rule_xplc_target_reach_fields(cfg))                 # R-PLC-024/025
    findings.extend(rule_xplc_value_mapping_by_type(cfg))               # R-PLC-030/031
    findings.extend(rule_xplc_target_mapping_by_type(cfg))              # R-PLC-032/033
    findings.extend(rule_xplc_clear_errors_cmd_stmt_optional(cfg))      # R-PLC-040

    return findings


def build_report(findings: List[Finding]) -> Dict[str, Any]:
    """
    Convert findings into a stable JSON report dict.
    """
    errors = sum(1 for f in findings if f.severity == Severity.ERROR)
    warnings = sum(1 for f in findings if f.severity == Severity.WARNING)

    return {
        "summary": {"errors": errors, "warnings": warnings},
        "findings": [f.to_dict() for f in findings],
    }


def has_errors(findings: List[Finding]) -> bool:
    """
    Convenience function: returns True if any ERROR exists.
    """
    return any(f.severity == Severity.ERROR for f in findings)
