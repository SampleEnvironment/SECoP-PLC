from __future__ import annotations

"""
PLC/tooling rules (x-plc coherence + mapping completeness).

These rules do not validate ST syntax itself. Their purpose is to validate that
the project-specific PLC mapping layer ("x-plc") is coherent with the SECoP
configuration and sufficiently complete for automatic code generation.

Current validation scope
------------------------
- x-plc blocks must only refer to accessibles that really exist
- x-plc fields must be coherent with SECoP datainfo and interface class
- contradictory configurations are reported as ERROR
- missing-but-expected PLC mapping fields are reported as WARNING

General policy
--------------
- ERROR means the configuration is inconsistent and code generation should stop
- WARNING means generation may continue, but manual PLC completion will likely
  be required later
"""

from typing import List, Optional, Dict, Any

from codegen.model.secnode import SecNodeConfig
from codegen.rules.types import Finding, Severity


IMPLEMENTATION_WARNING_SUFFIX = (
    "Manual PLC implementation will be required. Refer to generated tasks list."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_empty(value: Optional[str]) -> bool:
    """
    Return True when a string-like configuration field should be considered
    missing for PLC mapping purposes.
    """
    return value is None or str(value).strip() == ""


def _is_drivable(interface_classes: Optional[List[str]]) -> bool:
    """
    Convenience helper used by several x-plc target rules.
    """
    return "Drivable" in (interface_classes or [])


def _status_enum_members(mod: Any) -> Optional[Dict[str, int]]:
    """
    Return the status enum members dict when status has the expected
    tuple(enum, string) shape. Otherwise return None.
    """
    accs = getattr(mod, "accessibles", None) or {}
    if "status" not in accs:
        return None

    di = accs["status"].datainfo
    if getattr(di, "type", None) != "tuple":
        return None

    members = getattr(di, "members", None)
    if not isinstance(members, list) or len(members) != 2:
        return None

    m0 = members[0]
    if not isinstance(m0, dict) or m0.get("type") != "enum":
        return None

    enum_members = m0.get("members")
    if not isinstance(enum_members, dict):
        return None

    return enum_members


def _value_type(mod: Any) -> str:
    """
    Return accessibles.value.datainfo.type or an empty string.
    """
    accs = getattr(mod, "accessibles", None) or {}
    if "value" not in accs:
        return ""
    return (accs["value"].datainfo.type or "").strip()


def _target_type(mod: Any) -> str:
    """
    Return accessibles.target.datainfo.type or an empty string.
    """
    accs = getattr(mod, "accessibles", None) or {}
    if "target" not in accs:
        return ""
    return (accs["target"].datainfo.type or "").strip()


def _is_numeric_type(secop_type: str) -> bool:
    """
    Return True for SECoP numeric scalar types currently treated as numeric by
    this PLC code generator.
    """
    return secop_type in ("double", "int")


def _is_string_type(secop_type: str) -> bool:
    """
    Return True for SECoP string type.
    """
    return secop_type == "string"


def _is_enum_type(secop_type: str) -> bool:
    """
    Return True for SECoP enum type.
    """
    return secop_type == "enum"


# ---------------------------------------------------------------------------
# Core x-plc existence / completeness rules
# ---------------------------------------------------------------------------

def rule_xplc_keys_exist_in_secop_accessibles(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-001:
    x-plc standard blocks must only exist when the corresponding SECoP
    accessible exists.

    This rule applies only to the standard x-plc sections:
    - value
    - status
    - target
    - clear_errors
    """
    findings: List[Finding] = []

    xplc_to_acc = {
        "value": "value",
        "status": "status",
        "target": "target",
        "clear_errors": "clear_errors",
    }

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        secop_accs = mod.accessibles or {}

        for x_key, acc_key in xplc_to_acc.items():
            if getattr(xplc, x_key, None) is None:
                continue

            if acc_key not in secop_accs:
                findings.append(
                    Finding(
                        rule_id="R-PLC-001",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.{x_key}",
                        message=(
                            f"x-plc.{x_key} is present but the SECoP accessible "
                            f"'{acc_key}' is missing."
                        ),
                    )
                )

    return findings


def rule_xplc_node_fields_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-010:
    Node-level x-plc fields should be configured.

    These fields are optional in the Pydantic model, but they conceptually apply
    to the PLC SEC node project, so missing values produce WARNING findings.
    """
    findings: List[Finding] = []

    xplc = cfg.x_plc
    if not xplc:
        return findings

    tcp = xplc.tcp
    if tcp is None:
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.tcp",
                message=f"The field x-plc.tcp is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
            )
        )
        return findings

    if _is_empty(tcp.server_ip):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.tcp.server_ip",
                message=f"The field x-plc.tcp.server_ip is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
            )
        )

    if tcp.server_port is None:
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.tcp.server_port",
                message=f"The field x-plc.tcp.server_port is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
            )
        )

    if _is_empty(tcp.interface_healthy_tag):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.tcp.interface_healthy_tag",
                message=f"The field x-plc.tcp.interface_healthy_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
            )
        )

    if _is_empty(xplc.secop_version):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.secop_version",
                message=f"The field x-plc.secop_version is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
            )
        )

    if _is_empty(xplc.plc_timestamp_tag):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.plc_timestamp_tag",
                message=f"The field x-plc.plc_timestamp_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
            )
        )

    return findings


