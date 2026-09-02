from __future__ import annotations

from typing import Any

from sos.services import config_drift as _config_drift_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _config_drift_service.run(request)
