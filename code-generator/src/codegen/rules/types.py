from __future__ import annotations

"""
Core types for business-rule validation.

These types are intentionally small and independent from the Pydantic models so
that:

- validation rules are easy to test in isolation,
- reporting remains stable and predictable,
- the validation layer does not need to know anything about code generation
  internals.

Current design choice
---------------------

A validation finding is now intentionally minimal. It carries only the
information required to understand what failed and where:

- rule_id
- severity
- path
- message

Why this simplification is useful:
- rule output stays easy to read and stable over time,
- validation does not try to predict later PLC artefact names,
- task-list generation can be implemented later as a separate step, based on
  resolved models and/or generated TODO placeholders.

Severity model
--------------

- ERROR:
    configuration is not acceptable for this code generator; generation must stop
- WARNING:
    generation may continue, but manual PLC completion may be required
"""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict


class Severity(str, Enum):
    """
    Two-level severity model used by business-rule validation.

    ERROR
        The configuration is not valid for this generator and code generation
        must not continue.

    WARNING
        The configuration is acceptable enough to continue, but the generated
        PLC project may still require manual completion.
    """

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Finding:
    """
    One validation finding produced by a business rule.

    Fields
    ------
    rule_id:
        Stable identifier used in rule documentation, reports and tests.

    severity:
        ERROR or WARNING.

    path:
        JSONPath-like location that helps the user identify where the problem is.

    message:
        Human-readable explanation of the finding.

    Notes
    -----
    This object is intentionally minimal. It does not carry code-generation
    references or extra metadata. Those concerns belong to later stages such as
    resolved-model analysis or task-list generation.
    """

    rule_id: str
    severity: Severity
    path: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the finding into a JSON-serialisable dictionary.

        The Severity enum is converted to its string value so that the validation
        report remains simple and easy to consume from tools or tests.
        """
        data = asdict(self)
        data["severity"] = self.severity.value
        return data