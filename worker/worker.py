from __future__ import annotations

import argparse
import html
import importlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from worker.sos import attach_sos_request_context, expand_sos_bridge_configs


SCHEMA = "novali.client_side_pb_bridge.v1"
COMMAND_QUEUE_SCHEMA = "novali.client_side_pb.command_queue.v1"
AUTOCRAFTING_BLUEPRINT_SCHEMA = "novali.client_side_pb.autocrafting_blueprints.v1"
SCRIPT_INSTANCES_SCHEMA = "novali.client_side_pb.script_instances.v1"
BRIDGE_HEALTH_SCHEMA = "novali.client_side_pb.bridge_health.v1"
VOLATILE_COMMAND_KINDS = {"transfer_item", "write_text_surface"}
INTEGRITY_SNAPSHOT_KEYS = ("integrity_snapshot", "ship_integrity", "damage_snapshot")
INTEGRITY_BLOCK_KEYS = (
    "integrity_ratio",
    "integrity",
    "current_integrity",
    "max_integrity",
    "maximum_integrity",
    "functional",
    "is_functional",
)
LOGISTICS_SNAPSHOT_KEYS = ("inventory_snapshot", "ship_inventory", "logistics_snapshot")
LOGISTICS_READY_KEYS = ("cargo", "cargo_containers", "ammo", "fuel", "resources", "production")
FUEL_SUBTYPE_KEYS = {"ice", "uranium"}
AIRLOCK_SNAPSHOT_KEYS = ("airlock_snapshot", "door_snapshot", "ship_doors")
AIRLOCK_READY_KEYS = ("doors", "airlocks", "vents", "compartments")
MAINTENANCE_SNAPSHOT_KEYS = ("maintenance_snapshot", "repair_snapshot", "damage_control_snapshot", "projector_snapshot")
ENVIRONMENT_SNAPSHOT_KEYS = ("environment_snapshot", "hazard_snapshot", "weather_snapshot", "external_snapshot")
NAVIGATION_SNAPSHOT_KEYS = ("navigation_snapshot", "nav_snapshot", "flight_snapshot", "motion_snapshot")
MINING_SNAPSHOT_KEYS = ("mining_snapshot", "harvest_snapshot", "resource_snapshot", "ore_snapshot")
ALERTS_SNAPSHOT_KEYS = ("alerts_snapshot", "notification_snapshot")
READINESS_SNAPSHOT_KEYS = ("readiness_snapshot", "operator_readiness_snapshot")
CAPABILITIES_SNAPSHOT_KEYS = (
    "capability_snapshot",
    "capabilities_snapshot",
    "ship_capabilities_snapshot",
    "role_snapshot",
)
TELEMETRY_QUALITY_SNAPSHOT_KEYS = (
    "telemetry_quality_snapshot",
    "evidence_snapshot",
    "data_quality_snapshot",
    "signal_quality_snapshot",
)
AUTOMATION_SNAPSHOT_KEYS = (
    "automation_snapshot",
    "control_logic_snapshot",
    "script_health_snapshot",
    "pb_snapshot",
    "programmable_block_snapshot",
)
CONFIG_DRIFT_SNAPSHOT_KEYS = (
    "config_drift_snapshot",
    "configuration_snapshot",
    "contract_snapshot",
    "registry_snapshot",
    "ship_registry_snapshot",
    "template_snapshot",
    "host_manifest_snapshot",
    "script_instances_snapshot",
)
CONFIG_DRIFT_SHARED_DIAGNOSTICS_KEYS = ("contract_snapshot",)
TOPOLOGY_SNAPSHOT_KEYS = (
    "topology_snapshot",
    "dependency_snapshot",
    "dependency_map_snapshot",
    "blast_radius_snapshot",
)
REDUNDANCY_SNAPSHOT_KEYS = (
    "redundancy_snapshot",
    "failover_snapshot",
    "critical_systems_snapshot",
    "coverage_snapshot",
    "resilience_snapshot",
)
GUIDANCE_SNAPSHOT_KEYS = ("guidance_snapshot", "operator_guidance_snapshot", "watch_snapshot", "priorities_snapshot")
DIAGNOSTICS_SNAPSHOT_KEYS = (
    "contract_snapshot",
    "diagnostics_snapshot",
    "contract_health_snapshot",
    "command_analysis_snapshot",
    "child_health_snapshot",
)
WATCH_LOG_SNAPSHOT_KEYS = (
    "watch_log_snapshot",
    "event_log_snapshot",
    "timeline_snapshot",
    "history_snapshot",
    "operator_log_snapshot",
)
MISSION_PROFILE_SNAPSHOT_KEYS = (
    "mission_profile_snapshot",
    "operating_envelope_snapshot",
    "operating_profile_snapshot",
    "profile_snapshot",
)
ENDURANCE_SNAPSHOT_KEYS = (
    "endurance_snapshot",
    "consumables_snapshot",
    "resource_forecast_snapshot",
    "supply_snapshot",
    "runway_snapshot",
)
RUNBOOK_SNAPSHOT_KEYS = ("runbook_snapshot", "checklist_snapshot", "procedure_snapshot", "operator_checklist_snapshot")
DISPLAY_SNAPSHOT_KEYS = (
    "display_snapshot",
    "displays_snapshot",
    "surface_snapshot",
    "surfaces_snapshot",
    "text_surface_snapshot",
    "lcd_snapshot",
)
DEFAULT_LCD_QUEUE_COOLDOWN_SEQUENCES = 1
DEFAULT_BRIDGE_STALE_SECONDS = 120
DEFAULT_PROCESSED_REQUEST_RETENTION_SECONDS = 300
DEFAULT_PROCESSED_REQUEST_CLEANUP_MAX_FILES = 250
RESULT_STORAGE_MAX_STRING_CHARS = 1000
RESULT_STORAGE_MAX_COMMAND_TEXT_CHARS = 48
RESULT_STORAGE_MAX_COMMAND_ITEMS = 16
RESULT_STORAGE_MAX_LIST_ITEMS = 28
RESULT_STORAGE_MAX_DEPTH = 8
RESULT_STORAGE_MAX_BYTES = 64000
RESULT_STORAGE_COMPACT_WARNING_ITEMS = 3
RESULT_STORAGE_COMPACT_SOURCE_ITEMS = 8
RESULT_STORAGE_COMPACT_TEXT_CHARS = 180


@dataclass
class WorkerScript:
    script_id: str
    source: str
    display_name: str
    module: str
    input_schema: str
    output_schema: str
    timeout_ms: int
    enabled: bool
    runtime: str = "python"
    source_path: str = ""
    base_script_id: str = ""
    config_id: str = ""
    instance_bridge_id: str = ""


