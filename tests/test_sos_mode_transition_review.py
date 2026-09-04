from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

from worker.scripts.sos_mode_transition_review import run
from worker.worker import WorkerScript, compact_result_for_storage, enriched_child_runtime_telemetry, execute_orchestrator_request, execute_request, load_manifest


RAW_MODE_CONTROL_ALIASES = (
    "mode_transition_request",
    "operator_mode_transition",
    "mode_change_request",
    "operating_mode_request",
    "mode_transition_plan_snapshot",
    "mode_ledger_snapshot",
    "active_mode_snapshot",
    "mode_transition_ledger",
    "mode_transition_snapshot",
    "operator_mode_transition_approval",
    "mode_transition_approval_snapshot",
    "sos_mode_transition_approval",
    "operating_mode_approval",
    "mode_transition_receipt",
    "active_mode_receipt",
    "operating_mode_receipt",
    "mode_transition_apply_receipt",
)
DIRECTIVE_ALIASES = ("operating_directive_snapshot", "desired_mode_snapshot", "operator_mode_request")


def test_sos_mode_transition_review_adapter_import_checkpoint():
    assert callable(run)


def test_sos_mode_transition_review_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.mode_transition_review as review_service

    expected = {"summary": "review package", "commands": [], "sos_mode_transition_review": {"state": "unknown"}}
    monkeypatch.setattr(review_service, "run", lambda request: expected)

    assert run({"bridge_id": "bridge-a"}) == expected


def test_sos_mode_transition_review_degrades_safely_without_history():
    result = run({
        "bridge_id": "bridge-a", "sequence": 10,
        "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "mode": "Docked", "expected_grid_entity_id": 10, "identity_status": "ok"},
        "grid_snapshot": {"grid_entity_id": 10, "identity_status": "ok"},
        "runtime_telemetry": {},
    })

    assert result["sos_mode_transition_review"]["state"] == "unknown"
    assert result["sos_mode_transition_review"]["snapshot_status"] == "missing_plan"
    assert result["commands"] == []


def test_sos_mode_transition_review_manifest_instance_and_registry_parity(tmp_path: Path):
    worker_dir = tmp_path / "worker"
    data_dir = tmp_path / "data"
    worker_dir.mkdir()
    data_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "script_instances.json").write_text(Path("data/script_instances.json").read_text(encoding="utf-8"), encoding="utf-8")

    scripts = load_manifest(tmp_path)
    registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))

    assert scripts["sos_mode_transition_review"].module == "worker.scripts.sos_mode_transition_review"
    assert scripts["pb-bridge-001-sos_mode_transition_review"].base_script_id == "sos_mode_transition_review"
    assert {"service_id": "mode_transition_review", "script_id": "pb-bridge-001-sos_mode_transition_review", "enabled": True} in registry["ships"][0]["services"]


