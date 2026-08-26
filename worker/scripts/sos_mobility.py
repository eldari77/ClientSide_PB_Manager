from __future__ import annotations

from typing import Any

from sos.services import mobility as _mobility_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _mobility_service.run(request)
