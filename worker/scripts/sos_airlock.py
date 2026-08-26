from __future__ import annotations

from typing import Any

from sos.services import airlock as _airlock_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _airlock_service.run(request)
