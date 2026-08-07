from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from worker.virtual_pb import analyze_virtual_pb_script


REPORT_SCHEMA = "novali.client_side_pb.adapter_prep_report.v1"


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


def update_manifest(root: Path, script_id: str, module_name: str, display_name: str) -> None:
    manifest_path = root / "worker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scripts = manifest.setdefault("scripts", [])
    for item in scripts:
        if item.get("script_id") == script_id:
            item["display_name"] = display_name
            item["module"] = f"worker.scripts.{module_name}"
            item["source"] = "workshop_import"
            item["enabled"] = False
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
                "enabled": False,
            }
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def can_prepare_virtual_pb(compatibility: dict[str, Any]) -> bool:
    block_types = compatibility.get("supported_block_types")
    return (
        compatibility.get("status") == "supported"
        and compatibility.get("uses_grid_terminal_system") is True
        and isinstance(block_types, list)
        and bool(block_types)
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
    compatibility = analyze_virtual_pb_script(imported_script)

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
            "analysis": analyze_script(imported_script),
            "compatibility": compatibility,
            "status": "virtual_pb_ready",
            "meaning": "This Workshop PB script fits the reviewed virtual PB subset. It was imported unchanged and registered as a virtual_pb_csharp worker script.",
        }
        report_path = import_dir / "adapter_report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        mark_catalog_prepared(catalog_path, workshop_id, f"Virtual PB adapter: {script_id}", "virtual_pb_ready")
        return report

    module_name = safe_module_name(workshop_id)
    script_id = f"workshop_{workshop_id}_adapter"
    module_path = root / "worker" / "scripts" / f"{module_name}.py"
    create_adapter_source(module_path, workshop_id, display_name)
    update_manifest(root, script_id, module_name, display_name)

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
        "analysis": analyze_script(imported_script),
        "status": "adapter_scaffold_created",
        "meaning": "manual_adapter_required means the Workshop PB script is available locally, but it cannot be safely executed unchanged outside Space Engineers. The scaffold is a starting point for mapping PB state to external worker logic.",
    }
    report_path = import_dir / "adapter_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    mark_catalog_prepared(catalog_path, workshop_id, f"Adapter scaffold: {script_id}")
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
