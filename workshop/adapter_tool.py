from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from worker.virtual_pb import analyze_virtual_pb_script
from workshop.profile_pack import profile_for_workshop


REPORT_SCHEMA = "novali.client_side_pb.adapter_prep_report.v1"
WORKER_CONFIG_SCHEMA = "novali.client_side_pb.worker_config.v1"


ISY_PROFILE_DEFAULT_CONFIG = [
    ("inventorySortingEnabled", True, "bool", "Enable Isy inventory sorting command planning for this worker."),
    ("inventorySortingDryRun", False, "bool", "Report planned sorting commands without applying them."),
    ("maxApplyCommands", 8, "int", "Maximum commands the PB shim may apply from one result when runtime budget allows."),
    ("maxPlannedTransfers", 16, "int", "Maximum transfer or rename commands the worker plans per tick."),
    ("maxPlannedMachineCommands", 12, "int", "Maximum Isy machine setup/autocrafting commands planned per tick."),
    ("allowConnectedGrids", False, "bool", "Allow planning and applying commands across connected grids."),
    ("virtualPbCustomData", "", "multiline_text", "Virtual PB CustomData, including Isy-style itemID;blueprintID mappings used by scripts that read Me.CustomData."),
]


def safe_module_name(workshop_id: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", workshop_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "workshop_" + cleaned
    return cleaned + "_adapter"


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_record(catalog: dict[str, Any], workshop_id: str) -> dict[str, Any]:
    for record in catalog.get("records", []):
        if str(record.get("workshop_id", "")) == workshop_id:
            return record
    raise ValueError(f"Workshop id not found in catalog: {workshop_id}")


def analyze_script(source: Path) -> dict[str, Any]:
    text = source.read_text(encoding="utf-8", errors="replace")
    return {
        "line_count": len(text.splitlines()),
        "character_count": len(text),
        "has_main": "void Main(" in text or "public void Main(" in text,
        "uses_grid_terminal_system": "GridTerminalSystem" in text,
        "uses_runtime": "Runtime." in text,
        "uses_igc": "IGC" in text,
        "uses_me_custom_data": "Me.CustomData" in text,
    }


def detect_known_profile(workshop_id: str, display_name: str, source: Path) -> dict[str, Any] | None:
    packed = profile_for_workshop(workshop_id, display_name)
    if packed is not None and packed.get("strategy") == "profile_adapter":
        return {
            "profile_id": str(packed.get("profile_id", "")),
            "profile_confidence": "high",
            "profile_reason": f"matched reviewed profile pack entry for Workshop {workshop_id}",
        }
    text = source.read_text(encoding="utf-8", errors="replace").lower()
    title = display_name.lower()
    is_isy_id = workshop_id == "1216126863"
    has_isy_title = "isy" in title and "inventory" in title
    has_isy_source = "isy's inventory manager" in text or "iim-" in text or "iim_" in text
    if is_isy_id or (has_isy_title and has_isy_source):
        return {
            "profile_id": "isy_inventory_manager",
            "profile_confidence": "high" if is_isy_id else "medium",
            "profile_reason": "matched Isy's Inventory Manager workshop id"
            if is_isy_id
            else "matched Isy's Inventory Manager title and source markers",
        }
    return None


def create_adapter_source(module_path: Path, workshop_id: str, display_name: str) -> None:
    if module_path.exists():
        return
    module_path.write_text(
        f'''from __future__ import annotations

from typing import Any


def run(request: dict[str, Any]) -> dict[str, Any]:
    """Adapter scaffold for Workshop {workshop_id}: {display_name}."""
    state = request.get("state") if isinstance(request.get("state"), dict) else {{}}
    return {{
        "summary": "Adapter scaffold created; manual mapping still required.",
        "commands": [
            {{
                "kind": "echo",
                "text": "Adapter scaffold for Workshop {workshop_id} needs implementation."
            }}
        ],
        "observed_state_keys": sorted(state.keys()),
    }}
''',
        encoding="utf-8",
    )


def create_profile_adapter_source(module_path: Path, profile_id: str) -> None:
    if profile_id != "isy_inventory_manager":
        raise ValueError(f"Unknown adapter profile: {profile_id}")
    module_path.write_text(
        '''from __future__ import annotations

from typing import Any

from worker.isy_foundation import plan_isy_foundation


def run(request: dict[str, Any]) -> dict[str, Any]:
    return plan_isy_foundation(request)
''',
        encoding="utf-8",
    )


def update_manifest(
    root: Path,
    script_id: str,
    module_name: str,
    display_name: str,
    workshop_id: str | None = None,
    enabled: bool | None = None,
    profile_id: str = "",
) -> None:
    manifest_path = root / "worker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scripts = manifest.setdefault("scripts", [])
    if workshop_id:
        virtual_source_path = f"data/imports/{workshop_id}/Script.cs"
        scripts[:] = [
            item
            for item in scripts
            if not (
                item.get("runtime") == "virtual_pb_csharp"
                and str(item.get("source_path", "")).replace("\\", "/") == virtual_source_path
            )
        ]
    for item in scripts:
        if item.get("script_id") == script_id:
            item["display_name"] = display_name
            item["module"] = f"worker.scripts.{module_name}"
            item["source"] = "workshop_import"
            item["input_schema"] = str(item.get("input_schema") or "adapter_tick.v1")
            item["output_schema"] = str(item.get("output_schema") or "compact_commands.v1")
            item["timeout_ms"] = int(item.get("timeout_ms", 1000) or 1000)
            item["enabled"] = bool(item.get("enabled", False)) if enabled is None else enabled
            if profile_id:
                item["profile_id"] = profile_id
            else:
                item.pop("profile_id", None)
            break
    else:
        scripts.append(
            {
                "script_id": script_id,
                "source": "workshop_import",
                "display_name": display_name,
                "module": f"worker.scripts.{module_name}",
                "input_schema": "adapter_tick.v1",
                "output_schema": "compact_commands.v1",
                "timeout_ms": 1000,
                "enabled": False if enabled is None else enabled,
                **({"profile_id": profile_id} if profile_id else {}),
            }
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def seed_profile_worker_config(root: Path, script_id: str, display_name: str, profile_id: str) -> None:
    if profile_id != "isy_inventory_manager":
        return
    path = root / "data" / "worker_configs" / f"{script_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    else:
        payload = {}
    payload["schema"] = WORKER_CONFIG_SCHEMA
    payload["script_id"] = script_id
    payload["display_name"] = display_name
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    existing = {str(entry.get("key", "")).lower() for entry in entries if isinstance(entry, dict)}
    for key, value, value_type, description in ISY_PROFILE_DEFAULT_CONFIG:
        if key.lower() in existing:
            continue
        entries.append({"key": key, "value": value, "value_type": value_type, "description": description})
    payload["entries"] = entries
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def can_prepare_virtual_pb(compatibility: dict[str, Any]) -> bool:
    block_types = compatibility.get("supported_block_types")
    return (
        compatibility.get("status") == "supported"
        and compatibility.get("compiled") is True
        and compatibility.get("uses_grid_terminal_system") is True
        and isinstance(block_types, list)
        and bool(block_types)
    )


def is_virtual_pb_blocked(compatibility: dict[str, Any]) -> bool:
    blocked = compatibility.get("blocked_command_mappings")
    return (
        compatibility.get("status") == "blocked_command_mapping"
        or (isinstance(blocked, list) and bool(blocked))
    )


def upsert_virtual_manifest(root: Path, workshop_id: str, display_name: str) -> str:
    manifest_path = root / "worker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scripts = manifest.setdefault("scripts", [])
    source_path = f"data/imports/{workshop_id}/Script.cs"
    manual_script_id = f"workshop_{workshop_id}_adapter"
    selected: dict[str, Any] | None = None
    kept_scripts = []
    for item in scripts:
        if item.get("script_id") == manual_script_id:
            continue
        if item.get("runtime") == "virtual_pb_csharp" and str(item.get("source_path", "")).replace("\\", "/") == source_path:
            selected = item
        kept_scripts.append(item)
    scripts[:] = kept_scripts
    if selected is None:
        selected = {
            "script_id": f"virtual_workshop_{workshop_id}",
            "source": "workshop_import",
            "display_name": display_name + " (Virtual PB)",
            "runtime": "virtual_pb_csharp",
            "source_path": source_path,
            "input_schema": "virtual_pb_tick.v1",
            "output_schema": "compact_commands.v1",
            "timeout_ms": 5000,
            "enabled": True,
        }
        scripts.append(selected)
    else:
        selected["source"] = "workshop_import"
        selected["display_name"] = str(selected.get("display_name") or display_name + " (Virtual PB)")
        selected["runtime"] = "virtual_pb_csharp"
        selected["source_path"] = source_path
        selected["input_schema"] = "virtual_pb_tick.v1"
        selected["output_schema"] = "compact_commands.v1"
        selected["timeout_ms"] = int(selected.get("timeout_ms", 5000) or 5000)
        selected["enabled"] = True
    module_path = root / "worker" / "scripts" / f"{safe_module_name(workshop_id)}.py"
    if module_path.exists():
        module_path.unlink()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return str(selected["script_id"])


def mark_catalog_prepared(catalog_path: Path, workshop_id: str, notes: str, compatibility: str = "adapter_scaffold_created") -> None:
    catalog = load_catalog(catalog_path)
    for record in catalog.get("records", []):
        if str(record.get("workshop_id", "")) == workshop_id:
            record["compatibility"] = compatibility
            record["notes"] = notes
            break
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def save_compatibility_summary(root: Path, script_id: str, compatibility: dict[str, Any], report_status: str, summary: str) -> None:
    path = root / "data" / "virtual_pb_compatibility.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        payload = {"schema": "novali.client_side_pb.virtual_pb_compatibility.v1", "scripts": {}}
    now = datetime.now(timezone.utc).isoformat()
    scripts = payload.setdefault("scripts", {})
    scripts[script_id] = {
        "compiled": compatibility.get("compiled", False),
        "status": compatibility.get("status", report_status),
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
        "emitted_command_kinds": compatibility.get("emitted_command_kinds", []),
        "last_run_status": report_status,
        "summary": summary,
        "updated_at": now,
    }
    payload["updated_at"] = now
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def prepare_adapter(root: Path, catalog_path: Path, workshop_id: str) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    record = find_record(catalog, workshop_id)
    if record.get("detected_kind") != "pb_script":
        raise ValueError(f"Only pb_script records can be prepared, got {record.get('detected_kind')}")
    source = Path(str(record.get("source_path", "")))
    if not source.exists():
        raise FileNotFoundError(source)

    display_name = str(record.get("workshop_title") or record.get("detected_title") or f"Workshop {workshop_id}")
    import_dir = root / "data" / "imports" / workshop_id
    import_dir.mkdir(parents=True, exist_ok=True)
    imported_script = import_dir / "Script.cs"
    shutil.copy2(source, imported_script)
    compatibility = analyze_virtual_pb_script(imported_script, root)
    analysis = analyze_script(imported_script)

    if can_prepare_virtual_pb(compatibility):
        script_id = upsert_virtual_manifest(root, workshop_id, display_name)
        report = {
            "schema": REPORT_SCHEMA,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "workshop_id": workshop_id,
            "display_name": display_name,
            "script_id": script_id,
            "runtime": "virtual_pb_csharp",
            "enabled": True,
            "source_path": str(source),
            "imported_script": str(imported_script),
            "analysis": analysis,
            "compatibility": compatibility,
            "status": "virtual_pb_ready",
            "meaning": "This Workshop PB script fits the reviewed virtual PB subset. It was imported unchanged and registered as a virtual_pb_csharp worker script.",
        }
        report_path = import_dir / "adapter_report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        mark_catalog_prepared(catalog_path, workshop_id, f"Virtual PB adapter: {script_id}", "virtual_pb_ready")
        save_compatibility_summary(root, script_id, compatibility, "virtual_pb_ready", report["meaning"])
        return report

    profile = detect_known_profile(workshop_id, display_name, imported_script)
    if profile is not None:
        module_name = safe_module_name(workshop_id)
        script_id = f"workshop_{workshop_id}_adapter"
        module_path = root / "worker" / "scripts" / f"{module_name}.py"
        create_profile_adapter_source(module_path, str(profile["profile_id"]))
        update_manifest(
            root,
            script_id,
            module_name,
            display_name,
            workshop_id,
            enabled=True,
            profile_id=str(profile["profile_id"]),
        )
        seed_profile_worker_config(root, script_id, display_name, str(profile["profile_id"]))
        report_meaning = (
            "This Workshop PB script matched a reviewed framework profile. "
            "It was imported unchanged and registered as an enabled Python profile adapter."
        )
        profile_compatibility = dict(compatibility)
        profile_compatibility["status"] = "profile_adapter_ready"
        report = {
            "schema": REPORT_SCHEMA,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "workshop_id": workshop_id,
            "display_name": display_name,
            "script_id": script_id,
            "module": f"worker.scripts.{module_name}",
            "runtime": "python",
            "enabled": True,
            "profile_id": profile["profile_id"],
            "profile_confidence": profile["profile_confidence"],
            "profile_reason": profile["profile_reason"],
            "source_path": str(source),
            "imported_script": str(imported_script),
            "analysis": analysis,
            "compatibility": profile_compatibility,
            "status": "profile_adapter_ready",
            "meaning": report_meaning,
        }
        report_path = import_dir / "adapter_report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        mark_catalog_prepared(catalog_path, workshop_id, f"Profile adapter: {script_id}", "profile_adapter_ready")
        save_compatibility_summary(root, script_id, profile_compatibility, "profile_adapter_ready", report_meaning)
        return report

    module_name = safe_module_name(workshop_id)
    script_id = f"workshop_{workshop_id}_adapter"
    module_path = root / "worker" / "scripts" / f"{module_name}.py"
    create_adapter_source(module_path, workshop_id, display_name)
    update_manifest(root, script_id, module_name, display_name, workshop_id)

    blocked = is_virtual_pb_blocked(compatibility)
    report_status = "virtual_pb_blocked" if blocked else "adapter_scaffold_created"
    report_meaning = (
        "This Workshop PB script is close to the virtual PB subset, but needs reviewed command mappings before it can run unchanged."
        if blocked
        else "manual_adapter_required means the Workshop PB script is available locally, but it cannot be safely executed unchanged outside Space Engineers. The scaffold is a starting point for mapping PB state to external worker logic."
    )
    report = {
        "schema": REPORT_SCHEMA,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "workshop_id": workshop_id,
        "display_name": display_name,
        "script_id": script_id,
        "module": f"worker.scripts.{module_name}",
        "enabled": False,
        "source_path": str(source),
        "imported_script": str(imported_script),
        "analysis": analysis,
        "compatibility": compatibility,
        "status": report_status,
        "meaning": report_meaning,
    }
    report_path = import_dir / "adapter_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    mark_catalog_prepared(catalog_path, workshop_id, f"Adapter scaffold: {script_id}", report_status)
    save_compatibility_summary(root, script_id, compatibility, report_status, report_meaning)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a Workshop PB script adapter scaffold.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--catalog", type=Path, default=Path("data/workshop_catalog.json"))
    parser.add_argument("--workshop-id", required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    catalog = args.catalog if args.catalog.is_absolute() else root / args.catalog
    report = prepare_adapter(root, catalog, args.workshop_id)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
