from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path
from typing import Any

from worker.worker import WorkerScript, compact_result_for_storage, enriched_child_runtime_telemetry, execute_orchestrator_request, execute_request, load_manifest


DIRECTIVE_ALIASES = ("operating_directive_snapshot", "desired_mode_snapshot", "operator_mode_request")
MODE_LEDGER_ALIASES = ("mode_ledger_snapshot", "active_mode_snapshot", "operating_mode_receipt", "mode_transition_receipt", "mode_transition_ledger", "mode_transition_snapshot")
MODE_TRANSITION_PLAN_ALIASES = ("mode_transition_request", "operator_mode_transition", "mode_change_request", "operating_mode_request", "mode_transition_plan_snapshot")
AUTHORITY_ALIASES = ("authority_snapshot", "operating_authority_snapshot", "procedure_policy_snapshot")
RECOVERY_ALIASES = ("operator_approval_snapshot", "automation_approval_snapshot", "sos_automation_approval", "sos_automation", "automation_receipt_snapshot", "automation_recovery_receipt", "recovery_receipt_snapshot")


def _plan() -> dict[str, Any]:
    return {
        "action_id": "core-loop-action",
        "action_family": "programmable_block_recovery",
        "operation": "enable",
        "target": {"entity_id": 7001, "grid_entity_id": 10},
        "approval_nonce": "core-loop-nonce",
        "expires_after_sequence": 12,
        "state": "proposed",
        "approval_status": "required",
    }


def _write_result(root: Path, bridge_id: str, children: list[dict[str, Any]]) -> None:
    directory = root / "data" / "bridge_results"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{bridge_id}.json").write_text(json.dumps({"status": "ok", "result": {"child_results": children}}), encoding="utf-8")


def _orchestrator_request(bridge_id: str, *, mode: str = "Docked") -> dict[str, Any]:
    directive = {"operator_requested": True, "requested_mode": "Cruise", "request_id": "core-loop-directive", "requested_at_sequence": 10}
    approval = {"approved": True, "action_id": "core-loop-action", "approval_nonce": "core-loop-nonce", "target_entity_id": 7001, "target_grid_entity_id": 10}
    receipt = {"last_action_id": "core-loop-action", "approval_nonce": "core-loop-nonce", "last_outcome": "none", "last_sequence": 10}
    return {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": bridge_id,
        "sequence": 10,
        "script_id": f"{bridge_id}-orchestrator",
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "entity_id": 10, "identity_status": "ok", "blocks": []},
        "script_health_snapshot": {"programmable_blocks": [{"entity_id": 7001, "grid_entity_id": 10, "interface_type": "IMyProgrammableBlock", "functional": True, "enabled": False}]},
        "runtime_telemetry": {"limiter_state": "ok"},
        "state": {"mode": mode},
        **{key: dict(directive) for key in DIRECTIVE_ALIASES},
        **{key: {"active_mode": mode, "requested_mode": "Cruise", "transition_id": "core-loop-transition", "transition_sequence": 10, "last_outcome": "pending", "grid_entity_id": 10} for key in MODE_LEDGER_ALIASES},
        **{key: {"requested_mode": "Cruise", "request_id": "core-loop-plan", "expires_after_sequence": 20} for key in MODE_TRANSITION_PLAN_ALIASES},
        **{key: {"mode": mode} for key in AUTHORITY_ALIASES},
        "operator_approval_snapshot": approval,
        "automation_approval_snapshot": approval,
        "sos_automation_approval": approval,
        "sos_automation": receipt,
        "automation_receipt_snapshot": receipt,
        "automation_recovery_receipt": receipt,
        "recovery_receipt_snapshot": receipt,
    }


