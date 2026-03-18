"""
Resolved model for real module instances.

Purpose
-------

This resolver complements the existing module-class resolved model.

- Module classes are useful for:
  - ST_Module_<class>
  - ET_Module_<class>_...
  - FB_Module_<class>
  - FB_SecopProcessModules

- Real modules are useful for:
  - SecopInit
  - SecopMapFromPlc
  - SecopMapToPlc

This file resolves:
- SEC node level data
- real module instance data
- SECoP values
- x-plc tooling values

Design note
-----------
This layer stores concrete values for real modules.

Important distinction from module-class resolution:
- module-class flags such as has_min_max / has_limits / has_drive_tolerance
  describe structural applicability and configuration state
- real-module fields below store concrete values, which may be None

A concrete None value in this file does not, by itself, mean "not applicable".
For concepts with tri-state meaning, applicability is determined by the
corresponding class-level structural flags.

Fields that always apply in this project
----------------------------------------
Some PLC/tooling fields are conceptually required by the project and therefore
do not need a has_... structural flag here, for example:
- SEC node TCP port
- SEC node PLC timestamp tag
- module timestamp tag

For those fields:
- present value -> emit automatic mapping/initialisation
- missing value -> later emitters generate TODO_CODEGEN placeholders
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from codegen.resolve.types import (
    ResolvedCustomCommand,
    ResolvedCustomParameter,
    ResolvedModuleClasses,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedRealModuleValuePlc:
    """
    Resolved x-plc.value block for one real module.

    Current supported patterns:
    - numeric / string value -> read_expr
    - enum value             -> enum_tag
    """
    timestamp_tag: str | None
    read_expr: str | None
    enum_tag: str | None
    outofrange_min: float | int | None
    outofrange_max: float | int | None


@dataclass(frozen=True)
class ResolvedRealModuleStatusPlc:
    """
    Resolved x-plc.status block for one real module.
    """
    disabled_expr: str | None
    disabled_description: str | None
    comm_error_expr: str | None
    comm_error_description: str | None
    hw_error_expr: str | None
    hw_error_description: str | None


@dataclass(frozen=True)
class ResolvedRealModuleTargetPlc:
    """
    Resolved x-plc.target block for one real module.

    Current supported patterns:
    - numeric / string target -> write_stmt
    - enum target             -> enum_tag
    """
    write_stmt: str | None
    enum_tag: str | None
    change_possible_expr: str | None
    reach_timeout_s: int | None
    reach_abs_tolerance: float | int | None


@dataclass(frozen=True)
class ResolvedRealModuleClearErrorsPlc:
    """
    Resolved x-plc.clear_errors block for one real module.
    """
    cmd_stmt: str | None


@dataclass(frozen=True)
class ResolvedRealCustomParameterPlc:
    """
    Resolved x-plc.custom_parameters.<name> block for one real module.

    Current supported patterns:
    - numeric / string custom parameter -> read_expr
    - enum custom parameter             -> enum_tag
    """
    secop_name: str
    read_expr: str | None
    enum_tag: str | None


@dataclass(frozen=True)
class ResolvedRealModule:
    """
    Resolved data for one real module instance.

    Structural applicability belongs primarily to the corresponding resolved
    module class. This object stores concrete values for the real module.
    """
    module_name: str
    module_class_name: str
    interface_class: str
    description: str

    value_plc_type: str
    value_var_prefix: str
    value_is_numeric: bool
    value_is_enum: bool
    value_is_string: bool
    value_has_min_max: bool | None
    value_has_out_of_range: bool | None

    target_has_min_max: bool | None
    target_has_limits: bool | None
    target_has_drive_tolerance: bool | None

    value_min: float | int | None
    value_max: float | int | None
    value_out_of_range_l: float | int | None
    value_out_of_range_h: float | int | None

    target_min: float | int | None
    target_max: float | int | None
    target_limits_min: float | int | None
    target_limits_max: float | int | None
    target_drive_tolerance: float | int | None

    pollinterval_min: float | None
    pollinterval_max: float | None
    pollinterval_readonly: bool

    has_clear_errors_command: bool

    custom_parameters: list[ResolvedCustomParameter] = field(default_factory=list)
    custom_commands: list[ResolvedCustomCommand] = field(default_factory=list)

    x_plc_custom_parameters: dict[str, ResolvedRealCustomParameterPlc] = field(default_factory=dict)

    status_has_disabled: bool = False
    status_has_comm_error: bool = False
    status_has_hw_error: bool = False

    x_plc_value: ResolvedRealModuleValuePlc | None = None
    x_plc_status: ResolvedRealModuleStatusPlc | None = None
    x_plc_target: ResolvedRealModuleTargetPlc | None = None
    x_plc_clear_errors: ResolvedRealModuleClearErrorsPlc | None = None


@dataclass(frozen=True)
class ResolvedRealSecNode:
    """
    Resolved SEC node data used by PRG generators.

    The fields below are project-relevant runtime values, not protocol-level
    structural SECoP information.
    """
    firmware: str
    secop_version: str | None
    tcp_server_ip: str | None
    tcp_server_port: int | None
    plc_timestamp_tag: str | None
    tcp_server_interface_healthy_tag: str | None
    module_names_in_order: list[str]
    structure_report_json: str


@dataclass(frozen=True)
class ResolvedRealModules:
    """
    Root resolved model for real modules + SEC node.
    """
    sec_node: ResolvedRealSecNode
    modules: dict[str, ResolvedRealModule]

    def to_dict(self) -> dict:
        """
        Convert the resolved model to a plain dictionary for JSON dumping and
        debugging.
        """
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_accessible(module: dict[str, Any], name: str) -> dict[str, Any] | None:
    """
    Return accessibles.<name> if it exists and is a dict, else None.
    """
    accessibles = module.get("accessibles") or {}
    value = accessibles.get(name)
    return value if isinstance(value, dict) else None


def _get_datainfo(accessible: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Return accessible.datainfo if it exists and is a dict, else None.
    """
    if not isinstance(accessible, dict):
        return None
    di = accessible.get("datainfo")
    return di if isinstance(di, dict) else None


