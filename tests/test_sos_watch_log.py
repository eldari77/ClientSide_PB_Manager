import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_watch_log import run


def test_sos_watch_log_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.watch_log as watch_log_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(watch_log_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_watch_log_adapter_degrades_to_missing_child_result_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked", "status_surfaces": []},
        }
    )

    assert result["sos_watch_log"]["snapshot_status"] == "missing_child_result"
    assert result["sos_watch_log"]["state"] == "unknown"
    assert result["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Watch Log Ship A state=unknown events=0 snapshot=missing_child_result",
        }
    ]


def test_sos_watch_log_adapter_emits_only_allowed_status_commands():
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
                    "alerts": {
                        "service_id": "alerts",
                        "script_id": "bridge-a-sos_alerts",
                        "status": "ok",
                        "result": {"sos_alerts": {"state": "warning", "warnings": ["power_low"]}},
                    }
                },
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["commands"][0]["title"] == "SOS Watch Log"


def test_sos_watch_log_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_watch_log"].module == "worker.scripts.sos_watch_log"
    assert scripts["pb-bridge-001-sos_watch_log"].base_script_id == "sos_watch_log"
    assert scripts["pb-bridge-001-sos_watch_log"].module == "worker.scripts.sos_watch_log"
    assert {
        "service_id": "watch_log",
        "script_id": "pb-bridge-001-sos_watch_log",
        "enabled": True,
    } in registry["ships"][0]["services"]
