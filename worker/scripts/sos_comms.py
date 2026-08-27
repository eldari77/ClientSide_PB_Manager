from __future__ import annotations

from typing import Any

from sos.services import comms as _comms_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _comms_service.run(request)
