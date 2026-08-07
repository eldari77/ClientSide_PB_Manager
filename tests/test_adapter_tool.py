import json
from pathlib import Path

from workshop.adapter_tool import prepare_adapter, safe_module_name


def test_safe_module_name_prefixes_numeric_id():
    assert safe_module_name("123") == "workshop_123_adapter"


def test_prepare_adapter_creates_scaffold_and_manifest(tmp_path: Path):
    root = tmp_path
    source_dir = root / "steam" / "123"
    source_dir.mkdir(parents=True)
    source = source_dir / "Script.cs"
    source.write_text("public void Main(string argument) {}\n", encoding="utf-8")
    catalog = root / "data" / "workshop_catalog.json"
    catalog.parent.mkdir()
    catalog.write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.workshop_catalog.v1",
                "records": [
                    {
                        "workshop_id": "123",
                        "workshop_title": "Demo PB",
                        "source_path": str(source),
                        "detected_kind": "pb_script",
                        "compatibility": "manual_adapter_required",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = root / "worker"
    (worker / "scripts").mkdir(parents=True)
    (worker / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (worker / "manifest.json").write_text('{"schema":"x","scripts":[]}', encoding="utf-8")

    report = prepare_adapter(root, catalog, "123")
    assert report["status"] == "adapter_scaffold_created"
    assert (root / "data" / "imports" / "123" / "Script.cs").exists()
    assert (root / "worker" / "scripts" / "workshop_123_adapter.py").exists()
    manifest = json.loads((root / "worker" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scripts"][0]["script_id"] == "workshop_123_adapter"
    assert manifest["scripts"][0]["enabled"] is False
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "adapter_scaffold_created"


def test_prepare_adapter_prefers_virtual_pb_for_compatible_scripts(tmp_path: Path):
    root = tmp_path
    source_dir = root / "steam" / "416932930"
    source_dir.mkdir(parents=True)
    source = source_dir / "Script.cs"
    source.write_text(
        """
public void Main(string argument)
{
    var doors = new List<IMyDoor>();
    GridTerminalSystem.GetBlocksOfType(doors);
    foreach (var door in doors)
    {
        door.CloseDoor();
    }
}
""",
        encoding="utf-8",
    )
    catalog = root / "data" / "workshop_catalog.json"
    catalog.parent.mkdir()
    catalog.write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.workshop_catalog.v1",
                "records": [
                    {
                        "workshop_id": "416932930",
                        "workshop_title": "Whip's Auto Door and Airlock Script",
                        "source_path": str(source),
                        "detected_kind": "pb_script",
                        "compatibility": "manual_adapter_required",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = root / "worker"
    (worker / "scripts").mkdir(parents=True)
    (worker / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (worker / "scripts" / "workshop_416932930_adapter.py").write_text("# stale manual scaffold\n", encoding="utf-8")
    (worker / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "virtual_whip_auto_door",
                        "source": "workshop_import",
                        "display_name": "Whip's Auto Door and Airlock Script (Virtual PB)",
                        "runtime": "virtual_pb_csharp",
                        "source_path": "data/imports/416932930/Script.cs",
                        "input_schema": "virtual_pb_tick.v1",
                        "output_schema": "compact_commands.v1",
                        "timeout_ms": 5000,
                        "enabled": False,
                    },
                    {
                        "script_id": "workshop_416932930_adapter",
                        "source": "workshop_import",
                        "display_name": "Whip's Auto Door and Airlock Script",
                        "module": "worker.scripts.workshop_416932930_adapter",
                        "input_schema": "adapter_tick.v1",
                        "output_schema": "compact_commands.v1",
                        "timeout_ms": 1000,
                        "enabled": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = prepare_adapter(root, catalog, "416932930")

    assert report["status"] == "virtual_pb_ready"
    assert report["script_id"] == "virtual_whip_auto_door"
    assert report["runtime"] == "virtual_pb_csharp"
    assert report["compatibility"]["status"] == "supported"
    assert (root / "data" / "imports" / "416932930" / "Script.cs").exists()
    assert not (root / "worker" / "scripts" / "workshop_416932930_adapter.py").exists()
    manifest = json.loads((root / "worker" / "manifest.json").read_text(encoding="utf-8"))
    assert [item["script_id"] for item in manifest["scripts"]] == ["virtual_whip_auto_door"]
    assert manifest["scripts"][0]["enabled"] is True
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "virtual_pb_ready"


def test_prepare_adapter_falls_back_for_unemulated_virtual_pb_interfaces(tmp_path: Path):
    root = tmp_path
    source_dir = root / "steam" / "822950976"
    source_dir.mkdir(parents=True)
    source = source_dir / "Script.cs"
    source.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var panels = new List<IMyTextPanel>();
    var doors = new List<IMyDoor>();
    var containers = new List<IMyCargoContainer>();
    GridTerminalSystem.GetBlocksOfType(panels);
    GridTerminalSystem.GetBlocksOfType(doors);
    GridTerminalSystem.GetBlocksOfType(containers);
    panels[0].WriteText("hello");
}
""",
        encoding="utf-8",
    )
    catalog = root / "data" / "workshop_catalog.json"
    catalog.parent.mkdir()
    catalog.write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.workshop_catalog.v1",
                "records": [
                    {
                        "workshop_id": "822950976",
                        "workshop_title": "Automatic LCDs 2",
                        "source_path": str(source),
                        "detected_kind": "pb_script",
                        "compatibility": "manual_adapter_required",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = root / "worker"
    (worker / "scripts").mkdir(parents=True)
    (worker / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (worker / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "x",
                "scripts": [
                    {
                        "script_id": "virtual_workshop_822950976",
                        "source": "workshop_import",
                        "display_name": "Automatic LCDs 2 (Virtual PB)",
                        "runtime": "virtual_pb_csharp",
                        "source_path": "data/imports/822950976/Script.cs",
                        "input_schema": "virtual_pb_tick.v1",
                        "output_schema": "compact_commands.v1",
                        "timeout_ms": 5000,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = prepare_adapter(root, catalog, "822950976")

    assert report["status"] == "adapter_scaffold_created"
    assert report["script_id"] == "workshop_822950976_adapter"
    assert report["analysis"]["uses_grid_terminal_system"] is True
    assert report["compatibility"]["status"] == "unsupported"
    assert "IMyCargoContainer" in report["compatibility"]["unsupported_interfaces"]
    assert (root / "worker" / "scripts" / "workshop_822950976_adapter.py").exists()
    manifest = json.loads((root / "worker" / "manifest.json").read_text(encoding="utf-8"))
    assert [item["script_id"] for item in manifest["scripts"]] == ["workshop_822950976_adapter"]
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "adapter_scaffold_created"
