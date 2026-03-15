"""
Resolved model for real module instances.

Purpose
-------

This resolver complements the existing "module class" resolved model.

- Module classes are useful for:
  - ST_Module_<class>
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

It is designed to become the common resolved model for all PRGs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
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
    timestamp_tag: str
    read_expr: str | None
    enum_tag: str | None
    enum_member_map: dict[str, str] | None
    outofrange_min: float | int | None
    outofrange_max: float | int | None


@dataclass(frozen=True)
class ResolvedRealModuleStatusPlc:
    disabled_expr: str
    disabled_description: str
    hw_error_expr: str
    hw_error_description: str


@dataclass(frozen=True)
class ResolvedRealModuleTargetPlc:
    write_stmt: str | None
    enum_tag: str | None
    change_possible_expr: str | None
    reach_timeout_s: int | None
    reach_abs_tolerance: float | int | None


@dataclass(frozen=True)
class ResolvedRealModuleClearErrorsPlc:
    cmd_stmt: str | None


@dataclass(frozen=True)
class ResolvedRealModule:
    """
    Resolved data for one real module instance.
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
    value_has_min_max: bool
    value_has_out_of_range: bool

    target_has_min_max: bool
    target_has_limits: bool
    target_has_drive_tolerance: bool

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

    status_has_disabled: bool = False
    status_has_hw_error: bool = False

    x_plc_value: ResolvedRealModuleValuePlc | None = None
    x_plc_status: ResolvedRealModuleStatusPlc | None = None
    x_plc_target: ResolvedRealModuleTargetPlc | None = None
    x_plc_clear_errors: ResolvedRealModuleClearErrorsPlc | None = None


@dataclass(frozen=True)
class ResolvedRealSecNode:
    firmware: str
    secop_version: str
    tcp_server_ip: str
    tcp_server_port: int
    plc_timestamp_tag: str
    tcp_server_interface_healthy_tag: str
    module_names_in_order: list[str]
    structure_report_json: str


@dataclass(frozen=True)
class ResolvedRealModules:
    """
    Root resolved model for real modules + sec node.
    """
    sec_node: ResolvedRealSecNode
    modules: dict[str, ResolvedRealModule]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_accessible(module: dict[str, Any], name: str) -> dict[str, Any] | None:
    accessibles = module.get("accessibles") or {}
    value = accessibles.get(name)
    return value if isinstance(value, dict) else None


