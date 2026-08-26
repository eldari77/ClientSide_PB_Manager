from __future__ import annotations

from typing import Any

from sos.services import status as _status_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _status_service.run(request)
