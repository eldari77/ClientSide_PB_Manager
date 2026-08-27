from __future__ import annotations

from typing import Any

from sos.services import environment as _environment_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _environment_service.run(request)