def test_review_receives_shared_context_and_prior_history_but_no_raw_control_evidence(tmp_path: Path):
    captured: dict[str, dict] = {}
    review_module = types.ModuleType("tests.mode_transition_review_capture")
    sibling_module = types.ModuleType("tests.mode_transition_review_sibling")

    def run_review(request):
        captured["review"] = request
        return run(request)

    def run_sibling(request):
        captured[request["script_id"]] = request
        return {"summary": request["script_id"], "commands": []}

    review_module.run = run_review
    sibling_module.run = run_sibling
    sys.modules[review_module.__name__] = review_module
    sys.modules[sibling_module.__name__] = sibling_module
    bridge_id = "bridge-a"
    services = [
        {"service_id": "mode_transition_review", "script_id": f"{bridge_id}-sos_mode_transition_review"},
        {"service_id": "mode_transition_plan", "script_id": f"{bridge_id}-sos_mode_transition_plan"},
        {"service_id": "mode_ledger", "script_id": f"{bridge_id}-sos_mode_ledger"},
        {"service_id": "operating_directive", "script_id": f"{bridge_id}-sos_operating_directive"},
        {"service_id": "authority", "script_id": f"{bridge_id}-sos_authority"},
        {"service_id": "status", "script_id": f"{bridge_id}-sos_status"},
    ]
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{
        "ship_id": "ship-a", "bridge_id": bridge_id, "display_name": "Ship A", "expected_grid_entity_id": 10,
        "mode": "Docked", "services": services, "status_surfaces": [],
    }]}), encoding="utf-8")
    results = data / "bridge_results"
    results.mkdir()
    plan = {"plans": [{"state": "proposed", "approval_status": "required", "action_family": "active_mode_transition", "action_id": "review-action", "approval_nonce": "review-nonce", "target_grid_entity_id": 10, "from_mode": "Docked", "to_mode": "Cruise", "expires_after_sequence": 20}]}
    ledger = {"state": "pending", "snapshot_status": "ok", "active_mode": "Docked", "requested_mode": "Cruise", "grid_entity_id": 10}
    directive = {"state": "approval_required", "snapshot_status": "ok", "current_mode": "Docked", "requested_mode": "Cruise", "grid_entity_id": 10}
    authority = {"state": "allowed", "snapshot_status": "ok"}
    previous = [
        {"service_id": "mode_transition_plan", "script_id": f"{bridge_id}-sos_mode_transition_plan", "result": {"sos_mode_transition_plan": plan}},
        {"service_id": "mode_ledger", "script_id": f"{bridge_id}-sos_mode_ledger", "result": {"sos_mode_ledger": ledger}},
        {"service_id": "operating_directive", "script_id": f"{bridge_id}-sos_operating_directive", "result": {"sos_operating_directive": directive}},
        {"service_id": "authority", "script_id": f"{bridge_id}-sos_authority", "result": {"sos_authority": authority}},
    ]
    (results / f"{bridge_id}.json").write_text(json.dumps({"result": {"child_results": previous}}), encoding="utf-8")
    scripts = {f"{bridge_id}-orchestrator": WorkerScript(f"{bridge_id}-orchestrator", "script_instance", "SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator")}
    for service in services:
        script_id = service["script_id"]
        scripts[script_id] = WorkerScript(script_id, "manual", service["service_id"], review_module.__name__ if service["service_id"] == "mode_transition_review" else sibling_module.__name__, "", "", 1000, True)
    raw_aliases = {alias: {"raw": alias, "value": 7} for alias in RAW_MODE_CONTROL_ALIASES}
    raw_aliases.update({alias: {"raw": alias, "value": 8} for alias in DIRECTIVE_ALIASES})
    result = execute_request({
        "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": bridge_id,
        "sequence": 10, "script_id": f"{bridge_id}-orchestrator", "state": {},
        "grid_snapshot": {"grid_entity_id": 10, "identity_status": "ok", "blocks": [{"name": "Bridge PB", "functional": True, "integrity_ratio": 1.0}]},
        "runtime_telemetry": {"limiter_state": "ok", "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0}},
        **raw_aliases,
    }, scripts, {}, tmp_path)

    review_request = captured["review"]
    assert review_request["sos_ship"]["identity_status"] == "ok"
    assert review_request["grid_snapshot"]["grid_entity_id"] == 10
    assert review_request["integrity_snapshot"]["blocks"][0]["name"] == "Bridge PB"
    assert review_request["runtime_telemetry"]["queue_pressure"]["remaining"] == 0
    assert review_request["runtime_telemetry"]["child_services_by_service_id"]["mode_transition_plan"]["result"] == {"sos_mode_transition_plan": plan}
    assert review_request["runtime_telemetry"]["child_services_by_script_id"][f"{bridge_id}-sos_authority"]["result"] == {"sos_authority": authority}
    for alias in RAW_MODE_CONTROL_ALIASES + DIRECTIVE_ALIASES:
        assert alias not in review_request
    review_result = next(child for child in result["result"]["child_results"] if child["script_id"] == f"{bridge_id}-sos_mode_transition_review")
    assert review_result["result"]["sos_mode_transition_review"]["state"] == "ready"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}
    assert len(json.dumps(compact_result_for_storage(result), separators=(",", ":"))) < 64000


def test_mode_transition_review_history_is_same_bridge_only(tmp_path: Path):
    results = tmp_path / "data" / "bridge_results"
    results.mkdir(parents=True)
    child_config = ({"service_id": "mode_transition_review", "script_id": "pb-bridge-001-sos_mode_transition_review"},)
    for bridge_id, state in (("bridge-a", "ready"), ("bridge-b", "blocked")):
        child = {
            "service_id": "mode_transition_review", "script_id": "pb-bridge-001-sos_mode_transition_review",
            "result": {"sos_mode_transition_review": {"state": state}},
        }
        (results / f"{bridge_id}.json").write_text(json.dumps({"result": {"child_results": [child]}}), encoding="utf-8")

    telemetry_a = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, child_config)
    telemetry_b = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, child_config)
    assert telemetry_a["child_services_by_service_id"]["mode_transition_review"]["result"]["sos_mode_transition_review"]["state"] == "ready"
    assert telemetry_b["child_services_by_service_id"]["mode_transition_review"]["result"]["sos_mode_transition_review"]["state"] == "blocked"
    assert "set_sos_active_mode" not in inspect.getsource(execute_orchestrator_request)
