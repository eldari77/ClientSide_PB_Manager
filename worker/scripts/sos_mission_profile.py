from __future__ import annotations

from typing import Any

from sos.services import mission_profile as _mission_profile_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _mission_profile_service.run(request)
