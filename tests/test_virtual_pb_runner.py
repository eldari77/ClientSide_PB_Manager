import json
import subprocess
from pathlib import Path

from worker.worker import save_virtual_pb_compatibility_report
from worker.virtual_pb import analyze_virtual_pb_script, run_virtual_pb


def test_virtual_pb_analysis_rejects_unsafe_apis(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
using System.IO;
public Program() {}
public void Main(string argument) { File.WriteAllText("x", "y"); }
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert "System.IO" in report["unsupported_apis"]
    assert "File." in report["unsupported_apis"]


def test_virtual_pb_analysis_rejects_unemulated_interfaces(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var modded = new List<IMyExperimentalJumpGate>();
    GridTerminalSystem.GetBlocksOfType(modded);
}
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert "IMyExperimentalJumpGate" in report["unsupported_interfaces"]
    assert "unsupported_interface:IMyExperimentalJumpGate" in report["unsupported_apis"]


def test_virtual_pb_capabilities_mode_reports_harness_and_commands(tmp_path: Path):
    output = tmp_path / "capabilities.json"

    completed = subprocess.run(
        [
            "dotnet",
            "run",
            "--project",
            "virtual_pb_runner/NOVALI.VirtualPBRunner.csproj",
            "--",
            "--mode",
            "capabilities",
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "novali.client_side_pb.virtual_pb_capabilities.v1"
    assert "IMyTextPanel" in report["implemented_interfaces"]
    assert "write_text_surface" in report["available_command_kinds"]
    assert "grid_snapshot.blocks[].inventories[].items[]" in report["snapshot_fields"]


def test_virtual_pb_compiled_script_writes_text_panel_from_inventory_snapshot(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument, UpdateType updateSource)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels, p => p.CustomName.Contains("LCD"));
    var containers = new List<IMyCargoContainer>();
    GridTerminalSystem.GetBlocksOfType(containers);
    var items = new List<MyInventoryItem>();
    containers[0].GetInventory(0).GetItems(items);
    panels[0].WriteText(items[0].Type.SubtypeId + ":" + items[0].Amount.ToString(), false);
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 10,
        "script_id": "virtual_auto_lcd_fixture",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 301,
                    "name": "Main LCD",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "text": "",
                    "custom_data": "",
                    "inventories": [],
                },
                {
                    "entity_id": 401,
                    "name": "Cargo",
                    "same_construct": True,
                    "is_cargo": True,
                    "inventory_count": 1,
                    "inventories": [
                        {
                            "index": 0,
                            "current_volume": 1.0,
                            "max_volume": 10.0,
                            "items": [
                                {
                                    "type_id": "MyObjectBuilder_Ingot",
                                    "subtype_id": "Iron",
                                    "amount": 1200,
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["compiled"] is True
    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == [
        {
            "kind": "write_text_surface",
            "block_entity_id": 301,
            "surface_index": 0,
            "append": False,
            "text": "Iron:1200",
        }
    ]


def test_virtual_pb_rejects_unmapped_generic_terminal_mutation(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var blocks = new List<IMyTerminalBlock>();
    GridTerminalSystem.GetBlocksOfType(blocks);
    blocks[0].ApplyAction("OnOff_On");
}
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert "unsupported_member:IMyTerminalBlock.ApplyAction" in report["unsupported_members"]


def test_virtual_pb_fixture_closes_open_door_and_sets_light(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
const string Tag = "Airlock";
public Program() {}
public void Main(string argument)
{
    var doors = new List<IMyDoor>();
    GridTerminalSystem.GetBlocksOfType(doors, d => d.CustomName.Contains(Tag));
    foreach (var door in doors)
    {
        if (door.OpenRatio > 0.9f)
        {
            door.CloseDoor();
        }
    }
    var lights = new List<IMyLightingBlock>();
    GridTerminalSystem.GetBlocksOfType(lights, l => l.CustomName.Contains(Tag));
    foreach (var light in lights)
    {
        light.Enabled = true;
        light.Color = new Color(255, 40, 40);
    }
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 9,
        "script_id": "virtual_whip_auto_door",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 100,
                    "name": "A Airlock Interior",
                    "same_construct": True,
                    "is_door": True,
                    "door_open_ratio": 1.0,
                    "door_status": "Open",
                    "custom_data": "",
                },
                {
                    "entity_id": 200,
                    "name": "A Airlock Light",
                    "same_construct": True,
                    "is_light": True,
                    "enabled": False,
                    "color": {"r": 0, "g": 0, "b": 0, "a": 255},
                    "custom_data": "",
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert {"kind": "set_door_open", "block_entity_id": 100, "open": False} in result["commands"]
    assert {
        "kind": "set_light_color",
        "block_entity_id": 200,
        "color": {"r": 255, "g": 40, "b": 40, "a": 255},
    } in result["commands"]
    assert {"kind": "set_block_enabled", "block_entity_id": 200, "enabled": True} in result["commands"]


def test_virtual_pb_runner_project_exists():
    project = Path("virtual_pb_runner/NOVALI.VirtualPBRunner.csproj")
    assert project.exists()


def test_virtual_pb_compatibility_report_is_persisted(tmp_path: Path):
    save_virtual_pb_compatibility_report(
        tmp_path,
        "virtual_whip_auto_door",
        {
            "status": "supported",
            "compiled": True,
            "unsupported_apis": [],
            "unsupported_interfaces": [],
            "unsupported_members": [],
            "required_interfaces": ["IMyDoor"],
            "implemented_interfaces": ["IMyDoor", "IMyTextPanel"],
            "supported_block_types": ["IMyDoor"],
            "available_command_kinds": ["set_door_open", "write_text_surface"],
            "snapshot_requirements": ["grid_snapshot.blocks[].door_status"],
            "capability_version": "dynamic-harness-test",
        },
        {"summary": "Virtual PB tick processed.", "commands": [{"kind": "set_door_open"}]},
    )

    report = json.loads((tmp_path / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))

    assert report["scripts"]["virtual_whip_auto_door"]["compiled"] is True
    assert report["scripts"]["virtual_whip_auto_door"]["emitted_command_kinds"] == ["set_door_open"]
    assert report["scripts"]["virtual_whip_auto_door"]["required_interfaces"] == ["IMyDoor"]
    assert report["scripts"]["virtual_whip_auto_door"]["available_command_kinds"] == ["set_door_open", "write_text_surface"]
    assert report["scripts"]["virtual_whip_auto_door"]["snapshot_requirements"] == ["grid_snapshot.blocks[].door_status"]
