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


SCHEMA = "novali.client_side_pb_bridge.v1"
COMMAND_QUEUE_SCHEMA = "novali.client_side_pb.command_queue.v1"
AUTOCRAFTING_BLUEPRINT_SCHEMA = "novali.client_side_pb.autocrafting_blueprints.v1"
VOLATILE_COMMAND_KINDS = {"transfer_item", "write_text_surface"}
DEFAULT_LCD_QUEUE_COOLDOWN_SEQUENCES = 6


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


@dataclass
class BridgeScriptConfig:
    selected_script_id: str
    allowed_worker_scripts: tuple[str, ...]
    child_worker_scripts: tuple[dict[str, Any], ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return configs


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
    sort_command_queue(queue)

    drain_count = command_queue_drain_count(request, adapter_output)
    drained_entries = queue.get("entries", [])[:drain_count]
    drained_commands = [command_for_sequence(entry.get("command", {}), request, index + 1) for index, entry in enumerate(drained_entries)]

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
    }
    return adapter_output


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


def sort_command_queue(queue: dict[str, Any]) -> None:
    entries = queue.get("entries") if isinstance(queue.get("entries"), list) else []
    queue["entries"] = sorted(
        entries,
        key=lambda entry: (
            source_priority(entry.get("command") if isinstance(entry.get("command"), dict) else {}),
            command_priority(entry.get("command") if isinstance(entry.get("command"), dict) else {}),
            int(entry.get("first_seen_sequence", 0) or 0),
            str(entry.get("key", "")),
        ),
    )


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
    if kind == "write_text_surface":
        return 11
    if kind == "transfer_item" and str(command.get("reason", "")) == "refinery_output_cleanup":
        return 12
    if kind == "transfer_item" and str(command.get("reason", "")) == "assembler_output_cleanup":
        return 13
    if kind == "transfer_item" and str(command.get("reason", "")) == "refinery_input_unload":
        return 14
    if kind == "transfer_item" and str(command.get("reason", "")) == "inventory_sorting":
        return 15
    if kind == "write_block_custom_data":
        return 16
    if kind in {"set_use_conveyor", "set_block_enabled", "set_light_color", "set_assembler_cooperative_mode", "set_gas_auto_refill"}:
        return 20
    if kind == "transfer_item":
        subtype = str(command.get("item_subtype_id", "")).lower()
        type_id = str(command.get("item_type_id", "")).lower()
        if subtype == "uranium" and "ingot" in type_id:
            return 18
        if subtype == "ice" and str(command.get("reason", "")) == "gas_generator_topup":
            return 18
        if "ore" in type_id and str(command.get("reason", "")) in {"refinery_ore_input", "autocrafting_ore_refining"}:
            return 18
        if subtype == "ice":
            return 60
        if "ingot" in type_id:
            return 19
        return 45
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


def command_for_sequence(command: dict[str, Any], request: dict[str, Any], index: int) -> dict[str, Any]:
    emitted = dict(command)
    emitted["command_id"] = f"{request.get('bridge_id', 'bridge')}:{request.get('sequence', 0)}:queue:{index}:{emitted.get('kind', 'command')}"
    return emitted


def safe_file_name(value: str) -> str:
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in value)
    return safe or "bridge"


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


