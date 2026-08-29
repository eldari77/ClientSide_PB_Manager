from __future__ import annotations

from typing import Any

from sos.services import runbook as _runbook_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _runbook_service.run(request)
