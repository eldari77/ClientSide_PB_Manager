from __future__ import annotations

from typing import Any

from sos.services import navigation as _navigation_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _navigation_service.run(request)
