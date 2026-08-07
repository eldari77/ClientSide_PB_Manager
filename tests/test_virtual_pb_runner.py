import json
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
        {"status": "supported", "unsupported_apis": [], "supported_block_types": ["IMyDoor"]},
        {"summary": "Virtual PB tick processed.", "commands": [{"kind": "set_door_open"}]},
    )

    report = json.loads((tmp_path / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))

    assert report["scripts"]["virtual_whip_auto_door"]["compiled"] is True
    assert report["scripts"]["virtual_whip_auto_door"]["emitted_command_kinds"] == ["set_door_open"]
