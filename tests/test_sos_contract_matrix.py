from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import sos
from sos import services

from worker.scripts.sos_dashboard import run as run_dashboard_adapter
from worker.worker import (
    BridgeScriptConfig,
    WorkerScript,
    child_service_telemetry,
    compact_result_for_storage,
    enriched_child_runtime_telemetry,
    execute_request,
    load_bridge_script_configs,
)


ADDON_SRC = Path(
    r"C:\Users\eLDARi\Documents\VScode\.venv\SOS-Starship-Operating-System\SOS-Starship-Operating-System\src\sos"
)
ALLOWED_SOS_COMMAND_KINDS = {"echo", "write_text_surface"}
DASHBOARD_COMPOSED_SERVICES = {
    "alerts",
    "airlock",
    "automation",
    "capabilities",
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
META_SERVICE_IDS = ("capabilities", "topology", "telemetry_quality", "config_drift")


def _read_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _manifest_sos_scripts() -> list[dict[str, Any]]:
    payload = _read_json("worker/manifest.json")
    return [script for script in payload["scripts"] if str(script["script_id"]).startswith("sos_")]


def _default_sos_ship() -> dict[str, Any]:
    payload = _read_json("data/sos_ships.json")
    return payload["ships"][0]


def _mounted_sos_services() -> list[dict[str, Any]]:
    return [service for service in _default_sos_ship()["services"] if "-sos_" in service["script_id"]]


def _default_instance_ids() -> set[str]:
    payload = _read_json("data/script_instances.json")
    return set(payload["instances"])


def _service_id_from_script_id(script_id: str) -> str:
    return script_id.removeprefix("sos_")


def _write_sos_registry(root: Path, bridge_id: str, services_payload: list[dict[str, Any]]) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": f"ship-{bridge_id}",
                        "bridge_id": bridge_id,
                        "display_name": "Matrix Ship",
                        "expected_grid_entity_id": 0,
                        "mode": "Docked",
                        "services": services_payload,
                        "status_surfaces": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _request(bridge_id: str, script_id: str) -> dict[str, Any]:
    return {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": bridge_id,
        "sequence": 1,
        "script_id": script_id,
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 0, "blocks": []},
        "runtime_telemetry": {},
        "state": {},
    }


def test_manifest_sos_scripts_have_thin_adapter_default_instance_and_sos_ship_mount() -> None:
    mounted_by_script_id = {service["script_id"]: service for service in _mounted_sos_services()}
    instance_ids = _default_instance_ids()

    for script in _manifest_sos_scripts():
        script_id = script["script_id"]
        service_id = _service_id_from_script_id(script_id)
        mounted_id = f"pb-bridge-001-{script_id}"

        assert script["module"] == f"worker.scripts.{script_id}"
        assert Path("worker", "scripts", f"{script_id}.py").exists()
        assert mounted_id in instance_ids
        assert mounted_by_script_id[mounted_id]["service_id"] == service_id


def test_recent_meta_services_have_manifest_instance_registry_and_orchestrator_parity() -> None:
    manifest_by_script_id = {script["script_id"]: script for script in _manifest_sos_scripts()}
    mounted_by_service_id = {service["service_id"]: service for service in _mounted_sos_services()}
    instance_ids = _default_instance_ids()
    config = load_bridge_script_configs(Path("."))["pb-bridge-001"]
    child_by_service_id = {child["service_id"]: child for child in config.child_worker_scripts}

    for service_id in META_SERVICE_IDS:
        base_script_id = f"sos_{service_id}"
        mounted_script_id = f"pb-bridge-001-{base_script_id}"

        assert manifest_by_script_id[base_script_id]["module"] == f"worker.scripts.{base_script_id}"
        assert mounted_script_id in instance_ids
        assert mounted_by_service_id[service_id]["script_id"] == mounted_script_id
        assert mounted_script_id in config.allowed_worker_scripts
        assert child_by_service_id[service_id]["script_id"] == mounted_script_id


