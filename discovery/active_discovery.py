from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from workshop.profile_pack import operator_status_for_compatibility, operator_status_label, profile_for_workshop


DISCOVERY_SCHEMA = "novali.client_side_pb.discovery_report.v1"
API_SURFACE_SCHEMA = "novali.client_side_pb.se_api_surface.v1"
HARNESS_ALIGNMENT_SCHEMA = "novali.client_side_pb.harness_alignment.v1"
HARNESS_UPDATE_PLAN_SCHEMA = "novali.client_side_pb.harness_update_plan.v1"


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return default or {}
    return payload if isinstance(payload, dict) else default or {}


def standard_space_engineers_save_roots() -> list[Path]:
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        roots.append(Path(appdata) / "SpaceEngineers" / "Saves")
        roots.append(Path(appdata) / "SpaceEngineersDedicated" / "Saves")
    if programdata:
        roots.append(Path(programdata) / "SpaceEngineersDedicated")
    return roots


def standard_space_engineers_bin64() -> Path | None:
    path = Path("C:/Program Files (x86)/Steam/steamapps/common/SpaceEngineers/Bin64")
    return path if path.exists() else None


def find_space_engineers_saves(save_roots: Iterable[Path]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for root in save_roots:
        if not root.exists():
            continue
        try:
            configs = sorted(root.rglob("Sandbox_config.sbc"), key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for config in configs[:8]:
            try:
                updated = datetime.fromtimestamp(config.stat().st_mtime, timezone.utc).isoformat()
            except OSError:
                updated = ""
            hints.append(
                {
                    "name": config.parent.name,
                    "config_path": str(config),
                    "updated_at": updated,
                }
            )
    return sorted(hints, key=lambda item: item.get("updated_at", ""), reverse=True)[:8]


def discover_bridge_ids(root: Path, bridge_scripts: dict[str, Any], bridge_health: dict[str, Any]) -> list[str]:
    bridge_ids: set[str] = set()
    bridges = bridge_scripts.get("bridges")
    if isinstance(bridges, dict):
        bridge_ids.update(str(key) for key in bridges.keys())
    health_bridges = bridge_health.get("bridges")
    if isinstance(health_bridges, dict):
        bridge_ids.update(str(key) for key in health_bridges.keys())
    for folder in ("bridge_requests", "bridge_results"):
        path = root / "data" / folder
        if not path.exists():
            continue
        for item in path.glob("*.json"):
            bridge_ids.add(item.stem)
    return sorted(bridge_id for bridge_id in bridge_ids if not is_discovery_ignored_bridge(bridge_id))


def is_discovery_ignored_bridge(bridge_id: str) -> bool:
    return bridge_id.startswith("codex-guided-smoke-")


def bridge_status_for(bridge_id: str, plugin: dict[str, Any], health: dict[str, Any], repair_actions: set[str]) -> dict[str, Any]:
    marked_mailboxes = int(plugin.get("marked_mailboxes", 0) or 0)
    health_bridges = health.get("bridges") if isinstance(health.get("bridges"), dict) else {}
    bridge_health = health_bridges.get(bridge_id) if isinstance(health_bridges.get(bridge_id), dict) else {}
    health_status = str(bridge_health.get("status", "") or "")
    request_sequence = int(bridge_health.get("last_request_sequence", 0) or 0)
    result_sequence = int(bridge_health.get("last_result_sequence", 0) or 0)

    if health_status == "concealed_suspected" or request_sequence > result_sequence:
        operator_status = "stale_mailbox"
        repair_actions.add("run_pb_heartbeat")
        if marked_mailboxes <= 0:
            repair_actions.add("copy_pb_custom_data")
            repair_actions.add("paste_reviewed_pb_shim")
    elif marked_mailboxes <= 0:
        operator_status = "missing_shim"
        repair_actions.add("copy_pb_custom_data")
        repair_actions.add("paste_reviewed_pb_shim")
    else:
        operator_status = "ready"

    return {
        "bridge_id": bridge_id,
        "operator_status": operator_status,
        "health_status": health_status or "unknown",
        "last_request_sequence": request_sequence,
        "last_result_sequence": result_sequence,
        "marked_mailboxes": marked_mailboxes,
    }


def discover_workshop_scripts(root: Path, catalog: dict[str, Any], compatibility: dict[str, Any]) -> list[dict[str, Any]]:
    records = catalog.get("records") if isinstance(catalog.get("records"), list) else []
    compatibility_scripts = compatibility.get("scripts") if isinstance(compatibility.get("scripts"), dict) else {}
    scripts: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("detected_kind") != "pb_script":
            continue
        workshop_id = str(record.get("workshop_id", "") or "")
        title = str(record.get("workshop_title") or record.get("detected_title") or workshop_id)
        compat_status = str(record.get("compatibility", "") or "manual_adapter_required")
        profile = profile_for_workshop(workshop_id, title, root)
        script_id = str((profile or {}).get("script_id") or f"workshop_{workshop_id}_adapter")
        compat_detail = compatibility_scripts.get(script_id) if isinstance(compatibility_scripts.get(script_id), dict) else {}
        operator_status = operator_status_for_compatibility(compat_status, compat_detail, profile)
        scripts.append(
            {
                "workshop_id": workshop_id,
                "display_name": title,
                "script_id": script_id,
                "compatibility": compat_status,
                "operator_status": operator_status,
                "operator_label": operator_status_label(operator_status),
                "safe_default_enabled": bool((profile or {}).get("safe_default_enabled", False)),
                "role": str((profile or {}).get("role", "")),
                "blocked_command_mappings": compat_detail.get("blocked_command_mappings", []),
                "missing_snapshot_fields": compat_detail.get("missing_snapshot_fields", []),
            }
        )
    return scripts


def summarize_api_probe(api_surface: dict[str, Any], alignment: dict[str, Any], capabilities: dict[str, Any], repair_actions: set[str]) -> dict[str, Any]:
    surface_seen = api_surface.get("schema") == API_SURFACE_SCHEMA
    alignment_seen = alignment.get("schema") == HARNESS_ALIGNMENT_SCHEMA
    surface_hash = str(api_surface.get("api_hash", "") or "")
    alignment_hash = str(alignment.get("api_hash", "") or "")
    stale = bool(surface_seen and alignment_seen and surface_hash and alignment_hash and surface_hash != alignment_hash)
    summary = alignment.get("summary") if isinstance(alignment.get("summary"), dict) else {}

    if not surface_seen or not alignment_seen or stale:
        status = "stale_probe" if stale else "missing_probe"
        repair_actions.add("run_api_probe")
    else:
        status = str(alignment.get("operator_status", "") or "unknown")
        if status == "needs_mapping_review":
            repair_actions.add("review_api_mappings")
        elif status == "needs_harness_update":
            repair_actions.add("update_virtual_pb_harness")

    return {
        "status": status,
        "surface_status": "seen" if surface_seen else "missing",
        "alignment_status": "seen" if alignment_seen else "missing",
        "stale": stale,
        "api_hash": surface_hash,
        "alignment_api_hash": alignment_hash,
        "harness_capability_version": str(
            alignment.get("harness_capability_version")
            or capabilities.get("capability_version")
            or ""
        ),
        "generated_at": str(api_surface.get("generated_at", "") or ""),
        "aligned_at": str(alignment.get("generated_at", "") or ""),
        "summary": {
            "supported": int(summary.get("supported", 0) or 0),
            "missing_read_stub": int(summary.get("missing_read_stub", 0) or 0),
            "mutation_requires_command_mapping": int(summary.get("mutation_requires_command_mapping", 0) or 0),
            "blocked_for_safety": int(summary.get("blocked_for_safety", 0) or 0),
            "partial_traversal": int(summary.get("partial_traversal", 0) or 0),
        },
    }


def summarize_harness_update_plan(plan: dict[str, Any], repair_actions: set[str]) -> dict[str, Any]:
    seen = plan.get("schema") == HARNESS_UPDATE_PLAN_SCHEMA
    if not seen:
        repair_actions.add("run_api_probe")
        return {
            "status": "missing",
            "next_recommended_action": "run_api_probe",
            "summary": {
                "read_only_stub_queue": 0,
                "mapping_review_queue": 0,
                "blocked_for_safety_queue": 0,
            },
            "top_read_only_stubs": [],
            "top_mapping_reviews": [],
            "top_blocked_for_safety": [],
        }
    status = str(plan.get("operator_status", "") or "unknown")
    next_action = str(plan.get("next_recommended_action", "") or "")
    if next_action == "add_read_only_stubs":
        repair_actions.add("prioritize_read_only_stubs")
    elif next_action == "review_command_mappings":
        repair_actions.add("review_api_mappings")
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    return {
        "status": status,
        "next_recommended_action": next_action,
        "summary": {
            "read_only_stub_queue": int(summary.get("read_only_stub_queue", 0) or 0),
            "mapping_review_queue": int(summary.get("mapping_review_queue", 0) or 0),
            "blocked_for_safety_queue": int(summary.get("blocked_for_safety_queue", 0) or 0),
        },
        "top_read_only_stubs": top_plan_members(plan.get("read_only_stub_queue")),
        "top_mapping_reviews": top_plan_members(plan.get("mapping_review_queue")),
        "top_blocked_for_safety": top_plan_members(plan.get("blocked_for_safety_queue")),
    }


def top_plan_members(value: Any, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    members: list[str] = []
    for item in value[:limit]:
        if isinstance(item, dict) and item.get("member"):
            members.append(str(item["member"]))
    return members


def generate_discovery_report(
    root: Path,
    *,
    now: str | None = None,
    standard_save_roots: list[Path] | None = None,
    run_api_probe: bool = False,
    api_source_path: Path | None = None,
    space_engineers_bin64: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    data = root / "data"
    if run_api_probe:
        try:
            from discovery.api_probe import write_api_probe_reports

            write_api_probe_reports(
                root=root,
                source_path=api_source_path or Path("virtual_pb_runner/Program.cs"),
                surface_output=data / "se_api_surface.json",
                alignment_output=data / "harness_alignment.json",
                space_engineers_bin64=space_engineers_bin64 or standard_space_engineers_bin64(),
            )
        except (OSError, RuntimeError, ValueError):
            pass
    plugin = read_json(data / "plugin_status.json")
    worker_status = read_json(data / "worker_status.json")
    bridge_scripts = read_json(data / "bridge_scripts.json")
    bridge_health = read_json(data / "bridge_health.json")
    workshop_catalog = read_json(data / "workshop_catalog.json")
    compatibility = read_json(data / "virtual_pb_compatibility.json")
    api_surface = read_json(data / "se_api_surface.json")
    harness_alignment = read_json(data / "harness_alignment.json")
    harness_update_plan = read_json(data / "harness_update_plan.json")
    virtual_pb_capabilities = read_json(data / "virtual_pb_capabilities.json")
    repair_actions: set[str] = set()

    if not worker_status:
        repair_actions.add("start_docker")
    if not workshop_catalog:
        repair_actions.add("scan_workshop")
    if not plugin:
        repair_actions.add("build_plugin")
        repair_actions.add("handoff_plugin")

    bridge_ids = discover_bridge_ids(root, bridge_scripts, bridge_health)
    bridges = [bridge_status_for(bridge_id, plugin, bridge_health, repair_actions) for bridge_id in bridge_ids]
    if not bridges:
        repair_actions.add("create_bridge")

    workshop_scripts = discover_workshop_scripts(root, workshop_catalog, compatibility)
    if any(item["operator_status"] in {"ready_profile", "ready_virtual_pb"} for item in workshop_scripts):
        repair_actions.add("build_multi_script_bridge")

    api_probe = summarize_api_probe(api_surface, harness_alignment, virtual_pb_capabilities, repair_actions)
    harness_plan = summarize_harness_update_plan(harness_update_plan, repair_actions)
    saves = find_space_engineers_saves(standard_save_roots or standard_space_engineers_save_roots())
    return {
        "schema": DISCOVERY_SCHEMA,
        "generated_at": now or datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "plugin": {
            "status": str(plugin.get("status") or plugin.get("state") or "unknown"),
            "marked_mailboxes": int(plugin.get("marked_mailboxes", 0) or 0),
            "updated_at": str(plugin.get("updated_at", "") or ""),
        },
        "docker": {
            "status": "worker_status_seen" if worker_status else "unknown",
            "updated_at": str(worker_status.get("updated_at", "") or ""),
        },
        "space_engineers": {
            "active_save_status": "found" if saves else "not_found",
            "active_save_hints": saves,
        },
        "api_probe": api_probe,
        "harness_update_plan": harness_plan,
        "bridges": bridges,
        "workshop_scripts": workshop_scripts,
        "repair_actions": sorted(repair_actions),
    }


def write_discovery_report(
    root: Path,
    output: Path,
    *,
    run_api_probe: bool = False,
    api_source_path: Path | None = None,
    space_engineers_bin64: Path | None = None,
) -> dict[str, Any]:
    report = generate_discovery_report(
        root,
        run_api_probe=run_api_probe,
        api_source_path=api_source_path,
        space_engineers_bin64=space_engineers_bin64,
    )
    output = output if output.is_absolute() else root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover current client-side PB bridge readiness.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("data/discovery_report.json"))
    parser.add_argument("--run-api-probe", action="store_true", help="Refresh data/se_api_surface.json and data/harness_alignment.json before discovery.")
    parser.add_argument("--api-source", type=Path, default=Path("virtual_pb_runner/Program.cs"))
    parser.add_argument("--space-engineers-bin64", type=Path, default=None)
    args = parser.parse_args()
    report = write_discovery_report(
        args.root,
        args.output,
        run_api_probe=args.run_api_probe,
        api_source_path=args.api_source,
        space_engineers_bin64=args.space_engineers_bin64,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
