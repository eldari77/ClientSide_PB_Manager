from __future__ import annotations

from typing import Any


def run(request: dict[str, Any]) -> dict[str, Any]:
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    inventory_count = state.get("inventory_count", 0)
    block_count = state.get("block_count", 0)
    return {
        "summary": f"blocks={block_count};inventory={inventory_count}",
        "commands": [
            {
                "kind": "echo",
                "text": "sample_status_adapter completed",
            }
        ],
    }

