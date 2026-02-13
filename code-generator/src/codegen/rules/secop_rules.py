from __future__ import annotations

"""
SECoP business rules (protocol/domain coherence).

Pydantic already validated the "shape" (types, required fields, etc.).
These rules validate cross-field constraints and project-specific SECoP constraints.
"""

from typing import List, Set, Dict

from codegen.model.secnode import SecNodeConfig, Module
from codegen.rules.types import Finding, Severity

# --- Protocol/type constants --------------------------------------------------

PROTOCOL_TYPES = {
"double", "scaled", "int", "bool", "enum", "string",
"blob", "array", "tuple", "struct", "matrix", "command",
}

PLC_UNSUPPORTED_TYPES = {"scaled", "blob", "matrix", "struct"}

ALLOWED_TYPES_THIS_CODEGEN = PROTOCOL_TYPES - PLC_UNSUPPORTED_TYPES

# --- Helpers -----------------------------------------------------------------

def _has_class(m: Module, cls_name: str) -> bool:
    return cls_name in (m.interface_classes or [])


def _is_drivable(m: Module) -> bool:
    return _has_class(m, "Drivable")


def _is_writable(m: Module) -> bool:
    return _has_class(m, "Writable") or _is_drivable(m)


def _is_readable(m: Module) -> bool:
    return _has_class(m, "Readable") or _is_writable(m)


def _required_accessibles_for_module(m: Module) -> Set[str]:
    """
    Project simplification:
    - Readable: value, status, pollinterval
    - Writable: Readable + target
    - Drivable: Writable + stop
    """
    required = set()
    if _is_readable(m):
        required |= {"value", "status", "pollinterval"}
    if _is_writable(m):
        required |= {"target"}
    if _is_drivable(m):
        required |= {"stop"}
    return required


# --- Rules -------------------------------------------------------------------

