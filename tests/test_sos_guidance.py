import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_guidance import run


def test_sos_guidance_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.guidance as guidance_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(guidance_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_guidance_adapter_degrades_to_missing_child_result_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_guidance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_guidance"]["state"] == "unknown"
    assert result["commands"] == [
        {"kind": "echo", "text": "SOS Guidance Ship A state=unknown priorities=0 snapshot=missing_child_result"}
    ]


def test_sos_guidance_adapter_emits_only_allowed_status_commands():
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
                "child_services_by_service_id": {
                    "readiness": {
                        "service_id": "readiness",
                        "result": {"sos_readiness": {"state": "ready", "warnings": [], "blockers": []}},
                    }
                }
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["commands"][0]["title"] == "SOS Guidance"


def test_sos_guidance_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_guidance"].module == "worker.scripts.sos_guidance"
    assert scripts["pb-bridge-001-sos_guidance"].base_script_id == "sos_guidance"
    assert scripts["pb-bridge-001-sos_guidance"].module == "worker.scripts.sos_guidance"
    assert {"service_id": "guidance", "script_id": "pb-bridge-001-sos_guidance", "enabled": True} in registry["ships"][0]["services"]
