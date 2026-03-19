from __future__ import annotations

"""
SECoP business rules (protocol/domain coherence).

Pydantic already validates the structural shape of the configuration:
- required fields
- field types
- nested object structure
- forbidden extra keys

These business rules validate higher-level constraints such as:
- protocol coherence between accessibles and interface classes
- supported datainfo types for this PLC-based SEC node
- readonly policy
- status structure and status-code conventions
- project-specific restrictions and simplifications

General policy
--------------
- ERROR means the configuration is not acceptable for this generator
- WARNING means generation may continue, but the resulting PLC project may still
  need manual completion
"""

from typing import List, Set, Dict

from codegen.model.secnode import SecNodeConfig, Module
from codegen.rules.types import Finding, Severity


# ---------------------------------------------------------------------------
# Protocol/type constants
# ---------------------------------------------------------------------------

PROTOCOL_TYPES = {
    "double",
    "scaled",
    "int",
    "bool",
    "enum",
    "string",
    "blob",
    "array",
    "tuple",
    "struct",
    "matrix",
    "command",
}

PLC_UNSUPPORTED_TYPES = {"scaled", "blob", "matrix", "struct"}

ALLOWED_TYPES_THIS_CODEGEN = PROTOCOL_TYPES - PLC_UNSUPPORTED_TYPES
NUMERIC_TYPES_THIS_CODEGEN = {"double", "int"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_class(m: Module, cls_name: str) -> bool:
    """
    Return True when the module declares the given interface class.
    """
    return cls_name in (m.interface_classes or [])


def _is_drivable(m: Module) -> bool:
    """
    Drivable modules are the most capable standard class in this project.
    """
    return _has_class(m, "Drivable")


def _is_writable(m: Module) -> bool:
    """
    Writable is explicit for Writable modules and implicit for Drivable modules.
    """
    return _has_class(m, "Writable") or _is_drivable(m)


def _is_readable(m: Module) -> bool:
    """
    Readable is explicit for Readable modules and implicit for Writable and
    Drivable modules.
    """
    return _has_class(m, "Readable") or _is_writable(m)


def _required_accessibles_for_module(m: Module) -> Set[str]:
    """
    Return the set of required standard accessibles for one module according to
    the simplified interface-class model used by this generator.

    Project simplification:
    - Readable: value, status, pollinterval
    - Writable: Readable + target
    - Drivable: Writable + stop
    """
    required: Set[str] = set()

    if _is_readable(m):
        required |= {"value", "status", "pollinterval"}

    if _is_writable(m):
        required |= {"target"}

    if _is_drivable(m):
        required |= {"stop"}

    return required


def _datainfo_fields_other_than_type_and_command(di) -> Dict[str, object]:
    """
    Return a small dictionary of optional DataInfo fields used by the generic
    field-coherence rule.

    This helper makes the later rule more readable.
    """
    return {
        "unit": di.unit,
        "min": di.min,
        "max": di.max,
        "maxchars": di.maxchars,
        "maxlen": di.maxlen,
        "members": di.members,
        "argument": di.argument,
        "result": di.result,
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def rule_non_empty_modules(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-NODE-001:
    The node must contain at least one module.

    Pydantic accepts an empty dictionary for "modules", so this must be enforced
    here as a business rule.
    """
    findings: List[Finding] = []

    if not cfg.modules:
        findings.append(
            Finding(
                rule_id="R-NODE-001",
                severity=Severity.ERROR,
                path="$.modules",
                message="Node must contain at least one module.",
            )
        )

    return findings


def rule_interface_classes_single(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-MOD-001:
    interface_classes must contain exactly one element:
    Readable OR Writable OR Drivable.

    Readable is implicit in Writable.
    Writable is implicit in Drivable.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        classes = mod.interface_classes

        if not isinstance(classes, list) or len(classes) != 1:
            findings.append(
                Finding(
                    rule_id="R-MOD-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.interface_classes",
                    message=(
                        "interface_classes must be a list with exactly one "
                        "element: Readable, Writable or Drivable."
                    ),
                )
            )
            continue

        cls = classes[0]
        if cls not in ("Readable", "Writable", "Drivable"):
            findings.append(
                Finding(
                    rule_id="R-MOD-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.interface_classes",
                    message=(
                        f"Invalid interface class '{cls}'. Allowed values are "
                        "Readable, Writable and Drivable."
                    ),
                )
            )

    return findings


def rule_features_and_offset_not_supported_on_plc(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-MOD-002:
    This PLC SEC node does not support the HasOffset feature or the standard
    SECoP 'offset' accessible.

    Only the feature name 'HasOffset' is recognised here. Any other feature
    name is treated as unsupported.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        feats = mod.features or []

        unknown = [f for f in feats if f != "HasOffset"]
        if unknown:
            findings.append(
                Finding(
                    rule_id="R-MOD-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.features",
                    message=(
                        "Unsupported feature(s) found in module.features. "
                        f"Unknown={unknown}"
                    ),
                )
            )

        if "HasOffset" in feats:
            findings.append(
                Finding(
                    rule_id="R-MOD-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.features",
                    message=(
                        "features includes 'HasOffset', but this PLC-based SEC "
                        "node does not use protocol-level offset handling."
                    ),
                )
            )

        if "offset" in (mod.accessibles or {}):
            findings.append(
                Finding(
                    rule_id="R-MOD-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.offset",
                    message=(
                        "Module defines 'offset', but this PLC-based SEC node "
                        "does not use protocol-level offset handling."
                    ),
                )
            )

    return findings


def rule_required_accessibles(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-CLS-001 / R-CLS-002 / R-CLS-003:
    Validate the standard required accessibles for each interface class.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        accessibles = mod.accessibles or {}

        if _is_readable(mod):
            missing = [k for k in ("value", "status", "pollinterval") if k not in accessibles]
            if missing:
                findings.append(
                    Finding(
                        rule_id="R-CLS-001",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles",
                        message=(
                            "Readable modules must define value, status and "
                            f"pollinterval. Missing={missing}"
                        ),
                    )
                )

        if _is_writable(mod) and "target" not in accessibles:
            findings.append(
                Finding(
                    rule_id="R-CLS-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target",
                    message="Writable and Drivable modules must define target.",
                )
            )

        if _is_drivable(mod) and "stop" not in accessibles:
            findings.append(
                Finding(
                    rule_id="R-CLS-003",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.stop",
                    message="Drivable modules must define stop.",
                )
            )

    return findings


def rule_forbidden_accessibles_by_class(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-CLS-004:
    Forbid standard accessibles that are not allowed for the module interface
    class.

    Any accessible whose name starts with '_' is considered customised and is
    always allowed by this rule.
    """
    findings: List[Finding] = []

    allowed_by_class = {
        "Readable": {"value", "status", "pollinterval", "clear_errors"},
        "Writable": {"value", "status", "pollinterval", "target", "target_limits", "clear_errors"},
        "Drivable": {"value", "status", "pollinterval", "target", "target_limits", "clear_errors", "stop"},
    }

    for mod_name, mod in cfg.modules.items():
        cls = mod.interface_classes[0]
        allowed = allowed_by_class.get(cls, set())

        for acc in mod.accessibles.keys():
            if acc.startswith("_"):
                continue

            if acc not in allowed:
                findings.append(
                    Finding(
                        rule_id="R-CLS-004",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc}",
                        message=(
                            f"Accessible '{acc}' is not allowed or implemented on current PLC SEC node for interface "
                            f"class '{cls}'."
                        ),
                    )
                )

    return findings


def rule_status_structure_and_codes(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-STAT-001 / 002 / 003 / 004 / 005 combined.

    Validate:
    - status is tuple(enum, string)
    - mandatory base status codes exist and use protocol-fixed numeric values
    - BUSY exists only for Drivable modules and must use code 300
    - DISABLED, if present, must use code 0
    - extra status members are allowed only as a warning for now; they are not
      supported by the current PLC SEC node generator
    """
    findings: List[Finding] = []

    base_required: Dict[str, int] = {"IDLE": 100, "WARN": 200, "ERROR": 400}
    allowed_status_keys = {"DISABLED", "IDLE", "WARN", "BUSY", "ERROR"}

    for mod_name, mod in cfg.modules.items():
        if "status" not in mod.accessibles:
            continue

        status = mod.accessibles["status"]
        di = status.datainfo

        if di.type != "tuple":
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.type",
                    message="status must use datainfo.type == 'tuple'.",
                )
            )
            continue

        if not isinstance(di.members, list) or len(di.members) != 2:
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members",
                    message=(
                        "status must be tuple(enum, string) with exactly two "
                        "members."
                    ),
                )
            )
            continue

        member0 = di.members[0]
        member1 = di.members[1]

        if not isinstance(member0, dict) or member0.get("type") != "enum":
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0]",
                    message="status.members[0] must be an enum definition.",
                )
            )
            continue

        if not isinstance(member1, dict) or member1.get("type") != "string":
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[1]",
                    message="status.members[1] must be a string definition.",
                )
            )
            continue

        enum_members = member0.get("members")
        if not isinstance(enum_members, dict):
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message="status enum members must be a dictionary.",
                )
            )
            continue

        expected_codes: Dict[str, int] = dict(base_required)

        if _is_drivable(mod):
            expected_codes["BUSY"] = 300

        for key, expected in expected_codes.items():
            if key not in enum_members:
                rid = "R-STAT-003" if key == "BUSY" else "R-STAT-002"
                findings.append(
                    Finding(
                        rule_id=rid,
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                        message=f"{key}:{expected} is required.",
                    )
                )
                continue

            actual = enum_members.get(key)
            if actual != expected:
                rid = "R-STAT-003" if key == "BUSY" else "R-STAT-002"
                findings.append(
                    Finding(
                        rule_id=rid,
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                        message=(
                            f"Wrong status code for '{key}': expected {expected}, "
                            f"got {actual}."
                        ),
                    )
                )

        if (not _is_drivable(mod)) and ("BUSY" in enum_members):
            findings.append(
                Finding(
                    rule_id="R-STAT-003",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message="BUSY is forbidden for non-Drivable modules.",
                )
            )

        if "DISABLED" in enum_members and enum_members.get("DISABLED") != 0:
            findings.append(
                Finding(
                    rule_id="R-STAT-004",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message=(
                        "Wrong status code for 'DISABLED': expected 0, got "
                        f"{enum_members.get('DISABLED')}."
                    ),
                )
            )

        extra_keys = sorted([k for k in enum_members.keys() if k not in allowed_status_keys])
        if extra_keys:
            findings.append(
                Finding(
                    rule_id="R-STAT-005",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message=(
                        "status enum contains unsupported extra members for the "
                        f"current PLC SEC node generator. Extra={extra_keys}"
                    ),
                )
            )

    return findings


def rule_custom_command_accessibles_warn(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-001:
    Custom command accessibles (name starts with '_') are allowed, but the
    generator does not implement them automatically yet.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            if acc_name.startswith("_") and acc.datainfo.type == "command":
                findings.append(
                    Finding(
                        rule_id="R-ACC-001",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}",
                        message=(
                            f"Custom command accessible '{acc_name}' is not "
                            "generated automatically; manual PLC implementation "
                            "will be required."
                        ),
                    )
                )

    return findings


def rule_accessible_members_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-002:
    Validate the expected container type of datainfo.members for supported
    datainfo.type values that use it.

    - enum  -> members must be a dict
    - tuple -> members must be a list
    - array -> members must be a dict
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo

            if di.type == "enum":
                if not isinstance(di.members, dict):
                    findings.append(
                        Finding(
                            rule_id="R-ACC-002",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.members",
                            message="Invalid datainfo.members for type 'enum' (must be a dict).",
                        )
                    )

            elif di.type == "tuple":
                if not isinstance(di.members, list):
                    findings.append(
                        Finding(
                            rule_id="R-ACC-002",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.members",
                            message="Invalid datainfo.members for type 'tuple' (must be a list).",
                        )
                    )

            elif di.type == "array":
                if not isinstance(di.members, dict):
                    findings.append(
                        Finding(
                            rule_id="R-ACC-002",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.members",
                            message="Invalid datainfo.members for type 'array' (must be a dict).",
                        )
                    )

    return findings


def rule_numeric_ranges_coherent(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-003:
    If both min and max exist, min must be strictly less than max.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            if di.min is not None and di.max is not None and di.min >= di.max:
                findings.append(
                    Finding(
                        rule_id="R-ACC-003",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo",
                        message="Invalid numeric range: min must be < max.",
                    )
                )

    return findings


def rule_numeric_ranges_must_define_both_ends(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-003B:
    For numeric accessibles used in this project, min and max must be defined
    together.

    Applied to:
    - value
    - target
    - target_limits

    Rules:
    - if min is configured, max must also be configured
    - if max is configured, min must also be configured
    """
    findings: List[Finding] = []

    checked_accessibles = {"value", "target", "target_limits"}

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            if acc_name not in checked_accessibles:
                continue

            di = acc.datainfo
            t = (di.type or "").strip()

            # Only numeric SECoP scalar types are relevant for min/max pairs in
            # the current generator.
            if t not in NUMERIC_TYPES_THIS_CODEGEN:
                continue

            has_min = di.min is not None
            has_max = di.max is not None

            if has_min and not has_max:
                findings.append(
                    Finding(
                        rule_id="R-ACC-003B",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.max",
                        message=(
                            f"{acc_name}.datainfo.min is configured, so "
                            f"{acc_name}.datainfo.max must also be configured."
                        ),
                    )
                )

            if has_max and not has_min:
                findings.append(
                    Finding(
                        rule_id="R-ACC-003B",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.min",
                        message=(
                            f"{acc_name}.datainfo.max is configured, so "
                            f"{acc_name}.datainfo.min must also be configured."
                        ),
                    )
                )

    return findings


def rule_target_limits_within_target(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-004:
    If target_limits exists, it must restrict target.

    This rule is only enforced when the relevant values are present.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        accessibles = mod.accessibles or {}

        if "target" not in accessibles or "target_limits" not in accessibles:
            continue

        target_di = accessibles["target"].datainfo
        limits_di = accessibles["target_limits"].datainfo

        if (
            target_di.min is not None
            and limits_di.min is not None
            and limits_di.min < target_di.min
        ):
            findings.append(
                Finding(
                    rule_id="R-ACC-004",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target_limits.datainfo",
                    message="target_limits.min must be >= target.min.",
                )
            )

        if (
            target_di.max is not None
            and limits_di.max is not None
            and limits_di.max > target_di.max
        ):
            findings.append(
                Finding(
                    rule_id="R-ACC-004",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target_limits.datainfo",
                    message="target_limits.max must be <= target.max.",
                )
            )

    return findings


def rule_string_requires_maxchars(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-005:
    string datainfo must define maxchars > 0 because PLC code generation needs a
    fixed string length.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            if di.type == "string":
                if di.maxchars is None or di.maxchars <= 0:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-005",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.maxchars",
                            message=(
                                "On PLC SEC node datainfo.maxchars is required (>0) when "
                                "datainfo.type == 'string'."
                            ),
                        )
                    )

    return findings


def rule_array_requires_maxlen(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-006:
    array datainfo must define maxlen > 0 because PLC code generation needs a
    fixed array length.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            if di.type == "array":
                maxlen = getattr(di, "maxlen", None)
                if maxlen is None or maxlen <= 0:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-006",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.maxlen",
                            message=(
                                "datainfo.maxlen is required (>0) when "
                                "datainfo.type == 'array'."
                            ),
                        )
                    )

    return findings


def rule_standard_accessible_readonly_policy(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-007:
    Enforce the current readonly policy for this PLC SEC node.

    Project policy:
    - command accessibles are always writable conceptually:
        * readonly=true is forbidden
        * readonly=false is accepted
    - for non-command accessibles, readonly=false is allowed only for:
        * target
        * pollinterval
    - every other non-command accessible must have readonly=true
    """
    findings: List[Finding] = []

    writable_allowed = {"target", "pollinterval"}

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            acc_type = (acc.datainfo.type or "").strip()

            # Commands are conceptually writable.
            # Because the Pydantic model defaults readonly to False, we only
            # reject the contradictory case readonly=True.
            if acc_type == "command":
                if acc.readonly is True:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-007",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.readonly",
                            message=(
                                "The 'readonly' property must not be true for "
                                "command accessibles. Commands are writable."
                            ),
                        )
                    )
                continue

            expected_readonly = acc_name not in writable_allowed

            if acc.readonly != expected_readonly:
                if expected_readonly:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-007",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.readonly",
                            message=(
                                "Current PLC SEC node implements readonly=false "
                                "only for the parameters 'target' and "
                                "'pollinterval'."
                            ),
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-007",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.readonly",
                            message=(
                                f"Accessible '{acc_name}' must have readonly=false "
                                "in this PLC SEC node configuration."
                            ),
                        )
                    )

    return findings


def rule_target_datainfo_type_matches_value(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-008:
    In Writable and Drivable modules, target and target_limits must use the same
    datainfo.type as value.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        if not _is_writable(mod):
            continue

        accs = mod.accessibles or {}
        if "value" not in accs or "target" not in accs:
            continue

        value_type = (accs["value"].datainfo.type or "").strip()
        target_type = (accs["target"].datainfo.type or "").strip()

        if target_type != value_type:
            findings.append(
                Finding(
                    rule_id="R-ACC-008",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target.datainfo.type",
                    message=(
                        "target.datainfo.type must match value.datainfo.type. "
                        f"value.type='{value_type}', target.type='{target_type}'."
                    ),
                )
            )

        if "target_limits" in accs:
            lim_type = (accs["target_limits"].datainfo.type or "").strip()
            if lim_type != value_type:
                findings.append(
                    Finding(
                        rule_id="R-ACC-008",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.target_limits.datainfo.type",
                        message=(
                            "target_limits.datainfo.type must match "
                            f"value.datainfo.type. value.type='{value_type}', "
                            f"target_limits.type='{lim_type}'."
                        ),
                    )
                )

    return findings


def rule_bool_type_forbidden(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-009:
    datainfo.type == 'bool' is not accepted by this PLC SEC node project.

    Project guidance:
    use enum with values 0 and 1 and provide descriptive member names, as in the
    typical heatswitch pattern:
        {"type": "enum", "members": {"off": 0, "on": 1}}
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            if (acc.datainfo.type or "").strip() == "bool":
                findings.append(
                    Finding(
                        rule_id="R-ACC-009",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.type",
                        message=(
                            "datainfo.type 'bool' is not accepted in this PLC SEC "
                            "node project. Please use enum type with values 0 and 1, "
                            "and provide descriptive member names, for example "
                            '{"type": "enum", "members": {"off": 0, "on": 1}}.'
                        ),
                    )
                )

    return findings


def rule_command_datainfo_shape(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-010:
    For datainfo.type == 'command':

    - the only optional sub-fields allowed are 'argument' and 'result'
    - if argument/result exist, they must define 'type'
    - argument/result types must be supported by this generator
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            if (di.type or "").strip() != "command":
                continue

            if (
                di.unit is not None
                or di.min is not None
                or di.max is not None
                or di.maxchars is not None
                or di.maxlen is not None
                or di.members is not None
            ):
                findings.append(
                    Finding(
                        rule_id="R-ACC-010",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo",
                        message=(
                            "Invalid command datainfo: only 'argument' and/or "
                            "'result' are allowed as optional fields."
                        ),
                    )
                )

            for sub_name in ("argument", "result"):
                sub = getattr(di, sub_name, None)
                if sub is None:
                    continue

                sub_type = (getattr(sub, "type", None) or "").strip()
                if not sub_type:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-010",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.{sub_name}.type",
                            message=(
                                f"Invalid command datainfo: '{sub_name}' must "
                                "define 'type'."
                            ),
                        )
                    )
                    continue

                if sub_type not in ALLOWED_TYPES_THIS_CODEGEN:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-010",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.{sub_name}.type",
                            message=(
                                f"Invalid command datainfo: '{sub_name}.type' "
                                "is not supported on this PLC SEC node."
                            ),
                        )
                    )

    return findings


def rule_datainfo_field_coherence(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-DI-002:
    Validate coherence between datainfo.type and the optional DataInfo fields.

    Rules enforced in this project:
    - min/max only allowed for numeric scalar types currently supported here
      ('double', 'int')
    - maxchars only allowed for 'string'
    - maxlen only allowed for 'array'
    - members only allowed for 'enum', 'tuple', 'array'
    - argument/result only allowed for 'command'
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            t = (di.type or "").strip()

            if (di.min is not None or di.max is not None) and t not in NUMERIC_TYPES_THIS_CODEGEN:
                findings.append(
                    Finding(
                        rule_id="R-DI-002",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo",
                        message=(
                            "datainfo.min and datainfo.max are only allowed for "
                            "numeric types currently supported by this generator "
                            "('double' or 'int')."
                        ),
                    )
                )

            if di.maxchars is not None and t != "string":
                findings.append(
                    Finding(
                        rule_id="R-DI-002",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.maxchars",
                        message="datainfo.maxchars is only allowed when datainfo.type == 'string'.",
                    )
                )

            if di.maxlen is not None and t != "array":
                findings.append(
                    Finding(
                        rule_id="R-DI-002",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.maxlen",
                        message="datainfo.maxlen is only allowed when datainfo.type == 'array'.",
                    )
                )

            if di.members is not None and t not in {"enum", "tuple", "array"}:
                findings.append(
                    Finding(
                        rule_id="R-DI-002",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.members",
                        message=(
                            "datainfo.members is only allowed when datainfo.type "
                            "is 'enum', 'tuple' or 'array'."
                        ),
                    )
                )

            if (di.argument is not None or di.result is not None) and t != "command":
                findings.append(
                    Finding(
                        rule_id="R-DI-002",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo",
                        message=(
                            "datainfo.argument and datainfo.result are only "
                            "allowed when datainfo.type == 'command'."
                        ),
                    )
                )

    return findings


def rule_datainfo_type_supported(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-DI-001:
    datainfo.type must be defined by the SECoP protocol and supported by the
    current PLC SEC node generator.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            t = (di.type or "").strip()

            if t in PLC_UNSUPPORTED_TYPES:
                findings.append(
                    Finding(
                        rule_id="R-DI-001",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.type",
                        message=(
                            "datainfo.type is defined by SECoP but not supported "
                            "by the current PLC SEC node generator."
                        ),
                    )
                )
                continue

            if t not in PROTOCOL_TYPES:
                findings.append(
                    Finding(
                        rule_id="R-DI-001",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.type",
                        message=f"datainfo.type '{t}' is not defined by the SECoP protocol.",
                    )
                )

    return findings