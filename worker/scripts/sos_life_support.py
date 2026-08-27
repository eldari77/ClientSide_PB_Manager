from __future__ import annotations

from typing import Any

from sos.services import life_support as _life_support_service


def run(request: dict[str, Any]) -> dict[str, Any]:
    return _life_support_service.run(request)
