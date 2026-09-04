import inspect
import json
import sys
import types
from pathlib import Path

from worker.scripts.sos_authority import run
from worker.worker import WorkerScript, enriched_child_runtime_telemetry, execute_orchestrator_request, execute_request, load_manifest


def test_sos_authority_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.authority as authority_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": []}

    monkeypatch.setattr(authority_service, "run", fake_run)

    assert run({"bridge_id": "bridge-a"}) == {"summary": "from package", "commands": []}


def test_sos_authority_degrades_without_authority_context():
    result = run({"bridge_id": "bridge-a", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A"}})

    assert result["sos_authority"]["state"] == "unknown"
    assert result["sos_authority"]["policy_status"] == "unknown"
    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}


def test_sos_authority_registered_in_manifest_instance_and_ship_registry(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(Path("data/script_instances.json").read_text(encoding="utf-8"), encoding="utf-8")
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    scripts = load_manifest(tmp_path)

    assert scripts["sos_authority"].module == "worker.scripts.sos_authority"
    assert scripts["pb-bridge-001-sos_authority"].base_script_id == "sos_authority"
    assert {
        "service_id": "authority",
        "script_id": "pb-bridge-001-sos_authority",
        "enabled": True,
    } in registry["ships"][0]["services"]


def test_sos_authority_orchestrator_scopes_context_and_aliases_to_authority_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    authority_module = types.ModuleType("tests.sos_authority_capture")
    sibling_module = types.ModuleType("tests.sos_authority_siblings")

    def run_authority(request):
        captured["authority"] = request
        return run(request)

    def run_sibling(request):
        captured[request["script_id"]] = request
        return {"summary": request["script_id"], "commands": []}

    authority_module.run = run_authority
    sibling_module.run = run_sibling
    sys.modules[authority_module.__name__] = authority_module
    sys.modules[sibling_module.__name__] = sibling_module
    data = tmp_path / "data"
    data.mkdir()
    services = (
        ("automation_plan", "bridge-a-sos_automation_plan"),
        ("automation_recovery", "bridge-a-sos_automation_recovery"),
        ("authority", "bridge-a-sos_authority"),
        ("dashboard", "bridge-a-sos_dashboard"),
        ("guidance", "bridge-a-sos_guidance"),
        ("status", "bridge-a-sos_status"),
    )
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "expected_grid_entity_id": 10,
                        "mode": "Docked",
                        "services": [{"service_id": service_id, "script_id": script_id} for service_id, script_id in services],
                        "status_surfaces": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result_dir = data / "bridge_results"
    result_dir.mkdir()
    (result_dir / "bridge-a.json").write_text(
        json.dumps(
            {
                "result": {
                    "child_results": [
                        {
                            "script_id": "bridge-a-sos_automation_plan",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "recovery plan",
                            "result": {"sos_automation_plan": {"plans": [{"state": "proposed"}]}},
                        },
                        {
                            "script_id": "bridge-a-sos_automation_recovery",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "receipt pending",
                            "result": {"sos_automation_recovery": {"state": "passive", "receipt_status": "pending"}},
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        )
    }
    for service_id, script_id in services:
        scripts[script_id] = WorkerScript(
            script_id,
            "manual",
            service_id,
            authority_module.__name__ if service_id == "authority" else sibling_module.__name__,
            "",
            "",
            1000,
            True,
        )

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 10,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "identity_status": "ok",
                "blocks": [{"entity_id": 7001, "name": "Recovery PB", "functional": True, "integrity_ratio": 1.0}],
            },
            "authority_snapshot": {"mode": "Docked"},
            "operating_authority_snapshot": {"procedure": "recovery"},
            "procedure_policy_snapshot": {"policy": "operator_approval_required"},
            "runtime_telemetry": {"limiter_state": "ok", "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0}},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    authority_request = captured["authority"]
    assert authority_request["sos_ship"]["identity_status"] == "ok"
    assert authority_request["grid_snapshot"]["grid_entity_id"] == 10
    assert authority_request["integrity_snapshot"]["blocks"][0]["name"] == "Recovery PB"
    assert authority_request["runtime_telemetry"]["limiter_state"] == "ok"
    assert "automation_plan" in authority_request["runtime_telemetry"]["child_services_by_service_id"]
    assert "automation_recovery" in authority_request["runtime_telemetry"]["child_services_by_service_id"]
    for alias in ("authority_snapshot", "operating_authority_snapshot", "procedure_policy_snapshot"):
        assert alias in authority_request
    for _, script_id in services:
        if script_id == "bridge-a-sos_authority":
            continue
        for alias in ("authority_snapshot", "operating_authority_snapshot", "procedure_policy_snapshot"):
            assert alias not in captured[script_id]
    assert result["status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_sos_authority_history_stays_within_its_bridge(tmp_path: Path):
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir(parents=True)
    child_config = ({"service_id": "authority", "script_id": "pb-bridge-001-sos_authority"},)

    for bridge_id, state in (("bridge-a", "allowed"), ("bridge-b", "blocked")):
        (results_dir / f"{bridge_id}.json").write_text(
            json.dumps(
                {
                    "result": {
                        "child_results": [
                            {
                                "script_id": "pb-bridge-001-sos_authority",
                                "status": "ok",
                                "error_bucket": "none",
                                "summary": state,
                                "result": {"sos_authority": {"state": state}},
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)

    assert telemetry_a["child_services_by_service_id"]["authority"]["result"]["sos_authority"]["state"] == "allowed"
    assert telemetry_b["child_services_by_service_id"]["authority"]["result"]["sos_authority"]["state"] == "blocked"


def test_worker_orchestrator_does_not_construct_authority_commands():
    assert "set_block_enabled" not in inspect.getsource(execute_orchestrator_request)
