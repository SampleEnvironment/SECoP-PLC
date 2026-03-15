"""
Resolved model types for PLC code generation.

This layer sits between:
- normalized input config (Pydantic / JSON-shaped data)
and
- code emitters (ST, later PLCopenXML)

Why this layer exists:
- We do the parsing / checks / decisions only once.
- Emitters no longer need to inspect raw config structure.
- The code becomes easier to maintain as more generators are added
  (GVL, DUTs, FBs, PRGs, XML...).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ResolvedModuleVariable:
    """
    A resolved PLC variable belonging to a module class.

    Example:
        name="lrValue"
        plc_type="LREAL"
        category="value"
    """
    name: str
    plc_type: str
    category: str


@dataclass(frozen=True)
class ResolvedCustomParameter:
    """
    A resolved customised parameter (SECoP parameter name starts with '_').

    Example:
        _sensor -> s_Sensor : STRING(80)
    """
    secop_name: str
    description: str
    plc_var_name: str
    plc_type: str
    var_prefix: str
    is_numeric: bool
    is_enum: bool
    is_string: bool
    members: Optional[dict[str, int]] = None


@dataclass(frozen=True)
class ResolvedCustomCommand:
    """
    A resolved custom command.

    Example:
        reset_hw -> x_ResetHw
    """
    secop_name: str
    description: str
    plc_var_name: str


@dataclass(frozen=True)
class ResolvedValue:
    """
    Resolved PLC representation of accessibles.value.
    """
    plc_type: str
    var_prefix: str
    is_numeric: bool
    is_enum: bool
    is_string: bool
    has_min_max: Optional[bool]
    has_out_of_range: Optional[bool]
    members: Optional[dict[str, int]]


@dataclass(frozen=True)
class ResolvedTarget:
    """
    Resolved target-related behaviour.
    """
    has_min_max: Optional[bool]
    has_limits: Optional[bool]
    has_drive_tolerance: Optional[bool]


@dataclass(frozen=True)
class ResolvedModuleClass:
    """
    Fully resolved PLC-oriented view of one module class.
    """
    name: str
    interface_class: str
    value: ResolvedValue
    target: Optional[ResolvedTarget]
    has_clear_errors_command: bool
    pollinterval_changeable: bool
    custom_parameters: list[ResolvedCustomParameter] = field(default_factory=list)
    custom_commands: list[ResolvedCustomCommand] = field(default_factory=list)
    module_variables: list[ResolvedModuleVariable] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedModuleClasses:
    """
    Root object returned by the resolver for module classes.
    """
    module_to_class: dict[str, str]
    classes: dict[str, ResolvedModuleClass]

    def to_dict(self) -> dict:
        return asdict(self)