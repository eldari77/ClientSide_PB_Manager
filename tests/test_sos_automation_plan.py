import json
from pathlib import Path

from worker.worker import enriched_child_runtime_telemetry, load_manifest
from worker.scripts.sos_automation_plan import run


def test_sos_automation_plan_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.automation_plan as automation_plan_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": []}

    monkeypatch.setattr(automation_plan_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result == {"summary": "from package", "commands": []}


def test_sos_automation_plan_adapter_degrades_to_no_snapshot_without_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked"},
        }
    )

    assert result["sos_automation_plan"]["snapshot_status"] == "no_snapshot"
    assert result["sos_automation_plan"]["state"] == "unknown"
    assert result["commands"] == []


def test_sos_automation_plan_adapter_preserves_declarative_plan_without_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sequence": 10,
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked"},
            "automation_plan_snapshot": {
                "plans": [
                    {
                        "action_family": "programmable_block_recovery",
                        "operation": "restart",
                        "target": {"entity_id": 7001, "name": "Main PB"},
                        "expires_after_sequence": 11,
                    }
                ]
            },
        }
    )

    assert len(result["sos_automation_plan"]["plans"]) == 1
    assert result["sos_automation_plan"]["plans"][0]["operation"] == "restart"
    assert result["commands"] == []


def test_sos_automation_plan_adapter_preserves_identity_blocker_and_empty_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sequence": 10,
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "mode": "Docked",
                "expected_grid_entity_id": 10,
                "identity_status": "ok",
            },
            "grid_snapshot": {
                "grid_entity_id": 11,
                "identity_status": "mismatch",
                "blocks": [
                    {
                        "entity_id": 7001,
                        "name": "Main PB",
                        "grid_entity_id": 11,
                        "functional": False,
                        "heartbeat_status": "failed",
                    }
                ],
            },
            "automation_plan_snapshot": {
                "plans": [
                    {
                        "action_family": "programmable_block_recovery",
                        "operation": "restart",
                        "target": {"entity_id": 7001, "name": "Main PB", "grid_entity_id": 11},
                        "expires_after_sequence": 11,
                    }
                ]
            },
        }
    )

    assert "identity_mismatch" in result["sos_automation_plan"]["blockers"]
    assert result["commands"] == []


def test_sos_automation_plan_registered_in_manifest_and_default_instance(tmp_path: Path):
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

    assert scripts["sos_automation_plan"].module == "worker.scripts.sos_automation_plan"
    assert scripts["pb-bridge-001-sos_automation_plan"].base_script_id == "sos_automation_plan"
    assert scripts["pb-bridge-001-sos_automation_plan"].module == "worker.scripts.sos_automation_plan"
    assert {
        "service_id": "automation_plan",
        "script_id": "pb-bridge-001-sos_automation_plan",
        "enabled": True,
    } in registry["ships"][0]["services"]


def test_sos_automation_plan_history_stays_within_its_bridge(tmp_path: Path):
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir(parents=True)
    child_config = ({"service_id": "automation_plan", "script_id": "pb-bridge-001-sos_automation_plan"},)

    for bridge_id, plan_id in (("bridge-a", "plan-a"), ("bridge-b", "plan-b")):
        (results_dir / f"{bridge_id}.json").write_text(
            json.dumps(
                {
                    "result": {
                        "child_results": [
                            {
                                "script_id": "pb-bridge-001-sos_automation_plan",
                                "status": "ok",
                                "error_bucket": "none",
                                "summary": plan_id,
                                "result": {"sos_automation_plan": {"state": "proposal", "plan_id": plan_id}},
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)

    assert telemetry_a["child_services_by_service_id"]["automation_plan"]["result"]["sos_automation_plan"]["plan_id"] == "plan-a"
    assert telemetry_b["child_services_by_service_id"]["automation_plan"]["result"]["sos_automation_plan"]["plan_id"] == "plan-b"
