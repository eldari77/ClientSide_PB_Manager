from pathlib import Path

from bridge.limits import (
    BridgeLimitProfile,
    BridgeLimits,
    limiter_state,
    load_limits,
    profile_for_bridge,
    save_limits,
    validate_profile,
)


def test_default_runtime_limit_profile():
    profile = BridgeLimitProfile()
    assert profile.runtime_ms_limit == 0.25
    assert profile.runtime_ms_soft_ratio == 0.75
    assert profile.cooldown_seconds == 3
    assert profile.max_commands_per_minute == 60
    assert validate_profile(profile) == "none"


def test_invalid_profile_detected():
    assert validate_profile(BridgeLimitProfile(runtime_ms_soft_ratio=1.2)) == "runtime_ms_soft_ratio_invalid"
    assert validate_profile(BridgeLimitProfile(runtime_ms_limit=0)) == "disabled"


def test_per_bridge_override_precedence():
    limits = BridgeLimits(per_bridge={"bridge-a": BridgeLimitProfile(runtime_ms_limit=0.01)})
    assert profile_for_bridge(limits, "bridge-a").runtime_ms_limit == 0.01
    assert profile_for_bridge(limits, "bridge-b").runtime_ms_limit == 0.25


def test_limiter_state_transitions():
    profile = BridgeLimitProfile(runtime_ms_limit=0.25, runtime_ms_soft_ratio=0.75)
    assert limiter_state(profile, 0.1) == "ok"
    assert limiter_state(profile, 0.2) == "soft_limited"
    assert limiter_state(profile, 0.25) == "cooldown"
    assert limiter_state(profile, 0.1, cooldown_remaining_seconds=3) == "cooldown"


def test_limits_round_trip(tmp_path: Path):
    path = tmp_path / "bridge_limits.json"
    limits = BridgeLimits(per_bridge={"bridge-a": BridgeLimitProfile(runtime_ms_limit=0.02)})
    save_limits(path, limits)
    loaded = load_limits(path)
    assert loaded.default.runtime_ms_limit == 0.25
    assert loaded.per_bridge["bridge-a"].runtime_ms_limit == 0.02
