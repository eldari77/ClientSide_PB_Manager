from __future__ import annotations

from typing import Any

from worker.isy_foundation import plan_isy_foundation


def run(request: dict[str, Any]) -> dict[str, Any]:
    return plan_isy_foundation(request)
