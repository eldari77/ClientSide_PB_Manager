from __future__ import annotations

from typing import Any

from sos.services import maintenance as _maintenance_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _maintenance_service.run(request)
