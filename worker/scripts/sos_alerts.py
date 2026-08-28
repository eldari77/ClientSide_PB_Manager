from __future__ import annotations

from typing import Any

from sos.services import alerts as _alerts_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _alerts_service.run(request)
