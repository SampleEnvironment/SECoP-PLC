from __future__ import annotations

"""
Pydantic models for the SECoP configuration file plus the project-specific
PLC/tooling extension block ("x-plc").

Purpose of this layer
---------------------
- validate the JSON structure,
- apply defaults for optional fields,
- reject unexpected keys,
- provide a typed internal representation for the rest of the pipeline.

Important design note
---------------------
This file describes configuration structure only. It does not decide:
- whether a field is semantically allowed for a given SECoP type,
- whether a missing field should produce WARNING or ERROR,
- whether a missing PLC mapping should generate automatic code or TODO_CODEGEN.

Those decisions belong to the validation rules and to the resolve layer.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    """
    Base model used throughout the configuration schema.

    Rules:
    - extra fields are forbidden,
    - aliases such as "x-plc" are accepted during parsing and serialisation.
    """
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Node-level PLC/tooling configuration ("x-plc")
# ---------------------------------------------------------------------------

class PlcTcpConfig(StrictBaseModel):
    """
    TCP server settings used by the generated PLC project.

    Example:
        "x-plc": {
          "tcp": {
            "server_ip": "192.168.1.10",
            "server_port": 10767,
            "interface_healthy_tag": "G_stStatusPlc.G_xEthReady_If2"
          }
        }

    Notes:
    - Fields are optional at schema level.
    - Missing values are handled later by business rules and generators.
    """
    server_ip: Optional[str] = None
    server_port: Optional[int] = None
    interface_healthy_tag: Optional[str] = None


class PlcNodeConfig(StrictBaseModel):
    """
    Tooling configuration at SECoP node level.

    Notes:
    - This data is project-specific and not part of the SECoP protocol itself.
    - It is kept under "x-plc" so the protocol-facing structure can be derived
      independently when needed.
    """
    tcp: Optional[PlcTcpConfig] = None
    secop_version: Optional[str] = None
    plc_timestamp_tag: Optional[str] = None


# ---------------------------------------------------------------------------
# SECoP protocol datainfo and accessibles
# ---------------------------------------------------------------------------

class DataInfo(StrictBaseModel):
    """
    SECoP "datainfo" object.

    The exact set of optional fields that make sense depends on datainfo.type.
    This model allows the structural superset; semantic coherence is validated
    later by business rules.

    Important detail about "members":
    - enum  -> dictionary, e.g. {"off": 0, "on": 1}
    - tuple -> list of member definitions
    - array -> protocol-specific nested description, typically represented as a
      dictionary in this project
    """
    type: str

    # Common optional fields. Business rules decide where each one is allowed.
    unit: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    maxchars: Optional[int] = None
    maxlen: Optional[int] = None
    members: Optional[Union[Dict[str, int], List[Dict[str, Any]], Dict[str, Any]]] = None

    # command-specific optional nested datainfo
    argument: Optional["DataInfo"] = None
    result: Optional["DataInfo"] = None


class Accessible(StrictBaseModel):
    """
    One SECoP accessible inside the module "accessibles" block.

    Example:
        "value": {
          "description": "current field in T",
          "datainfo": {
            "type": "double",
            "unit": "T",
            "min": -15.0,
            "max": 15.0
          },
          "readonly": true
        }

    Notes:
    - "readonly" is kept in the model because it is part of the provided config.
    - Project-specific restrictions on which accessibles may be writable are
      enforced later by business rules.
    """
    description: str
    datainfo: DataInfo
    readonly: bool = False


# ---------------------------------------------------------------------------
# Module-level PLC/tooling configuration ("x-plc")
# ---------------------------------------------------------------------------

class PlcValueConfig(StrictBaseModel):
    """
    PLC mapping for the standard SECoP accessible 'value'.

    Supported current patterns:
    - numeric / string values:
        {
          "read_expr": "REAL_TO_LREAL(G_rMf)"
        }

    - enum values:
        {
          "enum_tag": "G_iHeatSwitchStatus"
        }

    Optional out-of-range fields are allowed at schema level and validated later
    by business rules.
    """
    read_expr: Optional[str] = None
    enum_tag: Optional[str] = None
    outofrange_min: Optional[float] = None
    outofrange_max: Optional[float] = None


class PlcStatusConfig(StrictBaseModel):
    """
    PLC-related status extensions used by this project.

    The generator may use these expressions to derive:
    - Disabled state
    - Communication error
    - Hardware error

    Notes:
    - These fields are optional at schema level.
    - Whether they are required or allowed in a specific module depends on
      business rules and the status definition of that module.
    """
    disabled_expr: Optional[str] = ""
    disabled_description: Optional[str] = ""
    comm_error_expr: Optional[str] = ""
    comm_error_description: Optional[str] = ""
    hw_error_expr: Optional[str] = ""
    hw_error_description: Optional[str] = ""


class PlcTargetConfig(StrictBaseModel):
    """
    PLC mapping for the standard SECoP accessible 'target'.

    Supported current patterns:
    - numeric / string targets:
        {
          "write_stmt": "G_rMfSetpoint := LREAL_TO_REAL(GVL_SecNode.G_st_mf.lrTargetChangeNewVal);",
          "change_possible_expr": "NOT G_xEquipLockedInLocal AND G_xRemoteSecopEnabled",
          "reach_timeout_s": 300,
          "reach_abs_tolerance": 0.1
        }

    - enum targets:
        {
          "enum_tag": "G_iHeatSwitchCmd",
          "change_possible_expr": "NOT G_xEquipLockedInLocal AND G_xRemoteSecopEnabled",
          "reach_timeout_s": 60
        }

    Notes:
    - write_stmt and enum_tag are polymorphic and validated later according to
      the target datatype.
    - reach_* fields are further constrained by interface class and datatype.
    """
    write_stmt: Optional[str] = None
    enum_tag: Optional[str] = None
    change_possible_expr: Optional[str] = None
    reach_timeout_s: Optional[int] = None
    reach_abs_tolerance: Optional[float] = None


class PlcClearErrorsConfig(StrictBaseModel):
    """
    PLC mapping for the standard SECoP command 'clear_errors'.

    Example:
        "clear_errors": {
          "cmd_stmt": "IF G_xRemoteSecopEnabled THEN G_xAck := TRUE; END_IF"
        }

    Note:
    - cmd_stmt is optional. The generator can still clear the SECoP-side error
      report even when no extra PLC action is configured.
    """
    cmd_stmt: Optional[str] = ""


class PlcCustomParamConfig(StrictBaseModel):
    """
    PLC mapping for one customised SECoP parameter (name starts with '_').

    Current supported patterns:
    - numeric / string custom parameter:
        {
          "read_expr": "G_sTc1ChannelATempSensorId"
        }

    - enum custom parameter:
        {
          "enum_tag": "G_iSomething"
        }

    Notes:
    - This mirrors the same idea used for the standard 'value' mapping.
    - Business rules later decide which fields are allowed according to the
      custom parameter datatype.
    """
    read_expr: Optional[str] = None
    enum_tag: Optional[str] = None


class PlcModuleConfig(StrictBaseModel):
    """
    Tooling configuration under one module-level "x-plc" block.

    Standard sections:
    - timestamp_tag
    - value
    - status
    - target
    - clear_errors

    Customised parameter mappings:
    - custom_parameters: dictionary keyed by SECoP custom parameter name
      (for example "_sensor")
    """
    timestamp_tag: Optional[str] = None

    value: Optional[PlcValueConfig] = None
    status: Optional[PlcStatusConfig] = None
    target: Optional[PlcTargetConfig] = None
    clear_errors: Optional[PlcClearErrorsConfig] = None

    custom_parameters: Dict[str, PlcCustomParamConfig] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Module + node models
# ---------------------------------------------------------------------------

class Module(StrictBaseModel):
    """
    One module inside the SECoP node.
    """
    interface_classes: List[str]
    features: List[str] = Field(default_factory=list)

    description: str
    implementation: str

    accessibles: Dict[str, Accessible]

    # Module-level tooling data
    x_plc: Optional[PlcModuleConfig] = Field(default=None, alias="x-plc")


class SecNodeConfig(StrictBaseModel):
    """
    Top-level configuration file structure.
    """
    equipment_id: str
    description: str
    firmware: str

    modules: Dict[str, Module]

    # Node-level tooling data
    x_plc: Optional[PlcNodeConfig] = Field(default=None, alias="x-plc")