import json
from pathlib import Path

from worker.worker import load_manifest
from worker.scripts.sos_endurance import run


def test_sos_endurance_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.endurance as endurance_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(endurance_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_endurance_adapter_degrades_to_missing_child_result_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked", "status_surfaces": []},
        }
    )

    assert result["sos_endurance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_endurance"]["state"] == "unknown"
    assert result["commands"] == [
        {
            "kind": "echo",
            "text": (
                "SOS Endurance Ship A state=unknown cargo=unknown ammo=unknown fuel=unknown "
                "energy=unknown survival=unknown transit=unknown sources=0 warnings=1"
            ),
        }
    ]


def test_sos_endurance_adapter_emits_only_allowed_status_commands():
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
                    "power": {
                        "service_id": "power",
                        "script_id": "bridge-a-sos_power",
                        "status": "ok",
                        "result": {"sos_power": {"state": "warning", "batteries": {"state": "warning"}}},
                    }
                },
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["commands"][0]["title"] == "SOS Endurance"


def test_sos_endurance_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_endurance"].module == "worker.scripts.sos_endurance"
    assert scripts["pb-bridge-001-sos_endurance"].base_script_id == "sos_endurance"
    assert scripts["pb-bridge-001-sos_endurance"].module == "worker.scripts.sos_endurance"
    assert {
        "service_id": "endurance",
        "script_id": "pb-bridge-001-sos_endurance",
        "enabled": True,
    } in registry["ships"][0]["services"]
