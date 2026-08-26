from __future__ import annotations

from typing import Any

from sos.services import integrity as _integrity_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _integrity_service.run(request)
