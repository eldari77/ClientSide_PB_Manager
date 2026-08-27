from __future__ import annotations

from typing import Any

from sos.services import defense as _defense_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _defense_service.run(request)
