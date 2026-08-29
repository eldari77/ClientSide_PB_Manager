from __future__ import annotations

from typing import Any

from sos.services import diagnostics as _diagnostics_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _diagnostics_service.run(request)