def _get_module_x_plc(module: dict[str, Any]) -> dict[str, Any]:
    """
    Return module['x-plc'] if it is a dict, else an empty dict.
    """
    x = module.get("x-plc")
    return x if isinstance(x, dict) else {}


def _as_dict_or_none(value: Any) -> dict[str, Any] | None:
    """
    Return the value if it is a dict, else None.
    """
    return value if isinstance(value, dict) else None


def _strip_or_none(value: Any) -> str | None:
    """
    Convert string-like values to stripped strings.

    Returns:
    - stripped string when non-empty
    - None when missing or blank
    """
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _int_or_none(value: Any) -> int | None:
    """
    Convert a value to int when possible, else return None.

    This is used for project fields that conceptually apply but may be omitted
    in the configuration. Emitters decide later whether to generate automatic
    code or TODO_CODEGEN placeholders.
    """
    if value is None:
        return None
    return int(value)


# ---------------------------------------------------------------------------
# Per-module resolver
# ---------------------------------------------------------------------------


def _resolve_real_custom_parameter_plc_map(
    module_cfg: dict[str, Any],
    resolved_custom_parameters: list[ResolvedCustomParameter],
) -> dict[str, ResolvedRealCustomParameterPlc]:
    """
    Resolve x-plc.custom_parameters for one real module.

    Only customised parameters already resolved at class level are considered.
    This keeps the real-module view aligned with the class-level structural
    model.
    """
    x_plc = _get_module_x_plc(module_cfg)
    xplc_custom = x_plc.get("custom_parameters")
    xplc_custom = xplc_custom if isinstance(xplc_custom, dict) else {}

    result: dict[str, ResolvedRealCustomParameterPlc] = {}

    for cp in resolved_custom_parameters:
        cfg = xplc_custom.get(cp.secop_name)
        cfg = cfg if isinstance(cfg, dict) else {}

        result[cp.secop_name] = ResolvedRealCustomParameterPlc(
            secop_name=cp.secop_name,
            read_expr=_strip_or_none(cfg.get("read_expr")),
            enum_tag=_strip_or_none(cfg.get("enum_tag")),
        )

    return result


