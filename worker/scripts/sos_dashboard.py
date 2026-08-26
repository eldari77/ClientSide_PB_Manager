from __future__ import annotations

from typing import Any

from sos.services import dashboard as _dashboard_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _dashboard_service.run(request)