def execute_request(
    request: dict[str, Any],
    scripts: dict[str, WorkerScript],
    bridge_configs: dict[str, BridgeScriptConfig] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    validation = validate_request(request)
    if validation != "none":
        return result_for(request, "rejected", {}, validation)

    script_id = str(request["script_id"])
    bridge_config = (bridge_configs or {}).get(str(request["bridge_id"]))
    if bridge_config is not None and bridge_config.allowed_worker_scripts and script_id not in bridge_config.allowed_worker_scripts:
        return result_for(request, "rejected", {}, "script_not_allowed_for_bridge")

    script = scripts.get(script_id)
    if script is None:
        return result_for(request, "rejected", {}, "script_not_found")
    if not script.enabled:
        return result_for(request, "rejected", {}, "script_disabled")
    if script_id == "bridge_orchestrator":
        return execute_orchestrator_request(request, scripts, bridge_configs or {}, bridge_config, root)

    try:
        active_root = root or Path(os.environ.get("NOVALI_CLIENT_SIDE_PB_ROOT", "."))
        request["worker_config"] = load_worker_config(active_root, script_id)
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
            if root is not None and status == "ok" and error_bucket == "none":
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
    allowed = set(bridge_config.allowed_worker_scripts if bridge_config is not None else ())
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
        child_result = execute_request(child_request, scripts, bridge_configs, root=None)
        result_payload = child_result.get("result") if isinstance(child_result.get("result"), dict) else {}
        child_results.append(
            {
                "script_id": child_id,
                "status": child_result.get("status", "unknown"),
                "error_bucket": child_result.get("error_bucket", "none"),
                "summary": result_payload.get("summary", ""),
            }
        )
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
        child_commands = [command for command in result_payload.get("commands", []) if isinstance(command, dict)]
        for command in child_commands[:budget]:
            tagged = dict(command)
            tagged.setdefault("source_script_id", child_id)
            tagged.setdefault("source_priority", priority)
            tagged.setdefault("source_order", index)
            merged_commands.append(tagged)

    merged_commands.sort(key=lambda command: (int(command.get("source_priority", 50) or 50), int(command.get("source_order", 0) or 0)))
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
        "child_results": child_results,
    }
    if root is not None:
        output = apply_command_queue(root, request, output)
    return result_for(request, "ok", output, "none")


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
    scripts[script_id] = {
        "compiled": status == "supported",
        "status": status,
        "unsupported_apis": compatibility.get("unsupported_apis", []),
        "supported_block_types": compatibility.get("supported_block_types", []),
        "emitted_command_kinds": emitted_kinds,
        "last_run_status": str(output.get("adapter_status", output.get("status", "ok")) or "ok"),
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
        result_path.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
        if result.get("bridge_id"):
            limiter_states[str(result["bridge_id"])] = str(result.get("limiter_state", "unknown"))
        archived = processed_dir / f"{request_path.stem}-{int(time.time() * 1000)}.json"
        request_path.replace(archived)
        count += 1
    status_path = root / "data" / "worker_status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_status.v1",
                "updated_at": utc_now(),
                "processed": count,
                "limiter_states": limiter_states,
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


def render_status_page(root: Path) -> str:
    worker_status = load_status_json(root, "worker_status.json")
    plugin_status = load_status_json(root, "plugin_status.json")
    virtual_pb = load_status_json(root, "virtual_pb_compatibility.json")
    bridge_scripts = load_status_json(root, "bridge_scripts.json")
    limiter_states = worker_status.get("limiter_states") if isinstance(worker_status.get("limiter_states"), dict) else {}
    virtual_scripts = virtual_pb.get("scripts") if isinstance(virtual_pb.get("scripts"), dict) else {}
    bridge_rows = "".join(
        f"<tr><td>{html.escape(str(bridge_id))}</td><td>{html.escape(str(state))}</td></tr>"
        for bridge_id, state in sorted(limiter_states.items())
    ) or "<tr><td colspan=\"2\">No bridge requests processed yet.</td></tr>"
    virtual_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(script_id))}</td>"
        f"<td>{html.escape(str(report.get('status', 'unknown')))}</td>"
        f"<td>{html.escape(', '.join(str(kind) for kind in report.get('emitted_command_kinds', [])))}</td>"
        "</tr>"
        for script_id, report in sorted(virtual_scripts.items())
        if isinstance(report, dict)
    ) or "<tr><td colspan=\"3\">No virtual PB compatibility report yet.</td></tr>"
    selected_scripts = []
    bridges = bridge_scripts.get("bridges") if isinstance(bridge_scripts.get("bridges"), dict) else {}
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
    main {{ max-width: 980px; margin: 0 auto; }}
    h1 {{ font-size: 26px; margin: 0 0 18px; letter-spacing: 0; }}
    h2 {{ font-size: 16px; margin: 22px 0 10px; letter-spacing: 0; }}
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
  <section class="grid">
    <div class="metric"><div class="label">Processed requests</div><div class="value">{html.escape(str(worker_status.get('processed', 0)))}</div></div>
    <div class="metric"><div class="label">Worker updated</div><div class="value">{html.escape(str(worker_status.get('updated_at', 'not yet')))}</div></div>
    <div class="metric"><div class="label">Plugin state</div><div class="value">{html.escape(str(plugin_status.get('state', 'unknown')))}</div></div>
  </section>
  <h2>Bridge Assignments</h2>
  <p><code>{html.escape(selected_text)}</code></p>
  <h2>Limiter States</h2>
  <table><thead><tr><th>Bridge</th><th>State</th></tr></thead><tbody>{bridge_rows}</tbody></table>
  <h2>Virtual PB Compatibility</h2>
  <table><thead><tr><th>Script</th><th>Status</th><th>Command Kinds</th></tr></thead><tbody>{virtual_rows}</tbody></table>
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
                }
                body = json.dumps(payload, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
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
