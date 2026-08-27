from __future__ import annotations

from typing import Any

from sos.services import docking as _docking_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _docking_service.run(request)