def test_thin_adapters_delegate_to_editable_sos_service_run(monkeypatch) -> None:
    for script in _manifest_sos_scripts():
        script_id = script["script_id"]
        service_id = _service_id_from_script_id(script_id)
        adapter = importlib.import_module(f"worker.scripts.{script_id}")
        service_module = getattr(adapter, f"_{service_id}_service")
        sentinel = {"summary": f"{service_id} delegated", "commands": [{"kind": "echo", "text": service_id}]}

        def fake_run(request: dict[str, Any], expected_service: str = service_id) -> dict[str, Any]:
            assert request["service_under_test"] == expected_service
            return sentinel

        monkeypatch.setattr(service_module, "run", fake_run)

        assert adapter.run({"service_under_test": service_id}) is sentinel


def test_editable_sos_imports_resolve_to_nested_addon_source() -> None:
    assert Path(sos.__file__).resolve().is_relative_to(ADDON_SRC)
    for service_id in services.__all__:
        module = importlib.import_module(f"sos.services.{service_id}")
        assert Path(module.__file__).resolve().is_relative_to(ADDON_SRC / "services")


def test_orchestrator_expansion_includes_all_configured_sos_children() -> None:
    config = load_bridge_script_configs(Path("."))["pb-bridge-001"]
    mounted_script_ids = [service["script_id"] for service in _default_sos_ship()["services"]]

    assert config.selected_script_id == "pb-bridge-001-orchestrator"
    assert list(config.allowed_worker_scripts) == ["pb-bridge-001-orchestrator", *mounted_script_ids]
    assert [child["script_id"] for child in config.child_worker_scripts] == mounted_script_ids
    assert {child["service_id"] for child in config.child_worker_scripts} == {
        service["service_id"] for service in _default_sos_ship()["services"]
    }


def test_dashboard_no_history_summary_has_unknown_tokens_for_all_composed_services() -> None:
    result = run_dashboard_adapter(
        {
            "bridge_id": "pb-bridge-001",
            "sos_ship": {"ship_id": "ship-pb-bridge-001", "display_name": "Primary SOS Ship", "status_surfaces": []},
        }
    )

    for service_id in sorted(DASHBOARD_COMPOSED_SERVICES):
        assert f"{service_id}=unknown" in result["summary"]


def test_runtime_telemetry_history_reaches_list_service_and_script_indexes() -> None:
    child_configs = (
        {"script_id": "bridge-a-sos_status", "service_id": "status"},
        {"script_id": "bridge-a-sos_readiness", "service_id": "readiness"},
        {"script_id": "bridge-a-sos_power", "service_id": "power"},
    )
    previous_payload = {
        "queue_pressure": {
            "queued": 3,
            "drained": 1,
            "remaining": 2,
            "by_source": {"bridge-a-sos_power": {"queued": 2, "drained": 1, "remaining": 1}},
        },
        "child_results": [
            {
                "script_id": "bridge-a-sos_status",
                "status": "ok",
                "error_bucket": "none",
                "summary": "status ok",
                "result": {"sos_status": {"mode": "Combat", "identity_status": "ok"}},
            },
            {
                "script_id": "bridge-a-sos_readiness",
                "status": "ok",
                "error_bucket": "none",
                "summary": "readiness ready",
                "result": {"sos_readiness": {"state": "ready", "summary": "ready sources=1 blockers=0 warnings=0"}},
            },
            {
                "script_id": "bridge-a-sos_power",
                "status": "ok",
                "error_bucket": "none",
                "summary": "power warning",
                "result": {"sos_power": {"state": "warning", "snapshot_status": "ok"}},
            },
        ],
    }

    telemetry_list = child_service_telemetry(child_configs, previous_payload, previous_payload["queue_pressure"])
    by_service = {item["service_id"]: item for item in telemetry_list}
    by_script = {item["script_id"]: item for item in telemetry_list}

    assert by_service["status"]["result"]["sos_status"]["mode"] == "Combat"
    assert by_service["readiness"]["result"]["sos_readiness"]["state"] == "ready"
    assert by_script["bridge-a-sos_power"]["result"]["sos_power"]["state"] == "warning"
    assert by_script["bridge-a-sos_power"]["command_queue"] == {"queued": 2, "drained": 1, "remaining": 1}