def test_orchestrator_routes_control_aliases_only_to_owning_children_and_preserves_all_history_shapes(tmp_path: Path) -> None:
    captured: dict[str, dict[str, Any]] = {}
    service_ids = ("status", "operating_directive", "mode_ledger", "mode_transition_plan", "authority", "guidance", "runbook", "automation_recovery", "dashboard")
    bridge_id = "bridge-loop"
    services = [{"service_id": service_id, "script_id": f"{bridge_id}-sos_{service_id}"} for service_id in service_ids]
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [{"ship_id": "loop-ship", "bridge_id": bridge_id, "display_name": "Loop Ship", "expected_grid_entity_id": 10, "mode": "Docked", "services": services, "status_surfaces": []}]}), encoding="utf-8")
    previous = [{"service_id": service_id, "script_id": f"{bridge_id}-sos_{service_id}", "result": {f"sos_{service_id}": {"state": "ok"}}} for service_id in service_ids]
    _write_result(tmp_path, bridge_id, previous)

    scripts: dict[str, WorkerScript] = {
        f"{bridge_id}-orchestrator": WorkerScript(f"{bridge_id}-orchestrator", "script_instance", "Loop SOS", "", "adapter_tick.v1", "compact_commands.v1", 1000, True, base_script_id="bridge_orchestrator", instance_bridge_id=bridge_id)
    }
    for service_id in service_ids:
        module_name = f"tests.operating_loop_capture_{service_id}"
        module = types.ModuleType(module_name)

        def run(request: dict[str, Any], expected: str = service_id) -> dict[str, Any]:
            captured[expected] = request
            return {"summary": expected, "commands": [{"kind": "echo", "text": expected}]}

        module.run = run
        sys.modules[module_name] = module
        scripts[f"{bridge_id}-sos_{service_id}"] = WorkerScript(f"{bridge_id}-sos_{service_id}", "manual", service_id, module_name, "adapter_tick.v1", "compact_commands.v1", 1000, True)

    result = execute_request(_orchestrator_request(bridge_id), scripts, {}, tmp_path)

    assert result["status"] == "ok"
    for alias in DIRECTIVE_ALIASES:
        assert alias in captured["operating_directive"]
        assert all(alias not in request for service_id, request in captured.items() if service_id != "operating_directive")
    for alias in MODE_LEDGER_ALIASES:
        assert alias in captured["mode_ledger"]
        assert all(alias not in request for service_id, request in captured.items() if service_id != "mode_ledger")
    for alias in MODE_TRANSITION_PLAN_ALIASES:
        assert alias in captured["mode_transition_plan"]
        assert all(alias not in request for service_id, request in captured.items() if service_id != "mode_transition_plan")
    for alias in AUTHORITY_ALIASES:
        assert alias in captured["authority"]
        assert all(alias not in request for service_id, request in captured.items() if service_id != "authority")
    for alias in RECOVERY_ALIASES:
        assert alias in captured["automation_recovery"]
        assert all(alias not in request for service_id, request in captured.items() if service_id != "automation_recovery")
    for service_id in ("authority", "operating_directive", "mode_ledger", "mode_transition_plan", "guidance", "runbook", "dashboard", "automation_recovery"):
        telemetry = captured[service_id]["runtime_telemetry"]
        assert telemetry["child_services"]
        assert telemetry["child_services_by_service_id"]
        assert telemetry["child_services_by_script_id"]


