from __future__ import annotations

from typing import Any

from sos.services import power as _power_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _power_service.run(request)
