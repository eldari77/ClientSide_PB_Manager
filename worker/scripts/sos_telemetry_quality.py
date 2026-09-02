from __future__ import annotations

from typing import Any

from sos.services import telemetry_quality as _telemetry_quality_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _telemetry_quality_service.run(request)