def test_previous_meta_service_payloads_flow_to_runtime_telemetry_by_service_id(tmp_path: Path) -> None:
    child_configs = tuple(
        {"script_id": f"bridge-a-sos_{service_id}", "service_id": service_id}
        for service_id in META_SERVICE_IDS
    )
    previous_payload = {
        "child_results": [
            {
                "script_id": f"bridge-a-sos_{service_id}",
                "status": "ok",
                "error_bucket": "none",
                "summary": f"{service_id} summary",
                "result": {f"sos_{service_id}": {"state": "ok", "snapshot_status": "ok"}},
            }
            for service_id in META_SERVICE_IDS
        ],
        "queue_pressure": {
            "queued": 4,
            "drained": 4,
            "remaining": 0,
            "by_source": {
                f"bridge-a-sos_{service_id}": {"queued": 1, "drained": 1, "remaining": 0}
                for service_id in META_SERVICE_IDS
            },
        },
    }
    result_dir = tmp_path / "data" / "bridge_results"
    result_dir.mkdir(parents=True)
    (result_dir / "bridge-a.json").write_text(json.dumps({"result": previous_payload}), encoding="utf-8")

    telemetry = enriched_child_runtime_telemetry(
        tmp_path,
        {"bridge_id": "bridge-a", "runtime_telemetry": {"limiter_state": "ok"}},
        child_configs,
    )

    for service_id in META_SERVICE_IDS:
        child = telemetry["child_services_by_service_id"][service_id]
        assert child["summary"] == f"{service_id} summary"
        assert child["result"][f"sos_{service_id}"]["state"] == "ok"
        assert child["command_queue"] == {"queued": 1, "drained": 1, "remaining": 0}


