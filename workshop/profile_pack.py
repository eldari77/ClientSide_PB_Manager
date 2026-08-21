from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


PROFILE_PACK_SCHEMA = "novali.client_side_pb.profile_pack.v1"


def builtin_profile_pack() -> dict[str, Any]:
    return {
        "schema": PROFILE_PACK_SCHEMA,
        "profiles": {
            "1216126863": {
                "workshop_id": "1216126863",
                "display_name": "Isy's Inventory Manager",
                "script_id": "workshop_1216126863_adapter",
                "strategy": "profile_adapter",
                "profile_id": "isy_inventory_manager",
                "operator_status": "ready_profile",
                "role": "maintenance",
                "reactive": False,
                "expires_after_sequences": 0,
                "fairness_weight": 1,
                "safe_default_enabled": True,
                "notes": "Reviewed Python profile adapter for inventory sorting and machine setup planning.",
            },
            "416932930": {
                "workshop_id": "416932930",
                "display_name": "Whip's Auto Door and Airlock Script",
                "script_id": "virtual_whip_auto_door",
                "strategy": "virtual_pb",
                "operator_status": "ready_virtual_pb",
                "role": "reactive",
                "reactive": True,
                "expires_after_sequences": 1,
                "fairness_weight": 3,
                "safe_default_enabled": True,
                "notes": "Known virtual PB door-control profile; stale commands should expire quickly.",
            },
            "822950976": {
                "workshop_id": "822950976",
                "display_name": "Automatic LCDs 2",
                "script_id": "virtual_workshop_822950976",
                "strategy": "virtual_pb",
                "operator_status": "ready_virtual_pb",
                "role": "display",
                "reactive": False,
                "expires_after_sequences": 0,
                "fairness_weight": 1,
                "safe_default_enabled": True,
                "notes": "Known virtual PB display profile with text-surface command output.",
            },
            "2831096030": {
                "workshop_id": "2831096030",
                "display_name": "Vector Thrust OS",
                "script_id": "workshop_2831096030_adapter",
                "strategy": "manual_adapter",
                "operator_status": "blocked_needs_command_mapping",
                "role": "flight_control",
                "reactive": True,
                "expires_after_sequences": 1,
                "fairness_weight": 4,
                "safe_default_enabled": False,
                "notes": "Blocked until reviewed thrust and rotor command mappings exist.",
            },
        },
    }


def load_profile_pack(root: Path) -> dict[str, Any]:
    path = root / "data" / "profile_pack.json"
    if not path.exists():
        return builtin_profile_pack()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return builtin_profile_pack()
    if payload.get("schema") != PROFILE_PACK_SCHEMA or not isinstance(payload.get("profiles"), dict):
        return builtin_profile_pack()
    merged = builtin_profile_pack()
    merged["profiles"].update(payload["profiles"])
    return merged


def profile_for_workshop(workshop_id: str, display_name: str = "", root: Path | None = None) -> dict[str, Any] | None:
    pack = load_profile_pack(root) if root is not None else builtin_profile_pack()
    profiles = pack.get("profiles") if isinstance(pack.get("profiles"), dict) else {}
    profile = profiles.get(str(workshop_id))
    if isinstance(profile, dict):
        return deepcopy(profile)

    title = display_name.casefold()
    for item in profiles.values():
        if not isinstance(item, dict):
            continue
        known_title = str(item.get("display_name", "")).casefold()
        if known_title and known_title in title:
            return deepcopy(item)
    return None


def operator_status_for_compatibility(
    compatibility_status: str,
    compatibility: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> str:
    if profile and profile.get("operator_status"):
        return str(profile["operator_status"])
    compatibility = compatibility or {}
    missing_snapshot = compatibility.get("missing_snapshot_fields")
    if isinstance(missing_snapshot, list) and missing_snapshot:
        return "missing_snapshot_fields"
    blocked = compatibility.get("blocked_command_mappings")
    if isinstance(blocked, list) and blocked:
        return "blocked_needs_command_mapping"
    mapping = {
        "profile_adapter_ready": "ready_profile",
        "virtual_pb_ready": "ready_virtual_pb",
        "virtual_pb_blocked": "blocked_needs_command_mapping",
        "adapter_scaffold_created": "manual_adapter_required",
        "manual_adapter_required": "manual_adapter_required",
    }
    return mapping.get(str(compatibility_status), "manual_adapter_required")


def operator_status_label(operator_status: str) -> str:
    labels = {
        "ready_profile": "Known profile ready",
        "ready_virtual_pb": "Virtual PB ready",
        "blocked_needs_command_mapping": "Blocked command mapping",
        "missing_snapshot_fields": "Missing snapshot fields",
        "manual_adapter_required": "Manual adapter required",
    }
    return labels.get(operator_status, "Manual review required")
