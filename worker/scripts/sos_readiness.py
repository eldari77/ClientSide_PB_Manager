from __future__ import annotations

from typing import Any

from sos.services import readiness as _readiness_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _readiness_service.run(request)
