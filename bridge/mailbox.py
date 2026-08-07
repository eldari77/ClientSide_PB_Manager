from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from bridge.limits import BridgeLimitProfile


SCHEMA = "novali.client_side_pb_bridge.v1"


@dataclass
class BridgeConfig:
    bridge_id: str
    mailbox_mode: str = "both"
    text_panel_name: str = "NOVALI PB Bridge"
    allowed_worker_scripts: tuple[str, ...] = ("sample_status_adapter",)
    max_commands_per_minute: int = 30
    fail_closed: bool = True
    limit_profile: BridgeLimitProfile = field(default_factory=BridgeLimitProfile)


def request_payload(
    config: BridgeConfig,
    sequence: int,
    script_id: str,
    state: dict[str, Any],
    runtime_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if sequence <= 0:
        raise ValueError("sequence must be positive")
    if script_id not in config.allowed_worker_scripts:
        raise ValueError("script_id is not allowlisted")
    payload = {
        "schema": SCHEMA,
        "message_kind": "request",
        "bridge_id": config.bridge_id,
        "sequence": sequence,
        "script_id": script_id,
        "request_kind": "adapter_tick",
        "state": state,
    }
    if runtime_telemetry is not None:
        payload["runtime_telemetry"] = runtime_telemetry
    return payload


def validate_result(config: BridgeConfig, expected_sequence: int, payload: dict[str, Any]) -> str:
    if payload.get("schema") != SCHEMA:
        return "schema_mismatch"
    if payload.get("message_kind") != "result":
        return "message_kind_invalid"
    if payload.get("bridge_id") != config.bridge_id:
        return "bridge_id_mismatch"
    if payload.get("sequence") != expected_sequence:
        return "sequence_mismatch"
    if payload.get("script_id") not in config.allowed_worker_scripts:
        return "script_not_allowlisted"
    if payload.get("status") not in {"ok", "rejected", "failed", "timeout"}:
        return "status_invalid"
    return "none"


def encode_mailbox(payload: dict[str, Any]) -> str:
    return "NOVALI_CLIENT_SIDE_PB_JSON_BEGIN\n" + json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\nNOVALI_CLIENT_SIDE_PB_JSON_END"


def decode_mailbox(text: str) -> dict[str, Any]:
    start = "NOVALI_CLIENT_SIDE_PB_JSON_BEGIN"
    end = "NOVALI_CLIENT_SIDE_PB_JSON_END"
    if start not in text or end not in text:
        raise ValueError("mailbox markers missing")
    body = text.split(start, 1)[1].split(end, 1)[0].strip()
    return json.loads(body)
