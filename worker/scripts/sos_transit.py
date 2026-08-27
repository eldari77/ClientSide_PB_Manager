from __future__ import annotations

from typing import Any

from sos.services import transit as _transit_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _transit_service.run(request)
