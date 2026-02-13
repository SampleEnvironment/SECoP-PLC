from __future__ import annotations

"""
PLC/tooling rules (x-plc coherence + mapping completeness).

These rules do NOT check ST syntax correctness.
They ensure:
- x-plc does not reference unknown accessibles
- x-plc mappings are coherent with SECoP datainfo (ERROR on contradictions)
- missing mappings generate implementation warnings
"""

from typing import List, Optional, Dict, Any

from codegen.model.secnode import SecNodeConfig
from codegen.rules.types import Finding, Severity


IMPLEMENTATION_WARNING_SUFFIX = (
    "Manual PLC implementation will be required. Refer to generated tasks list."
)


def _is_empty(value: Optional[str]) -> bool:
    return value is None or str(value).strip() == ""


def _is_drivable(interface_classes: Optional[List[str]]) -> bool:
    return "Drivable" in (interface_classes or [])


def _status_enum_members(mod: Any) -> Optional[Dict[str, int]]:
    """
    Return status enum members dict if status is tuple(enum,string), else None.
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


def rule_xplc_keys_exist_in_secop_accessibles(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-001:
    x-plc keys must match existing SECoP accessibles.
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
                            f"x-plc.{x_key} is present but the SECoP accessible '{acc_key}' is missing"
                        ),
                        hint=(
                            f"Either remove x-plc.{x_key} or add '{acc_key}' under "
                            f"modules.{mod_name}.accessibles."
                        ),
                    )
                )

    return findings


def rule_xplc_node_fields_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-010:
    Node-level x-plc fields should be configured.
    Empty string values (or missing optional fields) generate WARNING (implementation required).
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
                category="implementation",
                plc_refs=["SecopInit"],
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
                category="implementation",
                plc_refs=["SecopInit"],
            )
        )

    if tcp.server_port is None:
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.tcp.server_port",
                message=f"The field x-plc.tcp.server_port is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                category="implementation",
                plc_refs=["SecopInit"],
            )
        )

    if _is_empty(tcp.interface_healthy_tag):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.tcp.interface_healthy_tag",
                message=f"The field x-plc.tcp.interface_healthy_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                category="implementation",
                plc_refs=["SecopMapFromPlc"],
            )
        )

    if _is_empty(xplc.secop_version):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.secop_version",
                message=f"The field x-plc.secop_version is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                category="implementation",
                plc_refs=["SecopInit"],
            )
        )

    if _is_empty(xplc.plc_timestamp_tag):
        findings.append(
            Finding(
                rule_id="R-PLC-010",
                severity=Severity.WARNING,
                path="$.x-plc.plc_timestamp_tag",
                message=f"The field x-plc.plc_timestamp_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                category="implementation",
                plc_refs=["SecopMapFromPlc"],
            )
        )

    return findings


def rule_xplc_module_timestamp_tag_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-020:
    x-plc.timestamp_tag should be configured (WARNING, implementation required).
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
                    category="implementation",
                    plc_refs=["SecopMapFromPlc"],
                )
            )

    return findings


def rule_xplc_status_hw_error_fields_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-021:
    If x-plc.status exists, hw_error_expr and hw_error_description should be configured
    (WARNING, implementation required).
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
                    category="implementation",
                    plc_refs=["SecopMapFromPlc"],
                )
            )

        if _is_empty(xplc.status.hw_error_description):
            findings.append(
                Finding(
                    rule_id="R-PLC-021",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.status.hw_error_description",
                    message=f"The field x-plc.status.hw_error_description is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    category="implementation",
                    plc_refs=["SecopMapFromPlc"],
                )
            )

    return findings


def rule_xplc_status_disabled_fields_coherent(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-022 / R-PLC-023:
    - ERROR if x-plc.status.disabled_* is present but status enum does not contain DISABLED:0.
    - WARNING if status enum contains DISABLED:0 but x-plc.status.disabled_* is missing/empty.
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
                    message="x-plc.status.disabled_* is present but status enum does not contain DISABLED:0.",
                    hint="Add DISABLED:0 to status enum members or remove x-plc.status.disabled_* fields.",
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
                            "Status enum contains DISABLED:0, but x-plc.status.disabled_expr is not configured. "
                            f"{IMPLEMENTATION_WARNING_SUFFIX}"
                        ),
                        category="implementation",
                        plc_refs=["SecopMapFromPlc"],
                    )
                )

            if _is_empty(xplc.status.disabled_description):
                findings.append(
                    Finding(
                        rule_id="R-PLC-023",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.status.disabled_description",
                        message=(
                            "Status enum contains DISABLED:0, but x-plc.status.disabled_description is not configured. "
                            f"{IMPLEMENTATION_WARNING_SUFFIX}"
                        ),
                        category="implementation",
                        plc_refs=["SecopMapFromPlc"],
                    )
                )

    return findings


def rule_xplc_target_change_possible_expr_configured(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-026:
    If x-plc.target exists, change_possible_expr should be configured
    (WARNING, implementation required).
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
                    category="implementation",
                    plc_refs=["SecopMapFromPlc"],
                )
            )

    return findings


def rule_xplc_target_reach_fields(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-024 / R-PLC-025:
    - ERROR if reach_* fields are present and module is not Drivable.
    - WARNING if reach_timeout_s is missing for Drivable modules.
    - WARNING if reach_abs_tolerance is missing for Drivable modules with non-enum target.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc or xplc.target is None:
            continue

        is_drv = _is_drivable(mod.interface_classes)

        accs = mod.accessibles or {}
        target_type = ""
        if "target" in accs:
            target_type = (accs["target"].datainfo.type or "").strip()

        # ERROR if present but not Drivable
        if xplc.target.reach_timeout_s is not None and (not is_drv):
            findings.append(
                Finding(
                    rule_id="R-PLC-024",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_timeout_s",
                    message="x-plc.target.reach_timeout_s is only allowed for Drivable modules.",
                    hint="Remove reach_timeout_s or change module interface_classes to Drivable.",
                )
            )

        if xplc.target.reach_abs_tolerance is not None and (not is_drv):
            findings.append(
                Finding(
                    rule_id="R-PLC-024",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_abs_tolerance",
                    message="x-plc.target.reach_abs_tolerance is only allowed for Drivable modules.",
                    hint="Remove reach_abs_tolerance or change module interface_classes to Drivable.",
                )
            )

        # WARNINGS only apply for Drivable
        if not is_drv:
            continue

        # reach_timeout_s required for Drivable (enum or non-enum)
        if xplc.target.reach_timeout_s is None:
            findings.append(
                Finding(
                    rule_id="R-PLC-025",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_timeout_s",
                    message=f"The field x-plc.target.reach_timeout_s is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    category="implementation",
                    plc_refs=["SecopInit"],
                )
            )

        # reach_abs_tolerance required only for Drivable non-enum target
        if target_type != "enum" and xplc.target.reach_abs_tolerance is None:
            findings.append(
                Finding(
                    rule_id="R-PLC-025",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.x-plc.target.reach_abs_tolerance",
                    message=f"The field x-plc.target.reach_abs_tolerance is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                    category="implementation",
                    plc_refs=[f"ST_Module_{mod_name}"],
                )
            )

    return findings


def rule_xplc_value_mapping_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-030 / R-PLC-031:
    Validate polymorphic x-plc.value mapping for enum vs non-enum values.

    - WARNING (implementation) if missing/empty.
    - ERROR only on contradictions.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        accs = mod.accessibles or {}
        if "value" not in accs:
            continue

        v_type = (accs["value"].datainfo.type or "").strip()
        v_cfg = xplc.value

        has_read_expr = bool(v_cfg and (v_cfg.read_expr or "").strip())
        has_enum_tag = bool(v_cfg and (v_cfg.enum_tag or "").strip())
        has_enum_map = bool(v_cfg and v_cfg.enum_member_map)

        if v_type == "enum":
            if has_read_expr:
                findings.append(
                    Finding(
                        rule_id="R-PLC-030",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.value.read_expr",
                        message="Invalid x-plc.value: SECoP value is enum, so read_expr must not be defined.",
                        hint="Use x-plc.value.enum_tag + x-plc.value.enum_member_map for enum values.",
                    )
                )

            if not (has_enum_tag and has_enum_map):
                findings.append(
                    Finding(
                        rule_id="R-PLC-031",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.value",
                        message=f"The field x-plc.value (enum mapping) is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                        category="implementation",
                        plc_refs=["SecopMapFromPlc", f"ET_Module_{mod_name}"],
                    )
                )

        else:
            if has_enum_tag or has_enum_map:
                findings.append(
                    Finding(
                        rule_id="R-PLC-030",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.value",
                        message=(
                            f"Invalid x-plc.value: SECoP value is type '{v_type}', "
                            "so enum_tag/enum_member_map must not be defined."
                        ),
                        hint="Use x-plc.value.read_expr for non-enum values.",
                    )
                )

            if not has_read_expr:
                findings.append(
                    Finding(
                        rule_id="R-PLC-031",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.value.read_expr",
                        message=f"The field x-plc.value.read_expr is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                        category="implementation",
                        plc_refs=["SecopMapFromPlc"],
                    )
                )

    return findings


def rule_xplc_target_mapping_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-032 / R-PLC-033:
    Validate polymorphic x-plc.target mapping for enum vs non-enum targets.

    - WARNING (implementation) if missing/empty.
    - ERROR only on contradictions.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        xplc = mod.x_plc
        if not xplc:
            continue

        accs = mod.accessibles or {}
        if "target" not in accs:
            continue

        t_type = (accs["target"].datainfo.type or "").strip()
        t_cfg = xplc.target

        has_write_stmt = bool(t_cfg and (t_cfg.write_stmt or "").strip())
        has_enum_tag = bool(t_cfg and (t_cfg.enum_tag or "").strip())

        if t_type == "enum":
            if has_write_stmt:
                findings.append(
                    Finding(
                        rule_id="R-PLC-032",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.target.write_stmt",
                        message="Invalid x-plc.target: SECoP target is enum, so write_stmt must not be defined.",
                        hint="Use x-plc.target.enum_tag for enum targets.",
                    )
                )

            if not has_enum_tag:
                findings.append(
                    Finding(
                        rule_id="R-PLC-033",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.target.enum_tag",
                        message=f"The field x-plc.target.enum_tag is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                        category="implementation",
                        plc_refs=["SecopMapToPlc"],
                    )
                )

            if t_cfg is not None and (t_cfg.reach_abs_tolerance is not None):
                findings.append(
                    Finding(
                        rule_id="R-PLC-032",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.target.reach_abs_tolerance",
                        message="Invalid x-plc.target.reach_abs_tolerance: enum targets must not use reach_abs_tolerance.",
                        hint="Remove reach_abs_tolerance for enum targets.",
                    )
                )

        else:
            if has_enum_tag:
                findings.append(
                    Finding(
                        rule_id="R-PLC-032",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.x-plc.target.enum_tag",
                        message=f"Invalid x-plc.target: SECoP target is type '{t_type}', so enum_tag must not be defined.",
                        hint="Use x-plc.target.write_stmt for non-enum targets.",
                    )
                )

            if not has_write_stmt:
                findings.append(
                    Finding(
                        rule_id="R-PLC-033",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.x-plc.target.write_stmt",
                        message=f"The field x-plc.target.write_stmt is not configured. {IMPLEMENTATION_WARNING_SUFFIX}",
                        category="implementation",
                        plc_refs=["SecopMapToPlc"],
                    )
                )

    return findings


def rule_xplc_clear_errors_cmd_stmt_optional(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-PLC-040:
    If module defines clear_errors, cmd_stmt may be missing/empty (WARNING).
    The generator will always clear SECoP ErrorReport; cmd_stmt is only for extra actions.
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
                        "If you would like the command to perform an extra action, write it in cmd_stmt."
                    ),
                    category="implementation",
                    plc_refs=["SecopMapToPlc"],
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
                        "If you would like the command to perform an extra action, write it in cmd_stmt."
                    ),
                    category="implementation",
                    plc_refs=["SecopMapToPlc"],
                )
            )

    return findings
