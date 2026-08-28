from __future__ import annotations

from typing import Any

from sos.services import mining as _mining_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _mining_service.run(request)
