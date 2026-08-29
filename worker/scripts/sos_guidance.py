from __future__ import annotations

from typing import Any

from sos.services import guidance as _guidance_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _guidance_service.run(request)
