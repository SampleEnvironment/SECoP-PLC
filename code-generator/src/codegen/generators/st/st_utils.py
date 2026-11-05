"""
Shared utility functions for ST code generators.

Kept small on purpose — only helpers that are genuinely needed in more than
one generator module belong here.
"""

from __future__ import annotations

import json
import re


def sanitize_enum_member_name(name: str) -> str:
    """Convert a SECoP enum member name to a valid ST identifier.

    SECoP enum member names can contain arbitrary characters (spaces, commas,
    parentheses, etc.).  ST identifiers must start with a letter or underscore
    and may only contain letters, digits, and underscores.

    Transformation rules applied in order:
    1. Replace every character that is not a letter, digit, or underscore
       with an underscore.
    2. Collapse consecutive underscores into one.
    3. Strip leading and trailing underscores.
    4. If the result starts with a digit, prepend an underscore.

    Examples:
        "Local, Unavailable"  ->  "Local_Unavailable"
        "Alarm(s)"            ->  "Alarm_s"
        "Remote, Fault, Idle" ->  "Remote_Fault_Idle"
        "off"                 ->  "off"
    """
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized or "_unknown"


def format_st_string_literal(value: str) -> str:
    """
    Format a Python string as an IEC 61131-3 ST string literal.

    Escaping rules (IEC 61131-3):
    - '$' -> '$$' (escaped first, so the '$' of the next rule is kept)
    - "'" -> "$'"
    """
    escaped = value.replace("$", "$$").replace("'", "$'")
    return f"'{escaped}'"


def json_string_content(value: str) -> str:
    r"""
    Return the JSON-encoded form of a string, without the surrounding double
    quotes, using ASCII only (non-ASCII characters as \uXXXX escapes).

    Used for the SEC node strings that the PLC inserts as they are in JSON
    messages (e.g. the UDP discovery reply), so that the PLC does not need to
    escape them at runtime.

    Examples (Python values):
        "PLC SEC Node Demo"  ->  "PLC SEC Node Demo"
        "line1\nline2"       ->  "line1\\nline2"
        "20 °C"              ->  "20 \\u00b0C"
    """
    return json.dumps(value, ensure_ascii=True)[1:-1]
