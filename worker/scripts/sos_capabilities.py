from __future__ import annotations

from typing import Any

from sos.services import capabilities as _capabilities_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _capabilities_service.run(request)