def rule_xplc_module_timestamp_tag_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-020:
    Module-level x-plc.timestamp_tag should be configured.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        if _is_empty(xplc.timestamp_tag):
            findings.append(
                Finding(
                    rule_id="R-PLC-020",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.timestamp_tag",
                    message=f"The field x-plc.timestamp_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Status-related rules
# ---------------------------------------------------------------------------

def rule_xplc_status_hw_error_fields_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-021:
    If x-plc.status exists, hw_error_expr and hw_error_description should be
    configured.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.status is None:
            continue

        if _is_empty(xplc.status.hw_error_expr):
            findings.append(
                Finding(
                    rule_id="R-PLC-021",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.status.hw_error_expr",
                    message=f"The field x-plc.status.hw_error_expr is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                )
            )

        if _is_empty(xplc.status.hw_error_description):
            findings.append(
                Finding(
                    rule_id="R-PLC-021",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.status.hw_error_description",
                    message=f"The field x-plc.status.hw_error_description is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                )
            )

    return findings


def rule_xplc_status_hw_error_fields_coherent(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-021A:
    x-plc.status.hw_error_expr and hw_error_description must be configured
    together.

    This is a contradiction/coherence rule, so violations are ERROR.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.status is None:
            continue

        expr_present = not _is_empty(xplc.status.hw_error_expr)
        desc_present = not _is_empty(xplc.status.hw_error_description)

        if expr_present and not desc_present:
            findings.append(
                Finding(
                    rule_id="R-PLC-021A",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.status.hw_error_description",
                    message=(
                        "x-plc.status.hw_error_expr is configured, so "
                        "hw_error_description must also be configured."
                    ),
                )
            )

        if desc_present and not expr_present:
            findings.append(
                Finding(
                    rule_id="R-PLC-021A",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.status.hw_error_expr",
                    message=(
                        "x-plc.status.hw_error_description is configured, so "
                        "hw_error_expr must also be configured."
                    ),
                )
            )

    return findings


def rule_xplc_status_comm_error_fields_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-021B:
    comm_error_expr / comm_error_description are optional.

    If one is configured, the other should also be configured. The pair-coherence
    contradiction itself is handled by a separate ERROR rule.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.status is None:
            continue

        expr_present = not _is_empty(xplc.status.comm_error_expr)
        desc_present = not _is_empty(xplc.status.comm_error_description)

        if expr_present and not desc_present:
            findings.append(
                Finding(
                    rule_id="R-PLC-021B",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.status.comm_error_description",
                    message=(
                        "x-plc.status.comm_error_expr is configured, but "
                        "comm_error_description is missing. "
                        f"{IMPLEMENTATION_WARNING_SUFFIX}"
                    ),
                )
            )

        if desc_present and not expr_present:
            findings.append(
                Finding(
                    rule_id="R-PLC-021B",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.status.comm_error_expr",
                    message=(
                        "x-plc.status.comm_error_description is configured, but "
                        "comm_error_expr is missing. "
                        f"{IMPLEMENTATION_WARNING_SUFFIX}"
                    ),
                )
            )

    return findings


def rule_xplc_status_comm_error_fields_coherent(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-021C:
    x-plc.status.comm_error_expr and comm_error_description must be configured
    together.

    This is a contradiction/coherence rule, so violations are ERROR.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.status is None:
            continue

        expr_present = not _is_empty(xplc.status.comm_error_expr)
        desc_present = not _is_empty(xplc.status.comm_error_description)

        if expr_present and not desc_present:
            findings.append(
                Finding(
                    rule_id="R-PLC-021C",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.status.comm_error_description",
                    message=(
                        "x-plc.status.comm_error_expr is configured, so "
                        "comm_error_description must also be configured."
                    ),
                )
            )

        if desc_present and not expr_present:
            findings.append(
                Finding(
                    rule_id="R-PLC-021C",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.status.comm_error_expr",
                    message=(
                        "x-plc.status.comm_error_description is configured, so "
                        "comm_error_expr must also be configured."
                    ),
                )
            )

    return findings


def rule_xplc_status_disabled_fields_coherent(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-022 / R-PLC-023:

    - ERROR if x-plc.status.disabled_* is present but status enum does not
      contain DISABLED:0
    - WARNING if status enum contains DISABLED:0 but x-plc.status.disabled_*
      is missing or empty
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.status is None:
            continue

        enum_members = _status_enum_members(mod) or {}
        status_has_disabled_0 = enum_members.get("DISABLED") == 0

        disabled_expr_present = not _is_empty(xplc.status.disabled_expr)
        disabled_desc_present = not _is_empty(xplc.status.disabled_description)

        if (disabled_expr_present or disabled_desc_present) and (not status_has_disabled_0):
            findings.append(
                Finding(
                    rule_id="R-PLC-022",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.status",
                    message=(
                        "x-plc.status.disabled_* is present but status enum does "
                        "not contain DISABLED:0."
                    ),
                )
            )

        if status_has_disabled_0:
            if _is_empty(xplc.status.disabled_expr):
                findings.append(
                    Finding(
                        rule_id="R-PLC-023",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.status.disabled_expr",
                        message=(
                            "Status enum contains DISABLED:0, but "
                            "x-plc.status.disabled_expr is not configured. "
                            f"{IMPLEMENTATION_WARNING_SUFFIX}"
                        ),
                    )
                )

            if _is_empty(xplc.status.disabled_description):
                findings.append(
                    Finding(
                        rule_id="R-PLC-023",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.status.disabled_description",
                        message=(
                            "Status enum contains DISABLED:0, but "
                            "x-plc.status.disabled_description is not configured. "
                            f"{IMPLEMENTATION_WARNING_SUFFIX}"
                        ),
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Target-related rules
# ---------------------------------------------------------------------------

def rule_xplc_target_change_possible_expr_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-026:
    If x-plc.target exists, change_possible_expr should be configured.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.target is None:
            continue

        if _is_empty(xplc.target.change_possible_expr):
            findings.append(
                Finding(
                    rule_id="R-PLC-026",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.target.change_possible_expr",
                    message=f"The field x-plc.target.change_possible_expr is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                )
            )

    return findings


def rule_xplc_target_reach_fields(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-024 / R-PLC-025:

    - ERROR if reach_* fields are present and module is not Drivable
    - ERROR if reach_abs_tolerance is present for non-numeric targets
    - WARNING if reach_timeout_s is missing for Drivable modules
    - WARNING if reach_abs_tolerance is missing for Drivable numeric targets
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.target is None:
            continue

        is_drv = _is_drivable(mod.interface_classes)
        target_type = _target_type(mod)

        if xplc.target.reach_timeout_s is not None and (not is_drv):
            findings.append(
                Finding(
                    rule_id="R-PLC-024",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_timeout_s",
                    message="x-plc.target.reach_timeout_s is only allowed for Drivable modules.",
                )
            )

        if xplc.target.reach_abs_tolerance is not None and (not is_drv):
            findings.append(
                Finding(
                    rule_id="R-PLC-024",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_abs_tolerance",
                    message="x-plc.target.reach_abs_tolerance is only allowed for Drivable modules.",
                )
            )

        if xplc.target.reach_abs_tolerance is not None and not _is_numeric_type(target_type):
            findings.append(
                Finding(
                    rule_id="R-PLC-024",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_abs_tolerance",
                    message=(
                        "x-plc.target.reach_abs_tolerance is only allowed for "
                        "Drivable modules with numeric target type ('double' or 'int')."
                    ),
                )
            )

        if not is_drv:
            continue

        if xplc.target.reach_timeout_s is None:
            findings.append(
                Finding(
                    rule_id="R-PLC-025",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_timeout_s",
                    message=f"The field x-plc.target.reach_timeout_s is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                )
            )

        if _is_numeric_type(target_type) and xplc.target.reach_abs_tolerance is None:
            findings.append(
                Finding(
                    rule_id="R-PLC-025",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_abs_tolerance",
                    message=f"The field x-plc.target.reach_abs_tolerance is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Value mapping rules
# ---------------------------------------------------------------------------

def rule_xplc_value_mapping_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-030 / R-PLC-031:
    Validate x-plc.value mapping according to the SECoP value type.

    Supported mapping policy:
    - numeric / string value -> read_expr
    - enum value             -> enum_tag

    Missing mapping fields produce WARNING.
    Contradictory mapping fields produce ERROR.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        v_type = _value_type(mod)
        if not v_type:
            continue

        v_cfg = xplc.value

        has_read_expr = bool(v_cfg and not _is_empty(v_cfg.read_expr))
        has_enum_tag = bool(v_cfg and not _is_empty(v_cfg.enum_tag))

        if _is_enum_type(v_type):
            if has_read_expr:
                findings.append(
                    Finding(
                        rule_id="R-PLC-030",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.value.read_expr",
                        message="Invalid x-plc.value: SECoP value is enum, so read_expr must not be defined.",
                    )
                )

            if not has_enum_tag:
                findings.append(
                    Finding(
                        rule_id="R-PLC-031",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.value.enum_tag",
                        message=f"The field x-plc.value.enum_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    )
                )

        elif _is_numeric_type(v_type) or _is_string_type(v_type):
            if has_enum_tag:
                findings.append(
                    Finding(
                        rule_id="R-PLC-030",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.value.enum_tag",
                        message=(
                            f"Invalid x-plc.value: SECoP value is type '{v_type}', "
                            "so enum_tag must not be defined."
                        ),
                    )
                )

            if not has_read_expr:
                findings.append(
                    Finding(
                        rule_id="R-PLC-031",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.value.read_expr",
                        message=f"The field x-plc.value.read_expr is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    )
                )

    return findings


def rule_xplc_value_outofrange_numeric_only(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-034:
    x-plc.value.outofrange_min/outofrange_max are optional, but only allowed for
    numeric SECoP value types ('double' or 'int') and must be configured
    together.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.value is None:
            continue

        v_type = _value_type(mod)
        v_cfg = xplc.value

        oor_min = v_cfg.outofrange_min
        oor_max = v_cfg.outofrange_max

        if oor_min is None and oor_max is None:
            continue

        if not _is_numeric_type(v_type):
            findings.append(
                Finding(
                    rule_id="R-PLC-034",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.value",
                    message=(
                        "Invalid x-plc.value out-of-range configuration: "
                        "outofrange_min/outofrange_max are only allowed for "
                        "numeric SECoP value types ('double' or 'int')."
                    ),
                )
            )
            continue

        if oor_min is None or oor_max is None:
            findings.append(
                Finding(
                    rule_id="R-PLC-034",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.value",
                    message=(
                        "Invalid x-plc.value out-of-range configuration: the "
                        "out-of-range feature requires both outofrange_min and "
                        "outofrange_max to be set."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Target mapping rules
# ---------------------------------------------------------------------------

def rule_xplc_target_mapping_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-032 / R-PLC-033:
    Validate x-plc.target mapping according to the SECoP target type.

    Supported mapping policy:
    - numeric / string target -> write_stmt
    - enum target             -> enum_tag

    Missing mapping fields produce WARNING.
    Contradictory mapping fields produce ERROR.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        t_type = _target_type(mod)
        if not t_type:
            continue

        t_cfg = xplc.target

        has_write_stmt = bool(t_cfg and not _is_empty(t_cfg.write_stmt))
        has_enum_tag = bool(t_cfg and not _is_empty(t_cfg.enum_tag))

        if _is_enum_type(t_type):
            if has_write_stmt:
                findings.append(
                    Finding(
                        rule_id="R-PLC-032",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.target.write_stmt",
                        message="Invalid x-plc.target: SECoP target is enum, so write_stmt must not be defined.",
                    )
                )

            if not has_enum_tag:
                findings.append(
                    Finding(
                        rule_id="R-PLC-033",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.target.enum_tag",
                        message=f"The field x-plc.target.enum_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    )
                )

        elif _is_numeric_type(t_type) or _is_string_type(t_type):
            if has_enum_tag:
                findings.append(
                    Finding(
                        rule_id="R-PLC-032",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.target.enum_tag",
                        message=(
                            f"Invalid x-plc.target: SECoP target is type '{t_type}', "
                            "so enum_tag must not be defined."
                        ),
                    )
                )

            if not has_write_stmt:
                findings.append(
                    Finding(
                        rule_id="R-PLC-033",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.target.write_stmt",
                        message=f"The field x-plc.target.write_stmt is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# clear_errors rules
# ---------------------------------------------------------------------------

def rule_xplc_clear_errors_cmd_stmt_optional(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-040:
    If a module defines clear_errors, x-plc.clear_errors.cmd_stmt may be
    missing or empty.

    The generated code will always clear the SECoP ErrorReport. cmd_stmt is only
    needed when the PLC project should perform additional hardware-specific
    recovery actions.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        accs = mod.accessibles or {}
        if "clear_errors" not in accs:
            continue

        xplc = mod.x_plc
        if not xplc or xplc.clear_errors is None:
            findings.append(
                Finding(
                    rule_id="R-PLC-040",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.clear_errors",
                    message=(
                        f"Missing PLC command statement for {mod_name}.clear_errors. "
                        "The generator will clear SECoP ErrorReport only (by default). "
                        "If you would like the command to perform an extra action, "
                        "write it in cmd_stmt."
                    ),
                )
            )
            continue

        if _is_empty(xplc.clear_errors.cmd_stmt):
            findings.append(
                Finding(
                    rule_id="R-PLC-040",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.clear_errors.cmd_stmt",
                    message=(
                        f"Missing PLC command statement for {mod_name}.clear_errors. "
                        "The generator will clear SECoP ErrorReport only (by default). "
                        "If you would like the command to perform an extra action, "
                        "write it in cmd_stmt."
                    ),
                )
            )

    return findings


def rule_xplc_clear_errors_only_if_command_exists(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-041:
    x-plc.clear_errors is only allowed when the module defines the standard
    SECoP command clear_errors.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.clear_errors is None:
            continue

        if "clear_errors" not in (mod.accessibles or {}):
            findings.append(
                Finding(
                    rule_id="R-PLC-041",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.clear_errors",
                    message=(
                        "x-plc.clear_errors is present but the module does not "
                        "define the SECoP command 'clear_errors'."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Custom parameter x-plc rules
# ---------------------------------------------------------------------------

def rule_xplc_custom_parameters_exist_and_match_accessibles(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-050:
    Every key under x-plc.custom_parameters must refer to an existing customised
    SECoP parameter of the same module.

    Conditions:
    - the accessible must exist
    - its name must start with '_'
    - it must not be a command
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        for cp_name in xplc.custom_parameters.keys():
            acc = (mod.accessibles or {}).get(cp_name)

            if acc is None:
                findings.append(
                    Finding(
                        rule_id="R-PLC-050",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}",
                        message=(
                            f"x-plc.custom_parameters.{cp_name} is present but "
                            "the SECoP accessible does not exist."
                        ),
                    )
                )
                continue

            if not cp_name.startswith("_"):
                findings.append(
                    Finding(
                        rule_id="R-PLC-050",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}",
                        message=(
                            "Only customised SECoP parameters (names starting "
                            "with '_') may appear under x-plc.custom_parameters."
                        ),
                    )
                )
                continue

            if (acc.datainfo.type or "").strip() == "command":
                findings.append(
                    Finding(
                        rule_id="R-PLC-050",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}",
                        message=(
                            f"{cp_name} is a customised command, not a customised "
                            "parameter, so it must not appear under "
                            "x-plc.custom_parameters."
                        ),
                    )
                )

    return findings


def rule_xplc_custom_parameter_mapping_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-051 / R-PLC-052:
    Validate each x-plc.custom_parameters.<name> mapping according to the
    customised parameter datainfo.type.

    Supported mapping policy:
    - numeric / string custom parameter -> read_expr
    - enum custom parameter             -> enum_tag
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        for cp_name, cp_cfg in xplc.custom_parameters.items():
            acc = (mod.accessibles or {}).get(cp_name)
            if acc is None:
                continue

            cp_type = (acc.datainfo.type or "").strip()

            has_read_expr = not _is_empty(cp_cfg.read_expr)
            has_enum_tag = not _is_empty(cp_cfg.enum_tag)

            if _is_enum_type(cp_type):
                if has_read_expr:
                    findings.append(
                        Finding(
                            rule_id="R-PLC-051",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}.read_expr",
                            message=(
                                f"Invalid mapping for customised parameter {cp_name}: "
                                "enum parameters must not define read_expr."
                            ),
                        )
                    )

                if not has_enum_tag:
                    findings.append(
                        Finding(
                            rule_id="R-PLC-052",
                            severity=Severity.WARNING,
                            path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}.enum_tag",
                            message=(
                                f"The field x-plc.custom_parameters.{cp_name}.enum_tag "
                                f"is not configured. {IMPLEMENTATION_WARNING_SUFFIX}"
                            ),
                        )
                    )

            elif _is_numeric_type(cp_type) or _is_string_type(cp_type):
                if has_enum_tag:
                    findings.append(
                        Finding(
                            rule_id="R-PLC-051",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}.enum_tag",
                            message=(
                                f"Invalid mapping for customised parameter {cp_name}: "
                                f"SECoP type is '{cp_type}', so enum_tag must not "
                                "be defined."
                            ),
                        )
                    )

                if not has_read_expr:
                    findings.append(
                        Finding(
                            rule_id="R-PLC-052",
                            severity=Severity.WARNING,
                            path=f"$.modules.{mod_name}.x-plc.custom_parameters.{cp_name}.read_expr",
                            message=(
                                f"The field x-plc.custom_parameters.{cp_name}.read_expr "
                                f"is not configured. {IMPLEMENTATION_WARNING_SUFFIX}"
                            ),
                        )
                    )

    return findings