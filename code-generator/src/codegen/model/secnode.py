from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

"""
Pydantic models for the SECoP + tooling ("x-plc") configuration file.
- It validates that the JSON structure is correct (types, required fields, etc.).
- It applies defaults for optional fields.
- It gives very clear error messages with the exact path where something is wrong.
- It produces a typed internal representation (model instance), easier to use later when generating code.
"""


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# -----------------------------------------------------------------------------
# Node-level PLC/tooling configuration ("x-plc")
# -----------------------------------------------------------------------------

class PlcTcpConfig(StrictBaseModel):
    """
    TCP server settings used by the generated PLC project.

    Example in JSON:
      "x-plc": {
        "tcp": {
          "server_ip": "192.168.1.10",
          "server_port": 10767,
          "interface_healthy_tag": "G_stStatusPlc.G_xEthReady_If2"
        }
      }
    """
    server_ip: Optional[str] = None
    server_port: Optional[int] = None
    interface_healthy_tag: Optional[str] = None


class PlcNodeConfig(StrictBaseModel):
    """
    Tooling configuration at SECoP node level.

    Notes:
    - This data is NOT part of SECoP protocol itself.
    - We keep it under "x-plc" so it can be removed easily to create a pure SECoP "describe" JSON.
    """
    tcp: Optional[PlcTcpConfig] = None
    secop_version: Optional[str] = None
    plc_timestamp_tag: Optional[str] = None


# -----------------------------------------------------------------------------
# SECoP protocol datatypes (datainfo) and accessibles
# -----------------------------------------------------------------------------

class DataInfo(StrictBaseModel):
    """
    SECoP "datainfo" object.

    In SECoP describe, each accessible has a "datainfo" describing the datatype.

    Important detail:
    - For enums, "members" is a dictionary:
        {"off": 0, "on": 1}
    - For tuples, "members" is a list of member definitions:
        [
          {"type": "enum", "members": {"IDLE": 100, ...}},
          {"type": "string"}
        ]

    Therefore, we allow "members" to be either:
    - dict[str, int]  (enum)
    - list[dict[str, Any]] (tuple members)
    """
    type: str

    # Common optional fields used by numeric/string types
    unit: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    maxchars: Optional[int] = None
    maxlen: Optional[int] = None
    members: Optional[Union[Dict[str, int], List[Dict[str, Any]]]] = None

    # command-specific (SECoP): optional argument / result datainfo
    argument: Optional["DataInfo"] = None
    result: Optional["DataInfo"] = None


class Accessible(StrictBaseModel):
    """
    A SECoP accessible parameter/command in the 'describe' structure.

    Example:
      "value": {
        "description": "current field in T",
        "datainfo": {"type": "double", "unit": "T", "min": -15.0, "max": 15.0},
        "readonly": true
      }
    """
    description: str
    datainfo: DataInfo
    readonly: bool = False
    checkable: Optional[bool] = None


# -----------------------------------------------------------------------------
# Module-level PLC/tooling configuration ("x-plc")
# -----------------------------------------------------------------------------

class PlcValueConfig(StrictBaseModel):
    """
    PLC mapping for 'value' when the SECoP value is numeric/string/etc. Example:
      "value": {
        "read_expr": "REAL_TO_LREAL(G_rMf)"
      }

    PLC mapping for 'value' when the SECoP value is an enum. Example:
      "value": {
        "enum_tag": "G_iHeatSwitchStatus",
        "enum_member_map": {
          "off": "G_iHeatSwitchStatus = FALSE",
          "on": "G_iHeatSwitchStatus = TRUE"
        }
      }
    """
    read_expr: Optional[str] = None
    enum_tag: Optional[str] = None
    enum_member_map: Optional[Dict[str, str]] = None


class PlcStatusConfig(StrictBaseModel):
    """
    PLC-related status extensions (project-specific).
    """
    disabled_expr: Optional[str] = ""
    disabled_description: Optional[str] = ""
    hw_error_expr: Optional[str] = ""
    hw_error_description: Optional[str] = ""


class PlcTargetConfig(StrictBaseModel):
    """
    PLC mapping for 'target' write behaviour (numeric/string targets). Example:
      "target": {
        "write_stmt": "G_rMfSetpoint := LREAL_TO_REAL(GVL_SecNode.G_st_mf.lrTargetChangeNewVal);",
        "change_possible_expr": "NOT G_xEquipLockedInLocal AND G_xRemoteSecopEnabled;",
        "reach_timeout_s": 300,
        "reach_abs_tolerance": 0.1
      }

    PLC mapping for 'target' when the SECoP target is an enum. Example:
      "target": {
        "enum_tag": "G_iHeatSwitchCmd",
        "change_possible_expr": "NOT G_xEquipLockedInLocal AND G_xRemoteSecopEnabled;",
        "reach_timeout_s": 60
      }
    """
    write_stmt: Optional[str] = None
    enum_tag: Optional[str] = None
    change_possible_expr: Optional[str] = None
    reach_timeout_s: Optional[int] = None
    reach_abs_tolerance: Optional[float] = None


class PlcClearErrorsConfig(StrictBaseModel):
    """
    PLC mapping for 'clear_errors' command.

    Example:
      "clear_errors": { "cmd_stmt": "" }
    """
    cmd_stmt: Optional[str] = ""


class PlcModuleConfig(StrictBaseModel):
    """
    Tooling configuration under module-level "x-plc".
    """
    timestamp_tag: Optional[str] = None

    value: Optional[PlcValueConfig] = None
    status: Optional[PlcStatusConfig] = None
    target: Optional[PlcTargetConfig] = None
    clear_errors: Optional[PlcClearErrorsConfig] = None


# -----------------------------------------------------------------------------
# Module + Node models (SECoP structure + optional x-plc tooling)
# -----------------------------------------------------------------------------

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
