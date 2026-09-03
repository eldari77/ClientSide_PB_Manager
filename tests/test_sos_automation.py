import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_automation import run


def test_sos_automation_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.automation as automation_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(automation_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_automation_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked", "status_surfaces": []},
        }
    )

    assert result["sos_automation"]["snapshot_status"] == "no_snapshot"
    assert result["sos_automation"]["state"] == "unknown"
    assert result["commands"] == [
        {
            "kind": "echo",
            "text": (
                "SOS Automation Ship A state=unknown pbs=0/0 failing=0 stale=0 "
                "automation=0 disabled=0 damaged=0 warnings=0 blockers=0"
            ),
        }
    ]


def test_sos_automation_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "mode": "Docked",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
            "automation_snapshot": {
                "programmable_blocks": [{"name": "Main PB", "enabled": True, "running": True}],
                "automation_blocks": [{"name": "Timer", "enabled": True, "functional": True}],
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["commands"][0]["title"] == "SOS Automation"


def test_sos_automation_registered_in_manifest_and_default_instance(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(
        Path("data/script_instances.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    scripts = load_manifest(tmp_path)

    assert scripts["sos_automation"].module == "worker.scripts.sos_automation"
    assert scripts["pb-bridge-001-sos_automation"].base_script_id == "sos_automation"
    assert scripts["pb-bridge-001-sos_automation"].module == "worker.scripts.sos_automation"
    assert {
        "service_id": "automation",
        "script_id": "pb-bridge-001-sos_automation",
        "enabled": True,
    } in registry["ships"][0]["services"]
