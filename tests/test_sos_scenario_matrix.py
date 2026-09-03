from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from worker.worker import (
    BridgeScriptConfig,
    WorkerScript,
    compact_result_for_storage,
    enriched_child_runtime_telemetry,
    execute_request,
    load_manifest,
)


ALLOWED_SOS_COMMAND_KINDS = {"echo", "write_text_surface"}
DASHBOARD_TOKEN_SERVICES = {
    "alerts",
    "airlock",
    "automation",
    "automation_plan",
    "comms",
    "conveyor",
    "crew",
    "defense",
    "diagnostics",
    "config_drift",
    "display",
    "docking",
    "endurance",
    "environment",
    "guidance",
    "integrity",
    "life_support",
    "logistics",
    "maintenance",
    "mining",
    "mission_profile",
    "mobility",
    "navigation",
    "power",
    "production",
    "readiness",
    "telemetry_quality",
    "redundancy",
    "topology",
    "runbook",
    "transit",
    "watch_log",
}


def _read_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _default_sos_ship() -> dict[str, Any]:
    return _read_json("data/sos_ships.json")["ships"][0]


def _mounted_sos_services() -> list[dict[str, Any]]:
    return [service for service in _default_sos_ship()["services"] if "-sos_" in str(service.get("script_id", ""))]


def _write_sos_registry(root: Path, mode: str) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    ship = dict(_default_sos_ship())
    ship.update(
        {
            "ship_id": "ship-pb-bridge-001",
            "bridge_id": "pb-bridge-001",
            "display_name": "Primary SOS Ship",
            "mode": mode,
            "status_surfaces": [],
        }
    )
    (data / "sos_ships.json").write_text(
        json.dumps({"schema": "novali.client_side_pb.sos_ships.v1", "ships": [ship]}),
        encoding="utf-8",
    )


