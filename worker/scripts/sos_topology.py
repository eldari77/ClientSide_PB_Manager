from __future__ import annotations

from typing import Any

from sos.services import topology as _topology_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _topology_service.run(request)
