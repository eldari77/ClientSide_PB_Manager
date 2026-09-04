from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

from worker.scripts.sos_dashboard import run as run_dashboard
from worker.scripts.sos_mode_ledger import run as run_ledger
from worker.scripts.sos_mode_transition_apply import run as run_apply
from worker.scripts.sos_mode_transition_plan import run as run_plan
from worker.worker import WorkerScript, compact_result_for_storage, enriched_child_runtime_telemetry, execute_request, load_manifest


PLAN_ALIASES = ("mode_transition_request", "operator_mode_transition", "mode_change_request", "operating_mode_request", "mode_transition_plan_snapshot")
LEDGER_ALIASES = ("mode_ledger_snapshot", "active_mode_snapshot", "mode_transition_ledger", "mode_transition_snapshot")
APPROVAL_ALIASES = ("operator_mode_transition_approval", "mode_transition_approval_snapshot", "sos_mode_transition_approval", "operating_mode_approval")
RECEIPT_ALIASES = ("mode_transition_receipt", "active_mode_receipt", "operating_mode_receipt", "mode_transition_apply_receipt")


def _ship_file(tmp_path: Path, services: list[dict]) -> None:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{
        "ship_id": "ship-a", "bridge_id": "bridge-a", "display_name": "Ship A", "expected_grid_entity_id": 10,
        "mode": "Docked", "services": services, "status_surfaces": [],
    }]}), encoding="utf-8")


def _request(**aliases: object) -> dict:
    return {
        "schema": "novali.client_side_pb_bridge.v1", "message_kind": "request", "bridge_id": "bridge-a", "sequence": 10,
        "script_id": "bridge-a-orchestrator", "state": {},
        "grid_snapshot": {"grid_entity_id": 10, "identity_status": "ok", "blocks": []},
        "runtime_telemetry": {"limiter_state": "ok"}, **aliases,
    }


def test_commissioning_adapter_manifest_instance_and_registry_parity() -> None:
    scripts = load_manifest(Path("."))
    instances = json.loads(Path("data/script_instances.json").read_text(encoding="utf-8"))["instances"]
    services = {item["service_id"]: item["script_id"] for item in json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))["ships"][0]["services"]}

    for service_id, adapter in (("mode_ledger", run_ledger), ("mode_transition_plan", run_plan), ("mode_transition_apply", run_apply)):
        script_id = f"sos_{service_id}"
        instance_id = f"pb-bridge-001-sos_{service_id}"
        assert callable(adapter)
        assert scripts[script_id].module == f"worker.scripts.{script_id}"
        assert instances[instance_id]["base_script_id"] == script_id
        assert services[service_id] == instance_id


def test_commissioning_orchestrator_scopes_transition_aliases_to_their_owner_only(tmp_path: Path) -> None:
    captured: dict[str, dict] = {}
    service_ids = ("mode_ledger", "mode_transition_plan", "mode_transition_apply", "dashboard")
    services = [{"service_id": service_id, "script_id": f"bridge-a-sos_{service_id}"} for service_id in service_ids]
    _ship_file(tmp_path, services)
    scripts = {"bridge-a-orchestrator": WorkerScript("bridge-a-orchestrator", "script_instance", "SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator")}
    for service_id in service_ids:
        module = types.ModuleType(f"tests.commissioning_capture_{service_id}")

        def run(request, owner=service_id):
            captured[owner] = request
            return {"summary": owner, "commands": []}

        module.run = run
        sys.modules[module.__name__] = module
        scripts[f"bridge-a-sos_{service_id}"] = WorkerScript(f"bridge-a-sos_{service_id}", "manual", service_id, module.__name__, "", "", 1000, True)

    plan = {"requested_mode": "Cruise", "request_id": "request-1", "expires_after_sequence": 12}
    ledger = {"active_mode": "Docked", "requested_mode": "Cruise", "transition_id": "request-1"}
    approval = {"approved": True, "action_id": "action-1", "approval_nonce": "nonce-1", "target_grid_entity_id": 10, "from_mode": "Docked", "to_mode": "Cruise", "expires_after_sequence": 12}
    receipt = {"last_action_id": "action-1", "approval_nonce": "nonce-1", "last_outcome": "none", "last_sequence": 10}
    execute_request(_request(**{key: plan for key in PLAN_ALIASES}, **{key: ledger for key in LEDGER_ALIASES}, **{key: approval for key in APPROVAL_ALIASES}, **{key: receipt for key in RECEIPT_ALIASES}), scripts, {}, tmp_path)

    for alias in PLAN_ALIASES:
        assert alias in captured["mode_transition_plan"]
        assert all(alias not in captured[service_id] for service_id in service_ids if service_id != "mode_transition_plan")
    for alias in LEDGER_ALIASES:
        assert alias in captured["mode_ledger"]
        assert all(alias not in captured[service_id] for service_id in service_ids if service_id != "mode_ledger")
    for alias in APPROVAL_ALIASES + RECEIPT_ALIASES:
        assert alias in captured["mode_transition_apply"]
        assert all(alias not in captured[service_id] for service_id in service_ids if service_id != "mode_transition_apply")
    assert "mode_transition_snapshot" not in captured["mode_transition_apply"]


