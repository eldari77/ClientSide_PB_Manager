from __future__ import annotations

from typing import Any

from worker.isy_foundation import plan_isy_foundation


def run(request: dict[str, Any]) -> dict[str, Any]:
    """Adapter for Workshop 1216126863: Isy's Inventory Manager."""
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    if request.get("request_kind") == "adapter_tick" or state.get("snapshot_mode") == "minimal":
        result = plan_isy_foundation(request)
        result["config_keys"] = sorted(config.keys())
        result["observed_state_keys"] = sorted(state.keys())
        return result

    enabled_features = [
        name for name in (
            "autoContainerAssignment",
            "enableAutocrafting",
            "enableOreBalancing",
            "enableIceBalancing",
            "enableUraniumBalancing",
        )
        if config.get(name) is True
    ]
    return {
        "summary": "Isy's Inventory Manager config loaded; behavior mapping still required.",
        "commands": [
            {
                "kind": "echo",
                "text": "IIM adapter config loaded: " + str(len(config)) + " settings; enabled=" + ",".join(enabled_features)
            }
        ],
        "config_keys": sorted(config.keys()),
        "enabled_features": enabled_features,
        "observed_state_keys": sorted(state.keys()),
    }
