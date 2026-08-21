from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


LIMITS_SCHEMA = "novali.client_side_pb.bridge_limits.v1"
LIMITER_STATES = {"ok", "soft_limited", "cooldown", "disabled", "config_invalid"}


@dataclass(frozen=True)
class BridgeLimitProfile:
    runtime_ms_limit: float = 0.25
    runtime_ms_soft_ratio: float = 0.75
    cooldown_seconds: int = 3
    max_commands_per_minute: int = 60
    fail_closed: bool = True


@dataclass(frozen=True)
class BridgeLimits:
    schema: str = LIMITS_SCHEMA
    default: BridgeLimitProfile = field(default_factory=BridgeLimitProfile)
    per_bridge: dict[str, BridgeLimitProfile] = field(default_factory=dict)


def validate_profile(profile: BridgeLimitProfile) -> str:
    if profile.runtime_ms_limit < 0:
        return "runtime_ms_limit_negative"
    if profile.runtime_ms_limit == 0:
        return "disabled"
    if profile.runtime_ms_soft_ratio <= 0 or profile.runtime_ms_soft_ratio > 1:
        return "runtime_ms_soft_ratio_invalid"
    if profile.cooldown_seconds < 0:
        return "cooldown_seconds_negative"
    if profile.max_commands_per_minute < 0:
        return "max_commands_per_minute_negative"
    return "none"


def profile_from_dict(payload: dict[str, Any]) -> BridgeLimitProfile:
    return BridgeLimitProfile(
        runtime_ms_limit=float(payload.get("runtime_ms_limit", BridgeLimitProfile.runtime_ms_limit)),
        runtime_ms_soft_ratio=float(payload.get("runtime_ms_soft_ratio", BridgeLimitProfile.runtime_ms_soft_ratio)),
        cooldown_seconds=int(payload.get("cooldown_seconds", BridgeLimitProfile.cooldown_seconds)),
        max_commands_per_minute=int(payload.get("max_commands_per_minute", BridgeLimitProfile.max_commands_per_minute)),
        fail_closed=bool(payload.get("fail_closed", BridgeLimitProfile.fail_closed)),
    )


def limits_from_dict(payload: dict[str, Any]) -> BridgeLimits:
    default_payload = payload.get("default", {}) if isinstance(payload.get("default", {}), dict) else {}
    per_bridge_payload = payload.get("per_bridge", {}) if isinstance(payload.get("per_bridge", {}), dict) else {}
    return BridgeLimits(
        schema=str(payload.get("schema", LIMITS_SCHEMA)),
        default=profile_from_dict(default_payload),
        per_bridge={str(key): profile_from_dict(value) for key, value in per_bridge_payload.items() if isinstance(value, dict)},
    )


def profile_for_bridge(limits: BridgeLimits, bridge_id: str) -> BridgeLimitProfile:
    return limits.per_bridge.get(bridge_id, limits.default)


def load_limits(path: Path) -> BridgeLimits:
    if not path.exists():
        return BridgeLimits()
    return limits_from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_limits(path: Path, limits: BridgeLimits) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": limits.schema,
        "default": asdict(limits.default),
        "per_bridge": {key: asdict(value) for key, value in limits.per_bridge.items()},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def limiter_state(profile: BridgeLimitProfile, last_runtime_ms: float, cooldown_remaining_seconds: float = 0) -> str:
    validation = validate_profile(profile)
    if validation == "disabled":
        return "disabled"
    if validation != "none":
        return "config_invalid"
    if cooldown_remaining_seconds > 0:
        return "cooldown"
    if last_runtime_ms >= profile.runtime_ms_limit:
        return "cooldown"
    if last_runtime_ms >= profile.runtime_ms_limit * profile.runtime_ms_soft_ratio:
        return "soft_limited"
    return "ok"
