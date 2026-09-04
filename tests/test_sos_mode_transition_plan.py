import inspect
import json
import sys
import types
from pathlib import Path

from worker.scripts.sos_mode_transition_plan import run
from worker.worker import WorkerScript, enriched_child_runtime_telemetry, execute_orchestrator_request, execute_request, load_manifest


PLAN_ALIASES = (
    "mode_transition_request",
    "operator_mode_transition",
    "mode_change_request",
    "operating_mode_request",
    "mode_transition_plan_snapshot",
)
LEDGER_ONLY_ALIAS = "mode_transition_snapshot"


def test_sos_mode_transition_plan_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.mode_transition_plan as plan_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": []}

    monkeypatch.setattr(plan_service, "run", fake_run)
    assert run({"bridge_id": "bridge-a"}) == {"summary": "from package", "commands": []}


def test_sos_mode_transition_plan_degrades_without_request():
    result = run({"bridge_id": "bridge-a", "sos_ship": {"ship_id": "ship-a", "mode": "Docked"}})

    assert result["sos_mode_transition_plan"]["snapshot_status"] == "missing_request"
    assert result["sos_mode_transition_plan"]["plans"] == []
    assert result["commands"] == []


def test_sos_mode_transition_plan_registered_in_manifest_instance_and_ship_registry(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(Path("data/script_instances.json").read_text(encoding="utf-8"), encoding="utf-8")

    scripts = load_manifest(tmp_path)
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    assert scripts["sos_mode_transition_plan"].module == "worker.scripts.sos_mode_transition_plan"
    assert scripts["pb-bridge-001-sos_mode_transition_plan"].base_script_id == "sos_mode_transition_plan"
    assert {"service_id": "mode_transition_plan", "script_id": "pb-bridge-001-sos_mode_transition_plan", "enabled": True} in registry["ships"][0]["services"]


def test_sos_mode_transition_plan_orchestrator_preserves_plan_aliases_and_ledger_boundary(tmp_path: Path):
    captured: dict[str, dict] = {}
    plan_module = types.ModuleType("tests.sos_mode_transition_plan_capture")
    sibling_module = types.ModuleType("tests.sos_mode_transition_plan_siblings")

    def run_plan(request):
        captured["mode_transition_plan"] = request
        return run(request)

    def run_sibling(request):
        captured[request["script_id"]] = request
        return {"summary": request["script_id"], "commands": []}

    plan_module.run = run_plan
    sibling_module.run = run_sibling
    sys.modules[plan_module.__name__] = plan_module
    sys.modules[sibling_module.__name__] = sibling_module
    services = (
        ("mode_transition_plan", "bridge-a-sos_mode_transition_plan"),
        ("mode_ledger", "bridge-a-sos_mode_ledger"),
        ("operating_directive", "bridge-a-sos_operating_directive"),
        ("authority", "bridge-a-sos_authority"),
        ("automation_plan", "bridge-a-sos_automation_plan"),
        ("automation_recovery", "bridge-a-sos_automation_recovery"),
        ("dashboard", "bridge-a-sos_dashboard"),
        ("status", "bridge-a-sos_status"),
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{
        "ship_id": "ship-a", "bridge_id": "bridge-a", "display_name": "Ship A", "expected_grid_entity_id": 10, "mode": "Docked",
        "services": [{"service_id": service_id, "script_id": script_id} for service_id, script_id in services], "status_surfaces": [],
    }]}), encoding="utf-8")
    result_dir = data / "bridge_results"
    result_dir.mkdir()
    (result_dir / "bridge-a.json").write_text(json.dumps({"result": {"child_results": [{
        "script_id": "bridge-a-sos_mode_ledger", "status": "ok", "error_bucket": "none", "summary": "ledger",
        "result": {"sos_mode_ledger": {"state": "pending", "snapshot_status": "ok", "active_mode": "Docked", "requested_mode": "Cruise", "grid_entity_id": 10}},
    }]}}), encoding="utf-8")
    scripts = {"bridge-a-orchestrator": WorkerScript("bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator")}
    for service_id, script_id in services:
        scripts[script_id] = WorkerScript(script_id, "manual", service_id, plan_module.__name__ if service_id == "mode_transition_plan" else sibling_module.__name__, "", "", 1000, True)
    raw_request = {"requested_mode": "Cruise", "request_id": "plan-1", "expires_after_sequence": 20, "tags": ["operator", 7]}
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": "bridge-a", "sequence": 10,
            "script_id": "bridge-a-orchestrator", "state": {},
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "identity_status": "ok", "blocks": [{"name": "Bridge PB", "functional": True, "integrity_ratio": 1.0}]},
            "runtime_telemetry": {"limiter_state": "ok", "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0}},
            LEDGER_ONLY_ALIAS: {"active_mode": "Docked", "requested_mode": "Cruise", "transition_id": "ledger-1", "transition_sequence": 10},
            **{alias: dict(raw_request) for alias in PLAN_ALIASES},
        }, scripts, {}, tmp_path,
    )

    plan_request = captured["mode_transition_plan"]
    assert plan_request["sos_ship"]["identity_status"] == "ok"
    assert plan_request["sos_ship"]["mode"] == "Docked"
    assert plan_request["grid_snapshot"]["grid_entity_id"] == 10
    assert plan_request["integrity_snapshot"]["blocks"][0]["name"] == "Bridge PB"
    assert plan_request["runtime_telemetry"]["limiter_state"] == "ok"
    assert "mode_ledger" in plan_request["runtime_telemetry"]["child_services_by_service_id"]
    for alias in PLAN_ALIASES:
        assert plan_request[alias] == raw_request
        assert isinstance(plan_request[alias]["tags"][1], int)
    assert LEDGER_ONLY_ALIAS not in plan_request
    assert LEDGER_ONLY_ALIAS in captured["bridge-a-sos_mode_ledger"]
    for service_id, script_id in services:
        if service_id != "mode_transition_plan":
            assert all(alias not in captured[script_id] for alias in PLAN_ALIASES)
    assert json.loads((data / "sos_ships.json").read_text(encoding="utf-8"))["ships"][0]["mode"] == "Docked"
    assert result["status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_shim_transition_request_is_plan_only_and_uses_the_validated_ledger_mode(tmp_path: Path):
    captured: dict[str, dict] = {}
    plan_module = types.ModuleType("tests.sos_shim_transition_request_plan")
    sibling_module = types.ModuleType("tests.sos_shim_transition_request_sibling")

    def run_plan(request):
        captured["plan"] = request
        return {"summary": "plan", "commands": []}

    def run_sibling(request):
        captured["status"] = request
        return {"summary": "status", "commands": []}

    plan_module.run = run_plan
    sibling_module.run = run_sibling
    sys.modules[plan_module.__name__] = plan_module
    sys.modules[sibling_module.__name__] = sibling_module
    services = [
        {"service_id": "mode_transition_plan", "script_id": "bridge-a-sos_mode_transition_plan"},
        {"service_id": "status", "script_id": "bridge-a-sos_status"},
    ]
    data = tmp_path / "data"
    data.mkdir()
    ships = {
        "schema": "novali.client_side_pb.sos_ships.v1",
        "ships": [{
            "ship_id": "ship-a", "bridge_id": "bridge-a", "display_name": "Ship A",
            "expected_grid_entity_id": 10, "mode": "Docked", "services": services, "status_surfaces": [],
        }],
    }
    ship_file = data / "sos_ships.json"
    ship_file.write_text(json.dumps(ships), encoding="utf-8")
    scripts = {
        "bridge-a-orchestrator": WorkerScript("bridge-a-orchestrator", "script_instance", "SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"),
        "bridge-a-sos_mode_transition_plan": WorkerScript("bridge-a-sos_mode_transition_plan", "manual", "Plan", plan_module.__name__, "", "", 1000, True),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", sibling_module.__name__, "", "", 1000, True),
    }
    ledger = {
        "schema": "novali.sos_mode_ledger.v1", "active_mode": "Cruise", "previous_mode": "Docked",
        "target_mode": "Cruise", "action_id": "action-1", "approval_nonce": "nonce-1",
        "grid_entity_id": 10, "sequence": 12, "outcome": "applied", "rejection_reason": "",
    }
    request = {
        "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": "bridge-a",
        "sequence": 13, "script_id": "bridge-a-orchestrator", "state": {},
        "grid_snapshot": {"grid_entity_id": 10, "identity_status": "ok", "blocks": []},
        "mode_ledger_snapshot": ledger,
        "mode_transition_request": {"requested_mode": "Mining", "request_id": "operator-mining-001", "expires_after_sequence": 120},
    }

    result = execute_request(request, scripts, {}, tmp_path)

    assert result["status"] == "ok"
    assert captured["plan"]["mode_transition_request"] == request["mode_transition_request"]
    assert captured["plan"]["sos_ship"]["configured_mode"] == "Docked"
    assert captured["plan"]["sos_ship"]["mode"] == "Cruise"
    assert "mode_ledger_snapshot" not in captured["plan"]
    assert "mode_transition_request" not in captured["status"]
    assert json.loads(ship_file.read_text(encoding="utf-8")) == ships
    assert result["result"]["commands"] == []
    assert len(json.dumps(result, separators=(",", ":"))) < 64000


def test_sos_mode_transition_plan_history_stays_within_its_bridge(tmp_path: Path):
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir(parents=True)
    child_config = ({"service_id": "mode_transition_plan", "script_id": "pb-bridge-001-sos_mode_transition_plan"},)
    for bridge_id, state in (("bridge-a", "proposed"), ("bridge-b", "blocked")):
        (results_dir / f"{bridge_id}.json").write_text(json.dumps({"result": {"child_results": [{
            "script_id": "pb-bridge-001-sos_mode_transition_plan", "status": "ok", "error_bucket": "none", "summary": state,
            "result": {"sos_mode_transition_plan": {"state": state}},
        }]}}), encoding="utf-8")

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)
    assert telemetry_a["child_services_by_service_id"]["mode_transition_plan"]["result"]["sos_mode_transition_plan"]["state"] == "proposed"
    assert telemetry_b["child_services_by_service_id"]["mode_transition_plan"]["result"]["sos_mode_transition_plan"]["state"] == "blocked"


def test_worker_orchestrator_does_not_construct_mode_transition_plan_commands():
    assert "set_block_enabled" not in inspect.getsource(execute_orchestrator_request)
