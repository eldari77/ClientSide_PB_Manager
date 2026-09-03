from __future__ import annotations

from typing import Any

from sos.services import automation as _automation_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _automation_service.run(request)