def test_enriched_runtime_telemetry_exposes_child_history_in_all_supported_shapes(tmp_path: Path) -> None:
    result_dir = tmp_path / "data" / "bridge_results"
    result_dir.mkdir(parents=True)
    (result_dir / "bridge-a.json").write_text(
        json.dumps(
            {
                "result": {
                    "child_results": [
                        {
                            "script_id": "bridge-a-sos_status",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "status ok",
                            "result": {"sos_status": {"mode": "Combat"}},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    telemetry = enriched_child_runtime_telemetry(
        tmp_path,
        {"bridge_id": "bridge-a", "runtime_telemetry": {"limiter_state": "ok"}},
        ({"script_id": "bridge-a-sos_status", "service_id": "status"},),
    )

    assert telemetry["child_services"][0]["result"]["sos_status"]["mode"] == "Combat"
    assert telemetry["child_services_by_service_id"]["status"]["result"]["sos_status"]["mode"] == "Combat"
    assert telemetry["child_services_by_script_id"]["bridge-a-sos_status"]["result"]["sos_status"]["mode"] == "Combat"


def test_shared_contract_snapshot_reaches_diagnostics_and_config_drift_children(tmp_path: Path) -> None:
    captured: dict[str, set[str]] = {}
    services_payload = [
        {"script_id": "bridge-a-sos_diagnostics", "service_id": "diagnostics"},
        {"script_id": "bridge-a-sos_config_drift", "service_id": "config_drift"},
    ]
    _write_sos_registry(tmp_path, "bridge-a", services_payload)

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
    for service_id in ("diagnostics", "config_drift"):
        module_name = f"tests.contract_snapshot_capture_{service_id}"
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

    result = execute_request(
        _request("bridge-a", "bridge-a-orchestrator") | {
            "contract_snapshot": {
                "dashboard_tokens": ["diagnostics", "config_drift"],
                "commands": [{"kind": "echo"}],
            }
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert "contract_snapshot" in captured["diagnostics"]
    assert "contract_snapshot" in captured["config_drift"]


def test_service_specific_snapshot_aliases_do_not_leak_to_sibling_children(tmp_path: Path) -> None:
    captured: dict[str, set[str]] = {}
    service_ids = (
        "capabilities",
        "telemetry_quality",
        "automation",
        "conveyor",
        "redundancy",
        "topology",
        "endurance",
        "watch_log",
        "runbook",
        "readiness",
        "diagnostics",
        "config_drift",
        "maintenance",
        "status",
    )
    service_specific_aliases = {
        "capability_snapshot",
        "capabilities_snapshot",
        "ship_capabilities_snapshot",
        "role_snapshot",
        "telemetry_quality_snapshot",
        "evidence_snapshot",
        "data_quality_snapshot",
        "signal_quality_snapshot",
        "automation_snapshot",
        "control_logic_snapshot",
        "script_health_snapshot",
        "pb_snapshot",
        "programmable_block_snapshot",
        "conveyor_snapshot",
        "conveyor_network_snapshot",
        "inventory_network_snapshot",
        "resource_routing_snapshot",
        "redundancy_snapshot",
        "topology_snapshot",
        "dependency_snapshot",
        "dependency_map_snapshot",
        "blast_radius_snapshot",
        "endurance_snapshot",
        "watch_log_snapshot",
        "runbook_snapshot",
        "readiness_snapshot",
        "diagnostics_snapshot",
        "config_drift_snapshot",
        "configuration_snapshot",
        "contract_snapshot",
        "registry_snapshot",
        "ship_registry_snapshot",
        "template_snapshot",
        "host_manifest_snapshot",
        "script_instances_snapshot",
        "maintenance_snapshot",
    }
    services_payload = [{"script_id": f"bridge-a-sos_{service_id}", "service_id": service_id} for service_id in service_ids]
    _write_sos_registry(tmp_path, "bridge-a", services_payload)

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
        module_name = f"tests.matrix_capture_{service_id}"
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

    request = _request("bridge-a", "bridge-a-orchestrator") | {
        "capability_snapshot": {"capabilities": {"mining": {"state": "present"}}},
        "capabilities_snapshot": {"capabilities": {"power": {"state": "present"}}},
        "ship_capabilities_snapshot": {"capabilities": {"display": {"state": "present"}}},
        "role_snapshot": {"declared_role": "miner"},
        "telemetry_quality_snapshot": {"sources": [{"service_id": "status", "confidence": 0.99}]},
        "evidence_snapshot": {"evidence": [{"source": "grid_snapshot", "fresh": True}]},
        "data_quality_snapshot": {"services": {"status": {"state": "ok"}}},
        "signal_quality_snapshot": {"signals": [{"name": "grid_snapshot", "quality": "high"}]},
        "automation_snapshot": {"programmable_blocks": [{"name": "Main PB", "enabled": True}]},
        "control_logic_snapshot": {"timers": [{"name": "Timer A", "enabled": True}]},
        "script_health_snapshot": {"scripts": [{"name": "Main PB", "healthy": True}]},
        "pb_snapshot": {"blocks": [{"name": "Main PB", "enabled": True}]},
        "programmable_block_snapshot": {"programmable_blocks": [{"name": "Backup PB", "enabled": False}]},
        "conveyor_snapshot": {"conveyors": [{"name": "Cargo Line", "connected": True}]},
        "conveyor_network_snapshot": {"networks": [{"name": "Cargo Network", "connected": True}]},
        "inventory_network_snapshot": {"ports": [{"name": "Cargo Port", "connected": True}]},
        "resource_routing_snapshot": {"dependencies": {"logistics": {"state": "ok"}}},
        "redundancy_snapshot": {"capabilities": {"power": {"primary_count": 1, "backup_count": 1}}},
        "topology_snapshot": {"dependencies": [{"source": "power", "target": "mobility", "state": "ok"}]},
        "dependency_snapshot": {"chains": [{"source": "power", "target": "mobility", "state": "ok"}]},
        "dependency_map_snapshot": {"dependencies": [{"source_service": "power", "target_service": "mobility", "state": "ok"}]},
        "blast_radius_snapshot": {"affected_families": ["mobility"], "state": "ok"},
        "endurance_snapshot": {"cargo": {"used_volume": 10, "max_volume": 100}},
        "watch_log_snapshot": {"events": [{"message": "watch"}]},
        "runbook_snapshot": {"procedure": "Cruise Watch"},
        "readiness_snapshot": {"sources": [{"service_id": "power", "state": "ok"}]},
        "diagnostics_snapshot": {"checked_services": ["status"]},
        "config_drift_snapshot": {"expected_services": [{"service_id": "status", "script_id": "bridge-a-sos_status"}]},
        "configuration_snapshot": {"services": [{"service_id": "status", "script_id": "bridge-a-sos_status"}]},
        "contract_snapshot": {"commands": [{"kind": "echo"}]},
        "registry_snapshot": {"services": [{"service_id": "status", "script_id": "bridge-a-sos_status"}]},
        "ship_registry_snapshot": {"ships": [{"ship_id": "ship-a", "services": [{"service_id": "status"}]}]},
        "template_snapshot": {"services": [{"service_id": "status"}]},
        "host_manifest_snapshot": {"scripts": [{"script_id": "sos_status"}]},
        "script_instances_snapshot": {"instances": {"bridge-a-sos_status": {"base_script_id": "sos_status"}}},
        "maintenance_snapshot": {"projectors": [{"name": "Projector"}]},
    }
    result = execute_request(request, scripts, {}, tmp_path)

    assert result["status"] == "ok"
    assert "capability_snapshot" in captured["capabilities"]
    assert "capabilities_snapshot" in captured["capabilities"]
    assert "ship_capabilities_snapshot" in captured["capabilities"]
    assert "role_snapshot" in captured["capabilities"]
    assert "telemetry_quality_snapshot" in captured["telemetry_quality"]
    assert "evidence_snapshot" in captured["telemetry_quality"]
    assert "data_quality_snapshot" in captured["telemetry_quality"]
    assert "signal_quality_snapshot" in captured["telemetry_quality"]
    assert "automation_snapshot" in captured["automation"]
    assert "control_logic_snapshot" in captured["automation"]
    assert "script_health_snapshot" in captured["automation"]
    assert "pb_snapshot" in captured["automation"]
    assert "programmable_block_snapshot" in captured["automation"]
    assert "conveyor_snapshot" in captured["conveyor"]
    assert "conveyor_network_snapshot" in captured["conveyor"]
    assert "inventory_network_snapshot" in captured["conveyor"]
    assert "resource_routing_snapshot" in captured["conveyor"]
    assert "redundancy_snapshot" in captured["redundancy"]
    assert "topology_snapshot" in captured["topology"]
    assert "dependency_snapshot" in captured["topology"]
    assert "dependency_map_snapshot" in captured["topology"]
    assert "blast_radius_snapshot" in captured["topology"]
    assert "endurance_snapshot" in captured["endurance"]
    assert "watch_log_snapshot" in captured["watch_log"]
    assert "runbook_snapshot" in captured["runbook"]
    assert "readiness_snapshot" in captured["readiness"]
    assert "diagnostics_snapshot" in captured["diagnostics"]
    assert "config_drift_snapshot" in captured["config_drift"]
    assert "configuration_snapshot" in captured["config_drift"]
    assert "contract_snapshot" in captured["config_drift"]
    assert "registry_snapshot" in captured["config_drift"]
    assert "ship_registry_snapshot" in captured["config_drift"]
    assert "template_snapshot" in captured["config_drift"]
    assert "host_manifest_snapshot" in captured["config_drift"]
    assert "script_instances_snapshot" in captured["config_drift"]
    assert "maintenance_snapshot" in captured["maintenance"]
    assert captured["status"].isdisjoint(service_specific_aliases)
    assert "capability_snapshot" not in captured["redundancy"]
    assert "role_snapshot" not in captured["redundancy"]
    assert "telemetry_quality_snapshot" not in captured["redundancy"]
    assert "evidence_snapshot" not in captured["redundancy"]
    assert "data_quality_snapshot" not in captured["redundancy"]
    assert "signal_quality_snapshot" not in captured["redundancy"]
    assert "topology_snapshot" not in captured["redundancy"]
    assert "dependency_snapshot" not in captured["redundancy"]
    assert "dependency_map_snapshot" not in captured["redundancy"]
    assert "blast_radius_snapshot" not in captured["redundancy"]
    assert "endurance_snapshot" not in captured["redundancy"]
    assert "capability_snapshot" not in captured["telemetry_quality"]
    assert "redundancy_snapshot" not in captured["telemetry_quality"]
    assert "automation_snapshot" not in captured["telemetry_quality"]
    assert "conveyor_snapshot" not in captured["telemetry_quality"]
    assert "telemetry_quality_snapshot" not in captured["automation"]
    assert "conveyor_snapshot" not in captured["automation"]
    assert "redundancy_snapshot" not in captured["automation"]
    assert "automation_snapshot" not in captured["conveyor"]
    assert "redundancy_snapshot" not in captured["conveyor"]
    assert "redundancy_snapshot" not in captured["topology"]
    assert "capability_snapshot" not in captured["topology"]
    assert "redundancy_snapshot" not in captured["endurance"]
    assert "config_drift_snapshot" not in captured["redundancy"]
    assert "registry_snapshot" not in captured["redundancy"]
    assert "topology_snapshot" not in captured["config_drift"]
    assert "watch_log_snapshot" not in captured["endurance"]
    assert "runbook_snapshot" not in captured["watch_log"]
    assert "watch_log_snapshot" not in captured["runbook"]
    assert "maintenance_snapshot" not in captured["diagnostics"]


def test_configured_sos_orchestrator_no_history_tick_stays_within_command_allowlist_and_size_boundary(tmp_path: Path) -> None:
    _write_sos_registry(tmp_path, "pb-bridge-001", _default_sos_ship()["services"])
    scripts = {
        script_id: script
        for script_id, script in __import__("worker.worker", fromlist=["load_manifest"]).load_manifest(Path(".")).items()
        if script_id.startswith("pb-bridge-001-") or script_id.startswith("sos_") or script_id in {"bridge_orchestrator"}
    }
    result = execute_request(
        _request("pb-bridge-001", "pb-bridge-001-orchestrator"),
        scripts,
        {},
        tmp_path,
    )
    commands = result["result"]["commands"]

    assert result["status"] == "ok"
    assert result["result"]["orchestrator"]["child_count"] == len(_default_sos_ship()["services"])
    assert {command["kind"] for command in commands} <= ALLOWED_SOS_COMMAND_KINDS
    assert len(json.dumps(compact_result_for_storage(result), separators=(",", ":"))) < 64000


def test_expanded_meta_service_child_history_compaction_stays_under_storage_guardrail() -> None:
    dashboard_payload = {
        service_id: {
            "state": "warning",
            "snapshot_status": "ok",
            "summary": "warning " + ("expanded meta service summary " * 80),
            "warnings": [f"{service_id}:warning:{index}:" + ("detail " * 40) for index in range(40)],
            "source_services": [f"source-{index}" for index in range(40)],
        }
        for service_id in DASHBOARD_COMPOSED_SERVICES
    }
    dashboard_payload["mode"] = "Combat"
    dashboard_payload["posture"] = "threat-ready"
    raw_result = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "result",
        "bridge_id": "bridge-a",
        "sequence": 1,
        "script_id": "bridge-a-orchestrator",
        "status": "ok",
        "result": {
            "summary": "bridge_orchestrator processed expanded child surface",
            "commands": [
                {"kind": "write_text_surface", "text": "expanded command text " * 40, "block_entity_id": index}
                for index in range(40)
            ],
            "child_results": [
                {
                    "script_id": f"bridge-a-sos_{service_id}",
                    "status": "ok",
                    "summary": "child summary " * 80,
                    "result": {f"sos_{service_id}": {"state": "ok", "warnings": ["warning " * 80 for _ in range(40)]}},
                }
                for service_id in DASHBOARD_COMPOSED_SERVICES
            ],
            "sos_dashboard": dashboard_payload,
        },
    }

    compacted = compact_result_for_storage(raw_result)

    assert compacted["result"]["storage_compacted"] is True
    assert len(json.dumps(compacted, separators=(",", ":"))) < 64000
