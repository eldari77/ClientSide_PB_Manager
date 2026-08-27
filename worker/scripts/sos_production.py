from __future__ import annotations

from typing import Any

from sos.services import production as _production_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _production_service.run(request)
