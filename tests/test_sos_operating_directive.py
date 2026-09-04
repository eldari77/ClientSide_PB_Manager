import inspect
import json
import sys
import types
from pathlib import Path

from worker.scripts.sos_operating_directive import run
from worker.worker import WorkerScript, enriched_child_runtime_telemetry, execute_orchestrator_request, execute_request, load_manifest


DIRECTIVE_ALIASES = (
    "operating_directive_snapshot",
    "desired_mode_snapshot",
    "operator_mode_request",
)


def test_sos_operating_directive_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.operating_directive as directive_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": []}

    monkeypatch.setattr(directive_service, "run", fake_run)

    assert run({"bridge_id": "bridge-a"}) == {"summary": "from package", "commands": []}


def test_sos_operating_directive_degrades_without_directive():
    result = run({"bridge_id": "bridge-a", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked"}})

    assert result["sos_operating_directive"]["state"] == "no_directive"
    assert result["sos_operating_directive"]["requested_mode"] is None
    assert result["commands"] == []


def test_sos_operating_directive_preserves_sos_owned_invalid_directive_result():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked"},
            "operator_mode_request": {
                "operator_requested": True,
                "requested_mode": "Warp",
                "request_id": "directive-invalid",
                "requested_at_sequence": 10,
            },
        }
    )

    assert result["sos_operating_directive"]["state"] == "invalid_requested_mode"
    assert result["sos_operating_directive"]["current_mode"] == "Docked"
    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}


def test_sos_operating_directive_registered_in_manifest_instance_and_ship_registry(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(Path("data/script_instances.json").read_text(encoding="utf-8"), encoding="utf-8")
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    scripts = load_manifest(tmp_path)

    assert scripts["sos_operating_directive"].module == "worker.scripts.sos_operating_directive"
    assert scripts["pb-bridge-001-sos_operating_directive"].base_script_id == "sos_operating_directive"
    assert {
        "service_id": "operating_directive",
        "script_id": "pb-bridge-001-sos_operating_directive",
        "enabled": True,
    } in registry["ships"][0]["services"]


def test_sos_operating_directive_orchestrator_scopes_context_and_aliases_to_directive_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    directive_module = types.ModuleType("tests.sos_operating_directive_capture")
    sibling_module = types.ModuleType("tests.sos_operating_directive_siblings")

    def run_directive(request):
        captured["operating_directive"] = request
        return run(request)

    def run_sibling(request):
        captured[request["script_id"]] = request
        return {"summary": request["script_id"], "commands": []}

    directive_module.run = run_directive
    sibling_module.run = run_sibling
    sys.modules[directive_module.__name__] = directive_module
    sys.modules[sibling_module.__name__] = sibling_module
    services = (
        ("authority", "bridge-a-sos_authority"),
        ("automation_plan", "bridge-a-sos_automation_plan"),
        ("automation_recovery", "bridge-a-sos_automation_recovery"),
        ("operating_directive", "bridge-a-sos_operating_directive"),
        ("guidance", "bridge-a-sos_guidance"),
        ("runbook", "bridge-a-sos_runbook"),
        ("dashboard", "bridge-a-sos_dashboard"),
        ("status", "bridge-a-sos_status"),
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [{
                    "ship_id": "ship-a", "bridge_id": "bridge-a", "display_name": "Ship A",
                    "expected_grid_entity_id": 10, "mode": "Docked",
                    "services": [{"service_id": service_id, "script_id": script_id} for service_id, script_id in services],
                    "status_surfaces": [],
                }],
            }
        ),
        encoding="utf-8",
    )
    result_dir = data / "bridge_results"
    result_dir.mkdir()
    (result_dir / "bridge-a.json").write_text(
        json.dumps({"result": {"child_results": [{
            "script_id": "bridge-a-sos_automation_plan", "status": "ok", "error_bucket": "none", "summary": "plan",
            "result": {"sos_automation_plan": {"state": "proposed"}},
        }]}}),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        )
    }
    for service_id, script_id in services:
        scripts[script_id] = WorkerScript(
            script_id, "manual", service_id,
            directive_module.__name__ if service_id == "operating_directive" else sibling_module.__name__,
            "", "", 1000, True,
        )
    directive = {"operator_requested": True, "requested_mode": "Cruise", "request_id": "directive-1", "requested_at_sequence": 10}
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": "bridge-a",
            "sequence": 10, "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "identity_status": "ok",
                              "blocks": [{"entity_id": 7001, "name": "Bridge PB", "functional": True, "integrity_ratio": 1.0}]},
            "runtime_telemetry": {"limiter_state": "ok", "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0}},
            "state": {},
            **{alias: dict(directive) for alias in DIRECTIVE_ALIASES},
        },
        scripts, {}, tmp_path,
    )

    directive_request = captured["operating_directive"]
    assert directive_request["sos_ship"]["identity_status"] == "ok"
    assert directive_request["sos_ship"]["mode"] == "Docked"
    assert directive_request["grid_snapshot"]["grid_entity_id"] == 10
    assert directive_request["integrity_snapshot"]["blocks"][0]["name"] == "Bridge PB"
    assert directive_request["runtime_telemetry"]["limiter_state"] == "ok"
    assert "automation_plan" in directive_request["runtime_telemetry"]["child_services_by_service_id"]
    for alias in DIRECTIVE_ALIASES:
        assert directive_request[alias] == directive
    for service_id, script_id in services:
        if service_id != "operating_directive":
            assert all(alias not in captured[script_id] for alias in DIRECTIVE_ALIASES)
    assert json.loads((data / "sos_ships.json").read_text(encoding="utf-8"))["ships"][0]["mode"] == "Docked"
    assert result["status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_sos_operating_directive_history_stays_within_its_bridge(tmp_path: Path):
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir(parents=True)
    child_config = ({"service_id": "operating_directive", "script_id": "pb-bridge-001-sos_operating_directive"},)
    for bridge_id, state in (("bridge-a", "approval_required"), ("bridge-b", "blocked")):
        (results_dir / f"{bridge_id}.json").write_text(
            json.dumps({"result": {"child_results": [{
                "script_id": "pb-bridge-001-sos_operating_directive", "status": "ok", "error_bucket": "none", "summary": state,
                "result": {"sos_operating_directive": {"state": state}},
            }]}}),
            encoding="utf-8",
        )

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)

    assert telemetry_a["child_services_by_service_id"]["operating_directive"]["result"]["sos_operating_directive"]["state"] == "approval_required"
    assert telemetry_b["child_services_by_service_id"]["operating_directive"]["result"]["sos_operating_directive"]["state"] == "blocked"


def test_worker_orchestrator_does_not_construct_or_authorize_directive_commands():
    assert "set_block_enabled" not in inspect.getsource(execute_orchestrator_request)
