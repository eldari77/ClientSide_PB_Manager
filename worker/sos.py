from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import sos as _sos
from sos import (
    MODE_SERVICE_POLICIES,
    SOS_MODES,
    SOS_SHIPS_SCHEMA,
    SosRegistry,
    SosShip,
    infer_service_id,
)


def load_sos_registry(root: Path) -> SosRegistry:
    return _sos.load_sos_registry(root)


def validate_sos_registry(registry: SosRegistry) -> list[str]:
    return _sos.validate_sos_registry(registry)


def expand_sos_bridge_configs(
    root: Path,
    bridge_configs: dict[str, Any],
    bridge_config_factory: Callable[[str, tuple[str, ...], tuple[dict[str, Any], ...]], Any] | None = None,
) -> dict[str, Any]:
    factory = bridge_config_factory or _bridge_script_config_factory()
    return _sos.expand_sos_bridge_configs(
        root,
        bridge_configs,
        bridge_config_factory=factory,
    )


def sos_context_for_request(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    return _sos.sos_context_for_request(root, request)


def attach_sos_request_context(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    return _sos.attach_sos_request_context(root, request)


def _bridge_script_config_factory() -> Callable[[str, tuple[str, ...], tuple[dict[str, Any], ...]], Any]:
    from worker.worker import BridgeScriptConfig

    return BridgeScriptConfig
