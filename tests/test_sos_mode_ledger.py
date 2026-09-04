import inspect
import json
import sys
import types
from pathlib import Path

from worker.scripts.sos_mode_ledger import run
from worker.worker import WorkerScript, enriched_child_runtime_telemetry, execute_orchestrator_request, execute_request, load_manifest


LEDGER_ALIASES = (
    "mode_ledger_snapshot",
    "active_mode_snapshot",
    "mode_transition_ledger",
    "mode_transition_snapshot",
)


def test_sos_mode_ledger_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.mode_ledger as ledger_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": []}

    monkeypatch.setattr(ledger_service, "run", fake_run)

    assert run({"bridge_id": "bridge-a"}) == {"summary": "from package", "commands": []}


def test_sos_mode_ledger_degrades_without_snapshot():
    result = run({"bridge_id": "bridge-a", "sos_ship": {"ship_id": "ship-a", "mode": "Docked"}})

    assert result["sos_mode_ledger"]["snapshot_status"] == "missing_ledger"
    assert result["sos_mode_ledger"]["state"] == "unknown"
    assert result["commands"] == []


def test_sos_mode_ledger_registered_in_manifest_instance_and_ship_registry(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(Path("data/script_instances.json").read_text(encoding="utf-8"), encoding="utf-8")

    scripts = load_manifest(tmp_path)
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    assert scripts["sos_mode_ledger"].module == "worker.scripts.sos_mode_ledger"
    assert scripts["pb-bridge-001-sos_mode_ledger"].base_script_id == "sos_mode_ledger"
    assert {"service_id": "mode_ledger", "script_id": "pb-bridge-001-sos_mode_ledger", "enabled": True} in registry["ships"][0]["services"]


def test_sos_mode_ledger_orchestrator_preserves_raw_aliases_for_ledger_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    ledger_module = types.ModuleType("tests.sos_mode_ledger_capture")
    sibling_module = types.ModuleType("tests.sos_mode_ledger_siblings")

    def run_ledger(request):
        captured["mode_ledger"] = request
        return run(request)

    def run_sibling(request):
        captured[request["script_id"]] = request
        return {"summary": request["script_id"], "commands": []}

    ledger_module.run = run_ledger
    sibling_module.run = run_sibling
    sys.modules[ledger_module.__name__] = ledger_module
    sys.modules[sibling_module.__name__] = sibling_module
    services = (
        ("mode_ledger", "bridge-a-sos_mode_ledger"),
        ("operating_directive", "bridge-a-sos_operating_directive"),
        ("authority", "bridge-a-sos_authority"),
        ("automation_plan", "bridge-a-sos_automation_plan"),
        ("automation_recovery", "bridge-a-sos_automation_recovery"),
        ("guidance", "bridge-a-sos_guidance"),
        ("runbook", "bridge-a-sos_runbook"),
        ("dashboard", "bridge-a-sos_dashboard"),
        ("status", "bridge-a-sos_status"),
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{
            "ship_id": "ship-a", "bridge_id": "bridge-a", "display_name": "Ship A", "expected_grid_entity_id": 10,
            "mode": "Docked", "services": [{"service_id": service_id, "script_id": script_id} for service_id, script_id in services],
            "status_surfaces": [],
        }]}),
        encoding="utf-8",
    )
    result_dir = data / "bridge_results"
    result_dir.mkdir()
    (result_dir / "bridge-a.json").write_text(
        json.dumps({"result": {"child_results": [{
            "script_id": "bridge-a-sos_operating_directive", "status": "ok", "error_bucket": "none", "summary": "directive",
            "result": {"sos_operating_directive": {"state": "approval_required"}},
        }]}}),
        encoding="utf-8",
    )
    scripts = {"bridge-a-orchestrator": WorkerScript("bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator")}
    for service_id, script_id in services:
        scripts[script_id] = WorkerScript(script_id, "manual", service_id, ledger_module.__name__ if service_id == "mode_ledger" else sibling_module.__name__, "", "", 1000, True)
    raw_receipt = {"active_mode": "Docked", "requested_mode": "Cruise", "transition_id": "transition-1", "transition_sequence": 10, "last_outcome": "pending", "grid_entity_id": 10}
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": "bridge-a", "sequence": 10,
            "script_id": "bridge-a-orchestrator", "state": {},
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "identity_status": "ok", "blocks": [{"name": "Bridge PB", "functional": True, "integrity_ratio": 1.0}]},
            "runtime_telemetry": {"limiter_state": "ok", "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0}},
            **{alias: dict(raw_receipt) for alias in LEDGER_ALIASES},
        },
        scripts, {}, tmp_path,
    )

    ledger_request = captured["mode_ledger"]
    assert ledger_request["sos_ship"]["identity_status"] == "ok"
    assert ledger_request["sos_ship"]["mode"] == "Docked"
    assert ledger_request["grid_snapshot"]["grid_entity_id"] == 10
    assert ledger_request["integrity_snapshot"]["blocks"][0]["name"] == "Bridge PB"
    assert ledger_request["runtime_telemetry"]["limiter_state"] == "ok"
    assert "operating_directive" in ledger_request["runtime_telemetry"]["child_services_by_service_id"]
    for alias in LEDGER_ALIASES:
        assert ledger_request[alias] == raw_receipt
        assert isinstance(ledger_request[alias]["transition_sequence"], int)
    for service_id, script_id in services:
        if service_id != "mode_ledger":
            assert all(alias not in captured[script_id] for alias in LEDGER_ALIASES)
    assert json.loads((data / "sos_ships.json").read_text(encoding="utf-8"))["ships"][0]["mode"] == "Docked"
    assert result["status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_sos_mode_ledger_history_stays_within_its_bridge(tmp_path: Path):
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir(parents=True)
    child_config = ({"service_id": "mode_ledger", "script_id": "pb-bridge-001-sos_mode_ledger"},)
    for bridge_id, state in (("bridge-a", "confirmed"), ("bridge-b", "blocked")):
        (results_dir / f"{bridge_id}.json").write_text(
            json.dumps({"result": {"child_results": [{
                "script_id": "pb-bridge-001-sos_mode_ledger", "status": "ok", "error_bucket": "none", "summary": state,
                "result": {"sos_mode_ledger": {"state": state}},
            }]}}),
            encoding="utf-8",
        )

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)

    assert telemetry_a["child_services_by_service_id"]["mode_ledger"]["result"]["sos_mode_ledger"]["state"] == "confirmed"
    assert telemetry_b["child_services_by_service_id"]["mode_ledger"]["result"]["sos_mode_ledger"]["state"] == "blocked"


def test_worker_orchestrator_does_not_construct_mode_ledger_commands():
    assert "set_block_enabled" not in inspect.getsource(execute_orchestrator_request)
