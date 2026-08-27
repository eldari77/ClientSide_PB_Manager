from __future__ import annotations

from typing import Any

from sos.services import crew as _crew_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _crew_service.run(request)