def test_real_orchestrator_preserves_addon_recovery_envelope_terminal_suppression_and_storage_limit(tmp_path: Path) -> None:
    bridge_id = "pb-bridge-001"
    source_registry = json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))
    ship = dict(source_registry["ships"][0])
    ship.update({"bridge_id": bridge_id, "ship_id": "ship-pb-bridge-001", "display_name": "Core Loop Ship", "mode": "Docked", "expected_grid_entity_id": 10, "status_surfaces": []})
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [ship]}), encoding="utf-8")
    _write_result(tmp_path, bridge_id, [{"service_id": "automation_plan", "script_id": "pb-bridge-001-sos_automation_plan", "result": {"sos_automation_plan": {"plans": [_plan()]}}}])
    scripts = load_manifest(Path("."))

    request = _orchestrator_request(bridge_id)
    for alias in ("automation_approval_snapshot", "sos_automation_approval", "sos_automation", "automation_recovery_receipt", "recovery_receipt_snapshot"):
        request.pop(alias)
    result = execute_request(request, scripts, {}, tmp_path)
    output = result["result"]
    recovery = next(item for item in output["child_results"] if item["script_id"] == "pb-bridge-001-sos_automation_recovery")
    command = next(command for command in output["commands"] if command["kind"] == "set_block_enabled")
    assert recovery["result"]["sos_automation_recovery"]["state"] == "emitted"
    assert {key: command[key] for key in ("kind", "block_entity_id", "enabled", "sos_action_id", "sos_action_family", "sos_approval_nonce", "sos_target_grid_entity_id", "sos_expires_after_sequence")} == {"kind": "set_block_enabled", "block_entity_id": 7001, "enabled": True, "sos_action_id": "core-loop-action", "sos_action_family": "programmable_block_recovery", "sos_approval_nonce": "core-loop-nonce", "sos_target_grid_entity_id": 10, "sos_expires_after_sequence": 12}
    assert set(command) - {"kind", "block_entity_id", "enabled", "sos_action_id", "sos_action_family", "sos_approval_nonce", "sos_target_grid_entity_id", "sos_expires_after_sequence"} <= {"command_id", "source_order", "source_priority", "source_role", "source_script_id", "source_service_id", "expires_after_sequences"}
    assert json.loads((tmp_path / "data" / "sos_ships.json").read_text(encoding="utf-8"))["ships"][0]["mode"] == "Docked"
    assert len(json.dumps(compact_result_for_storage(result), separators=(",", ":"))) < 64000



def test_real_orchestrator_terminal_receipt_suppresses_future_recovery_command(tmp_path: Path) -> None:
    bridge_id = "pb-bridge-001"
    ship = dict(json.loads(Path("data/sos_ships.json").read_text(encoding="utf-8"))["ships"][0])
    ship.update({"bridge_id": bridge_id, "ship_id": "ship-pb-bridge-001", "mode": "Docked", "expected_grid_entity_id": 10, "status_surfaces": []})
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sos_ships.json").write_text(json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [ship]}), encoding="utf-8")
    _write_result(tmp_path, bridge_id, [{"service_id": "automation_plan", "script_id": "pb-bridge-001-sos_automation_plan", "result": {"sos_automation_plan": {"plans": [_plan()]}}}])
    request = _orchestrator_request(bridge_id)
    for alias in ("automation_approval_snapshot", "sos_automation_approval", "sos_automation", "automation_recovery_receipt", "recovery_receipt_snapshot"):
        request.pop(alias)
    request["automation_receipt_snapshot"] = {"last_action_id": "core-loop-action", "approval_nonce": "core-loop-nonce", "last_outcome": "applied", "last_sequence": 10}
    output = execute_request(request, load_manifest(Path(".")), {}, tmp_path)["result"]
    recovery = next(item for item in output["child_results"] if item["script_id"] == "pb-bridge-001-sos_automation_recovery")
    assert recovery["result"]["sos_automation_recovery"]["state"] == "applied"
    assert all(command["kind"] != "set_block_enabled" for command in output["commands"])


def test_bridge_identity_isolation_and_worker_non_authority_are_explicit(tmp_path: Path) -> None:
    child_config = ({"service_id": "operating_directive", "script_id": "pb-bridge-001-sos_operating_directive"},)
    _write_result(tmp_path, "ship-a", [{"script_id": "pb-bridge-001-sos_operating_directive", "result": {"sos_operating_directive": {"state": "approval_required"}}}])
    _write_result(tmp_path, "ship-b", [{"script_id": "pb-bridge-001-sos_operating_directive", "result": {"sos_operating_directive": {"state": "blocked"}}}])
    assert enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "ship-a"}, child_config)["child_services_by_service_id"]["operating_directive"]["result"]["sos_operating_directive"]["state"] == "approval_required"
    assert enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "ship-b"}, child_config)["child_services_by_service_id"]["operating_directive"]["result"]["sos_operating_directive"]["state"] == "blocked"
    assert "set_block_enabled" not in inspect.getsource(execute_orchestrator_request)
    assert "evaluate_authority" not in inspect.getsource(execute_orchestrator_request)
