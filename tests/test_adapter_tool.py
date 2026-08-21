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


def test_prepare_adapter_prefers_virtual_pb_for_compatible_scripts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "workshop.adapter_tool.analyze_virtual_pb_script",
        lambda script_path, root=None: {
            "status": "supported",
            "compiled": True,
            "unsupported_apis": [],
            "unsupported_interfaces": [],
            "unsupported_members": [],
            "supported_block_types": ["IMyDoor"],
            "uses_grid_terminal_system": True,
            "available_command_kinds": ["set_door_open"],
            "snapshot_requirements": ["grid_snapshot.blocks[]"],
        },
    )
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


def test_prepare_adapter_promotes_dynamic_virtual_pb_for_text_inventory_scripts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "workshop.adapter_tool.analyze_virtual_pb_script",
        lambda script_path, root=None: {
            "status": "supported",
            "compiled": True,
            "unsupported_apis": [],
            "unsupported_interfaces": [],
            "unsupported_members": [],
            "supported_block_types": ["IMyCargoContainer", "IMyDoor", "IMyTextPanel"],
            "uses_grid_terminal_system": True,
            "required_interfaces": ["IMyCargoContainer", "IMyDoor", "IMyTextPanel"],
            "implemented_interfaces": ["IMyCargoContainer", "IMyDoor", "IMyTextPanel"],
            "available_command_kinds": ["write_text_surface", "set_door_open"],
            "snapshot_requirements": ["grid_snapshot.blocks[].inventories[].items[]"],
        },
    )
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

    assert report["status"] == "virtual_pb_ready"
    assert report["script_id"] == "virtual_workshop_822950976"
    assert report["runtime"] == "virtual_pb_csharp"
    assert report["analysis"]["uses_grid_terminal_system"] is True
    assert report["compatibility"]["compiled"] is True
    assert "IMyCargoContainer" in report["compatibility"]["implemented_interfaces"]
    assert not (root / "worker" / "scripts" / "workshop_822950976_adapter.py").exists()
    manifest = json.loads((root / "worker" / "manifest.json").read_text(encoding="utf-8"))
    assert [item["script_id"] for item in manifest["scripts"]] == ["virtual_workshop_822950976"]
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "virtual_pb_ready"
    compatibility_summary = json.loads((root / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))
    assert compatibility_summary["scripts"]["virtual_workshop_822950976"]["last_run_status"] == "virtual_pb_ready"


def test_prepare_adapter_reports_virtual_pb_blocked_without_replacing_scaffold(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "workshop.adapter_tool.analyze_virtual_pb_script",
        lambda script_path, root=None: {
            "status": "blocked_command_mapping",
            "compiled": True,
            "unsupported_apis": [],
            "unsupported_interfaces": [],
            "unsupported_members": [],
            "blocked_members": ["unsupported_member:IMyTerminalBlock.SetValue:Dangerous.Property"],
            "blocked_command_mappings": ["Dangerous.Property"],
            "supported_block_types": ["IMyProgrammableBlock"],
            "uses_grid_terminal_system": True,
        },
    )
    root = tmp_path
    source_dir = root / "steam" / "2831096030"
    source_dir.mkdir(parents=True)
    source = source_dir / "Script.cs"
    source.write_text(
        """
public Program() {}
public void Main(string argument)
{
    Me.SetValue<float>("Dangerous.Property", 1f);
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
                        "workshop_id": "2831096030",
                        "workshop_title": "Vector Thrust OS",
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
                        "script_id": "workshop_2831096030_adapter",
                        "source": "workshop_import",
                        "display_name": "Vector Thrust OS",
                        "module": "worker.scripts.workshop_2831096030_adapter",
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = prepare_adapter(root, catalog, "2831096030")

    assert report["status"] == "virtual_pb_blocked"
    assert report["script_id"] == "workshop_2831096030_adapter"
    assert report["compatibility"]["blocked_command_mappings"] == ["Dangerous.Property"]
    assert (root / "worker" / "scripts" / "workshop_2831096030_adapter.py").exists()
    manifest = json.loads((worker / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scripts"][0]["enabled"] is True
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "virtual_pb_blocked"
    compatibility_summary = json.loads((root / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))
    blocked_summary = compatibility_summary["scripts"]["workshop_2831096030_adapter"]
    assert blocked_summary["last_run_status"] == "virtual_pb_blocked"
    assert blocked_summary["blocked_command_mappings"] == ["Dangerous.Property"]


def test_prepare_adapter_generates_enabled_isy_profile_adapter_and_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "workshop.adapter_tool.analyze_virtual_pb_script",
        lambda script_path, root=None: {
            "status": "unsupported",
            "compiled": False,
            "unsupported_apis": ["runner_unavailable"],
            "unsupported_members": ["runner_unavailable"],
        },
    )
    root = tmp_path
    source_dir = root / "steam" / "1216126863"
    source_dir.mkdir(parents=True)
    source = source_dir / "Script.cs"
    source.write_text(
        """
// Isy's Inventory Manager
public Program() {}
public void Main(string argument)
{
    Echo("Isy's Inventory Manager");
    GridTerminalSystem.GetBlocks(new List<IMyTerminalBlock>());
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
                        "workshop_id": "1216126863",
                        "workshop_title": "Isy's Inventory Manager",
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
    stale = worker / "scripts" / "workshop_1216126863_adapter.py"
    stale.write_text('"Adapter scaffold created; manual mapping still required."', encoding="utf-8")
    (worker / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "x",
                "scripts": [
                    {
                        "script_id": "workshop_1216126863_adapter",
                        "source": "workshop_import",
                        "display_name": "Isy's Inventory Manager",
                        "module": "worker.scripts.workshop_1216126863_adapter",
                        "enabled": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = prepare_adapter(root, catalog, "1216126863")

    assert report["status"] == "profile_adapter_ready"
    assert report["runtime"] == "python"
    assert report["profile_id"] == "isy_inventory_manager"
    assert report["profile_confidence"] == "high"
    assert report["enabled"] is True
    adapter_source = stale.read_text(encoding="utf-8")
    assert "from worker.isy_foundation import plan_isy_foundation" in adapter_source
    assert "return plan_isy_foundation(request)" in adapter_source
    assert "manual mapping still required" not in adapter_source
    manifest = json.loads((worker / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scripts"][0]["enabled"] is True
    assert manifest["scripts"][0]["profile_id"] == "isy_inventory_manager"
    config = json.loads((root / "data" / "worker_configs" / "workshop_1216126863_adapter.json").read_text(encoding="utf-8"))
    entries = {entry["key"]: entry["value"] for entry in config["entries"]}
    assert entries["inventorySortingEnabled"] is True
    assert entries["inventorySortingDryRun"] is False
    assert entries["maxApplyCommands"] == 8
    assert entries["maxPlannedTransfers"] == 16
    assert entries["maxPlannedMachineCommands"] == 12
    assert entries["allowConnectedGrids"] is False
    assert entries["virtualPbCustomData"] == ""
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "profile_adapter_ready"
