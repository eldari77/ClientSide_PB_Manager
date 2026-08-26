from __future__ import annotations

from typing import Any

from sos.services import logistics as _logistics_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _logistics_service.run(request)