@dataclass
class BridgeScriptConfig:
    selected_script_id: str
    allowed_worker_scripts: tuple[str, ...]
    child_worker_scripts: tuple[dict[str, Any], ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stale_seconds_from_env() -> int:
    try:
        return max(1, int(os.environ.get("NOVALI_CLIENT_SIDE_PB_STALE_SECONDS", str(DEFAULT_BRIDGE_STALE_SECONDS))))
    except ValueError:
        return DEFAULT_BRIDGE_STALE_SECONDS


def processed_request_retention_seconds_from_env() -> int:
    try:
        return max(
            0,
            int(
                os.environ.get(
                    "NOVALI_CLIENT_SIDE_PB_PROCESSED_REQUEST_RETENTION_SECONDS",
                    str(DEFAULT_PROCESSED_REQUEST_RETENTION_SECONDS),
                )
            ),
        )
    except ValueError:
        return DEFAULT_PROCESSED_REQUEST_RETENTION_SECONDS


def processed_request_cleanup_max_files_from_env() -> int:
    try:
        return max(
            1,
            int(
                os.environ.get(
                    "NOVALI_CLIENT_SIDE_PB_PROCESSED_REQUEST_CLEANUP_MAX_FILES",
                    str(DEFAULT_PROCESSED_REQUEST_CLEANUP_MAX_FILES),
                )
            ),
        )
    except ValueError:
        return DEFAULT_PROCESSED_REQUEST_CLEANUP_MAX_FILES


def load_manifest(root: Path) -> dict[str, WorkerScript]:
    manifest_path = root / "worker" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    scripts: dict[str, WorkerScript] = {}
    for item in payload.get("scripts", []):
        script = WorkerScript(
            script_id=str(item["script_id"]),
            source=str(item.get("source", "manual")),
            display_name=str(item.get("display_name", item["script_id"])),
            module=str(item.get("module", "")),
            input_schema=str(item.get("input_schema", "")),
            output_schema=str(item.get("output_schema", "")),
            timeout_ms=int(item.get("timeout_ms", 1000)),
            enabled=bool(item.get("enabled", False)),
            runtime=str(item.get("runtime", "python")),
            source_path=str(item.get("source_path", "")),
        )
        scripts[script.script_id] = script
    scripts.update(load_script_instances(root, scripts))
    return scripts


def load_script_instances(root: Path, base_scripts: dict[str, WorkerScript]) -> dict[str, WorkerScript]:
    path = root / "data" / "script_instances.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    if payload.get("schema") != SCRIPT_INSTANCES_SCHEMA:
        return {}
    instances = payload.get("instances")
    if not isinstance(instances, dict):
        return {}
    scripts: dict[str, WorkerScript] = {}
    for key, item in instances.items():
        if not isinstance(item, dict):
            continue
        instance_id = str(item.get("instance_id", key)).strip()
        base_script_id = str(item.get("base_script_id", "")).strip()
        if not instance_id or not base_script_id:
            continue
        base = base_scripts.get(base_script_id)
        if base is None:
            continue
        scripts[instance_id] = WorkerScript(
            script_id=instance_id,
            source="script_instance",
            display_name=str(item.get("display_name", instance_id)),
            module=base.module,
            input_schema=base.input_schema,
            output_schema=base.output_schema,
            timeout_ms=base.timeout_ms,
            enabled=bool(item.get("enabled", True)) and base.enabled,
            runtime=base.runtime,
            source_path=base.source_path,
            base_script_id=base_script_id,
            config_id=str(item.get("config_id", instance_id) or instance_id),
            instance_bridge_id=str(item.get("bridge_id", "") or ""),
        )
    return scripts


def load_bridge_script_configs(root: Path) -> dict[str, BridgeScriptConfig]:
    path = root / "data" / "bridge_scripts.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    configs: dict[str, BridgeScriptConfig] = {}
    bridges = payload.get("bridges")
    if not isinstance(bridges, dict):
        return configs
    for bridge_id, item in bridges.items():
        if not isinstance(item, dict):
            continue
        allowed = item.get("allowed_worker_scripts", [])
        if not isinstance(allowed, list):
            allowed = []
        configs[str(bridge_id)] = BridgeScriptConfig(
            selected_script_id=str(item.get("selected_script_id", "")),
            allowed_worker_scripts=tuple(str(script_id) for script_id in allowed if str(script_id)),
            child_worker_scripts=tuple(
                child
                for child in item.get("child_worker_scripts", [])
                if isinstance(child, dict) and str(child.get("script_id", ""))
            ),
        )
    return expand_sos_bridge_configs(root, configs, bridge_config_factory=BridgeScriptConfig)


def load_worker_config(root: Path, script_id: str) -> dict[str, Any]:
    path = root / "data" / "worker_configs" / f"{script_id}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    config: dict[str, Any] = {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return config
    for entry in entries:
        if isinstance(entry, dict) and entry.get("key"):
            config[str(entry["key"])] = entry.get("value")
    return config


def load_effective_worker_config(root: Path, script: WorkerScript) -> dict[str, Any]:
    config_id = script.config_id or script.script_id
    config = load_worker_config(root, config_id)
    if config or not script.base_script_id:
        return config
    return load_worker_config(root, script.base_script_id)


def attach_virtual_pb_custom_data(request: dict[str, Any]) -> None:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    configured = str(config.get("virtualPbCustomData", "") or "")
    virtual_pb = request.get("virtual_pb") if isinstance(request.get("virtual_pb"), dict) else {}
    if configured:
        virtual_pb = dict(virtual_pb)
        virtual_pb["custom_data"] = configured
        virtual_pb["custom_data_source"] = "worker_config.virtualPbCustomData"
        request["virtual_pb"] = virtual_pb
    elif virtual_pb.get("custom_data"):
        virtual_pb = dict(virtual_pb)
        virtual_pb.setdefault("custom_data_source", "request.virtual_pb.custom_data")
        request["virtual_pb"] = virtual_pb


def autocrafting_blueprint_dir(root: Path) -> Path:
    return root / "data" / "autocrafting_blueprints"


def autocrafting_blueprint_path(root: Path, bridge_id: str, script_id: str) -> Path:
    return autocrafting_blueprint_dir(root) / f"{safe_file_name(bridge_id)}-{safe_file_name(script_id)}.json"


def load_autocrafting_blueprints(root: Path, bridge_id: str, script_id: str) -> dict[str, Any]:
    path = autocrafting_blueprint_path(root, bridge_id, script_id)
    if not path.exists():
        return new_autocrafting_blueprints(bridge_id, script_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return new_autocrafting_blueprints(bridge_id, script_id)
    if payload.get("schema") != AUTOCRAFTING_BLUEPRINT_SCHEMA or payload.get("bridge_id") != bridge_id or payload.get("script_id") != script_id:
        return new_autocrafting_blueprints(bridge_id, script_id)
    if not isinstance(payload.get("items"), dict):
        payload["items"] = {}
    return payload


def new_autocrafting_blueprints(bridge_id: str, script_id: str) -> dict[str, Any]:
    return {
        "schema": AUTOCRAFTING_BLUEPRINT_SCHEMA,
        "bridge_id": bridge_id,
        "script_id": script_id,
        "updated_at": utc_now(),
        "items": {},
    }


def save_autocrafting_blueprints(root: Path, bridge_id: str, script_id: str, payload: dict[str, Any]) -> None:
    directory = autocrafting_blueprint_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = utc_now()
    autocrafting_blueprint_path(root, bridge_id, script_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def learn_autocrafting_blueprints(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    bridge_id = str(request.get("bridge_id", ""))
    script_id = str(request.get("script_id", ""))
    payload = load_autocrafting_blueprints(root, bridge_id, script_id)
    changed = False
    blocks = ((request.get("grid_snapshot") if isinstance(request.get("grid_snapshot"), dict) else {}).get("blocks"))
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or not bool(block.get("is_assembler")):
            continue
        for queued in block.get("production_queue") if isinstance(block.get("production_queue"), list) else []:
            if not isinstance(queued, dict):
                continue
            blueprint_id = str(queued.get("blueprint_id", "")).strip()
            component_subtype = component_name_from_blueprint_id(blueprint_id)
            if not blueprint_id or not component_subtype:
                continue
            key = normalize_component_key(component_subtype)
            suffix = blueprint_id.split("/")[-1].strip()
            aliases = sorted({component_subtype, suffix})
            item = {
                "component_subtype": component_subtype,
                "blueprint_id": blueprint_id,
                "aliases": aliases,
                "learned_from": "assembler_queue",
                "updated_at": utc_now(),
            }
            if payload["items"].get(key) != item:
                payload["items"][key] = item
                changed = True
    if changed:
        save_autocrafting_blueprints(root, bridge_id, script_id, payload)
    return payload


def attach_integrity_snapshot_from_grid_snapshot(request: dict[str, Any]) -> None:
    if any(isinstance(request.get(key), dict) for key in INTEGRITY_SNAPSHOT_KEYS):
        return
    grid_snapshot = request.get("grid_snapshot") if isinstance(request.get("grid_snapshot"), dict) else {}
    snapshot = integrity_snapshot_from_grid_snapshot(grid_snapshot)
    if snapshot:
        request["integrity_snapshot"] = snapshot


def integrity_snapshot_from_grid_snapshot(grid_snapshot: dict[str, Any]) -> dict[str, Any]:
    blocks_payload = grid_snapshot.get("blocks") if isinstance(grid_snapshot.get("blocks"), list) else []
    blocks = [block for block in (normalized_integrity_block(item) for item in blocks_payload) if block]
    critical_payload = grid_snapshot.get("critical_systems") if isinstance(grid_snapshot.get("critical_systems"), list) else []
    critical_systems = [
        system for system in (normalized_critical_system(item) for item in critical_payload) if system
    ]
    if not blocks and not critical_systems:
        return {}
    return {"blocks": blocks, "critical_systems": critical_systems}


def normalized_integrity_block(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict) or not any(key in block and block.get(key) is not None for key in INTEGRITY_BLOCK_KEYS):
        return {}
    normalized: dict[str, Any] = {}
    name = first_text(block, "name", "custom_name", "display_name")
    block_type = first_text(block, "type", "subtype", "definition")
    subtype = first_text(block, "subtype")
    if name:
        normalized["name"] = name
    if block_type:
        normalized["type"] = block_type
    if subtype:
        normalized["subtype"] = subtype
    if block.get("integrity_ratio") is not None:
        normalized["integrity_ratio"] = json_scalar(block.get("integrity_ratio"))
    else:
        integrity = block.get("integrity", block.get("current_integrity"))
        max_integrity = block.get("max_integrity", block.get("maximum_integrity"))
        if integrity is not None:
            normalized["integrity"] = json_scalar(integrity)
        if max_integrity is not None:
            normalized["max_integrity"] = json_scalar(max_integrity)
    functional = block.get("functional", block.get("is_functional"))
    if functional is not None:
        normalized["functional"] = bool(functional)
    return normalized


def normalized_critical_system(system: Any) -> dict[str, Any]:
    if not isinstance(system, dict):
        return {}
    normalized: dict[str, Any] = {}
    name = first_text(system, "name", "custom_name", "display_name")
    system_type = first_text(system, "type", "subtype", "role")
    subtype = first_text(system, "subtype")
    if name:
        normalized["name"] = name
    if system_type:
        normalized["type"] = system_type
    if subtype:
        normalized["subtype"] = subtype
    if system.get("present") is not None:
        normalized["present"] = bool(system.get("present"))
    return normalized


def attach_logistics_snapshot_from_host_snapshots(request: dict[str, Any]) -> None:
    for key in ("logistics_snapshot", "ship_inventory", "inventory_snapshot"):
        snapshot = request.get(key)
        if isinstance(snapshot, dict) and logistics_snapshot_is_ready(snapshot):
            request["inventory_snapshot"] = snapshot
            return

    inventory_snapshot = request.get("inventory_snapshot") if isinstance(request.get("inventory_snapshot"), dict) else {}
    grid_snapshot = request.get("grid_snapshot") if isinstance(request.get("grid_snapshot"), dict) else {}
    snapshot = logistics_snapshot_from_host_snapshots(inventory_snapshot, grid_snapshot)
    if snapshot:
        request["inventory_snapshot"] = snapshot
        return
    for key in LOGISTICS_SNAPSHOT_KEYS:
        request.pop(key, None)


def logistics_snapshot_is_ready(snapshot: dict[str, Any]) -> bool:
    return any(snapshot.get(key) not in (None, "", [], {}) for key in LOGISTICS_READY_KEYS)


def logistics_snapshot_from_host_snapshots(inventory_snapshot: dict[str, Any], grid_snapshot: dict[str, Any]) -> dict[str, Any]:
    cargo_used = 0.0
    cargo_max = 0.0
    has_cargo = False
    ammo: dict[str, float] = {}
    fuel: dict[str, float] = {}
    inventory_blocks = inventory_snapshot.get("blocks") if isinstance(inventory_snapshot.get("blocks"), list) else []
    for block in inventory_blocks:
        if not isinstance(block, dict):
            continue
        inventories = block.get("inventories") if isinstance(block.get("inventories"), list) else []
        for inventory in inventories:
            if not isinstance(inventory, dict):
                continue
            current_volume = float_or_none(inventory.get("current_volume", inventory.get("used_volume")))
            max_volume = float_or_none(inventory.get("max_volume", inventory.get("capacity")))
            if current_volume is not None:
                cargo_used += current_volume
                has_cargo = True
            if max_volume is not None:
                cargo_max += max_volume
                has_cargo = True
            items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                amount = float_or_none(item.get("amount", item.get("current")))
                if amount is None:
                    continue
                if is_ammo_snapshot_item(item):
                    item_name = logistics_item_name(item)
                    if item_name:
                        ammo[item_name] = ammo.get(item_name, 0.0) + amount
                elif is_fuel_snapshot_item(item):
                    fuel_name = logistics_fuel_name(item)
                    if fuel_name:
                        fuel[fuel_name] = fuel.get(fuel_name, 0.0) + amount

    production = logistics_production_from_grid_snapshot(grid_snapshot)
    snapshot: dict[str, Any] = {}
    if has_cargo:
        snapshot["cargo"] = {"used_volume": cargo_used, "max_volume": cargo_max}
    if ammo:
        snapshot["ammo"] = [
            {"name": name, "current": ammo[name], "minimum": None}
            for name in sorted(ammo)
        ]
    if fuel:
        snapshot["fuel"] = {
            name: {"current": fuel[name], "minimum": None}
            for name in sorted(fuel)
        }
    if production:
        snapshot["production"] = production
    return snapshot


def logistics_production_from_grid_snapshot(grid_snapshot: dict[str, Any]) -> dict[str, Any]:
    queue: list[dict[str, Any]] = []
    blockers: list[Any] = []
    blocks = grid_snapshot.get("blocks") if isinstance(grid_snapshot.get("blocks"), list) else []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_queue = block.get("production_queue") if isinstance(block.get("production_queue"), list) else []
        for item in block_queue:
            if not isinstance(item, dict):
                continue
            queued: dict[str, Any] = {}
            item_name = first_text(item, "item", "name", "subtype_id", "blueprint_id")
            if item_name:
                queued["item"] = item_name
            remaining = item.get("remaining", item.get("amount"))
            if remaining is not None:
                queued["remaining"] = json_scalar(remaining)
            if queued:
                queue.append(queued)
        block_blockers = block.get("production_blockers", block.get("blockers"))
        if isinstance(block_blockers, list):
            blockers.extend(json_scalar(item) for item in block_blockers)
    if not queue and not blockers:
        return {}
    return {"queue": queue, "blockers": blockers}


def logistics_item_name(item: dict[str, Any]) -> str:
    return first_text(item, "subtype_id", "name", "type_id", "item")


def logistics_fuel_name(item: dict[str, Any]) -> str:
    subtype = first_text(item, "subtype_id", "name")
    lower = subtype.lower()
    if lower in FUEL_SUBTYPE_KEYS:
        return lower
    if "hydrogen" in lower:
        return "hydrogen"
    if "oxygen" in lower:
        return "oxygen"
    return lower


def is_ammo_snapshot_item(item: dict[str, Any]) -> bool:
    type_id = str(item.get("type_id", "")).lower()
    subtype = str(item.get("subtype_id", "")).lower()
    return "ammo" in type_id or "ammo" in subtype


def is_fuel_snapshot_item(item: dict[str, Any]) -> bool:
    type_id = str(item.get("type_id", "")).lower()
    subtype = str(item.get("subtype_id", item.get("name", ""))).lower()
    return (
        subtype in FUEL_SUBTYPE_KEYS
        or "gascontainerobject" in type_id
        or "hydrogen" in subtype
        or "oxygen" in subtype
    )


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def attach_airlock_snapshot_from_grid_snapshot(request: dict[str, Any]) -> None:
    for key in ("airlock_snapshot", "door_snapshot", "ship_doors"):
        snapshot = request.get(key)
        if isinstance(snapshot, dict) and airlock_snapshot_is_ready(snapshot):
            request["airlock_snapshot"] = snapshot
            return

    grid_snapshot = request.get("grid_snapshot") if isinstance(request.get("grid_snapshot"), dict) else {}
    snapshot = airlock_snapshot_from_grid_snapshot(grid_snapshot)
    if snapshot:
        request["airlock_snapshot"] = snapshot
        return
    for key in AIRLOCK_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_environment_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in ENVIRONMENT_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_navigation_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in NAVIGATION_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_maintenance_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in MAINTENANCE_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_mining_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in MINING_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_alerts_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in ALERTS_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_readiness_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in READINESS_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_capabilities_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in CAPABILITIES_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_snapshot_aliases(request: dict[str, Any], keys: tuple[str, ...], preserve: tuple[str, ...] = ()) -> None:
    for key in keys:
        if key not in preserve:
            request.pop(key, None)


def remove_telemetry_quality_only_snapshot_aliases(request: dict[str, Any]) -> None:
    remove_snapshot_aliases(request, TELEMETRY_QUALITY_SNAPSHOT_KEYS)


def remove_automation_only_snapshot_aliases(request: dict[str, Any]) -> None:
    remove_snapshot_aliases(request, AUTOMATION_SNAPSHOT_KEYS)


def remove_config_drift_only_snapshot_aliases(request: dict[str, Any], preserve: tuple[str, ...] = ()) -> None:
    remove_snapshot_aliases(request, CONFIG_DRIFT_SNAPSHOT_KEYS, preserve)


def attach_config_drift_host_snapshots(request: dict[str, Any], root: Path) -> None:
    ship_registry = json_file_snapshot(root / "data" / "sos_ships.json")
    if ship_registry and not isinstance(request.get("ship_registry_snapshot"), dict):
        request["ship_registry_snapshot"] = ship_registry
    if ship_registry and not isinstance(request.get("registry_snapshot"), dict):
        request["registry_snapshot"] = ship_registry

    host_manifest = json_file_snapshot(root / "worker" / "manifest.json")
    if host_manifest and not isinstance(request.get("host_manifest_snapshot"), dict):
        request["host_manifest_snapshot"] = host_manifest

    script_instances = json_file_snapshot(root / "data" / "script_instances.json")
    if script_instances and not isinstance(request.get("script_instances_snapshot"), dict):
        request["script_instances_snapshot"] = script_instances


def json_file_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def remove_topology_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in TOPOLOGY_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_redundancy_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in REDUNDANCY_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_guidance_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in GUIDANCE_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_diagnostics_only_snapshot_aliases(request: dict[str, Any], preserve: tuple[str, ...] = ()) -> None:
    remove_snapshot_aliases(request, DIAGNOSTICS_SNAPSHOT_KEYS, preserve)


def remove_watch_log_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in WATCH_LOG_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_mission_profile_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in MISSION_PROFILE_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_endurance_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in ENDURANCE_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_runbook_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in RUNBOOK_SNAPSHOT_KEYS:
        request.pop(key, None)


def remove_display_only_snapshot_aliases(request: dict[str, Any]) -> None:
    for key in DISPLAY_SNAPSHOT_KEYS:
        request.pop(key, None)


def airlock_snapshot_is_ready(snapshot: dict[str, Any]) -> bool:
    return any(snapshot.get(key) not in (None, "", [], {}) for key in AIRLOCK_READY_KEYS)


def airlock_snapshot_from_grid_snapshot(grid_snapshot: dict[str, Any]) -> dict[str, Any]:
    blocks = grid_snapshot.get("blocks") if isinstance(grid_snapshot.get("blocks"), list) else []
    doors = [door for door in (normalized_airlock_door(block) for block in blocks) if door]
    vents = [vent for vent in (normalized_airlock_vent(block) for block in blocks) if vent]
    airlocks_payload = grid_snapshot.get("airlocks", grid_snapshot.get("airlock_groups"))
    airlocks = [
        airlock for airlock in (normalized_airlock_group(item) for item in airlocks_payload)
        if airlock
    ] if isinstance(airlocks_payload, list) else []
    compartments_payload = grid_snapshot.get("compartments") if isinstance(grid_snapshot.get("compartments"), list) else []
    compartments = [
        compartment for compartment in (normalized_airlock_compartment(item) for item in compartments_payload)
        if compartment
    ]
    snapshot: dict[str, Any] = {}
    if doors:
        snapshot["doors"] = doors
    if airlocks:
        snapshot["airlocks"] = airlocks
    if vents:
        snapshot["vents"] = vents
    if compartments:
        snapshot["compartments"] = compartments
    return snapshot


def normalized_airlock_door(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict) or not looks_like_airlock_door(block):
        return {}
    normalized: dict[str, Any] = {}
    entity_id = block.get("entity_id")
    if entity_id is not None:
        normalized["entity_id"] = json_scalar(entity_id)
    name = first_text(block, "name", "custom_name", "display_name")
    if name:
        normalized["name"] = name
    opened = bool_or_none(block.get("is_open", block.get("door_open", block.get("open", block.get("opened")))))
    if opened is None:
        ratio = float_or_none(block.get("door_open_ratio", block.get("open_ratio")))
        if ratio is not None:
            opened = ratio > 0.0
    if opened is None:
        opened = bool_or_none(block.get("door_status", block.get("status", block.get("state"))))
    if opened is not None:
        normalized["is_open"] = opened
    is_exterior = bool_or_none(block.get("is_exterior", block.get("exterior")))
    if is_exterior is not None:
        normalized["is_exterior"] = is_exterior
    add_bool_if_present(normalized, block, "functional", "functional")
    add_bool_if_present(normalized, block, "enabled", "enabled")
    ratio = integrity_ratio_from_payload(block)
    if ratio is not None:
        normalized["integrity_ratio"] = ratio
    airlock_id = first_text(block, "airlock_id", "airlock")
    if airlock_id:
        normalized["airlock_id"] = airlock_id
    return normalized


def normalized_airlock_vent(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict) or not looks_like_airlock_vent(block):
        return {}
    normalized: dict[str, Any] = {}
    vent_entity_id = block.get("vent_entity_id", block.get("entity_id"))
    if vent_entity_id is not None:
        normalized["vent_entity_id"] = json_scalar(vent_entity_id)
    name = first_text(block, "name", "custom_name", "display_name")
    if name:
        normalized["name"] = name
    compartment_id = first_text(block, "compartment_id", "compartment")
    if compartment_id:
        normalized["compartment_id"] = compartment_id
    compartment_name = first_text(block, "compartment_name", "compartment", "room")
    if compartment_name:
        normalized["compartment_name"] = compartment_name
    add_float_if_present(normalized, block, "oxygen_level", "oxygen_level", "oxygen_ratio", "oxygen")
    add_float_if_present(normalized, block, "pressure_ratio", "pressure_ratio", "pressure")
    add_bool_if_present(normalized, block, "pressurized", "pressurized")
    add_bool_if_present(normalized, block, "depressurized", "depressurized")
    add_bool_if_present(normalized, block, "functional", "functional")
    add_bool_if_present(normalized, block, "enabled", "enabled")
    ratio = integrity_ratio_from_payload(block)
    if ratio is not None:
        normalized["integrity_ratio"] = ratio
    return normalized


def normalized_airlock_group(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in ("airlock_id", "name", "inner_door_id", "outer_door_id"):
        value = item.get(key)
        if value is not None and value != "":
            normalized[key] = json_scalar(value)
    for key in ("inner_door_open", "outer_door_open", "safe", "pressurized"):
        value = bool_or_none(item.get(key))
        if value is not None:
            normalized[key] = value
    return normalized


def normalized_airlock_compartment(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in ("compartment_id", "compartment_name", "name"):
        value = item.get(key)
        if value is not None and value != "":
            normalized[key] = json_scalar(value)
    add_float_if_present(normalized, item, "oxygen_level", "oxygen_level", "oxygen_ratio", "oxygen")
    add_float_if_present(normalized, item, "pressure_ratio", "pressure_ratio", "pressure")
    add_bool_if_present(normalized, item, "pressurized", "pressurized")
    add_bool_if_present(normalized, item, "depressurized", "depressurized")
    return normalized


def looks_like_airlock_door(block: dict[str, Any]) -> bool:
    type_key = " ".join(first_text(block, key) for key in ("type", "subtype", "name", "custom_name")).lower()
    return (
        bool(block.get("is_door") or block.get("is_hangar_door"))
        or "door" in type_key
        or any(key in block for key in ("door_status", "door_open_ratio", "door_open", "is_open", "open", "opened"))
    )


def looks_like_airlock_vent(block: dict[str, Any]) -> bool:
    type_key = " ".join(first_text(block, key) for key in ("type", "subtype", "name", "custom_name")).lower()
    return (
        bool(block.get("is_air_vent") or block.get("is_vent"))
        or "airvent" in type_key
        or "air vent" in type_key
        or any(key in block for key in ("oxygen_level", "oxygen_ratio", "pressure_ratio", "pressurized", "depressurized"))
    )


def add_bool_if_present(target: dict[str, Any], source: dict[str, Any], target_key: str, *source_keys: str) -> None:
    for key in source_keys:
        if key in source:
            value = bool_or_none(source.get(key))
            if value is not None:
                target[target_key] = value
                return


def add_float_if_present(target: dict[str, Any], source: dict[str, Any], target_key: str, *source_keys: str) -> None:
    for key in source_keys:
        if key in source:
            value = float_or_none(source.get(key))
            if value is not None:
                target[target_key] = value
                return


def integrity_ratio_from_payload(payload: dict[str, Any]) -> float | None:
    ratio = float_or_none(payload.get("integrity_ratio"))
    if ratio is not None:
        return ratio
    integrity = float_or_none(payload.get("integrity", payload.get("current_integrity")))
    max_integrity = float_or_none(payload.get("max_integrity", payload.get("maximum_integrity")))
    if integrity is None or max_integrity is None or max_integrity <= 0:
        return None
    ratio = integrity / max_integrity
    return max(0.0, min(1.0, ratio))


def bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on", "open", "opened"}:
        return True
    if text in {"false", "0", "no", "off", "closed", "close", "shut"}:
        return False
    return None


def first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def json_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def component_name_from_blueprint_id(blueprint_id: str) -> str:
    suffix = str(blueprint_id).split("/")[-1].strip()
    if suffix.endswith("Component") and len(suffix) > len("Component"):
        suffix = suffix[: -len("Component")]
    if suffix.endswith("Blueprint") and len(suffix) > len("Blueprint"):
        suffix = suffix[: -len("Blueprint")]
    return suffix


def normalize_component_key(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def result_for(request: dict[str, Any], status: str, result: Any = None, error_bucket: str = "none") -> dict[str, Any]:
    payload = {
        "schema": SCHEMA,
        "message_kind": "result",
        "bridge_id": str(request.get("bridge_id", "")),
        "sequence": int(request.get("sequence", 0) or 0),
        "script_id": str(request.get("script_id", "")),
        "status": status,
        "result": result if result is not None else {},
        "error_bucket": error_bucket,
        "completed_at": utc_now(),
    }
    if isinstance(request.get("runtime_telemetry"), dict):
        payload["runtime_telemetry"] = request["runtime_telemetry"]
        payload["limiter_state"] = str(request["runtime_telemetry"].get("limiter_state", "unknown"))
    return payload


def compact_result_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
    changed = False

    def truncated_string(value: str, max_chars: int) -> str:
        nonlocal changed
        if len(value) <= max_chars:
            return value
        changed = True
        omitted = len(value) - max_chars
        return f"{value[:max_chars]}... [truncated {omitted} chars]"

    def compact(value: Any, depth: int = 0) -> Any:
        nonlocal changed
        if depth > RESULT_STORAGE_MAX_DEPTH:
            changed = True
            return {"truncated_depth": True}
        if isinstance(value, str):
            return truncated_string(value, RESULT_STORAGE_MAX_STRING_CHARS)
        if isinstance(value, list):
            kept = [compact(item, depth + 1) for item in value[:RESULT_STORAGE_MAX_LIST_ITEMS]]
            if len(value) > RESULT_STORAGE_MAX_LIST_ITEMS:
                changed = True
                kept.append({"truncated_count": len(value) - RESULT_STORAGE_MAX_LIST_ITEMS})
            return kept
        if isinstance(value, dict):
            if isinstance(value.get("kind"), str) and isinstance(value.get("text"), str):
                return {
                    key: truncated_string(item, RESULT_STORAGE_MAX_COMMAND_TEXT_CHARS) if key == "text" else compact(item, depth + 1)
                    for key, item in value.items()
                }
            compacted_dict: dict[str, Any] = {}
            for key, item in value.items():
                if key == "commands" and isinstance(item, list):
                    kept = [compact(command, depth + 1) for command in item[:RESULT_STORAGE_MAX_COMMAND_ITEMS]]
                    if len(item) > RESULT_STORAGE_MAX_COMMAND_ITEMS:
                        changed = True
                        kept.append({"truncated_count": len(item) - RESULT_STORAGE_MAX_COMMAND_ITEMS})
                    compacted_dict[key] = kept
                else:
                    compacted_dict[key] = compact(item, depth + 1)
            return compacted_dict
        return value

    compacted = compact(payload)
    if isinstance(compacted, dict) and compacted_storage_size(compacted) >= RESULT_STORAGE_MAX_BYTES:
        compacted = compact_oversized_sos_result_for_storage(compacted)
        changed = True
    if changed and isinstance(compacted, dict):
        result = compacted.get("result")
        if isinstance(result, dict):
            result["storage_compacted"] = True
        else:
            compacted["storage_compacted"] = True
    return compacted


def compacted_storage_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":")))


def compact_oversized_sos_result_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return payload
    compacted = dict(payload)
    result = dict(result)
    compacted["result"] = result

    dashboard = result.get("sos_dashboard")
    if isinstance(dashboard, dict):
        result["sos_dashboard"] = compact_sos_payload_for_storage("sos_dashboard", dashboard)

    children = result.get("child_results")
    if isinstance(children, list):
        compact_children = []
        for child in children[:RESULT_STORAGE_MAX_LIST_ITEMS]:
            if not isinstance(child, dict):
                continue
            item: dict[str, Any] = {}
            for field in ("script_id", "status", "error_bucket", "command_queue"):
                if field in child:
                    item[field] = child[field]
            if "summary" in child:
                item["summary"] = compact_storage_text(str(child.get("summary", "") or ""))
            child_result = child.get("result")
            if isinstance(child_result, dict):
                history = {
                    key: compact_sos_payload_for_storage(key, value)
                    for key, value in child_result.items()
                    if key.startswith("sos_") and isinstance(value, dict)
                }
                if history:
                    item["result"] = history
            compact_children.append(item)
        if len(children) > RESULT_STORAGE_MAX_LIST_ITEMS:
            compact_children.append({"truncated_count": len(children) - RESULT_STORAGE_MAX_LIST_ITEMS})
        result["child_results"] = compact_children
    return compacted


def compact_sos_payload_for_storage(key: str, value: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    if key == "sos_dashboard":
        for field in ("mode", "posture"):
            if field in value:
                compacted[field] = value[field]
        for service_id, payload in value.items():
            if not isinstance(payload, dict) or service_id in {"identity", "service_health", "queue_pressure", "mode_effects"}:
                continue
            item = compact_sos_payload_for_storage(f"sos_{service_id}", payload)
            if item:
                compacted[service_id] = item
        return compacted

    for field in (
        "state",
        "snapshot_status",
        "mode",
        "identity_status",
        "confidence_label",
        "queue_pressure_state",
        "declared_role",
        "observed_role",
        "role_match",
    ):
        if field in value:
            compacted[field] = value[field]
    if "summary" in value:
        compacted["summary"] = compact_storage_text(str(value.get("summary", "") or ""))
    for field, item in value.items():
        if field.endswith("_count") and isinstance(item, (int, float, str)):
            compacted[field] = item
    for field in ("warnings", "blockers"):
        items = compact_storage_list(value.get(field), RESULT_STORAGE_COMPACT_WARNING_ITEMS)
        if items:
            compacted[field] = items
    sources = compact_storage_list(value.get("source_services"), RESULT_STORAGE_COMPACT_SOURCE_ITEMS)
    if sources:
        compacted["source_services"] = sources
    return compacted


def compact_storage_list(source: Any, max_items: int) -> list[Any]:
    if not isinstance(source, list):
        return []
    items = [compact_storage_text(str(item)) if not isinstance(item, dict) else item for item in source[:max_items]]
    if len(source) > max_items:
        items.append({"truncated_count": len(source) - max_items})
    return items


def compact_storage_text(value: str) -> str:
    if len(value) <= RESULT_STORAGE_COMPACT_TEXT_CHARS:
        return value
    omitted = len(value) - RESULT_STORAGE_COMPACT_TEXT_CHARS
    return f"{value[:RESULT_STORAGE_COMPACT_TEXT_CHARS]}... [truncated {omitted} chars]"


def request_requested_at(request: dict[str, Any]) -> datetime | None:
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    return parse_utc_timestamp(state.get("requested_at_utc"))


def request_is_stale(request: dict[str, Any], stale_seconds: int | None = None) -> bool:
    requested_at = request_requested_at(request)
    if requested_at is None:
        return False
    max_age = stale_seconds if stale_seconds is not None else stale_seconds_from_env()
    age = datetime.now(timezone.utc) - requested_at
    return age.total_seconds() > max_age


def stale_request_result(request: dict[str, Any]) -> dict[str, Any]:
    return result_for(
        request,
        "stale_held",
        {
            "summary": "Bridge request was held because its PB snapshot is stale. Commands will resume after a fresh heartbeat.",
            "commands": [],
            "bridge_health": {
                "status": "concealed_suspected",
                "queue_policy": "hold_until_fresh_heartbeat",
            },
        },
        "stale_request_held",
    )


def command_queue_dir(root: Path) -> Path:
    return root / "data" / "command_queues"


def command_queue_path(root: Path, bridge_id: str) -> Path:
    return command_queue_dir(root) / f"{safe_file_name(bridge_id)}.json"


def load_command_queue(root: Path, bridge_id: str, script_id: str) -> dict[str, Any]:
    path = command_queue_path(root, bridge_id)
    if not path.exists():
        return new_command_queue(bridge_id, script_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return new_command_queue(bridge_id, script_id)
    if payload.get("schema") != COMMAND_QUEUE_SCHEMA or payload.get("bridge_id") != bridge_id or payload.get("script_id") != script_id:
        return new_command_queue(bridge_id, script_id)
    if not isinstance(payload.get("entries"), list):
        payload["entries"] = []
    if not isinstance(payload.get("in_flight"), list):
        payload["in_flight"] = []
    if not isinstance(payload.get("delivered"), dict):
        payload["delivered"] = {}
    normalize_command_queue(payload)
    return payload


def new_command_queue(bridge_id: str, script_id: str) -> dict[str, Any]:
    return {
        "schema": COMMAND_QUEUE_SCHEMA,
        "bridge_id": bridge_id,
        "script_id": script_id,
        "updated_at": utc_now(),
        "entries": [],
        "in_flight": [],
        "delivered": {},
        "last_emitted_sequence": 0,
    }


def save_command_queue(root: Path, bridge_id: str, queue: dict[str, Any]) -> None:
    directory = command_queue_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    queue["updated_at"] = utc_now()
    command_queue_path(root, bridge_id).write_text(json.dumps(queue, indent=2), encoding="utf-8")


def apply_command_queue(root: Path, request: dict[str, Any], adapter_output: dict[str, Any]) -> dict[str, Any]:
    commands = adapter_output.get("commands")
    if not isinstance(commands, list):
        return adapter_output
    if adapter_output.get("apply_mode") == "dry_run":
        return adapter_output

    bridge_id = str(request.get("bridge_id", ""))
    script_id = str(request.get("script_id", ""))
    sequence = int(request.get("sequence", 0) or 0)
    if not bridge_id or not script_id or sequence <= 0:
        return adapter_output

    queue = load_command_queue(root, bridge_id, script_id)
    acknowledge_command_queue(queue, request)
    prune_managed_machine_transfers(queue, request)

    passthrough = [command for command in commands if isinstance(command, dict) and command.get("kind") == "echo"]
    planned = [command for command in commands if isinstance(command, dict) and command.get("kind") != "echo"]
    enqueue_planned_commands(queue, planned, sequence, lcd_command_queue_cooldown(request))
    prune_stale_commands(queue, sequence)
    sort_command_queue(queue, sequence, lcd_command_queue_max_wait(request))

    drain_count = command_queue_drain_count(request, adapter_output)
    entries = queue.get("entries", []) if isinstance(queue.get("entries"), list) else []
    drained_entries = reserve_text_surface_refresh_in_drain(entries, drain_count)
    drained_commands = [command_for_sequence(entry.get("command", {}), request, index + 1) for index, entry in enumerate(drained_entries)]
    by_source = command_queue_stats_by_source(entries, drained_entries, script_id)

    queue["in_flight"] = [{"key": entry.get("key"), "command": command} for entry, command in zip(drained_entries, drained_commands)]
    queue["last_emitted_sequence"] = sequence
    save_command_queue(root, bridge_id, queue)

    adapter_output = dict(adapter_output)
    adapter_output["commands"] = passthrough + drained_commands
    adapter_output["remaining_commands"] = max(0, len(queue.get("entries", [])) - len(drained_entries))
    adapter_output["queued_commands"] = len(queue.get("entries", []))
    adapter_output["drained_commands"] = len(drained_commands)
    adapter_output["command_queue"] = {
        "state": "active",
        "queued": len(queue.get("entries", [])),
        "drained": len(drained_commands),
        "remaining": adapter_output["remaining_commands"],
        "by_source": by_source,
    }
    return adapter_output


def reserve_text_surface_refresh_in_drain(entries: list[dict[str, Any]], drain_count: int) -> list[dict[str, Any]]:
    selected = entries[:drain_count]
    if drain_count <= 1 or not selected:
        return selected
    if any(entry_command_kind(entry) == "write_text_surface" for entry in selected):
        return selected
    refresh = next((entry for entry in entries[drain_count:] if entry_command_kind(entry) == "write_text_surface"), None)
    if refresh is None:
        return selected
    return [*selected[:-1], refresh]


def entry_command_kind(entry: dict[str, Any]) -> str:
    command = entry.get("command") if isinstance(entry.get("command"), dict) else {}
    return str(command.get("kind", ""))


def command_source_id(entry: dict[str, Any], fallback_script_id: str) -> str:
    command = entry.get("command") if isinstance(entry.get("command"), dict) else {}
    source_id = str(command.get("source_script_id", "") or "").strip()
    return source_id or fallback_script_id


def command_queue_stats_by_source(
    entries: list[dict[str, Any]],
    drained_entries: list[dict[str, Any]],
    fallback_script_id: str,
) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}

    def ensure(source_id: str) -> dict[str, int]:
        return stats.setdefault(source_id, {"queued": 0, "drained": 0, "remaining": 0})

    drained_keys = {str(entry.get("key", "")) for entry in drained_entries if isinstance(entry, dict)}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id = command_source_id(entry, fallback_script_id)
        row = ensure(source_id)
        row["queued"] += 1
        if str(entry.get("key", "")) in drained_keys:
            row["drained"] += 1
        else:
            row["remaining"] += 1
    return stats


def acknowledge_command_queue(queue: dict[str, Any], request: dict[str, Any]) -> None:
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    last_apply = state.get("last_apply") if isinstance(state.get("last_apply"), dict) else {}
    applied_sequence = int(last_apply.get("sequence", -1) or -1)
    if applied_sequence != int(queue.get("last_emitted_sequence", 0) or 0):
        return
    in_flight = queue.get("in_flight") if isinstance(queue.get("in_flight"), list) else []
    if not in_flight:
        return
    applied = max(0, int(last_apply.get("applied", 0) or 0))
    skipped = max(0, int(last_apply.get("skipped", 0) or 0))
    ack_count = applied
    if ack_count == 0 and skipped > 0:
        ack_count = 1
    ack_count = min(max(ack_count, 0), len(in_flight))
    if ack_count <= 0:
        return
    acknowledged = {str(item.get("key", "")) for item in in_flight[:ack_count] if item.get("key")}
    delivered = queue.get("delivered") if isinstance(queue.get("delivered"), dict) else {}
    for key in acknowledged:
        delivered[key] = applied_sequence
    queue["delivered"] = delivered
    queue["entries"] = [entry for entry in queue.get("entries", []) if str(entry.get("key", "")) not in acknowledged]
    queue["in_flight"] = in_flight[ack_count:]


def prune_managed_machine_transfers(queue: dict[str, Any], request: dict[str, Any]) -> None:
    blocked_entities = managed_machine_entity_ids(request)
    if not blocked_entities:
        return
    kept = []
    blocked_in_flight = set()
    for entry in queue.get("entries", []) if isinstance(queue.get("entries"), list) else []:
        command = entry.get("command") if isinstance(entry.get("command"), dict) else {}
        if (
            str(command.get("kind", "")) == "transfer_item"
            and (
                int(command.get("source_entity_id", 0) or 0) in blocked_entities
                or int(command.get("destination_entity_id", 0) or 0) in blocked_entities
            )
        ):
            blocked_in_flight.add(str(entry.get("key", "")))
            continue
        kept.append(entry)
    queue["entries"] = kept
    queue["in_flight"] = [
        entry
        for entry in queue.get("in_flight", []) if isinstance(queue.get("in_flight"), list)
        if str(entry.get("key", "")) not in blocked_in_flight
    ]


def managed_machine_entity_ids(request: dict[str, Any]) -> set[int]:
    snapshot = request.get("inventory_snapshot") if isinstance(request.get("inventory_snapshot"), dict) else {}
    blocks = snapshot.get("blocks") if isinstance(snapshot.get("blocks"), list) else []
    blocked: set[int] = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = (str(block.get("type", "")) + " " + str(block.get("subtype", ""))).lower()
        if any(marker in block_type for marker in ("myreactor", "mygasgenerator", "myassembler", "myrefinery")):
            try:
                blocked.add(int(block.get("entity_id", 0) or 0))
            except (TypeError, ValueError):
                continue
    blocked.discard(0)
    return blocked


def enqueue_planned_commands(queue: dict[str, Any], commands: list[dict[str, Any]], sequence: int, lcd_cooldown_sequences: int) -> None:
    entries = queue.get("entries") if isinstance(queue.get("entries"), list) else []
    by_key = {str(entry.get("key", "")): entry for entry in entries if entry.get("key")}
    delivered = queue.get("delivered") if isinstance(queue.get("delivered"), dict) else {}
    for command in commands:
        key = command_queue_key(command)
        if not key:
            continue
        stored_command = {key_name: value for key_name, value in command.items() if key_name != "command_id"}
        entry = by_key.get(key)
        if entry is None:
            if is_lcd_write_on_cooldown(stored_command, key, delivered, sequence, lcd_cooldown_sequences):
                continue
            entry = {
                "key": key,
                "command": stored_command,
                "first_seen_sequence": sequence,
                "last_seen_sequence": sequence,
                "attempts": 0,
            }
            entries.append(entry)
            by_key[key] = entry
        else:
            entry["command"] = stored_command
            entry["last_seen_sequence"] = sequence
    queue["entries"] = entries


def is_lcd_write_on_cooldown(
    command: dict[str, Any],
    key: str,
    delivered: dict[str, Any],
    sequence: int,
    cooldown_sequences: int,
) -> bool:
    if str(command.get("kind", "")) != "write_text_surface" or cooldown_sequences <= 0:
        return False
    try:
        delivered_sequence = int(delivered.get(key, 0) or 0)
    except (TypeError, ValueError):
        return False
    return delivered_sequence > 0 and sequence - delivered_sequence < cooldown_sequences


def prune_stale_commands(queue: dict[str, Any], sequence: int) -> None:
    kept = []
    for entry in queue.get("entries", []):
        command = entry.get("command") if isinstance(entry.get("command"), dict) else {}
        kind = str(command.get("kind", ""))
        last_seen = int(entry.get("last_seen_sequence", sequence) or sequence)
        if command_expired(command, entry, sequence):
            continue
        if kind in VOLATILE_COMMAND_KINDS and sequence - last_seen > 20:
            continue
        kept.append(entry)
    queue["entries"] = kept[:250]
    delivered = queue.get("delivered") if isinstance(queue.get("delivered"), dict) else {}
    queue["delivered"] = {
        key: value
        for key, value in delivered.items()
        if isinstance(key, str) and isinstance(value, (int, float)) and sequence - int(value) <= 100
    }


def command_expired(command: dict[str, Any], entry: dict[str, Any], sequence: int) -> bool:
    try:
        expiry_sequence = int(command.get("expiry_sequence", 0) or 0)
    except (TypeError, ValueError):
        expiry_sequence = 0
    if expiry_sequence > 0 and sequence > expiry_sequence:
        return True
    try:
        expires_after = int(command.get("expires_after_sequences", 0) or 0)
    except (TypeError, ValueError):
        expires_after = 0
    if expires_after <= 0:
        return False
    first_seen = int(entry.get("first_seen_sequence", sequence) or sequence)
    return sequence - first_seen > expires_after


def command_queue_drain_count(request: dict[str, Any], adapter_output: dict[str, Any]) -> int:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    configured = config.get("commandQueueDrainPerResult", config.get("commandQueueDrainCommands", 1))
    try:
        drain_count = int(configured)
    except (TypeError, ValueError):
        drain_count = 1
    dynamic_enabled = bool_config_value(config.get("dynamicCommandQueueDrain"), True)
    telemetry = request.get("runtime_telemetry") if isinstance(request.get("runtime_telemetry"), dict) else {}
    if dynamic_enabled and bool_config_value(telemetry.get("dynamic_apply_commands"), True):
        telemetry_budget = telemetry.get("dynamic_apply_budget")
        try:
            drain_count = int(telemetry_budget)
        except (TypeError, ValueError):
            pass
    max_apply = adapter_output.get("max_apply_commands", 1)
    try:
        max_apply_count = int(max_apply)
    except (TypeError, ValueError):
        max_apply_count = 1
    return max(0, min(max(drain_count, 0), max(max_apply_count, 1)))


def bool_config_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def lcd_command_queue_cooldown(request: dict[str, Any]) -> int:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    configured = config.get("lcdCommandQueueCooldownSequences", DEFAULT_LCD_QUEUE_COOLDOWN_SEQUENCES)
    try:
        return max(0, int(configured))
    except (TypeError, ValueError):
        return DEFAULT_LCD_QUEUE_COOLDOWN_SEQUENCES


def lcd_command_queue_max_wait(request: dict[str, Any]) -> int:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    configured = config.get("lcdCommandQueueMaxWaitSequences", 8)
    try:
        return max(0, int(configured))
    except (TypeError, ValueError):
        return 8


def normalize_command_queue(queue: dict[str, Any]) -> None:
    normalized: dict[str, dict[str, Any]] = {}
    for entry in queue.get("entries", []) if isinstance(queue.get("entries"), list) else []:
        command = entry.get("command") if isinstance(entry, dict) and isinstance(entry.get("command"), dict) else {}
        key = command_queue_key(command)
        if not key:
            continue
        existing = normalized.get(key)
        if existing is None:
            entry = dict(entry)
            entry["key"] = key
            normalized[key] = entry
            continue
        if int(entry.get("last_seen_sequence", 0) or 0) >= int(existing.get("last_seen_sequence", 0) or 0):
            existing["command"] = command
            existing["last_seen_sequence"] = entry.get("last_seen_sequence", existing.get("last_seen_sequence", 0))
        existing["first_seen_sequence"] = min(
            int(existing.get("first_seen_sequence", 0) or 0),
            int(entry.get("first_seen_sequence", 0) or 0),
        )
    queue["entries"] = list(normalized.values())
    sort_command_queue(queue)


def sort_command_queue(queue: dict[str, Any], sequence: int | None = None, lcd_max_wait_sequences: int | None = None) -> None:
    entries = queue.get("entries") if isinstance(queue.get("entries"), list) else []
    queue["entries"] = sorted(
        entries,
        key=lambda entry: (
            source_priority(entry.get("command") if isinstance(entry.get("command"), dict) else {}),
            effective_command_priority(entry, sequence, lcd_max_wait_sequences),
            int(entry.get("first_seen_sequence", 0) or 0),
            str(entry.get("key", "")),
        ),
    )


def effective_command_priority(entry: dict[str, Any], sequence: int | None = None, lcd_max_wait_sequences: int | None = None) -> int:
    command = entry.get("command") if isinstance(entry.get("command"), dict) else {}
    priority = command_priority(command)
    if (
        str(command.get("kind", "")) == "write_text_surface"
        and sequence is not None
        and lcd_max_wait_sequences is not None
        and lcd_max_wait_sequences > 0
    ):
        first_seen = int(entry.get("first_seen_sequence", sequence) or sequence)
        if sequence - first_seen >= lcd_max_wait_sequences:
            return min(priority, 5)
    return priority


def source_priority(command: dict[str, Any]) -> int:
    try:
        return int(command.get("source_priority", 50) or 50)
    except (TypeError, ValueError):
        return 50


def command_priority(command: dict[str, Any]) -> int:
    kind = str(command.get("kind", ""))
    if kind == "set_door_open":
        return 3
    if kind == "set_assembler_mode":
        return 4
    if kind == "transfer_item" and str(command.get("reason", "")) == "refinery_ore_rebalance":
        return 5
    if kind == "enqueue_assembler_blueprint" and str(command.get("reason", "")) == "autocrafting_goal":
        return 6
    if kind == "transfer_item" and str(command.get("reason", "")) == "autocrafting_material":
        return 7
    if kind == "transfer_item" and str(command.get("reason", "")) == "assembler_input_cleanup":
        return 8
    if kind == "move_assembler_queue_item" and str(command.get("reason", "")) == "assembler_queue_consolidation":
        return 9
    if kind == "transfer_item" and str(command.get("reason", "")) == "autocrafting_ore_refining":
        return 10
    if kind == "transfer_item" and str(command.get("reason", "")) == "refinery_output_cleanup":
        return 11
    if kind == "transfer_item" and str(command.get("reason", "")) == "assembler_output_cleanup":
        return 12
    if kind == "transfer_item" and str(command.get("reason", "")) == "refinery_input_unload":
        return 13
    if kind == "transfer_item" and str(command.get("reason", "")) == "inventory_sorting":
        return 14
    if kind == "write_block_custom_data":
        return 26
    if kind in {"set_use_conveyor", "set_block_enabled", "set_light_color", "set_assembler_cooperative_mode", "set_gas_auto_refill"}:
        return 15
    if kind == "transfer_item":
        subtype = str(command.get("item_subtype_id", "")).lower()
        type_id = str(command.get("item_type_id", "")).lower()
        if subtype == "uranium" and "ingot" in type_id:
            return 16
        if subtype == "ice" and str(command.get("reason", "")) == "gas_generator_topup":
            return 16
        if "ore" in type_id and str(command.get("reason", "")) in {"refinery_ore_input", "autocrafting_ore_refining"}:
            return 16
        if subtype == "ice":
            return 60
        if "ingot" in type_id:
            return 17
        return 45
    if kind == "write_text_surface":
        return 25
    if kind in {"enqueue_assembler_blueprint", "move_assembler_queue_item", "remove_assembler_queue_item", "clear_assembler_queue"}:
        return 30
    if kind == "rename_block":
        return 40
    return 100


def command_queue_key(command: dict[str, Any]) -> str:
    kind = str(command.get("kind", ""))
    if not kind or kind == "echo":
        return ""
    key_payload = {
        key: value
        for key, value in command.items()
        if key not in {"command_id", "source_priority", "source_order", "expiry_sequence", "expires_after_sequences"}
    }
    if kind == "write_text_surface":
        key_payload = {key: value for key, value in key_payload.items() if key not in {"text", "title"}}
    if kind == "transfer_item":
        key_payload = {key: value for key, value in key_payload.items() if key not in {"amount", "reason"}}
    if kind == "enqueue_assembler_blueprint":
        key_payload = {key: value for key, value in key_payload.items() if key not in {"amount"}}
    return json.dumps(key_payload, sort_keys=True, separators=(",", ":"))


def orchestrator_conflict_target(command: dict[str, Any]) -> str:
    kind = str(command.get("kind", ""))
    if not kind or kind == "echo":
        return ""
    if "block_entity_id" in command:
        block_id = str(command.get("block_entity_id", ""))
        if kind == "write_text_surface":
            return f"{kind}:{block_id}:{command.get('surface_index', 0)}"
        return f"{kind}:{block_id}"
    if kind in {"transfer_item"}:
        return (
            f"{kind}:{command.get('source_entity_id', '')}:{command.get('source_inventory_index', 0)}:"
            f"{command.get('destination_entity_id', '')}:{command.get('destination_inventory_index', 0)}:"
            f"{command.get('item_type_id', '')}:{command.get('item_subtype_id', '')}"
        )
    if kind in {"enqueue_assembler_blueprint", "move_assembler_queue_item", "remove_assembler_queue_item", "clear_assembler_queue"}:
        return f"{kind}:{command.get('assembler_entity_id', command.get('block_entity_id', ''))}"
    return command_queue_key(command)


def resolve_orchestrator_conflicts(commands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    kept_by_target: dict[str, dict[str, Any]] = {}
    conflicts_by_target: dict[str, dict[str, Any]] = {}
    for command in commands:
        target = orchestrator_conflict_target(command)
        if not target:
            kept.append(command)
            continue
        existing = kept_by_target.get(target)
        if existing is None:
            kept_by_target[target] = command
            kept.append(command)
            continue
        if command_queue_key(existing) == command_queue_key(command) and existing == command:
            continue
        conflict = conflicts_by_target.setdefault(
            target,
            {
                "target": target,
                "kind": str(command.get("kind", "")),
                "kept_source_script_id": str(existing.get("source_script_id", "")),
                "suppressed_source_script_ids": [],
            },
        )
        source_id = str(command.get("source_script_id", ""))
        if source_id and source_id not in conflict["suppressed_source_script_ids"]:
            conflict["suppressed_source_script_ids"].append(source_id)
    return kept, list(conflicts_by_target.values())


def command_for_sequence(command: dict[str, Any], request: dict[str, Any], index: int) -> dict[str, Any]:
    emitted = dict(command)
    emitted["command_id"] = f"{request.get('bridge_id', 'bridge')}:{request.get('sequence', 0)}:queue:{index}:{emitted.get('kind', 'command')}"
    return emitted


def safe_file_name(value: str) -> str:
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in value)
    return safe or "bridge"


def string_equals(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def validate_request(request: dict[str, Any]) -> str:
    if request.get("schema") != SCHEMA:
        return "schema_mismatch"
    if request.get("message_kind") != "request":
        return "message_kind_invalid"
    if not request.get("bridge_id"):
        return "bridge_id_missing"
    if not isinstance(request.get("sequence"), int) or request.get("sequence", 0) <= 0:
        return "sequence_invalid"
    if not request.get("script_id"):
        return "script_id_missing"
    return "none"


def sos_blocker_result(request: dict[str, Any], error_bucket: str, blockers: list[Any]) -> dict[str, Any]:
    normalized_blockers = [str(item) for item in blockers if str(item)]
    blocker_text = ", ".join(normalized_blockers) if normalized_blockers else error_bucket
    bridge_id = str(request.get("bridge_id", "bridge") or "bridge")
    sos_ship = request.get("sos_ship") if isinstance(request.get("sos_ship"), dict) else {}
    identity_status = str(sos_ship.get("identity_status", "blocked") or "blocked")
    output = {
        "summary": f"SOS {bridge_id} rejected: {blocker_text}",
        "commands": [{"kind": "echo", "text": f"SOS {bridge_id} rejected: {blocker_text}"}],
        "orchestrator": {"status": error_bucket},
        "child_results": [],
        "sos": {
            "ship_id": str(sos_ship.get("ship_id", "")),
            "display_name": str(sos_ship.get("display_name", "")),
            "mode": str(sos_ship.get("mode", "")),
            "identity_status": identity_status,
            "blockers": normalized_blockers,
            "warnings": sos_ship.get("warnings", []) if isinstance(sos_ship.get("warnings"), list) else [],
        },
    }
    return result_for(request, "rejected", output, error_bucket)


def execute_request(
    request: dict[str, Any],
    scripts: dict[str, WorkerScript],
    bridge_configs: dict[str, BridgeScriptConfig] | None = None,
    root: Path | None = None,
    apply_queue: bool = True,
) -> dict[str, Any]:
    validation = validate_request(request)
    if validation != "none":
        return result_for(request, "rejected", {}, validation)
    if request_is_stale(request):
        return stale_request_result(request)

    script_id = str(request["script_id"])
    if root is not None:
        bridge_configs = expand_sos_bridge_configs(root, bridge_configs or {}, bridge_config_factory=BridgeScriptConfig)
    bridge_config = (bridge_configs or {}).get(str(request["bridge_id"]))
    if bridge_config is not None and bridge_config.allowed_worker_scripts and script_id not in bridge_config.allowed_worker_scripts:
        return result_for(request, "rejected", {}, "script_not_allowed_for_bridge")

    script = scripts.get(script_id)
    if script is None:
        return result_for(request, "rejected", {}, "script_not_found")
    if not script.enabled:
        return result_for(request, "rejected", {}, "script_disabled")
    if script.instance_bridge_id and not string_equals(script.instance_bridge_id, str(request["bridge_id"])):
        return result_for(request, "rejected", {}, "script_instance_bridge_mismatch")
    if script_id == "bridge_orchestrator" or script.base_script_id == "bridge_orchestrator":
        if root is not None:
            sos_context = attach_sos_request_context(root, request)
            if sos_context.get("registry_errors"):
                return sos_blocker_result(request, "sos_registry_invalid", sos_context["registry_errors"])
            blockers = sos_context.get("blockers")
            if isinstance(blockers, list) and blockers:
                return sos_blocker_result(request, "sos_identity_blocked", blockers)
        return execute_orchestrator_request(request, scripts, bridge_configs or {}, bridge_config, root)

    try:
        active_root = root or Path(os.environ.get("NOVALI_CLIENT_SIDE_PB_ROOT", "."))
        request["worker_config"] = load_effective_worker_config(active_root, script)
        attach_virtual_pb_custom_data(request)
        if script.base_script_id:
            request["script_instance_id"] = script.script_id
            request["base_script_id"] = script.base_script_id
        if root is not None:
            request["autocrafting_blueprints"] = learn_autocrafting_blueprints(active_root, request)
        if script.runtime == "virtual_pb_csharp":
            from worker.virtual_pb import run_virtual_pb

            source_path = Path(script.source_path)
            if not source_path.is_absolute():
                source_path = active_root / source_path
            output = run_virtual_pb(source_path, request, active_root)
            if root is not None and isinstance(output, dict):
                compatibility = output.get("compatibility") if isinstance(output.get("compatibility"), dict) else {}
                save_virtual_pb_compatibility_report(active_root, script_id, compatibility, output)
        else:
            module = importlib.import_module(script.module)
            run = getattr(module, "run")
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run, request)
                output = future.result(timeout=max(script.timeout_ms, 1) / 1000.0)
        status = "ok"
        error_bucket = "none"
        if isinstance(output, dict):
            status = str(output.pop("adapter_status", output.pop("status_override", status)) or status)
            error_bucket = str(output.get("error_bucket", error_bucket) or error_bucket)
            if root is not None and apply_queue and status == "ok" and error_bucket == "none":
                output = apply_command_queue(root, request, output)
        return result_for(request, status, output, error_bucket)
    except TimeoutError:
        return result_for(request, "timeout", {}, "script_timeout")
    except Exception as exc:  # pragma: no cover - exact adapter exceptions are intentionally bucketed
        return result_for(request, "failed", {"exception_type": type(exc).__name__}, "script_exception")


def execute_orchestrator_request(
    request: dict[str, Any],
    scripts: dict[str, WorkerScript],
    bridge_configs: dict[str, BridgeScriptConfig],
    bridge_config: BridgeScriptConfig | None,
    root: Path | None,
) -> dict[str, Any]:
    child_configs = bridge_config.child_worker_scripts if bridge_config is not None else ()
    if not child_configs:
        return result_for(
            request,
            "rejected",
            {
                "summary": "bridge_orchestrator has no enabled child scripts",
                "commands": [{"kind": "echo", "text": "bridge_orchestrator rejected: no child scripts configured"}],
                "orchestrator": {"status": "no_children"},
                "child_results": [],
            },
            "orchestrator_no_children",
        )

    merged_commands: list[dict[str, Any]] = []
    child_results: list[dict[str, Any]] = []
    scheduler_fairness: list[dict[str, Any]] = []
    allowed = set(bridge_config.allowed_worker_scripts if bridge_config is not None else ())
    child_runtime_telemetry = enriched_child_runtime_telemetry(root, request, child_configs)
    for index, child_config in enumerate(child_configs):
        child_id = str(child_config.get("script_id", "")).strip()
        if not child_id or child_id == "bridge_orchestrator" or not bool(child_config.get("enabled", True)):
            continue
        if allowed and child_id not in allowed:
            child_results.append({"script_id": child_id, "status": "rejected", "error_bucket": "script_not_allowed_for_bridge"})
            continue
        child_request = dict(request)
        child_request["script_id"] = child_id
        child_request["parent_script_id"] = "bridge_orchestrator"
        child_request["runtime_telemetry"] = child_runtime_telemetry
        child_service_id = str(child_config.get("service_id", "") or "").strip().lower()
        is_environment_child = child_service_id == "environment" or "sos_environment" in child_id.lower()
        is_navigation_child = child_service_id == "navigation" or "sos_navigation" in child_id.lower() or "sos_nav" in child_id.lower()
        is_maintenance_child = (
            child_service_id == "maintenance"
            or "sos_maintenance" in child_id.lower()
            or "sos_repair" in child_id.lower()
            or "sos_damage_control" in child_id.lower()
            or "sos_projector" in child_id.lower()
        )
        is_mining_child = (
            child_service_id == "mining"
            or "sos_mining" in child_id.lower()
            or "sos_harvest" in child_id.lower()
            or "sos_resource" in child_id.lower()
            or "sos_ore" in child_id.lower()
        )
        is_alerts_child = (
            child_service_id == "alerts"
            or "sos_alerts" in child_id.lower()
            or "sos_alert" in child_id.lower()
            or "sos_notifications" in child_id.lower()
            or "sos_notify" in child_id.lower()
        )
        is_readiness_child = (
            child_service_id == "readiness"
            or "sos_readiness" in child_id.lower()
            or "sos_operator_readiness" in child_id.lower()
            or "sos_ship_readiness" in child_id.lower()
            or "sos_ops_readiness" in child_id.lower()
        )
        is_capabilities_child = (
            child_service_id == "capabilities"
            or "sos_capabilities" in child_id.lower()
            or "sos_capability_inventory" in child_id.lower()
            or "sos_ship_capabilities" in child_id.lower()
            or "sos_role_fit" in child_id.lower()
        )
        is_telemetry_quality_child = (
            child_service_id == "telemetry_quality"
            or "sos_telemetry_quality" in child_id.lower()
            or "sos_evidence_quality" in child_id.lower()
            or "sos_data_quality" in child_id.lower()
            or "sos_signal_quality" in child_id.lower()
        )
        is_automation_child = (
            child_service_id == "automation"
            or "sos_automation" in child_id.lower()
            or "sos_control_logic" in child_id.lower()
            or "sos_script_health" in child_id.lower()
            or "sos_programmable_block" in child_id.lower()
        )
        is_config_drift_child = (
            child_service_id == "config_drift"
            or "sos_config_drift" in child_id.lower()
            or "sos_configuration_drift" in child_id.lower()
            or "sos_contract_drift" in child_id.lower()
            or "sos_registry_drift" in child_id.lower()
        )
        is_topology_child = (
            child_service_id == "topology"
            or "sos_topology" in child_id.lower()
            or "sos_dependency_topology" in child_id.lower()
            or "sos_dependency_map" in child_id.lower()
            or "sos_blast_radius" in child_id.lower()
        )
        is_redundancy_child = (
            child_service_id == "redundancy"
            or "sos_redundancy" in child_id.lower()
            or "sos_failover" in child_id.lower()
            or "sos_critical_systems" in child_id.lower()
            or "sos_coverage" in child_id.lower()
            or "sos_resilience" in child_id.lower()
        )
        is_guidance_child = (
            child_service_id == "guidance"
            or "sos_guidance" in child_id.lower()
            or "sos_operator_guidance" in child_id.lower()
            or "sos_watch" in child_id.lower()
            or "sos_priorities" in child_id.lower()
        )
        is_diagnostics_child = (
            child_service_id == "diagnostics"
            or "sos_diagnostics" in child_id.lower()
            or "sos_diagnostic" in child_id.lower()
            or "sos_contract_health" in child_id.lower()
            or "sos_healthcheck" in child_id.lower()
        )
        is_watch_log_child = (
            child_service_id == "watch_log"
            or "sos_watch_log" in child_id.lower()
            or "sos_event_log" in child_id.lower()
            or "sos_timeline" in child_id.lower()
            or "sos_history" in child_id.lower()
            or "sos_operator_log" in child_id.lower()
        )
        is_mission_profile_child = (
            child_service_id == "mission_profile"
            or "sos_mission_profile" in child_id.lower()
            or "sos_profile" in child_id.lower()
            or "sos_operating_envelope" in child_id.lower()
            or "sos_envelope" in child_id.lower()
        )
        is_endurance_child = (
            child_service_id == "endurance"
            or "sos_endurance" in child_id.lower()
            or "sos_consumables" in child_id.lower()
            or "sos_resource_forecast" in child_id.lower()
            or "sos_supply" in child_id.lower()
            or "sos_runway" in child_id.lower()
        )
        is_runbook_child = (
            child_service_id == "runbook"
            or "sos_runbook" in child_id.lower()
            or "sos_checklist" in child_id.lower()
            or "sos_procedure" in child_id.lower()
            or "sos_operator_checklist" in child_id.lower()
        )
        is_display_child = (
            child_service_id == "display"
            or "sos_display" in child_id.lower()
            or "sos_displays" in child_id.lower()
            or "sos_surfaces" in child_id.lower()
            or "sos_lcd" in child_id.lower()
            or "sos_status_surface" in child_id.lower()
        )
        if not is_environment_child and not is_navigation_child and not is_mining_child:
            remove_environment_only_snapshot_aliases(child_request)
        if not is_navigation_child:
            remove_navigation_only_snapshot_aliases(child_request)
        if not is_maintenance_child:
            remove_maintenance_only_snapshot_aliases(child_request)
        if not is_mining_child and not is_endurance_child:
            remove_mining_only_snapshot_aliases(child_request)
        if not is_alerts_child:
            remove_alerts_only_snapshot_aliases(child_request)
        if not is_readiness_child:
            remove_readiness_only_snapshot_aliases(child_request)
        if not is_capabilities_child:
            remove_capabilities_only_snapshot_aliases(child_request)
        if not is_telemetry_quality_child:
            remove_telemetry_quality_only_snapshot_aliases(child_request)
        if not is_automation_child:
            remove_automation_only_snapshot_aliases(child_request)
        if not is_config_drift_child:
            preserve = CONFIG_DRIFT_SHARED_DIAGNOSTICS_KEYS if is_diagnostics_child else ()
            remove_config_drift_only_snapshot_aliases(child_request, preserve)
        if not is_topology_child:
            remove_topology_only_snapshot_aliases(child_request)
        if not is_redundancy_child:
            remove_redundancy_only_snapshot_aliases(child_request)
        if not is_guidance_child:
            remove_guidance_only_snapshot_aliases(child_request)
        if not is_diagnostics_child:
            preserve = CONFIG_DRIFT_SHARED_DIAGNOSTICS_KEYS if is_config_drift_child else ()
            remove_diagnostics_only_snapshot_aliases(child_request, preserve)
        if not is_watch_log_child:
            remove_watch_log_only_snapshot_aliases(child_request)
        if not is_mission_profile_child:
            remove_mission_profile_only_snapshot_aliases(child_request)
        if not is_endurance_child:
            remove_endurance_only_snapshot_aliases(child_request)
        if not is_runbook_child:
            remove_runbook_only_snapshot_aliases(child_request)
        if not is_display_child and not is_redundancy_child:
            remove_display_only_snapshot_aliases(child_request)
        if is_config_drift_child:
            attach_config_drift_host_snapshots(child_request, root)
        if (
            child_service_id
            in {
                "integrity",
                "maintenance",
                "mining",
                "mobility",
                "navigation",
                "display",
                "power",
                "comms",
                "crew",
                "docking",
                "endurance",
                "redundancy",
                "capabilities",
                "topology",
                "life_support",
                "production",
                "transit",
                "defense",
                "environment",
                "automation",
            }
            or "sos_integrity" in child_id.lower()
            or "sos_damage" in child_id.lower()
            or "sos_maintenance" in child_id.lower()
            or "sos_repair" in child_id.lower()
            or "sos_damage_control" in child_id.lower()
            or "sos_projector" in child_id.lower()
            or "sos_mining" in child_id.lower()
            or "sos_harvest" in child_id.lower()
            or "sos_resource" in child_id.lower()
            or "sos_ore" in child_id.lower()
            or "sos_mobility" in child_id.lower()
            or "sos_navigation" in child_id.lower()
            or "sos_nav" in child_id.lower()
            or "sos_display" in child_id.lower()
            or "sos_displays" in child_id.lower()
            or "sos_surfaces" in child_id.lower()
            or "sos_lcd" in child_id.lower()
            or "sos_status_surface" in child_id.lower()
            or "sos_power" in child_id.lower()
            or "sos_comms" in child_id.lower()
            or "sos_crew" in child_id.lower()
            or "sos_docking" in child_id.lower()
            or "sos_endurance" in child_id.lower()
            or "sos_consumables" in child_id.lower()
            or "sos_resource_forecast" in child_id.lower()
            or "sos_supply" in child_id.lower()
            or "sos_runway" in child_id.lower()
            or "sos_redundancy" in child_id.lower()
            or "sos_failover" in child_id.lower()
            or "sos_critical_systems" in child_id.lower()
            or "sos_coverage" in child_id.lower()
            or "sos_resilience" in child_id.lower()
            or "sos_capabilities" in child_id.lower()
            or "sos_capability_inventory" in child_id.lower()
            or "sos_ship_capabilities" in child_id.lower()
            or "sos_role_fit" in child_id.lower()
            or "sos_topology" in child_id.lower()
            or "sos_dependency_topology" in child_id.lower()
            or "sos_dependency_map" in child_id.lower()
            or "sos_blast_radius" in child_id.lower()
            or "sos_life_support" in child_id.lower()
            or "sos_lifesupport" in child_id.lower()
            or "sos_production" in child_id.lower()
            or "sos_transit" in child_id.lower()
            or "sos_defense" in child_id.lower()
            or "sos_environment" in child_id.lower()
            or "sos_automation" in child_id.lower()
            or "sos_control_logic" in child_id.lower()
            or "sos_script_health" in child_id.lower()
            or "sos_programmable_block" in child_id.lower()
        ):
            attach_integrity_snapshot_from_grid_snapshot(child_request)
        if (
            child_service_id
            in {
                "logistics",
                "maintenance",
                "mining",
                "power",
                "life_support",
                "production",
                "transit",
                "defense",
                "endurance",
                "redundancy",
            }
            or "sos_logistics" in child_id.lower()
            or "sos_maintenance" in child_id.lower()
            or "sos_repair" in child_id.lower()
            or "sos_damage_control" in child_id.lower()
            or "sos_projector" in child_id.lower()
            or "sos_mining" in child_id.lower()
            or "sos_harvest" in child_id.lower()
            or "sos_resource" in child_id.lower()
            or "sos_ore" in child_id.lower()
            or "sos_power" in child_id.lower()
            or "sos_endurance" in child_id.lower()
            or "sos_consumables" in child_id.lower()
            or "sos_resource_forecast" in child_id.lower()
            or "sos_supply" in child_id.lower()
            or "sos_runway" in child_id.lower()
            or "sos_redundancy" in child_id.lower()
            or "sos_failover" in child_id.lower()
            or "sos_critical_systems" in child_id.lower()
            or "sos_coverage" in child_id.lower()
            or "sos_resilience" in child_id.lower()
            or "sos_life_support" in child_id.lower()
            or "sos_lifesupport" in child_id.lower()
            or "sos_production" in child_id.lower()
            or "sos_transit" in child_id.lower()
            or "sos_defense" in child_id.lower()
        ):
            attach_logistics_snapshot_from_host_snapshots(child_request)
        if child_service_id == "airlock" or "sos_airlock" in child_id.lower():
            attach_airlock_snapshot_from_grid_snapshot(child_request)
        child_result = execute_request(child_request, scripts, bridge_configs, root=root, apply_queue=False)
        result_payload = child_result.get("result") if isinstance(child_result.get("result"), dict) else {}
        child_result_summary = {
            "script_id": child_id,
            "status": child_result.get("status", "unknown"),
            "error_bucket": child_result.get("error_bucket", "none"),
            "summary": result_payload.get("summary", ""),
        }
        history_payload = child_result_history_payload(result_payload)
        if history_payload:
            child_result_summary["result"] = history_payload
        child_results.append(child_result_summary)
        if child_result.get("status") != "ok":
            continue
        try:
            budget = max(0, int(child_config.get("budget", 1) or 1))
        except (TypeError, ValueError):
            budget = 1
        try:
            priority = int(child_config.get("priority", 50) or 50)
        except (TypeError, ValueError):
            priority = 50
        try:
            fairness_weight = max(1, int(child_config.get("fairness_weight", 1) or 1))
        except (TypeError, ValueError):
            fairness_weight = 1
        try:
            expires_after = max(0, int(child_config.get("expires_after_sequences", 0) or 0))
        except (TypeError, ValueError):
            expires_after = 0
        role = str(child_config.get("role", "") or "")
        reactive = bool(child_config.get("reactive", False))
        operator_status = str(child_config.get("operator_status", "ok") or "ok")
        child_results[-1]["operator_status"] = operator_status
        scheduler_fairness.append(
            {
                "script_id": child_id,
                "role": role,
                "reactive": reactive,
                "budget": budget,
                "priority": priority,
                "fairness_weight": fairness_weight,
                "operator_status": operator_status,
                "emitted": 0,
            }
        )
        child_commands = [command for command in result_payload.get("commands", []) if isinstance(command, dict)]
        for command in child_commands[:budget]:
            tagged = dict(command)
            tagged.setdefault("source_script_id", child_id)
            tagged.setdefault("source_priority", priority)
            tagged.setdefault("source_order", index)
            if role:
                tagged.setdefault("source_role", role)
            if reactive and expires_after > 0:
                tagged.setdefault("expires_after_sequences", expires_after)
            merged_commands.append(tagged)
            scheduler_fairness[-1]["emitted"] += 1

    merged_commands.sort(key=lambda command: (int(command.get("source_priority", 50) or 50), int(command.get("source_order", 0) or 0)))
    merged_commands, conflicts = resolve_orchestrator_conflicts(merged_commands)
    output = {
        "summary": f"bridge_orchestrator processed {len(child_results)} child script(s)",
        "commands": merged_commands,
        "apply_mode": "immediate",
        "max_apply_commands": max(1, len(merged_commands)),
        "remaining_commands": 0,
        "orchestrator": {
            "status": "processed",
            "child_count": len(child_results),
            "command_count": len(merged_commands),
        },
        "scheduler": {
            "policy": "priority_fairness_v1",
            "child_count": len(child_results),
            "eligible_child_count": len(scheduler_fairness),
            "emitted_child_count": sum(1 for item in scheduler_fairness if int(item.get("emitted", 0) or 0) > 0),
            "fairness": scheduler_fairness,
        },
        "conflicts": conflicts,
        "child_results": child_results,
    }
    sos_ship = request.get("sos_ship") if isinstance(request.get("sos_ship"), dict) else {}
    if sos_ship:
        output["sos"] = {
            "ship_id": str(sos_ship.get("ship_id", "")),
            "display_name": str(sos_ship.get("display_name", "")),
            "mode": str(sos_ship.get("mode", "")),
            "identity_status": str(sos_ship.get("identity_status", "")),
            "blockers": sos_ship.get("blockers", []) if isinstance(sos_ship.get("blockers"), list) else [],
            "warnings": sos_ship.get("warnings", []) if isinstance(sos_ship.get("warnings"), list) else [],
        }
    if root is not None:
        output = apply_command_queue(root, request, output)
    output["queue_pressure"] = queue_pressure_summary(output)
    attach_child_queue_stats(output)
    return result_for(request, "ok", output, "none")


def enriched_child_runtime_telemetry(
    root: Path | None,
    request: dict[str, Any],
    child_configs: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    telemetry = request.get("runtime_telemetry") if isinstance(request.get("runtime_telemetry"), dict) else {}
    enriched = dict(telemetry)
    previous = previous_orchestrator_result(root, str(request.get("bridge_id", "")))
    previous_payload = previous.get("result") if isinstance(previous.get("result"), dict) else {}
    queue_pressure = stable_queue_pressure(previous_payload)
    child_services = child_service_telemetry(child_configs, previous_payload, queue_pressure)
    enriched["queue_pressure"] = queue_pressure
    enriched.setdefault("command_queue", queue_pressure)
    enriched["child_services"] = child_services
    enriched["child_services_by_script_id"] = {
        item["script_id"]: item for item in child_services if str(item.get("script_id", ""))
    }
    enriched["child_services_by_service_id"] = {
        item["service_id"]: item for item in child_services if str(item.get("service_id", ""))
    }
    return enriched


def previous_orchestrator_result(root: Path | None, bridge_id: str) -> dict[str, Any]:
    if root is None or not bridge_id:
        return {}
    return read_json_file(root / "data" / "bridge_results" / f"{safe_file_name(bridge_id)}.json")


def stable_queue_pressure(previous_payload: dict[str, Any]) -> dict[str, Any]:
    queue = previous_payload.get("queue_pressure") if isinstance(previous_payload.get("queue_pressure"), dict) else {}
    if not queue and isinstance(previous_payload.get("command_queue"), dict):
        queue = previous_payload["command_queue"]
    by_source = queue.get("by_source") if isinstance(queue.get("by_source"), dict) else {}
    return {
        "queued": int_value(queue.get("queued"), 0),
        "drained": int_value(queue.get("drained"), 0),
        "remaining": int_value(queue.get("remaining"), 0),
        "by_source": {
            str(source_id): stable_queue_stats(stats)
            for source_id, stats in by_source.items()
            if isinstance(stats, dict) and str(source_id)
        },
    }


def child_service_telemetry(
    child_configs: tuple[dict[str, Any], ...],
    previous_payload: dict[str, Any],
    queue_pressure: dict[str, Any],
) -> list[dict[str, Any]]:
    previous_children = previous_payload.get("child_results") if isinstance(previous_payload.get("child_results"), list) else []
    previous_by_script = {
        str(item.get("script_id", "")): item
        for item in previous_children
        if isinstance(item, dict) and str(item.get("script_id", ""))
    }
    by_source = queue_pressure.get("by_source") if isinstance(queue_pressure.get("by_source"), dict) else {}
    children: list[dict[str, Any]] = []
    for child_config in child_configs:
        if not isinstance(child_config, dict):
            continue
        script_id = str(child_config.get("script_id", "")).strip()
        if not script_id or script_id == "bridge_orchestrator":
            continue
        service_id = str(child_config.get("service_id", "") or script_id).strip()
        previous = previous_by_script.get(script_id, {})
        item = {
            "service_id": service_id,
            "script_id": script_id,
            "status": str(previous.get("status", "unknown") or "unknown"),
            "error_bucket": str(previous.get("error_bucket", "none") or "none"),
            "summary": str(previous.get("summary", "") or ""),
            "command_queue": stable_queue_stats(by_source.get(script_id) if isinstance(by_source.get(script_id), dict) else {}),
        }
        previous_result = previous.get("result") if isinstance(previous.get("result"), dict) else {}
        if previous_result:
            item["result"] = previous_result
        children.append(item)
    return children


def child_result_history_payload(result_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: compact_sos_child_history_payload(key, value)
        for key, value in result_payload.items()
        if key.startswith("sos_") and isinstance(value, dict)
    }


def compact_sos_child_history_payload(key: str, value: dict[str, Any]) -> dict[str, Any]:
    if key != "sos_dashboard":
        return value
    compacted: dict[str, Any] = {}
    for field in ("mode", "posture"):
        if field in value:
            compacted[field] = value[field]
    for service_id, payload in value.items():
        if not isinstance(payload, dict) or service_id in {"identity", "service_health", "queue_pressure", "mode_effects"}:
            continue
        item: dict[str, Any] = {}
        for field in ("state", "snapshot_status"):
            if field in payload:
                item[field] = payload[field]
        for field in (
            "warning_count",
            "blocker_count",
            "missing_child_result_count",
            "child_error_count",
            "queue_remaining",
        ):
            if field in payload:
                item[field] = payload[field]
        warnings = payload.get("warnings")
        if isinstance(warnings, list) and warnings:
            item["warnings"] = warnings[:10]
            if len(warnings) > 10:
                item["warnings"].append({"truncated_count": len(warnings) - 10})
        if item:
            compacted[service_id] = item
    return compacted


def stable_queue_stats(stats: dict[str, Any]) -> dict[str, int]:
    return {
        "queued": int_value(stats.get("queued"), 0),
        "drained": int_value(stats.get("drained"), 0),
        "remaining": int_value(stats.get("remaining"), 0),
    }


def int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def queue_pressure_summary(output: dict[str, Any]) -> dict[str, Any]:
    command_queue = output.get("command_queue") if isinstance(output.get("command_queue"), dict) else {}
    return {
        "queued": int(command_queue.get("queued", output.get("queued_commands", 0)) or 0),
        "drained": int(command_queue.get("drained", len(output.get("commands", []) if isinstance(output.get("commands"), list) else [])) or 0),
        "remaining": int(command_queue.get("remaining", output.get("remaining_commands", 0)) or 0),
        "by_source": command_queue.get("by_source", {}) if isinstance(command_queue.get("by_source"), dict) else {},
    }


def attach_child_queue_stats(output: dict[str, Any]) -> None:
    command_queue = output.get("command_queue") if isinstance(output.get("command_queue"), dict) else {}
    by_source = command_queue.get("by_source") if isinstance(command_queue.get("by_source"), dict) else {}
    child_results = output.get("child_results") if isinstance(output.get("child_results"), list) else []
    for child in child_results:
        if not isinstance(child, dict):
            continue
        child_id = str(child.get("script_id", "") or "")
        stats = by_source.get(child_id)
        if isinstance(stats, dict):
            child["command_queue"] = {
                "queued": int(stats.get("queued", 0) or 0),
                "drained": int(stats.get("drained", 0) or 0),
                "remaining": int(stats.get("remaining", 0) or 0),
            }
        else:
            child["command_queue"] = {"queued": 0, "drained": 0, "remaining": 0}


def save_virtual_pb_compatibility_report(
    root: Path,
    script_id: str,
    compatibility: dict[str, Any],
    output: dict[str, Any],
) -> None:
    path = root / "data" / "virtual_pb_compatibility.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    scripts = existing.get("scripts") if isinstance(existing.get("scripts"), dict) else {}
    commands = output.get("commands") if isinstance(output.get("commands"), list) else []
    emitted_kinds = sorted(
        {
            str(command.get("kind", ""))
            for command in commands
            if isinstance(command, dict) and str(command.get("kind", ""))
        }
    )
    status = str(compatibility.get("status", "unknown"))
    compatibility_emitted = compatibility.get("emitted_command_kinds")
    if isinstance(compatibility_emitted, list) and compatibility_emitted:
        emitted_kinds = sorted({str(kind) for kind in compatibility_emitted if str(kind)})
    scripts[script_id] = {
        "compiled": bool(compatibility.get("compiled", status == "supported")),
        "status": status,
        "unsupported_apis": compatibility.get("unsupported_apis", []),
        "unsupported_interfaces": compatibility.get("unsupported_interfaces", []),
        "unsupported_members": compatibility.get("unsupported_members", []),
        "blocked_members": compatibility.get("blocked_members", []),
        "blocked_command_mappings": compatibility.get("blocked_command_mappings", []),
        "missing_types": compatibility.get("missing_types", []),
        "missing_members": compatibility.get("missing_members", []),
        "compile_errors": compatibility.get("compile_errors", []),
        "required_interfaces": compatibility.get("required_interfaces", []),
        "implemented_interfaces": compatibility.get("implemented_interfaces", []),
        "available_command_kinds": compatibility.get("available_command_kinds", []),
        "snapshot_requirements": compatibility.get("snapshot_requirements", []),
        "supported_block_types": compatibility.get("supported_block_types", []),
        "client_overlay_writes": compatibility.get("client_overlay_writes", []),
        "capability_categories": compatibility.get("capability_categories", {}),
        "emitted_command_kinds": emitted_kinds,
        "last_run_status": str(output.get("adapter_status", output.get("status", "ok")) or "ok"),
        "capability_version": compatibility.get("capability_version", ""),
        "summary": str(output.get("summary", "")),
        "updated_at": utc_now(),
    }
    report = {
        "schema": "novali.client_side_pb.virtual_pb_compatibility.v1",
        "updated_at": utc_now(),
        "scripts": scripts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def request_key(path: Path) -> str:
    return path.stem


def load_bridge_health(root: Path) -> dict[str, Any]:
    path = root / "data" / "bridge_health.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"schema": BRIDGE_HEALTH_SCHEMA, "bridges": {}}
    if payload.get("schema") != BRIDGE_HEALTH_SCHEMA:
        return {"schema": BRIDGE_HEALTH_SCHEMA, "bridges": {}}
    if not isinstance(payload.get("bridges"), dict):
        payload["bridges"] = {}
    return payload


def discover_bridge_ids(root: Path) -> set[str]:
    bridge_ids: set[str] = set()
    bridges = load_status_json(root, "bridges.json").get("bridges")
    if isinstance(bridges, dict):
        bridge_ids.update(str(bridge_id) for bridge_id in bridges.keys() if str(bridge_id))
    assignments = load_status_json(root, "bridge_scripts.json").get("bridges")
    if isinstance(assignments, dict):
        bridge_ids.update(str(bridge_id) for bridge_id in assignments.keys() if str(bridge_id))
    for directory in (root / "data" / "bridge_requests", root / "data" / "bridge_results"):
        if directory.exists():
            bridge_ids.update(path.stem for path in directory.glob("*.json"))
    processed = root / "data" / "bridge_requests" / "processed"
    if processed.exists():
        for path in processed.glob("*.json"):
            name = path.stem
            bridge_ids.add(name.rsplit("-", 1)[0] if "-" in name else name)
    return bridge_ids


def latest_request_path(root: Path, bridge_id: str) -> Path | None:
    active = root / "data" / "bridge_requests" / f"{bridge_id}.json"
    if active.exists():
        return active
    processed = root / "data" / "bridge_requests" / "processed"
    if not processed.exists():
        return None
    candidates = list(processed.glob(f"{bridge_id}-*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: archived_request_order_key(path, bridge_id))


def archived_request_order_key(path: Path, bridge_id: str) -> tuple[int, str]:
    prefix = f"{bridge_id}-"
    stem = path.stem
    suffix = stem[len(prefix) :] if stem.startswith(prefix) else ""
    try:
        archive_timestamp = int(suffix)
    except ValueError:
        archive_timestamp = -1
    return (archive_timestamp, path.name)


def read_json_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def update_bridge_health(root: Path, stale_seconds: int | None = None) -> dict[str, Any]:
    max_age = stale_seconds if stale_seconds is not None else stale_seconds_from_env()
    previous = load_bridge_health(root)
    previous_bridges = previous.get("bridges") if isinstance(previous.get("bridges"), dict) else {}
    now_ts = time.time()
    rows: dict[str, Any] = {}
    for bridge_id in sorted(discover_bridge_ids(root)):
        request_path = latest_request_path(root, bridge_id)
        result_path = root / "data" / "bridge_results" / f"{bridge_id}.json"
        request = read_json_file(request_path)
        result = read_json_file(result_path)
        request_age = (now_ts - request_path.stat().st_mtime) if request_path is not None and request_path.exists() else None
        result_age = (now_ts - result_path.stat().st_mtime) if result_path.exists() else None
        request_sequence = int(request.get("sequence", 0) or 0)
        result_sequence = int(result.get("sequence", 0) or 0)
        result_status = str(result.get("status", "")) if result else ""
        fresh_request = request_age is not None and request_age <= max_age
        fresh_result = result_age is not None and result_age <= max_age
        previous_status = ""
        previous_row = previous_bridges.get(bridge_id) if isinstance(previous_bridges, dict) else {}
        if isinstance(previous_row, dict):
            previous_status = str(previous_row.get("status", ""))
        if not fresh_request:
            status = "concealed_suspected"
            queue_policy = "hold_until_fresh_heartbeat"
        elif not fresh_result or request_sequence <= 0 or result_sequence != request_sequence:
            status = "stale"
            queue_policy = "hold_until_fresh_heartbeat"
        elif result_status == "stale_held":
            status = "concealed_suspected"
            queue_policy = "hold_until_fresh_heartbeat"
        elif previous_status in {"concealed_suspected", "stale"}:
            status = "recovered"
            queue_policy = "drain"
        else:
            status = "active"
            queue_policy = "drain"
        rows[bridge_id] = {
            "bridge_id": bridge_id,
            "status": status,
            "queue_policy": queue_policy,
            "last_request_path": str(request_path) if request_path is not None else "",
            "last_result_path": str(result_path) if result_path.exists() else "",
            "last_request_age_seconds": None if request_age is None else round(request_age, 3),
            "last_result_age_seconds": None if result_age is None else round(result_age, 3),
            "last_sequence": result_sequence,
            "last_result_status": result_status,
            "updated_at": utc_now(),
        }
    payload = {"schema": BRIDGE_HEALTH_SCHEMA, "updated_at": utc_now(), "stale_seconds": max_age, "bridges": rows}
    path = root / "data" / "bridge_health.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def cleanup_processed_requests(
    root: Path,
    retention_seconds: int | None = None,
    now: float | None = None,
    max_files_per_pass: int | None = None,
) -> dict[str, int]:
    retention = (
        processed_request_retention_seconds_from_env()
        if retention_seconds is None
        else max(0, int(retention_seconds))
    )
    max_files = (
        processed_request_cleanup_max_files_from_env()
        if max_files_per_pass is None
        else max(1, int(max_files_per_pass))
    )
    cutoff = (time.time() if now is None else now) - retention
    processed_dir = root / "data" / "bridge_requests" / "processed"
    stats = {
        "retention_seconds": retention,
        "max_files_per_pass": max_files,
        "scanned": 0,
        "removed": 0,
        "failed": 0,
        "limit_reached": 0,
    }
    if not processed_dir.exists():
        return stats
    for path in processed_dir.glob("*.json"):
        if not path.is_file():
            continue
        stats["scanned"] += 1
        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink()
                stats["removed"] += 1
                if stats["removed"] >= max_files:
                    stats["limit_reached"] = 1
                    break
        except OSError:
            stats["failed"] += 1
    return stats


def process_pending(root: Path, scripts: dict[str, WorkerScript]) -> int:
    bridge_configs = load_bridge_script_configs(root)
    requests_dir = root / "data" / "bridge_requests"
    results_dir = root / "data" / "bridge_results"
    processed_dir = requests_dir / "processed"
    results_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    limiter_states: dict[str, str] = {}
    for request_path in sorted(requests_dir.glob("*.json")):
        try:
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            request = {"bridge_id": request_key(request_path), "sequence": 0, "script_id": "", "schema": ""}
            result = result_for(request, "rejected", {}, "invalid_json")
        else:
            result = execute_request(request, scripts, bridge_configs, root)
        result_path = results_dir / f"{request_key(request_path)}.json"
        result_for_storage = compact_result_for_storage(result)
        result_path.write_text(json.dumps(result_for_storage, separators=(",", ":")), encoding="utf-8")
        if result.get("bridge_id"):
            limiter_states[str(result["bridge_id"])] = str(result.get("limiter_state", "unknown"))
        archived = processed_dir / f"{request_path.stem}-{int(time.time() * 1000)}.json"
        request_path.replace(archived)
        count += 1
    bridge_health = update_bridge_health(root)
    processed_cleanup = cleanup_processed_requests(root)
    status_path = root / "data" / "worker_status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_status.v1",
                "updated_at": utc_now(),
                "processed": count,
                "limiter_states": limiter_states,
                "bridge_health": bridge_health.get("bridges", {}),
                "processed_request_cleanup": processed_cleanup,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return count


def load_status_json(root: Path, name: str) -> dict[str, Any]:
    path = root / "data" / name
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def summarize_report_list(report: dict[str, Any], key: str, limit: int = 6) -> str:
    values = report.get(key)
    if not isinstance(values, list):
        return ""
    text_values = [str(value) for value in values if str(value)]
    if len(text_values) > limit:
        return ", ".join(text_values[:limit]) + f", +{len(text_values) - limit}"
    return ", ".join(text_values)


def latest_child_statuses(root: Path, bridge_id: str) -> dict[str, str]:
    payload = load_status_json(root, f"bridge_results/{bridge_id}.json")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    child_results = result.get("child_results") if isinstance(result.get("child_results"), list) else []
    statuses: dict[str, str] = {}
    for child in child_results:
        if not isinstance(child, dict):
            continue
        script_id = str(child.get("script_id", "")).strip()
        if not script_id:
            continue
        status = str(child.get("status", "unknown") or "unknown")
        error_bucket = str(child.get("error_bucket", "none") or "none")
        statuses[script_id] = status if error_bucket == "none" else f"{status}: {error_bucket}"
    return statuses


def render_status_page(root: Path) -> str:
    worker_status = load_status_json(root, "worker_status.json")
    plugin_status = load_status_json(root, "plugin_status.json")
    virtual_pb = load_status_json(root, "virtual_pb_compatibility.json")
    bridge_scripts = load_status_json(root, "bridge_scripts.json")
    bridge_health = load_status_json(root, "bridge_health.json")
    limiter_states = worker_status.get("limiter_states") if isinstance(worker_status.get("limiter_states"), dict) else {}
    health_rows_payload = bridge_health.get("bridges") if isinstance(bridge_health.get("bridges"), dict) else {}
    virtual_scripts = virtual_pb.get("scripts") if isinstance(virtual_pb.get("scripts"), dict) else {}
    bridges = bridge_scripts.get("bridges") if isinstance(bridge_scripts.get("bridges"), dict) else {}
    bridge_rows = "".join(
        f"<tr><td>{html.escape(str(bridge_id))}</td><td>{html.escape(str(state))}</td></tr>"
        for bridge_id, state in sorted(limiter_states.items())
    ) or "<tr><td colspan=\"2\">No bridge requests processed yet.</td></tr>"
    health_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(bridge_id))}</td>"
        f"<td>{html.escape(str(row.get('status', 'unknown')))}</td>"
        f"<td>{html.escape(str(row.get('queue_policy', 'unknown')))}</td>"
        f"<td>{html.escape(str(row.get('last_request_age_seconds', '')))}</td>"
        f"<td>{html.escape(str(row.get('last_result_status', '')))}</td>"
        "</tr>"
        for bridge_id, row in sorted(health_rows_payload.items())
        if isinstance(row, dict)
    ) or "<tr><td colspan=\"5\">No bridge heartbeat health recorded yet.</td></tr>"
    active_row_parts = []
    for bridge_id, bridge_config in sorted(bridges.items()):
        if not isinstance(bridge_config, dict):
            continue
        child_ids = [
            str(child.get("script_id", ""))
            for child in bridge_config.get("child_worker_scripts", [])
            if isinstance(child, dict) and str(child.get("script_id", ""))
        ]
        latest_statuses = latest_child_statuses(root, str(bridge_id))
        child_status_text = ", ".join(
            f"{child_id}={latest_statuses.get(child_id, 'no recent result')}"
            for child_id in child_ids
        )
        active_row_parts.append(
            "<tr>"
            f"<td>{html.escape(str(bridge_id))}</td>"
            f"<td>{html.escape(str(bridge_config.get('selected_script_id', '')))}</td>"
            f"<td>{html.escape(', '.join(child_ids))}</td>"
            f"<td>{html.escape(child_status_text)}</td>"
            f"<td>{html.escape(str(bridge_config.get('updated_at', '')))}</td>"
            "</tr>"
        )
    active_rows = "".join(active_row_parts) or "<tr><td colspan=\"5\">No active bridge script assignments.</td></tr>"
    virtual_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(script_id))}</td>"
        f"<td>{html.escape(str(report.get('status', 'unknown')))}</td>"
        f"<td>{html.escape(str(report.get('compiled', False)))}</td>"
        f"<td>{html.escape(summarize_report_list(report, 'required_interfaces'))}</td>"
        f"<td>{html.escape(summarize_report_list(report, 'emitted_command_kinds'))}</td>"
        f"<td>{html.escape(summarize_report_list(report, 'available_command_kinds'))}</td>"
        f"<td>{html.escape(summarize_report_list(report, 'blocked_command_mappings') or summarize_report_list(report, 'missing_members') or summarize_report_list(report, 'unsupported_members'))}</td>"
        f"<td>{html.escape(summarize_report_list(report, 'snapshot_requirements', 4))}</td>"
        f"<td>{html.escape(str(report.get('last_run_status', 'unknown')))}</td>"
        "</tr>"
        for script_id, report in sorted(virtual_scripts.items())
        if isinstance(report, dict)
    ) or "<tr><td colspan=\"9\">No virtual PB compatibility report yet.</td></tr>"
    selected_scripts = []
    for bridge_id, bridge_config in sorted(bridges.items()):
        if isinstance(bridge_config, dict):
            selected_scripts.append(f"{bridge_id}: {bridge_config.get('selected_script_id', '')}")
    selected_text = ", ".join(str(item) for item in selected_scripts) or "No bridge script assignments."
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NOVALI Client-Side PB Gateway</title>
  <style>
    :root {{ color-scheme: dark; font-family: Segoe UI, Arial, sans-serif; background: #0f141b; color: #e8eef7; }}
    body {{ margin: 0; padding: 28px; }}
    main {{ max-width: 1280px; margin: 0 auto; }}
    h1 {{ font-size: 26px; margin: 0 0 18px; letter-spacing: 0; }}
    h2 {{ font-size: 16px; margin: 22px 0 10px; letter-spacing: 0; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 18px; }}
    .button {{ display: inline-block; border: 1px solid #3b82f6; border-radius: 6px; background: #1d4ed8; color: #f8fafc; padding: 10px 14px; text-decoration: none; font-weight: 600; }}
    .button.secondary {{ background: #141b24; border-color: #475569; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }}
    .metric {{ border: 1px solid #263445; border-radius: 6px; padding: 14px; background: #141b24; }}
    .label {{ color: #9fb0c3; font-size: 12px; }}
    .value {{ font-size: 22px; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; background: #141b24; border: 1px solid #263445; }}
    th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #263445; vertical-align: top; }}
    th {{ color: #b9c7d8; font-size: 12px; }}
    code {{ color: #9fdaff; }}
  </style>
</head>
<body>
<main>
  <h1>NOVALI Client-Side PB Gateway</h1>
  <section class="actions">
    <a class="button" href="novali-client-side-pb-manager://open">Open Configuration UI</a>
    <a class="button secondary" href="/status.json">Status JSON</a>
    <a class="button secondary" href="/manager-launch.log">Launch Diagnostics</a>
  </section>
  <section class="grid">
    <div class="metric"><div class="label">Processed requests</div><div class="value">{html.escape(str(worker_status.get('processed', 0)))}</div></div>
    <div class="metric"><div class="label">Worker updated</div><div class="value">{html.escape(str(worker_status.get('updated_at', 'not yet')))}</div></div>
    <div class="metric"><div class="label">Plugin state</div><div class="value">{html.escape(str(plugin_status.get('state', 'unknown')))}</div></div>
  </section>
  <h2>Bridge Assignments</h2>
  <p><code>{html.escape(selected_text)}</code></p>
  <h2>Active Bridge Scripts</h2>
  <table><thead><tr><th>Bridge</th><th>Selected Runtime</th><th>Child Instances</th><th>Latest Child Status</th><th>Updated</th></tr></thead><tbody>{active_rows}</tbody></table>
  <h2>Bridge Heartbeat Health</h2>
  <table><thead><tr><th>Bridge</th><th>Status</th><th>Queue Policy</th><th>Request Age Seconds</th><th>Last Result</th></tr></thead><tbody>{health_rows}</tbody></table>
  <h2>Limiter States</h2>
  <table><thead><tr><th>Bridge</th><th>State</th></tr></thead><tbody>{bridge_rows}</tbody></table>
  <h2>Virtual PB Compatibility Inventory</h2>
  <p class="label">Import compatibility reports are not active bridge failures unless the script is assigned above.</p>
  <table><thead><tr><th>Script</th><th>Status</th><th>Compiled</th><th>Required Interfaces</th><th>Emitted</th><th>Available Commands</th><th>Unsupported</th><th>Snapshots</th><th>Last Run</th></tr></thead><tbody>{virtual_rows}</tbody></table>
</main>
</body>
</html>
"""


def start_status_server(root: Path, host: str, port: int) -> ThreadingHTTPServer:
    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
            if self.path in {"/", "/index.html"}:
                body = render_status_page(root).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/status.json":
                payload = {
                    "worker_status": load_status_json(root, "worker_status.json"),
                    "plugin_status": load_status_json(root, "plugin_status.json"),
                    "virtual_pb_compatibility": load_status_json(root, "virtual_pb_compatibility.json"),
                    "bridge_health": load_status_json(root, "bridge_health.json"),
                }
                body = json.dumps(payload, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/manager-launch.log":
                path = root / "data" / "manager_launch.log"
                text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else "No manager launch log has been written yet.\n"
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), StatusHandler)
    thread = threading.Thread(target=server.serve_forever, name="novali-worker-status-ui", daemon=True)
    thread.start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NOVALI Client-Side PB worker.")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("NOVALI_CLIENT_SIDE_PB_ROOT", ".")))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("NOVALI_CLIENT_SIDE_PB_POLL_SECONDS", "1.0")))
    parser.add_argument("--ui-host", default=os.environ.get("NOVALI_CLIENT_SIDE_PB_UI_HOST", "0.0.0.0"))
    parser.add_argument("--ui-port", type=int, default=int(os.environ.get("NOVALI_CLIENT_SIDE_PB_UI_PORT", "8788")))
    parser.add_argument("--no-ui", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    server = None
    if not args.once and not args.no_ui and args.ui_port > 0:
        server = start_status_server(root, args.ui_host, args.ui_port)
    while True:
        scripts = load_manifest(root)
        processed = process_pending(root, scripts)
        if args.once:
            print(json.dumps({"processed": processed}, indent=2))
            return 0
        try:
            time.sleep(max(args.poll_seconds, 0.1))
        except KeyboardInterrupt:
            if server is not None:
                server.shutdown()
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