def test_commissioning_core_transports_addon_envelope_without_mode_or_cross_bridge_mutation(tmp_path: Path) -> None:
    services = [{"service_id": "mode_transition_apply", "script_id": "bridge-a-sos_mode_transition_apply"}]
    _ship_file(tmp_path, services)
    module = types.ModuleType("tests.commissioning_apply")
    envelope = {"kind": "set_sos_active_mode", "from_mode": "Docked", "to_mode": "Cruise", "sos_action_id": "action-1", "sos_action_family": "active_mode_transition", "sos_approval_nonce": "nonce-1", "sos_target_grid_entity_id": 10, "sos_expires_after_sequence": 12}
    module.run = lambda request: {"summary": "apply", "commands": [envelope]}
    sys.modules[module.__name__] = module
    scripts = {
        "bridge-a-orchestrator": WorkerScript("bridge-a-orchestrator", "script_instance", "SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"),
        "bridge-a-sos_mode_transition_apply": WorkerScript("bridge-a-sos_mode_transition_apply", "manual", "Apply", module.__name__, "", "", 1000, True),
    }
    results = tmp_path / "data" / "bridge_results"
    results.mkdir()
    for bridge, state in (("bridge-a", "applied"), ("bridge-b", "rejected")):
        (results / f"{bridge}.json").write_text(json.dumps({"result": {"child_results": [{"service_id": "mode_transition_apply", "script_id": "bridge-a-sos_mode_transition_apply", "result": {"sos_mode_transition_apply": {"state": state}}}]}}), encoding="utf-8")

    result = execute_request(_request(), scripts, {}, tmp_path)
    command = result["result"]["commands"][0]
    assert {key: command[key] for key in envelope} == envelope
    assert json.loads((tmp_path / "data" / "sos_ships.json").read_text(encoding="utf-8"))["ships"][0]["mode"] == "Docked"
    assert len(json.dumps(compact_result_for_storage(result), separators=(",", ":"))) < 64000
    assert enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-a"}, services)["child_services_by_service_id"]["mode_transition_apply"]["result"]["sos_mode_transition_apply"]["state"] == "applied"
    assert enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "bridge-b"}, services)["child_services_by_service_id"]["mode_transition_apply"]["result"]["sos_mode_transition_apply"]["state"] == "rejected"


def test_commissioning_dashboard_supports_all_prior_apply_history_shapes() -> None:
    payload = {"state": "rejected", "snapshot_status": "ok", "action_id": "action-1", "from_mode": "Docked", "to_mode": "Cruise", "approval_status": "approved", "receipt_status": "rejected", "receipt_reason": "current_mode_changed", "reconciliation_state": "rejected", "warnings": ["receipt_rejected:current_mode_changed"], "blockers": [], "source_services": ["mode_transition_plan", "mode_ledger"]}
    child = {"service_id": "mode_transition_apply", "script_id": "pb-bridge-001-sos_mode_transition_apply", "result": {"sos_mode_transition_apply": payload}}
    for telemetry in ({"child_services": [child]}, {"child_services_by_service_id": {"mode_transition_apply": child}}, {"child_services_by_script_id": {child["script_id"]: child}}):
        dashboard = run_dashboard({"sos_ship": {"ship_id": "ship-a", "mode": "Docked"}, "runtime_telemetry": telemetry})["sos_dashboard"]
        assert dashboard["mode_transition_apply"]["receipt_reason"] == "current_mode_changed"
        assert dashboard["mode_transition_apply"]["state"] == "rejected"


def test_commissioning_worker_and_dedicated_pb_shim_are_the_only_active_mode_path() -> None:
    worker_source = inspect.getsource(sys.modules["worker.worker"])
    shim = Path("pb_shim/ClientSidePBBridgeShim.cs").read_text(encoding="utf-8")
    gate = shim[shim.index("bool ValidateSosModeTransitionCommand"):shim.index("bool ApplySetBlockEnabledCommand")]

    assert '"kind": "set_sos_active_mode"' not in worker_source
    assert "sos_ship[\"mode\"] =" not in worker_source
    assert "bool sosModeTransitionEnabled = false;" in shim
    for expected in ("sos_mode_transition_approval_action_id=", "sos_mode_transition_approval_nonce=", "sos_mode_transition_approval_grid_id=0", "sos_mode_transition_approval_from_mode=", "sos_mode_transition_approval_to_mode=", "sos_mode_transition_approval_expires_sequence=0", 'if (kind == "set_sos_active_mode")', "ApplySetSosActiveModeCommand(command, resultSequence)", "sos_mode_transition_disabled", "sos_mode_transition_approval_mismatch", "sos_mode_transition_approval_expiry_mismatch", "sos_mode_transition_expired", "sos_mode_transition_receipt_consumed", "sos_mode_transition_current_mode_mismatch", "targetGridEntityId != Me.CubeGrid.EntityId", "RecordSosModeTransitionReceipt", 'SaveField("sos_mode_transition_ledger", BuildSosModeTransitionLedger())', 'if (kind == "set_block_enabled")', "ApplySetBlockEnabledCommand(command, resultSequence)"):
        assert expected in shim or expected in gate
    assert "generic" not in gate.lower() or "generic approval" not in gate.lower()