def _get_datainfo(accessible: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(accessible, dict):
        return None
    di = accessible.get("datainfo")
    return di if isinstance(di, dict) else None


def _get_module_x_plc(module: dict[str, Any]) -> dict[str, Any]:
    x = module.get("x-plc")
    return x if isinstance(x, dict) else {}


def _deep_remove_x_plc(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: _deep_remove_x_plc(value)
            for key, value in obj.items()
            if key != "x-plc"
        }
    if isinstance(obj, list):
        return [_deep_remove_x_plc(item) for item in obj]
    return obj


def _build_structure_report_json(normalized_cfg: dict[str, Any]) -> str:
    without_x_plc = _deep_remove_x_plc(normalized_cfg)
    return json.dumps(without_x_plc, ensure_ascii=False, separators=(",", ":"))


def _as_dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------
# Per-module resolver
# ---------------------------------------------------------------------------


def _resolve_one_real_module(
    module_name: str,
    module_cfg: dict[str, Any],
    resolved_classes: ResolvedModuleClasses,
) -> ResolvedRealModule:
    module_class_name = resolved_classes.module_to_class[module_name]
    resolved_class = resolved_classes.classes[module_class_name]
    x_plc = _get_module_x_plc(module_cfg)

    # secop values
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

    # x-plc.value
    xplc_value = _as_dict_or_none(x_plc.get("value"))
    resolved_x_value = ResolvedRealModuleValuePlc(
        timestamp_tag=str(x_plc.get("timestamp_tag") or ""),
        read_expr=xplc_value.get("read_expr") if xplc_value else None,
        enum_tag=xplc_value.get("enum_tag") if xplc_value else None,
        enum_member_map=xplc_value.get("enum_member_map") if xplc_value else None,
        outofrange_min=xplc_value.get("outofrange_min") if xplc_value else None,
        outofrange_max=xplc_value.get("outofrange_max") if xplc_value else None,
    )

    # x-plc.status
    xplc_status = _as_dict_or_none(x_plc.get("status"))
    resolved_x_status = ResolvedRealModuleStatusPlc(
        disabled_expr=str(xplc_status.get("disabled_expr") or "") if xplc_status else "",
        disabled_description=str(xplc_status.get("disabled_description") or "") if xplc_status else "",
        hw_error_expr=str(xplc_status.get("hw_error_expr") or "") if xplc_status else "",
        hw_error_description=str(xplc_status.get("hw_error_description") or "") if xplc_status else "",
    )

    # x-plc.target
    xplc_target = _as_dict_or_none(x_plc.get("target"))
    resolved_x_target = ResolvedRealModuleTargetPlc(
        write_stmt=xplc_target.get("write_stmt") if xplc_target else None,
        enum_tag=xplc_target.get("enum_tag") if xplc_target else None,
        change_possible_expr=xplc_target.get("change_possible_expr") if xplc_target else None,
        reach_timeout_s=xplc_target.get("reach_timeout_s") if xplc_target else None,
        reach_abs_tolerance=xplc_target.get("reach_abs_tolerance") if xplc_target else None,
    )

    # x-plc.clear_errors
    xplc_clear = _as_dict_or_none(x_plc.get("clear_errors"))
    resolved_x_clear = ResolvedRealModuleClearErrorsPlc(
        cmd_stmt=xplc_clear.get("cmd_stmt") if xplc_clear else None
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
        value_has_min_max=bool(resolved_class.value.has_min_max),
        value_has_out_of_range=bool(resolved_class.value.has_out_of_range),

        target_has_min_max=bool(resolved_class.target.has_min_max) if resolved_class.target else False,
        target_has_limits=bool(resolved_class.target.has_limits) if resolved_class.target else False,
        target_has_drive_tolerance=bool(resolved_class.target.has_drive_tolerance) if resolved_class.target else False,

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

        has_clear_errors_command=any(v.name == "xClearErrors" for v in resolved_class.module_variables),

        custom_parameters=list(resolved_class.custom_parameters),
        custom_commands=list(resolved_class.custom_commands),

        status_has_disabled=bool(resolved_x_status.disabled_expr.strip()),
        status_has_hw_error=bool(resolved_x_status.hw_error_expr.strip()),

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
) -> ResolvedRealModules:
    """
    Resolve a common model for real modules and sec node.

    This model is intended to be reused by:
    - SecopInit
    - SecopMapFromPlc
    - SecopMapToPlc
    """
    modules_cfg = normalized_cfg.get("modules") or {}
    if not isinstance(modules_cfg, dict):
        raise ValueError("normalized_cfg.modules must be a dict")

    x_plc_node = normalized_cfg.get("x-plc") or {}
    if not isinstance(x_plc_node, dict):
        raise ValueError("normalized_cfg['x-plc'] must be a dict")

    tcp_cfg = x_plc_node.get("tcp") or {}
    if not isinstance(tcp_cfg, dict):
        raise ValueError("normalized_cfg['x-plc']['tcp'] must be a dict")

    sec_node = ResolvedRealSecNode(
        firmware=str(normalized_cfg.get("firmware") or ""),
        secop_version=str(x_plc_node.get("secop_version") or ""),
        tcp_server_ip=str(tcp_cfg.get("server_ip") or ""),
        tcp_server_port=int(tcp_cfg.get("server_port")),
        plc_timestamp_tag=str(x_plc_node.get("plc_timestamp_tag") or ""),
        tcp_server_interface_healthy_tag=str(tcp_cfg.get("interface_healthy_tag") or ""),
        module_names_in_order=list(modules_cfg.keys()),
        structure_report_json=_build_structure_report_json(normalized_cfg),
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