def _write_previous_result(root: Path, child_results: list[dict[str, Any]]) -> None:
    result_dir = root / "data" / "bridge_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "pb-bridge-001.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "result": {
                    "child_results": child_results,
                    "queue_pressure": {
                        "queued": len(child_results),
                        "drained": len(child_results),
                        "remaining": 0,
                        "by_source": {
                            item["script_id"]: {"queued": 1, "drained": 1, "remaining": 0}
                            for item in child_results
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _request() -> dict[str, Any]:
    return {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "pb-bridge-001",
        "sequence": 10,
        "script_id": "pb-bridge-001-orchestrator",
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 0, "blocks": []},
        "runtime_telemetry": {},
        "state": {},
    }


def _payload_key(service_id: str) -> str:
    return "sos_life_support" if service_id == "life_support" else f"sos_{service_id}"


def _payload(service_id: str, state: str = "ok", warnings: list[str] | None = None) -> dict[str, Any]:
    warnings = list(warnings or [])
    payload: dict[str, Any] = {
        "state": state,
        "summary": f"{state} matrix warnings={len(warnings)} blockers=0",
        "snapshot_status": "ok",
        "warnings": warnings,
        "blockers": [],
    }
    if service_id == "status":
        payload.update({"mode": "Docked", "identity_status": "ok"})
    elif service_id == "alerts":
        critical_count = sum(1 for item in warnings if item.startswith("alerts_critical"))
        payload.update(
            {
                "alert_count": len(warnings),
                "critical_count": critical_count,
                "warning_count": len(warnings) - critical_count,
                "blocker_count": 0,
                "routes": [],
                "top_alerts": [{"source": "alerts", "severity": "critical", "message": item} for item in warnings],
            }
        )
    elif service_id == "mission_profile":
        payload.update({"profile": "Docked", "profile_source": "snapshot", "required_services": [], "mismatches": []})
    elif service_id == "readiness":
        payload.update({"source_count": 1, "ready_source_count": 1, "critical_sources": [], "warning_sources": []})
    elif service_id == "telemetry_quality":
        payload.update(
            {
                "confidence": 0.8,
                "confidence_label": "high",
                "evaluated_service_count": 3,
                "missing_service_count": 1 if warnings else 0,
                "unknown_heavy_service_count": 0,
                "stale_service_count": 0,
                "blocked_service_count": 0,
                "warning_service_count": 1 if warnings else 0,
                "queue_pressure_state": "none",
                "source_services": ["status", "integrity", "logistics"],
            }
        )
    elif service_id == "automation":
        payload.update(
            {
                "loop_state": "degraded" if warnings else "ok",
                "confidence_label": "medium" if warnings else "high",
                "programmable_blocks": {
                    "total_count": 3,
                    "enabled_count": 2,
                    "disabled_count": 1 if warnings else 0,
                    "running_count": 2,
                    "failing_count": 1 if warnings else 0,
                    "stale_count": 0,
                    "unknown_count": 0,
                },
                "automation_blocks": {
                    "total_count": 2,
                    "enabled_count": 2,
                    "disabled_count": 0,
                    "damaged_or_nonfunctional_count": 1 if warnings else 0,
                    "unknown_count": 0,
                },
                "queue_pressure_state": "none",
                "source_services": ["status", "integrity"],
            }
        )
    elif service_id == "automation_plan":
        payload.update(
            {
                "proposed_count": 1,
                "approval_required_count": 1,
                "blocked_count": 0,
                "expired_count": 0,
            }
        )
    elif service_id == "guidance":
        payload.update({"priorities": [{"service_id": "power", "severity": "warning", "reason": item} for item in warnings]})
    elif service_id == "diagnostics":
        payload.update(
            {
                "missing_child_results": [],
                "child_errors": [],
                "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0, "state": "none"},
                "unexpected_command_kinds": [],
            }
        )
    elif service_id == "config_drift":
        payload.update(
            {
                "expected_service_count": 3,
                "observed_service_count": 3,
                "missing_service_count": 1 if warnings else 0,
                "unknown_service_count": 0,
                "mismatched_service_count": 0,
                "duplicate_service_count": 0,
                "drift_count": 1 if warnings else 0,
                "source_services": ["status", "dashboard"],
            }
        )
    elif service_id == "watch_log":
        payload.update(
            {
                "events": [{"source_service": "power", "kind": "warning", "severity": "warning", "message": item} for item in warnings],
                "repeated_sources": [],
                "queue_pressure": {"queued": 0, "drained": 0, "remaining": 0, "state": "none"},
            }
        )
    elif service_id == "endurance":
        payload.update(
            {
                "cargo": {"state": "pressure" if state == "warning" else "ok", "usage_ratio": 0.5, "headroom_ratio": 0.5},
                "ammo": {"state": "shortage" if warnings else "ok", "shortages": []},
                "fuel": {"state": "ok", "hydrogen_state": "ok", "uranium_state": "ok"},
                "energy": {"state": "ok", "runway": "45m", "runway_seconds": 2700},
                "survival": {"state": "ok", "runway": "90m"},
                "transit": {"state": "ok", "constraints": []},
            }
        )
    elif service_id == "redundancy":
        payload.update(
            {
                "covered_capability_count": 8,
                "critical_capability_count": 9,
                "single_point_count": 1 if warnings else 0,
                "backup_unavailable_count": 1 if warnings else 0,
                "degraded_capability_count": 0,
                "missing_capability_count": 0,
                "unknown_coverage_count": 1 if warnings else 0,
            }
        )
    elif service_id == "topology":
        payload.update(
            {
                "dependency_count": 3,
                "degraded_dependency_count": 1 if warnings else 0,
                "blocked_dependency_count": 0,
                "unknown_dependency_count": 0,
                "critical_chain_count": 0,
                "blast_radius": {"state": state, "affected_families": ["mobility"] if warnings else [], "hints": []},
                "dependency_chains": [],
                "source_services": ["power", "mobility"],
            }
        )
    return payload


def _child_result(service_id: str, state: str = "ok", warnings: list[str] | None = None) -> dict[str, Any]:
    script_id = f"pb-bridge-001-sos_{service_id}"
    return {
        "script_id": script_id,
        "status": "ok",
        "error_bucket": "none",
        "summary": f"{service_id} {state}",
        "result": {_payload_key(service_id): _payload(service_id, state, warnings)},
    }


def _scenario_child_results(mode: str, states: dict[str, str], warnings: dict[str, list[str]]) -> list[dict[str, Any]]:
    children = [_child_result("status")]
    children[0]["result"]["sos_status"]["mode"] = mode
    for service_id in sorted(DASHBOARD_TOKEN_SERVICES):
        children.append(_child_result(service_id, states.get(service_id, "ok"), warnings.get(service_id, [])))
    return children


SCENARIOS = (
    ("docked_baseline", "Docked", {}, {}),
    (
        "cruise_degraded_mobility_power_comms",
        "Cruise",
        {"mobility": "degraded", "power": "warning", "comms": "limited"},
        {"mobility": ["thruster_degraded:port"], "power": ["battery_low_charge:reserve"], "comms": ["antenna_range_low:main"]},
    ),
    (
        "combat_defense_ammo_integrity",
        "Combat",
        {"defense": "warning", "logistics": "warning", "integrity": "degraded"},
        {"defense": ["ammo_shortage:Missile 200mm"], "logistics": ["ammo_shortage:Missile 200mm"], "integrity": ["integrity_degraded:reactor"]},
    ),
    (
        "emergency_mixed_blockers",
        "Emergency",
        {"alerts": "critical", "life_support": "blocked", "airlock": "warning", "power": "warning"},
        {"alerts": ["alerts_critical:1"], "life_support": ["oxygen_shortage:medbay"], "airlock": ["exterior_door_open:hangar"], "power": ["reactor_fuel_shortage:uranium"]},
    ),
    (
        "mining_cargo_production_power",
        "Mining",
        {"mining": "warning", "logistics": "warning", "production": "blocked", "power": "warning"},
        {"mining": ["ore_detector_offline:fore"], "logistics": ["cargo_capacity_pressure"], "production": ["blocked_blueprint:Steel Plate"], "power": ["generator_offline:aux"]},
    ),
    (
        "transit_jump_power_comms_docking",
        "Transit",
        {"transit": "blocked", "power": "warning", "comms": "limited", "docking": "blocked"},
        {"transit": ["jump_drive_not_ready:Jump A"], "power": ["battery_low_charge:jump"], "comms": ["laser_link_missing:relay"], "docking": ["connector_locked:Port"]},
    ),
    (
        "maintenance_repair_material_projector",
        "Maintenance",
        {"maintenance": "blocked", "integrity": "degraded", "logistics": "warning", "production": "warning"},
        {"maintenance": ["material_shortage:Steel Plate:24", "projector_offline:Repair Plan"], "integrity": ["damaged_block:Gyro A"], "logistics": ["component_shortage:Steel Plate"], "production": ["assembler_blocked:Assembler A"]},
    ),
)


@pytest.mark.parametrize(("name", "mode", "states", "warnings"), SCENARIOS)
def test_orchestrator_scenario_matrix_feeds_prior_payloads_to_dashboard(
    tmp_path: Path,
    name: str,
    mode: str,
    states: dict[str, str],
    warnings: dict[str, list[str]],
) -> None:
    _write_sos_registry(tmp_path, mode)
    _write_previous_result(tmp_path, _scenario_child_results(mode, states, warnings))
    scripts = {
        script_id: script
        for script_id, script in load_manifest(Path(".")).items()
        if script_id.startswith("pb-bridge-001-") or script_id.startswith("sos_") or script_id in {"bridge_orchestrator"}
    }

    result = execute_request(_request(), scripts, {}, tmp_path)
    output = result["result"]
    dashboard_child = next(item for item in output["child_results"] if item["script_id"] == "pb-bridge-001-sos_dashboard")
    dashboard_payload = dashboard_child["result"]["sos_dashboard"]

    assert result["status"] == "ok", name
    assert output["orchestrator"]["child_count"] == len(_default_sos_ship()["services"])
    assert {item["script_id"] for item in output["child_results"]} >= {service["script_id"] for service in _mounted_sos_services()}
    assert {command["kind"] for command in output["commands"]} <= ALLOWED_SOS_COMMAND_KINDS
    assert output["orchestrator"]["command_count"] <= len(_default_sos_ship()["services"])
    compacted = compact_result_for_storage(result)
    assert len(json.dumps(compacted, separators=(",", ":"))) < 64000
    for service_id in DASHBOARD_TOKEN_SERVICES:
        assert f"{service_id}={states.get(service_id, 'ok')}" in dashboard_child["summary"]
        assert dashboard_payload[service_id]["state"] == states.get(service_id, "ok")
    for service_id, expected_warnings in warnings.items():
        for warning in expected_warnings:
            assert warning in dashboard_child["summary"] or warning in json.dumps(dashboard_payload[service_id])


def test_scenario_child_history_is_available_by_list_service_id_and_script_id(tmp_path: Path) -> None:
    services_payload = [{"script_id": f"pb-bridge-001-sos_{service_id}", "service_id": service_id} for service_id in ("status", "power", "dashboard")]
    child_results = _scenario_child_results("Cruise", {"power": "warning"}, {"power": ["battery_low_charge:reserve"]})
    _write_previous_result(tmp_path, child_results)

    telemetry = enriched_child_runtime_telemetry(tmp_path, {"bridge_id": "pb-bridge-001"}, tuple(services_payload))

    assert telemetry["child_services"][1]["result"]["sos_power"]["state"] == "warning"
    assert telemetry["child_services_by_service_id"]["power"]["result"]["sos_power"]["warnings"] == ["battery_low_charge:reserve"]
    assert telemetry["child_services_by_script_id"]["pb-bridge-001-sos_power"]["result"]["sos_power"]["state"] == "warning"
    assert telemetry["child_services_by_script_id"]["pb-bridge-001-sos_power"]["command_queue"] == {"queued": 1, "drained": 1, "remaining": 0}


def test_service_specific_snapshot_aliases_stay_isolated_between_sos_children(tmp_path: Path) -> None:
    captured: dict[str, set[str]] = {}
    service_ids = (
        "status",
        "dashboard",
        "readiness",
        "guidance",
        "runbook",
        "watch_log",
        "diagnostics",
        "config_drift",
        "endurance",
        "telemetry_quality",
        "automation",
        "automation_plan",
        "conveyor",
        "redundancy",
        "topology",
        "maintenance",
        "mining",
        "display",
    )
    services_payload = [{"script_id": f"bridge-a-sos_{service_id}", "service_id": service_id} for service_id in service_ids]
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-bridge-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Bridge A",
                        "expected_grid_entity_id": 0,
                        "mode": "Transit",
                        "services": services_payload,
                        "status_surfaces": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A SOS",
            "",
            "adapter_tick.v1",
            "compact_commands.v1",
            1000,
            True,
            base_script_id="bridge_orchestrator",
            instance_bridge_id="bridge-a",
        )
    }
    for service_id in service_ids:
        module_name = f"tests.sos_scenario_capture_{service_id}"
        module = types.ModuleType(module_name)

        def run(request: dict[str, Any], expected_service: str = service_id) -> dict[str, Any]:
            captured[expected_service] = set(request)
            return {"summary": expected_service, "commands": [{"kind": "echo", "text": expected_service}]}

        module.run = run
        sys.modules[module_name] = module
        scripts[f"bridge-a-sos_{service_id}"] = WorkerScript(
            f"bridge-a-sos_{service_id}",
            "manual",
            service_id,
            module_name,
            "adapter_tick.v1",
            "compact_commands.v1",
            1000,
            True,
        )

    request = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-a",
        "sequence": 10,
        "script_id": "bridge-a-orchestrator",
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 0, "blocks": []},
        "runtime_telemetry": {"limiter_state": "ok"},
        "state": {},
        "readiness_snapshot": {"sources": [{"service_id": "power", "state": "ok"}]},
        "guidance_snapshot": {"priorities": [{"service_id": "power", "reason": "battery_low"}]},
        "runbook_snapshot": {"procedure": "Transit Watch"},
        "watch_log_snapshot": {"events": [{"message": "jump prep"}]},
        "diagnostics_snapshot": {"checked_services": ["status"]},
        "config_drift_snapshot": {"expected_services": [{"service_id": "status"}]},
        "contract_snapshot": {"commands": [{"kind": "echo"}]},
        "endurance_snapshot": {"cargo": {"used_volume": 10, "max_volume": 100}},
        "telemetry_quality_snapshot": {"sources": [{"service_id": "status", "confidence": 0.99}]},
        "automation_snapshot": {"programmable_blocks": [{"name": "Main PB", "enabled": True}]},
        "automation_plan_snapshot": {"plans": [{"operation": "restart"}]},
        "conveyor_snapshot": {"conveyors": [{"name": "Cargo Line", "connected": True}]},
        "redundancy_snapshot": {"capabilities": {"transit_jump": {"primary_count": 1, "backup_count": 0}}},
        "topology_snapshot": {"dependencies": [{"source": "power", "target": "mobility", "state": "ok"}]},
        "maintenance_snapshot": {"projectors": [{"name": "Repair Plan"}]},
        "mining_snapshot": {"drills": [{"name": "Drill A"}]},
        "display_snapshot": {"available_surfaces": 1},
    }

    result = execute_request(request, scripts, {}, tmp_path)
    service_specific_aliases = {
        "readiness_snapshot",
        "guidance_snapshot",
        "runbook_snapshot",
        "watch_log_snapshot",
        "diagnostics_snapshot",
        "config_drift_snapshot",
        "contract_snapshot",
        "endurance_snapshot",
        "telemetry_quality_snapshot",
        "automation_snapshot",
        "automation_plan_snapshot",
        "conveyor_snapshot",
        "redundancy_snapshot",
        "topology_snapshot",
        "maintenance_snapshot",
        "mining_snapshot",
        "display_snapshot",
    }

    assert result["status"] == "ok"
    assert "readiness_snapshot" in captured["readiness"]
    assert "guidance_snapshot" in captured["guidance"]
    assert "runbook_snapshot" in captured["runbook"]
    assert "watch_log_snapshot" in captured["watch_log"]
    assert "diagnostics_snapshot" in captured["diagnostics"]
    assert "config_drift_snapshot" in captured["config_drift"]
    assert "contract_snapshot" in captured["config_drift"]
    assert "endurance_snapshot" in captured["endurance"]
    assert "telemetry_quality_snapshot" in captured["telemetry_quality"]
    assert "automation_snapshot" in captured["automation"]
    assert "automation_plan_snapshot" in captured["automation_plan"]
    assert "conveyor_snapshot" in captured["conveyor"]
    assert "redundancy_snapshot" in captured["redundancy"]
    assert "topology_snapshot" in captured["topology"]
    assert "maintenance_snapshot" in captured["maintenance"]
    assert "mining_snapshot" in captured["mining"]
    assert "display_snapshot" in captured["display"]
    assert "display_snapshot" in captured["redundancy"]
    assert captured["status"].isdisjoint(service_specific_aliases)
    assert captured["dashboard"].isdisjoint(service_specific_aliases)
    assert "endurance_snapshot" not in captured["redundancy"]
    assert "telemetry_quality_snapshot" not in captured["redundancy"]
    assert "redundancy_snapshot" not in captured["telemetry_quality"]
    assert "redundancy_snapshot" not in captured["endurance"]
    assert "topology_snapshot" not in captured["redundancy"]
    assert "redundancy_snapshot" not in captured["topology"]
    assert "config_drift_snapshot" not in captured["redundancy"]
    assert "redundancy_snapshot" not in captured["config_drift"]
    assert "automation_snapshot" not in captured["redundancy"]
    assert "automation_plan_snapshot" not in captured["redundancy"]
    assert "conveyor_snapshot" not in captured["redundancy"]
    assert "automation_snapshot" not in captured["automation_plan"]
    assert "automation_snapshot" not in captured["conveyor"]
    assert "redundancy_snapshot" not in captured["automation"]
    assert "mining_snapshot" in captured["endurance"]
    assert "mining_snapshot" not in captured["maintenance"]
    assert "maintenance_snapshot" not in captured["mining"]
