from __future__ import annotations

"""
Validation orchestrator.

This module is the single entry point for business-rule validation.

Responsibilities
----------------
- run all configured validation rules,
- return a flat list of findings,
- build a stable JSON-friendly validation report,
- expose a helper to check whether any ERROR exists.

Validation policy
-----------------
- ERROR findings stop code generation
- WARNING findings allow generation to continue

Design note
-----------
The validation layer is intentionally independent from the later code-generation
steps. A validation finding contains only the minimum information required to
understand the issue:
- rule_id
- severity
- path
- message

Any later task-list generation should be handled separately from this module.
"""

from typing import Any

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
    rule_numeric_ranges_must_define_both_ends,
    rule_target_limits_within_target,
    rule_string_requires_maxchars,
    rule_array_requires_maxlen,
    rule_standard_accessible_readonly_policy,
    rule_target_datainfo_type_matches_value,
    rule_bool_type_forbidden,
    rule_datainfo_field_coherence,
    rule_datainfo_type_supported,
    rule_status_structure_and_codes,
    rule_value_type_requires_manual_implementation,
    rule_target_range_restriction_mutually_exclusive,
    rule_target_range_restriction_requires_numeric_target,
    rule_target_range_restriction_requires_target_range,
)
from codegen.rules.plc_rules import (
    rule_xplc_keys_exist_in_secop_accessibles,
    rule_xplc_node_fields_configured,
    rule_xplc_module_timestamp_tag_configured,
    rule_xplc_status_hw_error_fields_configured,
    rule_xplc_status_hw_error_fields_coherent,
    rule_xplc_status_comm_error_fields_configured,
    rule_xplc_status_comm_error_fields_coherent,
    rule_xplc_status_disabled_fields_coherent,
    rule_xplc_target_change_possible_expr_configured,
    rule_xplc_target_reach_fields,
    rule_xplc_value_mapping_by_type,
    rule_xplc_target_mapping_by_type,
    rule_xplc_value_outofrange_numeric_only,
    rule_xplc_clear_errors_cmd_stmt_optional,
    rule_xplc_clear_errors_only_if_command_exists,
    rule_xplc_custom_parameters_exist_and_match_accessibles,
    rule_xplc_custom_parameter_mapping_by_type,
)


def validate_config(cfg: SecNodeConfig) -> list[Finding]:
    """
    Run all business rules and return a flat list of findings.

    The order is deliberate and stable so that validation reports are easier to
    compare during development and testing.
    """
    findings: list[Finding] = []

    # ------------------------------------------------------------------
    # SECoP / protocol-level rules
    # ------------------------------------------------------------------
    findings.extend(rule_non_empty_modules(cfg))                         # R-NODE-001
    findings.extend(rule_interface_classes_single(cfg))                  # R-MOD-001
    findings.extend(rule_features_and_offset_not_supported_on_plc(cfg))  # R-MOD-002
    findings.extend(rule_required_accessibles(cfg))                      # R-CLS-001/002/003
    findings.extend(rule_forbidden_accessibles_by_class(cfg))            # R-CLS-004
    findings.extend(rule_custom_command_accessibles_warn(cfg))           # R-ACC-001
    findings.extend(rule_accessible_members_by_type(cfg))                # R-ACC-002
    findings.extend(rule_numeric_ranges_coherent(cfg))                   # R-ACC-003
    findings.extend(rule_numeric_ranges_must_define_both_ends(cfg))      # R-ACC-003B
    findings.extend(rule_target_limits_within_target(cfg))               # R-ACC-004
    findings.extend(rule_string_requires_maxchars(cfg))                  # R-ACC-005
    findings.extend(rule_array_requires_maxlen(cfg))                     # R-ACC-006
    findings.extend(rule_standard_accessible_readonly_policy(cfg))       # R-ACC-007
    findings.extend(rule_target_datainfo_type_matches_value(cfg))        # R-ACC-008
    findings.extend(rule_bool_type_forbidden(cfg))                       # R-ACC-009
    findings.extend(rule_command_datainfo_shape(cfg))                    # R-ACC-010
    findings.extend(rule_datainfo_field_coherence(cfg))                  # R-DI-002
    findings.extend(rule_datainfo_type_supported(cfg))                   # R-DI-001
    findings.extend(rule_status_structure_and_codes(cfg))                # R-STAT-001/002/003/004/005
    findings.extend(rule_value_type_requires_manual_implementation(cfg)) # R-ACC-011
    findings.extend(rule_target_range_restriction_mutually_exclusive(cfg))         # R-ACC-012
    findings.extend(rule_target_range_restriction_requires_numeric_target(cfg))    # R-ACC-013
    findings.extend(rule_target_range_restriction_requires_target_range(cfg))      # R-ACC-014

    # ------------------------------------------------------------------
    # PLC / x-plc rules
    # ------------------------------------------------------------------
    findings.extend(rule_xplc_keys_exist_in_secop_accessibles(cfg))              # R-PLC-001
    findings.extend(rule_xplc_node_fields_configured(cfg))                       # R-PLC-010
    findings.extend(rule_xplc_module_timestamp_tag_configured(cfg))              # R-PLC-020
    findings.extend(rule_xplc_status_hw_error_fields_configured(cfg))            # R-PLC-021
    findings.extend(rule_xplc_status_hw_error_fields_coherent(cfg))              # R-PLC-021A
    findings.extend(rule_xplc_status_comm_error_fields_configured(cfg))          # R-PLC-021B
    findings.extend(rule_xplc_status_comm_error_fields_coherent(cfg))            # R-PLC-021C
    findings.extend(rule_xplc_status_disabled_fields_coherent(cfg))              # R-PLC-022/023
    findings.extend(rule_xplc_target_change_possible_expr_configured(cfg))       # R-PLC-026
    findings.extend(rule_xplc_target_reach_fields(cfg))                          # R-PLC-024/025
    findings.extend(rule_xplc_value_mapping_by_type(cfg))                        # R-PLC-030/031
    findings.extend(rule_xplc_target_mapping_by_type(cfg))                       # R-PLC-032/033
    findings.extend(rule_xplc_value_outofrange_numeric_only(cfg))                # R-PLC-034
    findings.extend(rule_xplc_clear_errors_cmd_stmt_optional(cfg))               # R-PLC-040
    findings.extend(rule_xplc_clear_errors_only_if_command_exists(cfg))          # R-PLC-041
    findings.extend(rule_xplc_custom_parameters_exist_and_match_accessibles(cfg))  # R-PLC-050
    findings.extend(rule_xplc_custom_parameter_mapping_by_type(cfg))             # R-PLC-051/052

    return findings


def build_report(findings: list[Finding]) -> dict[str, Any]:
    """
    Convert findings into a stable JSON-friendly report.

    Report structure:
    - summary.errors
    - summary.warnings
    - findings: list of finding dictionaries
    """
    errors = sum(1 for f in findings if f.severity == Severity.ERROR)
    warnings = sum(1 for f in findings if f.severity == Severity.WARNING)

    return {
        "summary": {
            "errors": errors,
            "warnings": warnings,
        },
        "findings": [f.to_dict() for f in findings],
    }


def has_errors(findings: list[Finding]) -> bool:
    """
    Return True if at least one ERROR finding exists.
    """
    return any(f.severity == Severity.ERROR for f in findings)