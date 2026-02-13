from __future__ import annotations

"""
Core types for business-rule validation.

We keep these types independent from Pydantic models so that:
- rules can be tested easily,
- reporting is consistent,
- severity can be handled uniformly (ERROR stops, WARNING continues).
"""

from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, Optional, List


class Severity(str, Enum):
    """
    Two-level severity model:
    - ERROR: cannot proceed to generate an importable PLC project.
    - WARNING: generation can continue, but placeholders will be emitted.
    """
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Finding:
    """
    A single rule finding.

    Fields:
    - rule_id: stable identifier (used in documentation and CI logs later).
    - severity: ERROR or WARNING.
    - path: JSONPath-like location to help users fix the issue quickly.
    - message: human-readable explanation.
    - hint: optional guidance (e.g., refer to SecNodeDemo).
    - category: optional classification (e.g. "implementation").
    - plc_refs: optional PLC code references where the developer may need to act.
    """
    rule_id: str
    severity: Severity
    path: str
    message: str
    hint: Optional[str] = None
    category: Optional[str] = None
    plc_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        if not d.get("hint"):
            d.pop("hint", None)
        if not d.get("category"):
            d.pop("category", None)
        if not d.get("plc_refs"):
            d.pop("plc_refs", None)
        return d
