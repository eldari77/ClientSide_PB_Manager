from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from worker.worker import WorkerScript, compact_result_for_storage, execute_request, load_manifest


APPROVAL_ALIASES = (
    "operator_mode_transition_approval",
    "mode_transition_approval_snapshot",
    "sos_mode_transition_approval",
    "operating_mode_approval",
)
RECEIPT_ALIASES = (
    "mode_transition_receipt",
    "active_mode_receipt",
    "operating_mode_receipt",
    "mode_transition_apply_receipt",
)


def test_mode_transition_apply_adapter_delegates_and_preserves_passive_no_snapshot_fallback(monkeypatch):
    import worker.scripts.sos_mode_transition_apply as adapter

    from sos.services.mode_transition_apply import run

    result = run({"bridge_id": "pb-bridge-001", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A"}})
    assert result["commands"] == []
    assert result["sos_mode_transition_apply"]["snapshot_status"] == "missing_plan"

    expected = {"summary": "delegated", "commands": [], "sos_mode_transition_apply": {"state": "unknown"}}
    monkeypatch.setattr(adapter._mode_transition_apply_service, "run", lambda request: expected)
    assert adapter.run({"sequence": 7}) is expected


def test_mode_transition_apply_manifest_instance_and_registry_mount_are_executable():
    scripts = load_manifest(Path("."))
    assert scripts["sos_mode_transition_apply"].module == "worker.scripts.sos_mode_transition_apply"

    instances = json.loads(Path("data/script_instances.json").read_text(encoding="utf-8"))["instances"]
    assert instances["pb-bridge-001-sos_mode_transition_apply"]["base_script_id"] == "sos_mode_transition_apply"

    ship = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))["ships"][0]
    assert {item["service_id"]: item["script_id"] for item in ship["services"]}["mode_transition_apply"] == "pb-bridge-001-sos_mode_transition_apply"


def test_orchestrator_scopes_mode_transition_apply_evidence_without_sibling_leakage(tmp_path: Path):
    bridge_id = "bridge-a"
    captured: dict[str, dict] = {}
    service_ids = ("mode_transition_apply", "mode_ledger", "mode_transition_plan", "dashboard", "status")
    services = [{"service_id": service_id, "script_id": f"{bridge_id}-sos_{service_id}"} for service_id in service_ids]
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sos_ships.json").write_text(
        json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{"ship_id": "ship-a", "bridge_id": bridge_id, "display_name": "Ship A", "expected_grid_entity_id": 10, "mode": "Docked", "services": services, "status_surfaces": []}]}),
        encoding="utf-8",
    )
    scripts = {
        f"{bridge_id}-orchestrator": WorkerScript(f"{bridge_id}-orchestrator", "script_instance", "SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator", instance_bridge_id=bridge_id),
    }
    for service_id in service_ids:
        module_name = f"tests.mode_transition_apply_capture_{service_id}"
        module = types.ModuleType(module_name)

        def run(request, expected=service_id):
            captured[expected] = request
            return {"summary": expected, "commands": []}

        module.run = run
        sys.modules[module_name] = module
        scripts[f"{bridge_id}-sos_{service_id}"] = WorkerScript(f"{bridge_id}-sos_{service_id}", "manual", service_id, module_name, "", "", 1000, True)

    approval = {"approved": True, "action_id": "action-1", "approval_nonce": "nonce-1", "target_grid_entity_id": 10, "from_mode": "Docked", "to_mode": "Cruise", "expires_after_sequence": 12}
    receipt = {"last_action_id": "action-1", "approval_nonce": "nonce-1", "last_outcome": "none", "last_sequence": 10, "target_grid_entity_id": 10}
    request = {
        "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": bridge_id, "sequence": 10, "script_id": f"{bridge_id}-orchestrator",
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "identity_status": "ok", "blocks": []},
        "integrity_snapshot": {"blocks": []}, "runtime_telemetry": {"limiter_state": "ok"}, "state": {},
        **{key: approval for key in APPROVAL_ALIASES},
        **{key: receipt for key in RECEIPT_ALIASES},
        "mode_transition_snapshot": {"active_mode": "Docked"},
    }
    result = execute_request(request, scripts, {}, tmp_path)

    assert result["status"] == "ok"
    apply_request = captured["mode_transition_apply"]
    for alias in APPROVAL_ALIASES + RECEIPT_ALIASES:
        assert apply_request[alias] is request[alias]
        assert all(alias not in sibling for service_id, sibling in captured.items() if service_id != "mode_transition_apply")
    assert "mode_transition_snapshot" not in apply_request
    assert captured["mode_ledger"]["mode_transition_snapshot"] == {"active_mode": "Docked"}
    assert apply_request["sos_ship"]["identity_status"] == "ok"
    assert "queue_pressure" in apply_request["runtime_telemetry"]


