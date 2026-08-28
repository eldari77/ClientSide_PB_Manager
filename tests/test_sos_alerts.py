import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_alerts import run


def test_sos_alerts_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.alerts as alerts_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(alerts_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_alerts_adapter_degrades_to_missing_child_result_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_alerts"]["snapshot_status"] == "missing_child_result"
    assert result["sos_alerts"]["state"] == "unknown"
    assert result["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Alerts Ship A state=unknown alerts=0 critical=0 warnings=0 blockers=0 snapshot=missing_child_result",
        }
    ]


def test_sos_alerts_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
            "runtime_telemetry": {
                "queue_pressure": {"queued": 3, "drained": 1, "remaining": 2},
                "child_services_by_service_id": {
                    "integrity": {
                        "service_id": "integrity",
                        "script_id": "bridge-a-sos_integrity",
                        "result": {
                            "sos_integrity": {
                                "state": "critical",
                                "snapshot_status": "ok",
                                "blockers": ["critical_block_damaged:Reactor"],
                                "warnings": ["integrity_degraded"],
                            }
                        },
                    }
                },
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["sos_alerts"]["state"] == "critical"


def test_sos_alerts_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_alerts"].module == "worker.scripts.sos_alerts"
    assert scripts["pb-bridge-001-sos_alerts"].base_script_id == "sos_alerts"
    assert scripts["pb-bridge-001-sos_alerts"].module == "worker.scripts.sos_alerts"
    assert {"service_id": "alerts", "script_id": "pb-bridge-001-sos_alerts", "enabled": True} in registry["ships"][0]["services"]
