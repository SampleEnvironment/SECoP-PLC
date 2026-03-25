"""
Resolved model types for PLC code generation.

This layer sits between:
- normalized input config (Pydantic / JSON-shaped data),
and
- code emitters (ST now, PLCopenXML later).

Why this layer exists
---------------------
- parsing, interpretation and design decisions happen once,
- emitters no longer inspect raw config structure,
- generation becomes easier to maintain as new artefacts are added.

Resolved-model design philosophy
--------------------------------
This file intentionally distinguishes between:

1) structural applicability at module-class level
2) concrete configured values at real-module level

For structural flags such as has_min_max, has_limits or
has_drive_tolerance, we use a three-state meaning:

- True:
    the concept applies to this module class and is configured
- False:
    the concept applies to this module class, but it is not configured
- None:
    the concept does not apply to this module class

Examples:
- numeric value with no configured min/max:
    has_min_max = False
- string value:
    has_min_max = None
- Drivable numeric target with configured tolerance:
    has_drive_tolerance = True
- Drivable numeric target without configured tolerance:
    has_drive_tolerance = False
- Writable module:
    has_drive_tolerance = None

Important note
--------------
At real-module level, the concrete value itself may still be None.
That None alone does NOT tell us whether the concept:
- does not apply, or
- applies but was not configured.

That distinction is carried by the corresponding structural has_... flag.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ResolvedModuleVariable:
    """
    One resolved PLC variable belonging to a module class.

    Example:
        name="lrValue"
        plc_type="LREAL"
        category="value"

    category is used only as lightweight classification for generation logic and
    debugging. It does not change the PLC type itself.
    """
    name: str
    plc_type: str
    category: str


@dataclass(frozen=True)
class ResolvedCustomParameter:
    """
    One resolved customised SECoP parameter (name starts with '_').

    This object describes the SECoP-side parameter as resolved for PLC
    generation. For custom parameters, the PLC type can be:
    - numeric scalar
    - STRING(n)
    - enum DUT generated specifically for that custom parameter

    Enum naming policy
    ------------------
    If a customised parameter is enum, its PLC type is:

        ET_Module_<moduleclass>_<customparameter>

    Example:
        module class: tc
        custom parameter: _sensor
        enum type: ET_Module_tc__sensor

    The original customised parameter name is preserved in the type suffix, so
    leading underscores are not removed.
    """
    secop_name: str
    description: str
    plc_var_name: str
    plc_type: str
    var_prefix: str
    is_numeric: bool
    is_enum: bool
    is_string: bool
    is_array: bool = False
    is_tuple: bool = False
    members: Optional[dict[str, int]] = None


@dataclass(frozen=True)
class ResolvedCustomCommand:
    """
    One resolved customised SECoP command.

    Example:
        _reset_hw -> x_Reset_hw

    Current design:
    - the command is resolved so that types and FB interfaces can expose it,
    - automatic command behaviour is not generated yet,
    - later stages may use this information for TODO_CODEGEN output or task-list
      generation.
    """
    secop_name: str
    description: str
    plc_var_name: str


@dataclass(frozen=True)
class ResolvedValue:
    """
    Resolved PLC-oriented representation of accessibles.value.

    Fields
    ------
    plc_type:
        Final PLC type used by generation.
        Examples: LREAL, DINT, STRING(80), ET_Module_mf_value

    var_prefix:
        CODESYS-style variable prefix used by the generator.
        Examples: lr, di, s, et

    is_numeric / is_enum / is_string:
        Convenience flags used throughout emitters and resolve logic.

    has_min_max:
        Tri-state structural flag:
        - True  -> value min/max concept applies and is configured
        - False -> value min/max concept applies but is not configured
        - None  -> value min/max does not apply conceptually

    has_out_of_range:
        Tri-state structural flag using the same convention.
        This refers to the optional x-plc out-of-range mechanism, not the normal
        SECoP min/max range.

    members:
        Enum members when value is enum, otherwise None.
    """
    plc_type: str
    var_prefix: str
    is_numeric: bool
    is_enum: bool
    is_string: bool
    is_array: bool
    is_tuple: bool
    has_min_max: Optional[bool]
    has_out_of_range: Optional[bool]
    members: Optional[dict[str, int]]


@dataclass(frozen=True)
class ResolvedTarget:
    """
    Resolved target-related behaviour for Writable / Drivable module classes.

    Tri-state flags
    ---------------
    has_min_max:
        - True  -> target min/max applies and is configured
        - False -> target min/max applies but is not configured
        - None  -> target min/max does not apply conceptually

    has_limits:
        - True  -> target_limits applies and is configured
        - False -> target_limits applies but is not configured
        - None  -> target_limits does not apply conceptually

    has_drive_tolerance:
        - True  -> drive tolerance applies and is configured
        - False -> drive tolerance applies but is not configured
        - None  -> drive tolerance does not apply conceptually

    Notes
    -----
    - drive tolerance only makes conceptual sense for Drivable numeric targets
    - Readable modules do not have target at all, so they use target=None in
      ResolvedModuleClass
    """
    has_min_max: Optional[bool]
    has_limits: Optional[bool]
    has_drive_tolerance: Optional[bool]


@dataclass(frozen=True)
class ResolvedModuleClass:
    """
    Fully resolved PLC-oriented view of one module class.

    A module class represents a shared SECoP/PLC structure reused by one or more
    real modules.

    Typical consumers:
    - ST_Module_<class>
    - ET_Module_<class>_...
    - FB_Module_<class>
    - FB_SecopProcessModules
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
    Root object returned by the module-class resolver.

    Fields
    ------
    module_to_class:
        Mapping from real module name to resolved module-class name.

    classes:
        Resolved data for each module class.

    Example:
        tc1 -> tc
        tc2 -> tc
        mf  -> mf
    """
    module_to_class: dict[str, str]
    classes: dict[str, ResolvedModuleClass]

    def to_dict(self) -> dict:
        """
        Convert the resolved model to a plain dictionary for JSON dumping and
        debugging.
        """
        return asdict(self)