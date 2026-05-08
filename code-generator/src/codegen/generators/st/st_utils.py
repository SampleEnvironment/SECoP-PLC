"""
Shared utility functions for ST code generators.

Kept small on purpose — only helpers that are genuinely needed in more than
one generator module belong here.
"""

from __future__ import annotations

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
