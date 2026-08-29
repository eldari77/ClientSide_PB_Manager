import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_display import run


def test_sos_display_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.display as display_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(display_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_display_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_display"]["snapshot_status"] == "no_snapshot"
    assert result["sos_display"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Display Ship A state=unknown snapshot=no_snapshot"}]


def test_sos_display_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
            "grid_snapshot": {
                "blocks": [
                    {
                        "entity_id": 9001,
                        "name": "Status LCD",
                        "type": "TextPanel",
                        "surface_count": 1,
                        "functional": True,
                        "enabled": True,
                    }
                ]
            },
            "runtime_telemetry": {"queue_pressure": {"queued": 1, "drained": 1, "remaining": 0}},
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["sos_display"]["snapshot_status"] == "partial"


def test_sos_display_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_display"].module == "worker.scripts.sos_display"
    assert scripts["pb-bridge-001-sos_display"].base_script_id == "sos_display"
    assert scripts["pb-bridge-001-sos_display"].module == "worker.scripts.sos_display"
    assert {"service_id": "display", "script_id": "pb-bridge-001-sos_display", "enabled": True} in registry["ships"][0]["services"]
