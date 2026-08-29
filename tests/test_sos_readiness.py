import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_readiness import run


def test_sos_readiness_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.readiness as readiness_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(readiness_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_readiness_adapter_degrades_to_missing_child_result_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_readiness"]["snapshot_status"] == "missing_child_result"
    assert result["sos_readiness"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Readiness Ship A state=unknown snapshot=missing_child_result"}]


def test_sos_readiness_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "mode": "Docked",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
            "runtime_telemetry": {
                "queue_pressure": {"queued": 2, "drained": 1, "remaining": 1},
                "child_services_by_service_id": {
                    "logistics": {"service_id": "logistics", "result": {"sos_logistics": {"state": "ok"}}},
                    "production": {"service_id": "production", "result": {"sos_production": {"state": "ok"}}},
                    "maintenance": {"service_id": "maintenance", "result": {"sos_maintenance": {"state": "ok"}}},
                    "power": {"service_id": "power", "result": {"sos_power": {"state": "ok"}}},
                    "display": {"service_id": "display", "result": {"sos_display": {"state": "ok"}}},
                    "alerts": {"service_id": "alerts", "result": {"sos_alerts": {"state": "ok"}}},
                },
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["sos_readiness"]["state"] == "ready"


def test_sos_readiness_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_readiness"].module == "worker.scripts.sos_readiness"
    assert scripts["pb-bridge-001-sos_readiness"].base_script_id == "sos_readiness"
    assert scripts["pb-bridge-001-sos_readiness"].module == "worker.scripts.sos_readiness"
    assert {"service_id": "readiness", "script_id": "pb-bridge-001-sos_readiness", "enabled": True} in registry["ships"][0]["services"]