def rule_non_empty_modules(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-NODE-001:
    Node must contain at least one module.

    Note:
    Pydantic accepts an empty dict for modules (it's still a valid dict type),
    so this rule enforces a business constraint.
    """
    findings: List[Finding] = []

    if not cfg.modules:
        findings.append(
            Finding(
                rule_id="R-NODE-001",
                severity=Severity.ERROR,
                path="$.modules",
                message="Node must contain at least one module",
            )
        )

    return findings


def rule_interface_classes_single(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-MOD-001:
    "interface_classes" must be a list with exactly one element:
    Readable OR Writable OR Drivable.

    Readable is implicit in Writable, and Writable is implicit in Drivable.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        classes = mod.interface_classes

        # Pydantic already ensures it's a list[str],
        # but we still enforce the project rule: exactly one class.
        if not isinstance(classes, list) or len(classes) != 1:
            findings.append(
                Finding(
                    rule_id="R-MOD-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.interface_classes",
                    message="interface_classes must be a list with exactly one element",
                    hint=(
                        "Use exactly one of: ['Readable'], ['Writable'], or ['Drivable']. "
                        "Readable is implicit in Writable, and Writable is implicit in Drivable."
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
                    message=f"Invalid interface class '{cls}'",
                    hint=(
                        "Allowed values are: Readable, Writable, Drivable. "
                        "Readable is implicit in Writable, and Writable is implicit in Drivable."
                    ),
                )
            )

    return findings


def rule_features_and_offset_not_supported_on_plc(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-MOD-002:
    PLC SEC node does not support HasOffset feature nor the 'offset' accessible.
    Only known feature name is HasOffset; any other feature name is not implemented.
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
                    message="Unsupported feature(s) in module.features (not implemented on this PLC SEC node).",
                    hint=f"Only supported protocol feature name is 'HasOffset' (but PLC does not implement it). Unknown={unknown}",
                )
            )

        if "HasOffset" in feats:
            findings.append(
                Finding(
                    rule_id="R-MOD-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.features",
                    message="features includes 'HasOffset', but this PLC SEC node does not implement HasOffset.",
                    hint="For PLC nodes, offset/scaling/format conversions should be handled directly in PLC logic; provide the final scaled value via 'value'.",
                )
            )

        if "offset" in (mod.accessibles or {}):
            findings.append(
                Finding(
                    rule_id="R-MOD-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.offset",
                    message="Module defines 'offset', but this PLC SEC node does not implement the offset accessible.",
                    hint="For PLC nodes, apply offsets in PLC logic and expose only the final scaled value via 'value'.",
                )
            )

    return findings


def rule_required_accessibles(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-CLS-001 / R-CLS-002 / R-CLS-003:
    Required accessibles depending on interface class.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        accessibles = mod.accessibles or {}

        # R-CLS-001 — Readable required accessibles
        if _is_readable(mod):
            missing = [k for k in ("value", "status", "pollinterval") if k not in accessibles]
            if missing:
                findings.append(
                    Finding(
                        rule_id="R-CLS-001",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles",
                        message="Readable modules must define value/status/pollinterval",
                        hint=f"Missing: {missing}",
                    )
                )

        # R-CLS-002 — Writable required accessible: target
        if _is_writable(mod) and "target" not in accessibles:
            findings.append(
                Finding(
                    rule_id="R-CLS-002",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target",
                    message="Writable/Drivable modules must define target",
                )
            )

        # R-CLS-003 — Drivable required command: stop
        if _is_drivable(mod) and "stop" not in accessibles:
            findings.append(
                Finding(
                    rule_id="R-CLS-003",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.stop",
                    message="Drivable modules must define stop command",
                )
            )

    return findings


def rule_forbidden_accessibles_by_class(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-CLS-004:
    Forbid standard SECoP accessibles that are not allowed for the module's interface class.
    Any accessible whose name starts with '_' is considered "customised" and is always allowed.
    """
    findings: List[Finding] = []

    allowed_by_class = {
        "Readable": {"value", "status", "pollinterval", "clear_errors"},
        "Writable": {"value", "status", "pollinterval", "target", "target_limits", "clear_errors"},
        "Drivable": {"value", "status", "pollinterval", "target", "target_limits", "clear_errors", "stop"},
    }

    for mod_name, mod in cfg.modules.items():
        cls = mod.interface_classes[0]  # safe because R-MOD-001 enforces exactly 1
        allowed = allowed_by_class.get(cls, set())

        for acc in mod.accessibles.keys():
            # Customised accessibles are allowed
            if acc.startswith("_"):
                continue

            if acc not in allowed:
                findings.append(
                    Finding(
                        rule_id="R-CLS-004",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc}",
                        message=f"Accessible '{acc}' is not allowed for interface class '{cls}'",
                        hint=(
                            "Supported non-customised accessibles are: "
                            "Readable: value, status, pollinterval, clear_errors; "
                            "Writable: Readable + target, target_limits; "
                            "Drivable: Writable + stop."
                        ),
                    )
                )

    return findings


def rule_status_structure_and_codes(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-STAT-001/002/003/004/005 combined. Validate:
    - status is tuple(enum, string)
    - base status codes are present AND fixed by protocol:
        * IDLE=100, WARN=200, ERROR=400
      (ERROR if missing OR wrong status code)
    - BUSY:
        * required for Drivable modules with fixed code BUSY=300
        * forbidden for non-Drivable modules
      (ERROR if missing/forbidden OR if present with a wrong code)
    - DISABLED code must be 0 if present
    - extra status enum members are not supported by the current PLC SEC node version
      (WARNING; they will be ignored by the generator)
    """
    findings: List[Finding] = []

    base_required: Dict[str, int] = {"IDLE": 100, "WARN": 200, "ERROR": 400}
    allowed_status_keys = {"DISABLED", "IDLE", "WARN", "BUSY", "ERROR"}

    for mod_name, mod in cfg.modules.items():
        if "status" not in mod.accessibles:
            continue

        status = mod.accessibles["status"]
        di = status.datainfo

        # 1) Structure: tuple(enum, string)
        if di.type != "tuple":
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.type",
                    message="status must be datainfo.type == 'tuple'",
                )
            )
            continue

        if not isinstance(di.members, list) or len(di.members) != 2:
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members",
                    message="status must be tuple(enum,string) with exactly 2 members, as defined by the protocol",
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
                    message="status.members[0] must be an enum definition",
                )
            )
            continue

        if not isinstance(member1, dict) or member1.get("type") != "string":
            findings.append(
                Finding(
                    rule_id="R-STAT-001",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[1]",
                    message="status.members[1] must be a string definition",
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
                    message="status enum members must be a dictionary",
                )
            )
            continue

        # disabled_expr
        disabled_expr = ""
        if mod.x_plc and mod.x_plc.status:
            disabled_expr = (mod.x_plc.status.disabled_expr or "").strip()

        # 2) Expected codes (presence + exact code) for mandatory states
        expected_codes: Dict[str, int] = dict(base_required)

        # BUSY iff Drivable
        if _is_drivable(mod):
            expected_codes["BUSY"] = 300

        # 2a) Validate expected keys: missing or wrong code
        for key, expected in expected_codes.items():
            if key not in enum_members:
                rid = "R-STAT-002"
                if key == "BUSY":
                    rid = "R-STAT-003"

                findings.append(
                    Finding(
                        rule_id=rid,
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                        message=f"{key}:{expected} is required",
                    )
                )
                continue

            actual = enum_members.get(key)
            if actual != expected:
                rid = "R-STAT-002"
                if key == "BUSY":
                    rid = "R-STAT-003"

                findings.append(
                    Finding(
                        rule_id=rid,
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                        message=f"Wrong status code for '{key}': expected {expected}, got {actual}",
                        hint="Status codes are fixed by the SECoP protocol.",
                    )
                )

        # 3) Forbidden keys
        if (not _is_drivable(mod)) and ("BUSY" in enum_members):
            findings.append(
                Finding(
                    rule_id="R-STAT-003",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message="BUSY is forbidden for non-Drivable modules",
                )
            )

        # 4) DISABLED: if present, it must use the fixed code 0 (no x-plc coherence checks here)
        if "DISABLED" in enum_members and enum_members.get("DISABLED") != 0:
            findings.append(
                Finding(
                    rule_id="R-STAT-004",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message=f"Wrong status code for 'DISABLED': expected 0, got {enum_members.get('DISABLED')}",
                    hint="DISABLED status code is fixed by the SECoP protocol.",
                )
            )

        # 5) Extra status codes (WARNING)
        extra_keys = sorted([k for k in enum_members.keys() if k not in allowed_status_keys])
        if extra_keys:
            findings.append(
                Finding(
                    rule_id="R-STAT-005",
                    severity=Severity.WARNING,
                    path=f"$.modules.{mod_name}.accessibles.status.datainfo.members[0].members",
                    message=(
                        "Status enum contains unsupported members for current PLC SEC node version; "
                        f"they will be ignored by the generator. Extra={extra_keys}"
                    ),
                )
            )

    return findings


def rule_custom_command_accessibles_warn(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-001:
    Custom command accessibles (name starts with '_') are allowed, but the generator
    will not implement them automatically. We warn so the developer completes the PLC code.
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
                            f"Custom command accessible '{acc_name}' is not generated automatically; "
                            "the generator will emit placeholders and the developer must implement it manually."
                        ),
                        hint="Implement the command behaviour manually in the PLC project (or follow the demo patterns).",
                    )
                )

    return findings


def rule_accessible_members_by_type(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-002:
    datainfo.members rules by type:
    - enum  => members must be a dict
    - tuple => members must be a list
    - array => members must be a dict
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
                            message="Invalid datainfo.members for type 'array' (must be an object/dict).",
                        )
                    )

    return findings


def rule_numeric_ranges_coherent(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-003:
    If both min and max exist, min must be < max.
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


def rule_target_limits_within_target(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-004:
    If target_limits exists, it must restrict target:
    - target_limits.min >= target.min
    - target_limits.max <= target.max

    We only enforce the check when the relevant min/max values are present.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        accessibles = mod.accessibles or {}

        if "target" not in accessibles or "target_limits" not in accessibles:
            continue

        target_di = accessibles["target"].datainfo
        limits_di = accessibles["target_limits"].datainfo

        # Only check when both sides provide the values needed.
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
                    message="target_limits.min must be >= target.min (target_limits restricts target).",
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
                    message="target_limits.max must be <= target.max (target_limits restricts target).",
                )
            )

    return findings


def rule_string_requires_maxchars(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-005:
    If datainfo.type == 'string', maxchars must be provided (>0),
    because PLC code needs a fixed string length.
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
                            message="datainfo.maxchars is required (>0) when datainfo.type == 'string'.",
                            hint="Set maxchars so the generator can declare a PLC STRING with a fixed length.",
                        )
                    )

    return findings


def rule_array_requires_maxlen(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-006:
    If datainfo.type == 'array', maxlen must be provided (>0),
    because PLC code needs a fixed array length.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            di = acc.datainfo
            if di.type == "array":
                # maxlen is expected in DataInfo model (Optional[int])
                maxlen = getattr(di, "maxlen", None)
                if maxlen is None or maxlen <= 0:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-006",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.maxlen",
                            message="datainfo.maxlen is required (>0) when datainfo.type == 'array'.",
                            hint="Set maxlen so the generator can declare a PLC ARRAY with a fixed length.",
                        )
                    )

    return findings


def rule_standard_accessible_readonly_policy(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-007:
    Enforce readonly policy for standard SECoP accessibles used in this project:
    - value   must be readonly == True
    - status  must be readonly == True
    - target  must be readonly == False
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        accs = mod.accessibles or {}

        # value
        if "value" in accs and accs["value"].readonly is not True:
            findings.append(
                Finding(
                    rule_id="R-ACC-007",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.value.readonly",
                    message="Accessible 'value' must have readonly=true.",
                )
            )

        # status
        if "status" in accs and accs["status"].readonly is not True:
            findings.append(
                Finding(
                    rule_id="R-ACC-007",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.status.readonly",
                    message="Accessible 'status' must have readonly=true.",
                )
            )

        # target
        if "target" in accs and accs["target"].readonly is not False:
            findings.append(
                Finding(
                    rule_id="R-ACC-007",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target.readonly",
                    message="Accessible 'target' must have readonly=false.",
                )
            )

    return findings

def rule_target_datainfo_type_matches_value(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-008:
    In Writable/Drivable modules, target (and optional target_limits) must have the same datainfo.type as value.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        if not _is_writable(mod):  # writable includes drivable via _is_writable()
            continue

        accs = mod.accessibles or {}
        if "value" not in accs or "target" not in accs:
            continue  # other rules already handle required accessibles

        value_type = (accs["value"].datainfo.type or "").strip()
        target_type = (accs["target"].datainfo.type or "").strip()

        if target_type != value_type:
            findings.append(
                Finding(
                    rule_id="R-ACC-008",
                    severity=Severity.ERROR,
                    path=f"$.modules.{mod_name}.accessibles.target.datainfo.type",
                    message="target.datainfo.type must match value.datainfo.type",
                    hint=f"value.type='{value_type}', target.type='{target_type}'",
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
                        message="target_limits.datainfo.type must match value.datainfo.type",
                        hint=f"value.type='{value_type}', target_limits.type='{lim_type}'",
                    )
                )

    return findings



def rule_checkable_requires_manual_plc(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-009:
    If an accessible has checkable=true, generator will emit placeholders and developer must complete PLC code.
    """
    findings: List[Finding] = []

    for mod_name, mod in cfg.modules.items():
        for acc_name, acc in (mod.accessibles or {}).items():
            if acc.checkable is True:
                findings.append(
                    Finding(
                        rule_id="R-ACC-009",
                        severity=Severity.WARNING,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.checkable",
                        message="checkable=true requires manual PLC implementation (generator will emit placeholders)",
                        category="implementation",
                        plc_refs=[f"ST_Module_{mod_name}"],
                    )
                )

    return findings


def rule_command_datainfo_shape(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-ACC-010:
    For datainfo.type == 'command':
    - only optional fields allowed are 'argument' and 'result'
    - if argument/result exist, they must contain 'type'
    - argument/result types must be supported by this generator (same constraints as R-DI-001)
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
                        message="Invalid command datainfo: only 'argument' and/or 'result' are allowed as optional fields.",
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
                            message=f"Invalid command datainfo: '{sub_name}' must define 'type'.",
                        )
                    )
                    continue

                if sub_type not in ALLOWED_TYPES_THIS_CODEGEN:
                    findings.append(
                        Finding(
                            rule_id="R-ACC-010",
                            severity=Severity.ERROR,
                            path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.{sub_name}.type",
                            message=f"Invalid command datainfo: '{sub_name}.type' is not supported on this PLC SEC node.",
                            hint=f"Allowed types (this generator): {sorted(ALLOWED_TYPES_THIS_CODEGEN)}",
                        )
                    )

    return findings


def rule_datainfo_type_supported(cfg: SecNodeConfig) -> List[Finding]:
    """
    R-DI-001:
    datainfo.type must be defined by the SECoP protocol and supported by the current PLC SEC node version.
    """
    findings: List[Finding] = []

    allowed_sorted = sorted(ALLOWED_TYPES_THIS_CODEGEN)

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
                        message="type not required/supported on current sec node plc version",
                        hint=f"Allowed types (this generator): {allowed_sorted}",
                    )
                )
                continue

            if t not in PROTOCOL_TYPES:
                findings.append(
                    Finding(
                        rule_id="R-DI-001",
                        severity=Severity.ERROR,
                        path=f"$.modules.{mod_name}.accessibles.{acc_name}.datainfo.type",
                        message=f"datainfo.type '{t}' is not defined by the SECoP protocol",
                        hint=f"Allowed types (this generator): {allowed_sorted}",
                    )
                )

    return findings