def _resolve_one_real_module(
    module_name: str,
    module_cfg: dict[str, Any],
    resolved_classes: ResolvedModuleClasses,
) -> ResolvedRealModule:
    """
    Resolve one real module instance using:
    - its own config,
    - the previously resolved module-class information.
    """
    module_class_name = resolved_classes.module_to_class[module_name]
    resolved_class = resolved_classes.classes[module_class_name]
    x_plc = _get_module_x_plc(module_cfg)

    # ------------------------------------------------------------
    # SECoP values and datainfo ranges
    # ------------------------------------------------------------
    acc_value = _get_accessible(module_cfg, "value")
    di_value = _get_datainfo(acc_value) or {}
    value_min = di_value.get("min")
    value_max = di_value.get("max")

    acc_target = _get_accessible(module_cfg, "target")
    di_target = _get_datainfo(acc_target) or {}
    target_min = di_target.get("min")
    target_max = di_target.get("max")

    acc_target_limits = _get_accessible(module_cfg, "target_limits")
    di_target_limits = _get_datainfo(acc_target_limits) or {}
    target_limits_min = di_target_limits.get("min")
    target_limits_max = di_target_limits.get("max")

    acc_poll = _get_accessible(module_cfg, "pollinterval")
    di_poll = _get_datainfo(acc_poll) or {}
    pollinterval_min = di_poll.get("min")
    pollinterval_max = di_poll.get("max")
    pollinterval_readonly = bool(acc_poll.get("readonly", False)) if acc_poll else True

    # ------------------------------------------------------------
    # x-plc.value
    # ------------------------------------------------------------
    xplc_value = _as_dict_or_none(x_plc.get("value"))
    resolved_x_value = ResolvedRealModuleValuePlc(
        timestamp_tag=_strip_or_none(x_plc.get("timestamp_tag")),
        read_expr=_strip_or_none(xplc_value.get("read_expr")) if xplc_value else None,
        enum_tag=_strip_or_none(xplc_value.get("enum_tag")) if xplc_value else None,
        outofrange_min=xplc_value.get("outofrange_min") if xplc_value else None,
        outofrange_max=xplc_value.get("outofrange_max") if xplc_value else None,
    )

    # ------------------------------------------------------------
    # x-plc.status
    # ------------------------------------------------------------
    xplc_status = _as_dict_or_none(x_plc.get("status"))
    resolved_x_status = ResolvedRealModuleStatusPlc(
        disabled_expr=_strip_or_none(xplc_status.get("disabled_expr")) if xplc_status else None,
        disabled_description=_strip_or_none(xplc_status.get("disabled_description")) if xplc_status else None,
        comm_error_expr=_strip_or_none(xplc_status.get("comm_error_expr")) if xplc_status else None,
        comm_error_description=_strip_or_none(xplc_status.get("comm_error_description")) if xplc_status else None,
        hw_error_expr=_strip_or_none(xplc_status.get("hw_error_expr")) if xplc_status else None,
        hw_error_description=_strip_or_none(xplc_status.get("hw_error_description")) if xplc_status else None,
    )

    # ------------------------------------------------------------
    # x-plc.target
    # ------------------------------------------------------------
    xplc_target = _as_dict_or_none(x_plc.get("target"))
    resolved_x_target = ResolvedRealModuleTargetPlc(
        write_stmt=_strip_or_none(xplc_target.get("write_stmt")) if xplc_target else None,
        enum_tag=_strip_or_none(xplc_target.get("enum_tag")) if xplc_target else None,
        change_possible_expr=_strip_or_none(xplc_target.get("change_possible_expr")) if xplc_target else None,
        reach_timeout_s=xplc_target.get("reach_timeout_s") if xplc_target else None,
        reach_abs_tolerance=xplc_target.get("reach_abs_tolerance") if xplc_target else None,
    )

    # ------------------------------------------------------------
    # x-plc.clear_errors
    # ------------------------------------------------------------
    xplc_clear = _as_dict_or_none(x_plc.get("clear_errors"))
    resolved_x_clear = ResolvedRealModuleClearErrorsPlc(
        cmd_stmt=_strip_or_none(xplc_clear.get("cmd_stmt")) if xplc_clear else None
    )

    # ------------------------------------------------------------
    # x-plc.custom_parameters
    # ------------------------------------------------------------
    resolved_x_custom_parameters = _resolve_real_custom_parameter_plc_map(
        module_cfg=module_cfg,
        resolved_custom_parameters=list(resolved_class.custom_parameters),
    )

    return ResolvedRealModule(
        module_name=module_name,
        module_class_name=module_class_name,
        interface_class=resolved_class.interface_class,
        description=str(module_cfg.get("description") or ""),

        value_plc_type=resolved_class.value.plc_type,
        value_var_prefix=resolved_class.value.var_prefix,
        value_is_numeric=resolved_class.value.is_numeric,
        value_is_enum=resolved_class.value.is_enum,
        value_is_string=resolved_class.value.is_string,
        value_has_min_max=resolved_class.value.has_min_max,
        value_has_out_of_range=resolved_class.value.has_out_of_range,

        target_has_min_max=resolved_class.target.has_min_max if resolved_class.target else None,
        target_has_limits=resolved_class.target.has_limits if resolved_class.target else None,
        target_has_drive_tolerance=resolved_class.target.has_drive_tolerance if resolved_class.target else None,

        value_min=value_min,
        value_max=value_max,
        value_out_of_range_l=resolved_x_value.outofrange_min,
        value_out_of_range_h=resolved_x_value.outofrange_max,

        target_min=target_min,
        target_max=target_max,
        target_limits_min=target_limits_min,
        target_limits_max=target_limits_max,
        target_drive_tolerance=resolved_x_target.reach_abs_tolerance,

        pollinterval_min=pollinterval_min,
        pollinterval_max=pollinterval_max,
        pollinterval_readonly=pollinterval_readonly,

        has_clear_errors_command=resolved_class.has_clear_errors_command,

        custom_parameters=list(resolved_class.custom_parameters),
        custom_commands=list(resolved_class.custom_commands),

        x_plc_custom_parameters=resolved_x_custom_parameters,

        status_has_disabled=bool(resolved_x_status.disabled_expr),
        status_has_comm_error=bool(resolved_x_status.comm_error_expr),
        status_has_hw_error=bool(resolved_x_status.hw_error_expr),

        x_plc_value=resolved_x_value,
        x_plc_status=resolved_x_status,
        x_plc_target=resolved_x_target,
        x_plc_clear_errors=resolved_x_clear,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_real_modules(
    normalized_cfg: dict[str, Any],
    resolved_classes: ResolvedModuleClasses,
    structure_report_json: str,
) -> ResolvedRealModules:
    """
    Resolve a common model for real modules and SEC node.

    Parameters
    ----------
    normalized_cfg:
        Normalized configuration used to resolve internal data consistently.

    resolved_classes:
        Module-class resolved model produced earlier in the pipeline.

    structure_report_json:
        Protocol-facing structure report already prepared from the raw config.
        This is passed in explicitly so that this resolver does not rebuild it
        from normalized data.
    """
    modules_cfg = normalized_cfg.get("modules") or {}
    if not isinstance(modules_cfg, dict):
        raise ValueError("normalized_cfg.modules must be a dict")

    x_plc_node = normalized_cfg.get("x-plc") or {}
    if not isinstance(x_plc_node, dict):
        x_plc_node = {}

    tcp_cfg = x_plc_node.get("tcp") or {}
    if not isinstance(tcp_cfg, dict):
        tcp_cfg = {}

    sec_node = ResolvedRealSecNode(
        firmware=str(normalized_cfg.get("firmware") or ""),
        secop_version=_strip_or_none(x_plc_node.get("secop_version")),
        tcp_server_ip=_strip_or_none(tcp_cfg.get("server_ip")),
        tcp_server_port=_int_or_none(tcp_cfg.get("server_port")),
        plc_timestamp_tag=_strip_or_none(x_plc_node.get("plc_timestamp_tag")),
        tcp_server_interface_healthy_tag=_strip_or_none(tcp_cfg.get("interface_healthy_tag")),
        module_names_in_order=list(modules_cfg.keys()),
        structure_report_json=structure_report_json,
    )

    modules: dict[str, ResolvedRealModule] = {}
    for module_name, module_cfg in modules_cfg.items():
        if not isinstance(module_cfg, dict):
            raise ValueError(f"Module {module_name} must be a dict")
        modules[module_name] = _resolve_one_real_module(
            module_name=module_name,
            module_cfg=module_cfg,
            resolved_classes=resolved_classes,
        )

    return ResolvedRealModules(
        sec_node=sec_node,
        modules=modules,
    )