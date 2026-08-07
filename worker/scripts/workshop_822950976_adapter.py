from __future__ import annotations

from typing import Any


def run(request: dict[str, Any]) -> dict[str, Any]:
    """Adapter scaffold for Workshop 822950976: Automatic LCDs 2."""
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    return {
        "summary": "Adapter scaffold created; manual mapping still required.",
        "commands": [
            {
                "kind": "echo",
                "text": "Adapter scaffold for Workshop 822950976 needs implementation."
            }
        ],
        "observed_state_keys": sorted(state.keys()),
    }
