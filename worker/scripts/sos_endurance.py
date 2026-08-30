from __future__ import annotations

from typing import Any

from sos.services import endurance as _endurance_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _endurance_service.run(request)