def test_mode_transition_apply_history_is_bridge_scoped_and_preserves_the_addon_command_envelope(tmp_path: Path):
    bridge_id = "bridge-a"
    results = tmp_path / "data" / "bridge_results"
    results.mkdir(parents=True)
    prior = {
        "service_id": "mode_transition_apply", "script_id": f"{bridge_id}-sos_mode_transition_apply",
        "result": {"sos_mode_transition_apply": {"state": "applied", "receipt_status": "applied", "reconciliation_state": "applied"}},
    }
    (results / f"{bridge_id}.json").write_text(json.dumps({"result": {"child_results": [prior]}}), encoding="utf-8")
    (results / "bridge-b.json").write_text(json.dumps({"result": {"child_results": [{**prior, "result": {"sos_mode_transition_apply": {"state": "rejected"}}}]}}), encoding="utf-8")
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.mode_transition_apply_history_capture")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": "apply", "commands": [{"kind": "set_sos_active_mode", "from_mode": "Docked", "to_mode": "Cruise", "sos_action_id": "action-1", "sos_action_family": "active_mode_transition", "sos_approval_nonce": "nonce-1", "sos_target_grid_entity_id": 10, "sos_expires_after_sequence": 12}]}

    module.run = run
    sys.modules[module.__name__] = module
    (tmp_path / "data" / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{"ship_id": "ship-a", "bridge_id": bridge_id, "display_name": "Ship A", "expected_grid_entity_id": 10, "mode": "Docked", "services": [{"service_id": "mode_transition_apply", "script_id": f"{bridge_id}-sos_mode_transition_apply"}], "status_surfaces": []}]}), encoding="utf-8")
    scripts = {
        f"{bridge_id}-orchestrator": WorkerScript(f"{bridge_id}-orchestrator", "script_instance", "SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"),
        f"{bridge_id}-sos_mode_transition_apply": WorkerScript(f"{bridge_id}-sos_mode_transition_apply", "manual", "Apply", module.__name__, "", "", 1000, True),
    }
    result = execute_request({"schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": bridge_id, "sequence": 10, "script_id": f"{bridge_id}-orchestrator", "grid_snapshot": {"grid_entity_id": 10, "identity_status": "ok", "blocks": []}, "state": {}}, scripts, {}, tmp_path)

    telemetry = captured[f"{bridge_id}-sos_mode_transition_apply"]["runtime_telemetry"]
    assert telemetry["child_services"][0]["result"] == prior["result"]
    assert telemetry["child_services_by_service_id"]["mode_transition_apply"]["result"] == prior["result"]
    assert telemetry["child_services_by_script_id"][f"{bridge_id}-sos_mode_transition_apply"]["result"] == prior["result"]
    command = result["result"]["commands"][0]
    assert {key: command[key] for key in ("kind", "from_mode", "to_mode", "sos_action_id", "sos_action_family", "sos_approval_nonce", "sos_target_grid_entity_id", "sos_expires_after_sequence")} == {"kind": "set_sos_active_mode", "from_mode": "Docked", "to_mode": "Cruise", "sos_action_id": "action-1", "sos_action_family": "active_mode_transition", "sos_approval_nonce": "nonce-1", "sos_target_grid_entity_id": 10, "sos_expires_after_sequence": 12}
    assert len(json.dumps(compact_result_for_storage(result), separators=(",", ":"))) < 64000
