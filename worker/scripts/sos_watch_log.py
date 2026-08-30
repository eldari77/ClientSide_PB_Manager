from __future__ import annotations

from typing import Any

from sos.services import watch_log as _watch_log_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _watch_log_service.run(request)
