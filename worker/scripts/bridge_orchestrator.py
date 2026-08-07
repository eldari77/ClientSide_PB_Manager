from __future__ import annotations

from typing import Any


def run(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter_status": "rejected",
        "summary": "bridge_orchestrator is handled by worker.execute_orchestrator_request.",
        "commands": [{"kind": "echo", "text": "bridge_orchestrator direct module execution is disabled"}],
        "error_bucket": "orchestrator_direct_execution",
    }
