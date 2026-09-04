import json
import inspect
from pathlib import Path

from worker.scripts.sos_automation_recovery import run
from worker.worker import enriched_child_runtime_telemetry, execute_orchestrator_request, load_manifest


def _proposed_plan() -> dict:
    return {
        "state": "proposed",
        "approval_status": "required",
        "action_family": "programmable_block_recovery",
        "operation": "enable",
        "action_id": "sos-action-1",
        "approval_nonce": "sos-nonce-1",
        "target": {"entity_id": 7001, "grid_entity_id": 10},
        "expires_after_sequence": 12,
    }


def _request() -> dict:
    plan = _proposed_plan()
    return {
        "bridge_id": "bridge-a",
        "sequence": 10,
        "sos_ship": {
            "ship_id": "ship-a",
            "display_name": "Ship A",
            "mode": "Docked",
            "expected_grid_entity_id": 10,
            "identity_status": "ok",
        },
        "grid_snapshot": {"grid_entity_id": 10, "identity_status": "ok"},
        "integrity_snapshot": {"blocks": [{"name": "Recovery PB", "integrity_ratio": 1.0}]},
        "script_health_snapshot": {
            "programmable_blocks": [
                {
                    "entity_id": 7001,
                    "grid_entity_id": 10,
                    "interface_type": "IMyProgrammableBlock",
                    "functional": True,
                    "enabled": False,
                }
            ]
        },
        "runtime_telemetry": {
            "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0, "by_source": {}},
            "child_services_by_service_id": {
                "automation_plan": {
                    "service_id": "automation_plan",
                    "script_id": "bridge-a-sos_automation_plan",
                    "result": {"sos_automation_plan": {"plans": [plan]}},
                }
            },
        },
    }


def test_sos_automation_recovery_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.automation_recovery as automation_recovery_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": []}

    monkeypatch.setattr(automation_recovery_service, "run", fake_run)

    assert run({"bridge_id": "bridge-a"}) == {"summary": "from package", "commands": []}


def test_sos_automation_recovery_degrades_without_prior_plan_or_approval():
    result = run({"bridge_id": "bridge-a", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A"}})

    assert result["sos_automation_recovery"]["reason"] == "prior_plan_missing"
    assert result["commands"] == []


def test_sos_automation_recovery_requires_explicit_matching_approval():
    result = run(_request())

    assert result["sos_automation_recovery"]["reason"] == "approval_missing"
    assert result["commands"] == []


def test_sos_automation_recovery_preserves_terminal_shim_receipt_without_commands():
    request = _request()
    request["sos_automation"] = {
        "last_action_id": "sos-action-1",
        "last_outcome": "rejected",
        "last_rejection_reason": "sos_target_grid_mismatch",
        "last_sequence": 12,
    }

    result = run(request)

    recovery = result["sos_automation_recovery"]
    assert recovery["state"] == "rejected"
    assert recovery["receipt_status"] == "rejected"
    assert recovery["receipt_outcome"] == "rejected"
    assert recovery["receipt_reason"] == "sos_target_grid_mismatch"
    assert recovery["receipt_sequence"] == 12
    assert recovery["reconciliation_state"] == "rejected"
    assert result["commands"] == []


def test_sos_automation_recovery_preserves_the_approved_command_envelope():
    request = _request()
    request["operator_approval_snapshot"] = {
        "approved": True,
        "action_id": "sos-action-1",
        "approval_nonce": "sos-nonce-1",
        "target_entity_id": 7001,
        "target_grid_entity_id": 10,
    }

    result = run(request)

    assert result["sos_automation_recovery"]["state"] == "emitted"
    assert result["commands"] == [
        {
            "kind": "set_block_enabled",
            "block_entity_id": 7001,
            "enabled": True,
            "sos_action_id": "sos-action-1",
            "sos_action_family": "programmable_block_recovery",
            "sos_approval_nonce": "sos-nonce-1",
            "sos_target_grid_entity_id": 10,
            "sos_expires_after_sequence": 12,
        }
    ]


def test_sos_automation_recovery_registered_in_manifest_instance_and_ship_registry(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(Path("data/script_instances.json").read_text(encoding="utf-8"), encoding="utf-8")
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    scripts = load_manifest(tmp_path)

    assert scripts["sos_automation_recovery"].module == "worker.scripts.sos_automation_recovery"
    assert scripts["pb-bridge-001-sos_automation_recovery"].base_script_id == "sos_automation_recovery"
    assert {
        "service_id": "automation_recovery",
        "script_id": "pb-bridge-001-sos_automation_recovery",
        "enabled": True,
    } in registry["ships"][0]["services"]


def test_sos_automation_recovery_history_stays_within_its_bridge(tmp_path: Path):
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir(parents=True)
    child_config = ({"service_id": "automation_recovery", "script_id": "pb-bridge-001-sos_automation_recovery"},)

    for bridge_id, action_id in (("bridge-a", "action-a"), ("bridge-b", "action-b")):
        (results_dir / f"{bridge_id}.json").write_text(
            json.dumps(
                {
                    "result": {
                        "child_results": [
                            {
                                "script_id": "pb-bridge-001-sos_automation_recovery",
                                "status": "ok",
                                "error_bucket": "none",
                                "summary": action_id,
                                "result": {"sos_automation_recovery": {"state": "passive", "action_id": action_id}},
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)

    assert telemetry_a["child_services_by_service_id"]["automation_recovery"]["result"]["sos_automation_recovery"]["action_id"] == "action-a"
    assert telemetry_b["child_services_by_service_id"]["automation_recovery"]["result"]["sos_automation_recovery"]["action_id"] == "action-b"


def test_worker_orchestrator_does_not_construct_recovery_commands():
    assert "set_block_enabled" not in inspect.getsource(execute_orchestrator_request)
