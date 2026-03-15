"""
Helpers for CODESYS / IEC61131 naming conventions.

We follow the user's naming scheme:
- lr : LREAL
- di : DINT
- i  : INT
- ui : UINT
- x  : BOOL
- s  : STRING
- et : ENUM
- st : STRUCT
- a<base_prefix> : ARRAY (e.g. alrValue for ARRAY OF LREAL)

The goal is to have ONE place where prefixes are defined.
If tomorrow we decide INT uses 'si' instead of 'i', we change it here only.

Example:
    >>> prefix_for_scalar_type("LREAL")
    'lr'
    >>> make_var_name("lr", "Value")
    'lrValue'
    >>> array_var_name("lr", "Value")
    'alrValue'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# IEC scalar type -> prefix
PREFIX_BY_IEC_TYPE: dict[str, str] = {
    "LREAL": "lr",
    "DINT": "di",
    "INT": "i",
    "UINT": "ui",
    "BOOL": "x",
    "STRING": "s",
    # "ENUM" and "STRUCT" are not IEC primitive types in the same sense,
    # but we keep them here for consistent naming.
    "ENUM": "et",
    "STRUCT": "st",
}


def prefix_for_scalar_type(iec_type: str) -> str:
    """Return the prefix for a given IEC type."""
    try:
        return PREFIX_BY_IEC_TYPE[iec_type]
    except KeyError as exc:
        raise ValueError(f"Unknown IEC type for prefix mapping: {iec_type}") from exc


def make_var_name(prefix: str, base: str) -> str:
    """
    Build variable name (prefix + base) following user's style.

    Example:
        >>> make_var_name("lr", "Value")
        'lrValue'
        >>> make_var_name("s_", "Sensor")
        's_Sensor'
    """
    return f"{prefix}{base}"


def array_var_name(base_prefix: str, base: str) -> str:
    """
    Build array variable name: 'a' + base_prefix + base.

    Example:
        >>> array_var_name("lr", "Value")
        'alrValue'
    """
    return f"a{base_prefix}{base}"


def custom_param_var_name(datainfo_type: str, raw_param_name: str) -> str:
    """
    Convert a custom param name (starts with '_') to a CODESYS-styled name.

    Rule requested by user:
      '_sensor' -> 's_Sensor' (STRING)
    i.e. remove leading '_' and capitalise first letter, keep underscore after prefix.

    Example:
        >>> custom_param_var_name("string", "_sensor")
        's_Sensor'
    """
    if not raw_param_name.startswith("_"):
        raise ValueError(f"custom param must start with '_': {raw_param_name}")

    stem = raw_param_name[1:]  # remove leading "_"
    if not stem:
        raise ValueError("custom param name is '_' only")

    # Capitalise first char only; keep rest as-is (simple and deterministic)
    nice = stem[0].upper() + stem[1:]

    # Prefix depends on datainfo.type (SECoP)
    iec_type = secop_type_to_iec(datainfo_type, maxchars=None)
    pfx = prefix_for_scalar_type(iec_type)

    # For custom params user wants: s_Sensor, lr_Whatever, ...
    return f"{pfx}_{nice}"


def secop_type_to_iec(secop_type: str, maxchars: Optional[int]) -> str:
    """
    Map SECoP datainfo.type to IEC type used in ST.

    Supported in this phase:
      - double -> LREAL
      - int    -> DINT  (as specified by user)
      - string -> STRING
      - enum   -> ENUM  (actual type name is ET_Module_... generated elsewhere)
      - array  -> handled by caller (needs base element type + maxlen)

    We keep mapping minimal and explicit.

    Example:
        >>> secop_type_to_iec("double", None)
        'LREAL'
        >>> secop_type_to_iec("int", None)
        'DINT'
    """
    t = secop_type.lower()
    if t == "double":
        return "LREAL"
    if t == "int":
        return "DINT"
    if t == "string":
        return "STRING"
    if t == "enum":
        return "ENUM"
    if t == "bool":
        return "BOOL"
    # arrays and tuples/commands are handled elsewhere
    raise ValueError(f"Unsupported SECoP type -> IEC mapping: {secop_type}")