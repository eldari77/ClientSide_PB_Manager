import json
import os
import sys
import time
import types
from pathlib import Path

from worker.worker import (
    BridgeScriptConfig,
    WorkerScript,
    apply_command_queue,
    command_priority,
    command_queue_drain_count,
    command_queue_key,
    cleanup_processed_requests,
    execute_request,
    learn_autocrafting_blueprints,
    load_effective_worker_config,
    load_bridge_health,
    latest_request_path,
    load_manifest,
    render_status_page,
    process_pending,
    update_bridge_health,
)


def test_execute_sos_orchestrator_attaches_ship_context_and_status_child(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "expected_grid_entity_id": 99,
                        "mode": "Emergency",
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                        ],
                        "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
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
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status",
            "script_instance",
            "Bridge A SOS Status",
            "worker.scripts.sos_status",
            "",
            "",
            1000,
            True,
            base_script_id="sos_status",
            instance_bridge_id="bridge-a",
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 99, "blocks": []},
            "runtime_telemetry": {"limiter_state": "ok"},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    output = result["result"]
    assert output["sos"]["ship_id"] == "ship-a"
    assert output["sos"]["mode"] == "Emergency"
    assert output["child_results"][0]["script_id"] == "bridge-a-sos_status"
    assert output["commands"][0]["kind"] == "write_text_surface"
    assert "Limiter: ok" in output["commands"][0]["text"]
    assert output["commands"][0]["source_script_id"] == "bridge-a-sos_status"


def test_execute_sos_orchestrator_rejects_duplicate_ship_bridge_claims(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {"ship_id": "ship-a", "bridge_id": "bridge-a", "expected_grid_entity_id": 1, "services": []},
                    {"ship_id": "ship-b", "bridge_id": "bridge-a", "expected_grid_entity_id": 2, "services": []},
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
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        )
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "rejected"
    assert result["error_bucket"] == "sos_registry_invalid"


def test_execute_sos_orchestrator_grid_identity_mismatch_fails_closed(tmp_path: Path):
    module = types.ModuleType("tests.sos_identity_child")

    def run(request):
        return {
            "summary": "should not run",
            "commands": [{"kind": "set_door_open", "block_entity_id": 777, "open": True}],
        }

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "expected_grid_entity_id": 99,
                        "services": [{"script_id": "bridge-a-door", "service_id": "doors"}],
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
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-door": WorkerScript("bridge-a-door", "manual", "Door Child", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 100, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "rejected"
    assert result["error_bucket"] == "sos_identity_blocked"
    assert result["result"]["sos"]["identity_status"] == "grid_mismatch"
    assert result["result"]["sos"]["blockers"] == ["expected_grid_entity_id_mismatch"]
    assert result["result"]["commands"] == [
        {"kind": "echo", "text": "SOS bridge-a rejected: expected_grid_entity_id_mismatch"}
    ]
    assert result["result"]["child_results"] == []
    assert not (tmp_path / "data" / "command_queues" / "bridge-a.json").exists()


def test_execute_sos_multiple_ships_keep_child_results_and_queues_per_bridge(tmp_path: Path):
    def install_adapter(module_name: str, block_id: int) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": f"planned {request['bridge_id']}",
                "commands": [{"kind": "write_text_surface", "block_entity_id": block_id, "surface_index": 0, "text": request["bridge_id"]}],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_bridge_a_status", 101)
    install_adapter("tests.sos_bridge_b_status", 202)
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [{"script_id": "bridge-a-status", "service_id": "status"}],
                    },
                    {
                        "ship_id": "ship-b",
                        "bridge_id": "bridge-b",
                        "expected_grid_entity_id": 20,
                        "services": [{"script_id": "bridge-b-status", "service_id": "status"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-b-orchestrator": WorkerScript(
            "bridge-b-orchestrator", "script_instance", "Bridge B SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-status": WorkerScript("bridge-a-status", "manual", "A Status", "tests.sos_bridge_a_status", "", "", 1000, True),
        "bridge-b-status": WorkerScript("bridge-b-status", "manual", "B Status", "tests.sos_bridge_b_status", "", "", 1000, True),
    }

    result_a = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )
    result_b = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-b",
            "sequence": 1,
            "script_id": "bridge-b-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 20, "blocks": []},
            "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result_a["status"] == "ok"
    assert result_b["status"] == "ok"
    assert [child["script_id"] for child in result_a["result"]["child_results"]] == ["bridge-a-status"]
    assert [child["script_id"] for child in result_b["result"]["child_results"]] == ["bridge-b-status"]
    assert result_a["result"]["commands"][0]["block_entity_id"] == 101
    assert result_b["result"]["commands"][0]["block_entity_id"] == 202
    queue_a = json.loads((tmp_path / "data" / "command_queues" / "bridge-a.json").read_text(encoding="utf-8"))
    queue_b = json.loads((tmp_path / "data" / "command_queues" / "bridge-b.json").read_text(encoding="utf-8"))
    assert queue_a["bridge_id"] == "bridge-a"
    assert queue_b["bridge_id"] == "bridge-b"
    assert queue_a["script_id"] == "bridge-a-orchestrator"
    assert queue_b["script_id"] == "bridge-b-orchestrator"


def test_execute_sos_orchestrator_passes_enriched_runtime_telemetry_to_child_requests(tmp_path: Path):
    captured: list[dict] = []
    module = types.ModuleType("tests.sos_telemetry_status_child")

    def run(request):
        captured.append(request)
        return {
            "summary": "status child saw telemetry",
            "commands": [{"kind": "write_text_surface", "block_entity_id": 101, "surface_index": 0, "text": "tick"}],
        }

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [{"script_id": "bridge-a-sos_status", "service_id": "status"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "runtime_telemetry": {"limiter_state": "ok", "last_runtime_ms": 0.2},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    telemetry = captured[0]["runtime_telemetry"]
    assert telemetry["limiter_state"] == "ok"
    assert telemetry["last_runtime_ms"] == 0.2
    assert telemetry["queue_pressure"] == {"queued": 0, "drained": 0, "remaining": 0, "by_source": {}}
    assert telemetry["child_services"] == [
        {
            "service_id": "status",
            "script_id": "bridge-a-sos_status",
            "status": "unknown",
            "error_bucket": "none",
            "summary": "",
            "command_queue": {"queued": 0, "drained": 0, "remaining": 0},
        }
    ]
    assert telemetry["child_services_by_script_id"]["bridge-a-sos_status"]["service_id"] == "status"
    assert telemetry["child_services_by_service_id"]["status"]["script_id"] == "bridge-a-sos_status"


def test_execute_sos_orchestrator_passes_previous_child_result_on_next_tick(tmp_path: Path):
    captured: list[dict] = []

    def install_adapter(module_name: str, status: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            captured.append({"script_id": request["script_id"], "runtime_telemetry": request["runtime_telemetry"]})
            return {
                "summary": summary,
                "commands": [command],
                "error_bucket": "child_warning" if status == "ok" else "child_rejected",
                "status_override": status,
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter(
        "tests.sos_previous_status_child",
        "ok",
        "previous status summary",
        {"kind": "write_text_surface", "block_entity_id": 101, "surface_index": 0, "text": "status"},
    )
    install_adapter(
        "tests.sos_previous_inventory_child",
        "rejected",
        "previous inventory rejected",
        {"kind": "set_block_enabled", "block_entity_id": 202, "enabled": True},
    )
    data = tmp_path / "data"
    data.mkdir()
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
                            "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_previous_status_child", "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_previous_inventory_child", "", "", 1000, True),
    }
    request = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-a",
        "sequence": 1,
        "script_id": "bridge-a-orchestrator",
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
        "state": {},
    }
    first = execute_request(request, scripts, {}, tmp_path)
    results_dir = tmp_path / "data" / "bridge_results"
    results_dir.mkdir()
    (results_dir / "bridge-a.json").write_text(json.dumps(first), encoding="utf-8")
    captured.clear()

    second = execute_request({**request, "sequence": 2}, scripts, {}, tmp_path)

    assert second["status"] == "ok"
    telemetry = captured[0]["runtime_telemetry"]
    assert telemetry["queue_pressure"] == {
        "queued": 1,
        "drained": 1,
        "remaining": 0,
        "by_source": {"bridge-a-sos_status": {"queued": 1, "drained": 1, "remaining": 0}},
    }
    assert telemetry["child_services_by_script_id"]["bridge-a-sos_status"] == {
        "service_id": "status",
        "script_id": "bridge-a-sos_status",
        "status": "ok",
        "error_bucket": "child_warning",
        "summary": "previous status summary",
        "command_queue": {"queued": 1, "drained": 1, "remaining": 0},
    }
    assert telemetry["child_services_by_service_id"]["inventory"] == {
        "service_id": "inventory",
        "script_id": "bridge-a-inventory",
        "status": "rejected",
        "error_bucket": "child_rejected",
        "summary": "previous inventory rejected",
        "command_queue": {"queued": 0, "drained": 0, "remaining": 0},
    }


def test_execute_sos_orchestrator_runs_integrity_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_integrity", "service_id": "integrity"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_integrity": WorkerScript(
            "bridge-a-sos_integrity",
            "manual",
            "Integrity",
            "worker.scripts.sos_integrity",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_integrity",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    integrity_child = result["result"]["child_results"][1]
    assert integrity_child["summary"] == "SOS Integrity Ship A state=unknown snapshot=no_snapshot"
    assert integrity_child["error_bucket"] == "none"
    assert result["result"]["commands"][1]["kind"] == "echo"


def test_execute_sos_orchestrator_runs_logistics_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_logistics_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_logistics_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_logistics_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_integrity", "service_id": "integrity"},
                            {"script_id": "bridge-a-sos_logistics", "service_id": "logistics"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_logistics_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_integrity": WorkerScript(
            "bridge-a-sos_integrity",
            "manual",
            "Integrity",
            "worker.scripts.sos_integrity",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-sos_logistics": WorkerScript(
            "bridge-a-sos_logistics",
            "manual",
            "Logistics",
            "worker.scripts.sos_logistics",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_logistics_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_logistics_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_integrity",
        "bridge-a-sos_logistics",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    logistics_child = result["result"]["child_results"][2]
    assert logistics_child["summary"] == "SOS Logistics Ship A state=unknown snapshot=no_snapshot"
    assert logistics_child["error_bucket"] == "none"
    assert result["result"]["commands"][2]["kind"] == "echo"


def test_execute_sos_orchestrator_runs_dashboard_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_dashboard_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_dashboard_registry_integrity_child", "integrity ok", {"kind": "echo", "text": "integrity"})
    install_adapter("tests.sos_dashboard_registry_logistics_child", "logistics ok", {"kind": "echo", "text": "logistics"})
    install_adapter("tests.sos_dashboard_registry_maintenance_child", "maintenance ok", {"kind": "echo", "text": "maintenance"})
    install_adapter("tests.sos_dashboard_registry_navigation_child", "navigation ok", {"kind": "echo", "text": "navigation"})
    install_adapter("tests.sos_dashboard_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_dashboard_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_dashboard", "service_id": "dashboard"},
                            {"script_id": "bridge-a-sos_integrity", "service_id": "integrity"},
                            {"script_id": "bridge-a-sos_logistics", "service_id": "logistics"},
                            {"script_id": "bridge-a-sos_maintenance", "service_id": "maintenance"},
                            {"script_id": "bridge-a-sos_navigation", "service_id": "navigation"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_dashboard_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_dashboard": WorkerScript(
            "bridge-a-sos_dashboard",
            "manual",
            "Dashboard",
            "worker.scripts.sos_dashboard",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-sos_integrity": WorkerScript(
            "bridge-a-sos_integrity",
            "manual",
            "Integrity",
            "tests.sos_dashboard_registry_integrity_child",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-sos_logistics": WorkerScript(
            "bridge-a-sos_logistics",
            "manual",
            "Logistics",
            "tests.sos_dashboard_registry_logistics_child",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-sos_maintenance": WorkerScript(
            "bridge-a-sos_maintenance",
            "manual",
            "Maintenance",
            "tests.sos_dashboard_registry_maintenance_child",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-sos_navigation": WorkerScript(
            "bridge-a-sos_navigation",
            "manual",
            "Navigation",
            "tests.sos_dashboard_registry_navigation_child",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_dashboard_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_dashboard_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_dashboard",
        "bridge-a-sos_integrity",
        "bridge-a-sos_logistics",
        "bridge-a-sos_maintenance",
        "bridge-a-sos_navigation",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    dashboard_child = result["result"]["child_results"][1]
    assert dashboard_child["summary"] == (
        "SOS Dashboard Ship A mode=Docked integrity=unknown logistics=unknown maintenance=unknown airlock=unknown mobility=unknown navigation=unknown power=unknown comms=unknown crew=unknown docking=unknown life_support=unknown environment=unknown production=unknown transit=unknown defense=unknown queue=0 blockers=none"
    )
    assert dashboard_child["error_bucket"] == "none"
    assert result["result"]["commands"][1]["kind"] == "echo"


def test_execute_sos_orchestrator_passes_child_payload_history_to_dashboard_request(tmp_path: Path):
    captured: list[dict] = []
    module = types.ModuleType("tests.sos_dashboard_capture_child")

    def run(request):
        captured.append(request)
        return {"summary": "dashboard captured", "commands": [{"kind": "echo", "text": "dashboard"}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "bridge_results").mkdir()
    (data / "bridge_results" / "bridge-a.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "result",
                "bridge_id": "bridge-a",
                "sequence": 7,
                "script_id": "bridge-a-orchestrator",
                "status": "ok",
                "result": {
                    "queue_pressure": {
                        "queued": 3,
                        "drained": 1,
                        "remaining": 2,
                        "by_source": {"bridge-a-sos_dashboard": {"queued": 1, "drained": 0, "remaining": 1}},
                    },
                    "child_results": [
                        {
                            "script_id": "bridge-a-sos_status",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "status ok",
                            "result": {
                                "sos_status": {
                                    "mode": "Combat",
                                    "identity_status": "ok",
                                    "blockers": [],
                                    "warnings": ["inventory_delayed"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_integrity",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "integrity degraded",
                            "result": {
                                "sos_integrity": {
                                    "state": "degraded",
                                    "snapshot_status": "ok",
                                    "damaged_block_count": 2,
                                    "critical_damaged_count": 1,
                                    "warnings": ["integrity_degraded"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_logistics",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "logistics warning",
                            "result": {
                                "sos_logistics": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "cargo": {"state": "pressure", "usage_ratio": 0.9},
                                    "ammo": {"state": "ok"},
                                    "fuel": {"state": "ok"},
                                    "production": {"state": "ok", "queue_count": 1},
                                    "warnings": ["cargo_capacity_pressure"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_maintenance",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "maintenance warning",
                            "result": {
                                "sos_maintenance": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "damaged_block_count": 3,
                                    "critical_damage_count": 1,
                                    "missing_critical_count": 1,
                                    "projector_count": 1,
                                    "active_projector_count": 1,
                                    "welder_count": 2,
                                    "damaged_or_offline_welder_count": 1,
                                    "grinder_count": 1,
                                    "damaged_or_offline_grinder_count": 0,
                                    "material_shortage_count": 2,
                                    "projectors": {
                                        "total_count": 1,
                                        "active_count": 1,
                                        "missing_block_count": 4,
                                    },
                                    "welders": {"total_count": 2, "ready_count": 1, "damaged_or_offline_count": 1},
                                    "grinders": {"total_count": 1, "ready_count": 1, "damaged_or_offline_count": 0},
                                    "materials": {
                                        "state": "shortage",
                                        "shortage_count": 2,
                                        "hints": ["missing_material:SteelPlate"],
                                    },
                                    "blockers": ["critical_block_damaged:Reactor"],
                                    "warnings": ["projector_missing_blocks:4"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_airlock",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "airlock warning",
                            "result": {
                                "sos_airlock": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "doors": {
                                        "open_count": 1,
                                        "exterior_open_count": 1,
                                        "damaged_or_offline_count": 0,
                                    },
                                    "airlocks": {"unsafe_count": 1},
                                    "compartments": {"low_oxygen_count": 0, "depressurized_count": 1},
                                    "vents": {"damaged_or_offline_count": 0},
                                    "warnings": ["airlock_unsafe:Port Lock"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_mobility",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "mobility warning",
                            "result": {
                                "sos_mobility": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "thrusters": {"damaged_or_offline_count": 1, "total_count": 4},
                                    "gyros": {"damaged_or_offline_count": 0, "total_count": 2},
                                    "control_blocks": {"damaged_or_offline_count": 0, "total_count": 1},
                                    "jump_drives": {
                                        "damaged_or_offline_count": 0,
                                        "not_ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "power_fuel": {"blocker_count": 1, "blockers": ["battery_power_low:Main Battery"]},
                                    "warnings": ["thruster_damaged_or_offline:Port Thruster"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_navigation",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "navigation warning",
                            "result": {
                                "sos_navigation": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "motion": {"speed_mps": 14.2, "motion_state": "coasting", "stopped": False},
                                    "control": {
                                        "dampeners": "enabled",
                                        "autopilot": "disabled",
                                        "remote_control": "ready",
                                    },
                                    "route": {
                                        "present": True,
                                        "waypoint_count": 2,
                                        "active_waypoint": "Rendezvous",
                                    },
                                    "proximity": {
                                        "hazard_count": 1,
                                        "nearest_hazard_m": 450.0,
                                        "hints": ["hazard:asteroid:450m"],
                                    },
                                    "dependencies": {
                                        "mobility_state": "warning",
                                        "transit_state": "ok",
                                        "environment_state": "warning",
                                    },
                                    "blockers": [],
                                    "warnings": ["hazard:asteroid:450m"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_power",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "power warning",
                            "result": {
                                "sos_power": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "batteries": {
                                        "damaged_or_offline_count": 1,
                                        "low_charge_count": 1,
                                        "total_count": 3,
                                    },
                                    "reactors": {
                                        "damaged_or_offline_count": 0,
                                        "fuel_shortage_count": 1,
                                        "total_count": 1,
                                    },
                                    "generators": {"damaged_or_offline_count": 0, "total_count": 2},
                                    "blocker_count": 3,
                                    "warnings": ["battery_low_charge:Main Battery"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_comms",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "comms warning",
                            "result": {
                                "sos_comms": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "antennas": {
                                        "damaged_or_offline_count": 1,
                                        "disabled_count": 0,
                                        "low_or_no_range_count": 1,
                                        "total_count": 2,
                                    },
                                    "laser_antennas": {
                                        "damaged_or_offline_count": 0,
                                        "disconnected_or_unlinked_count": 1,
                                        "total_count": 1,
                                    },
                                    "beacons": {"damaged_or_offline_count": 0, "disabled_count": 0, "total_count": 1},
                                    "cameras": {"damaged_or_offline_count": 0, "disabled_count": 0, "total_count": 2},
                                    "sensors": {"damaged_or_offline_count": 1, "disabled_count": 1, "total_count": 3},
                                    "detectors": {"damaged_or_offline_count": 0, "disabled_count": 0, "total_count": 1},
                                    "blocker_count": 3,
                                    "warnings": ["antenna_low_or_no_range:Forward Antenna"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_crew",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "crew warning",
                            "result": {
                                "sos_crew": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "control_stations": {
                                        "ready_count": 1,
                                        "total_count": 2,
                                        "damaged_or_offline_count": 1,
                                        "cockpit_count": 1,
                                        "control_seat_count": 1,
                                        "flight_seat_count": 0,
                                    },
                                    "remote_controls": {
                                        "ready_count": 0,
                                        "total_count": 1,
                                        "damaged_or_offline_count": 1,
                                    },
                                    "cryo_chambers": {"total_count": 1, "occupied_count": 0},
                                    "passenger_seats": {"total_count": 2, "occupied_count": 1},
                                    "occupancy_hints": {"occupied_count": 1},
                                    "blockers": ["control_station_damaged_or_offline:Aft Seat"],
                                    "warnings": ["control_station_damaged_or_offline:Aft Seat"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_docking",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "docking warning",
                            "result": {
                                "sos_docking": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "connectors": {
                                        "connected_count": 0,
                                        "locked_count": 0,
                                        "ready_count": 1,
                                        "damaged_or_offline_count": 1,
                                        "disabled_count": 0,
                                        "total_count": 2,
                                    },
                                    "landing_gear": {
                                        "locked_count": 1,
                                        "ready_count": 0,
                                        "damaged_or_offline_count": 0,
                                        "disabled_count": 0,
                                        "total_count": 1,
                                    },
                                    "merge_blocks": {
                                        "merged_count": 0,
                                        "ready_count": 1,
                                        "damaged_or_offline_count": 0,
                                        "disabled_count": 0,
                                        "total_count": 1,
                                    },
                                    "blocker_count": 1,
                                    "warnings": ["connector_damaged_or_offline:Docking Connector"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_life_support",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "life support warning",
                            "result": {
                                "sos_life_support": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "medical_rooms": {
                                        "damaged_or_offline_count": 0,
                                        "disabled_count": 0,
                                        "ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "survival_kits": {
                                        "damaged_or_offline_count": 0,
                                        "disabled_count": 0,
                                        "ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "cryo_chambers": {
                                        "damaged_or_offline_count": 0,
                                        "depleted_count": 0,
                                        "disabled_count": 0,
                                        "occupied_count": 0,
                                        "ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "oxygen_tanks": {
                                        "damaged_or_offline_count": 0,
                                        "depleted_count": 1,
                                        "disabled_count": 0,
                                        "ready_count": 0,
                                        "total_count": 1,
                                    },
                                    "hydrogen_tanks": {
                                        "damaged_or_offline_count": 0,
                                        "depleted_count": 0,
                                        "disabled_count": 0,
                                        "ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "o2_h2_generators": {
                                        "damaged_or_offline_count": 0,
                                        "disabled_count": 0,
                                        "ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "oxygen_farms": {
                                        "damaged_or_offline_count": 0,
                                        "disabled_count": 0,
                                        "ready_count": 0,
                                        "total_count": 0,
                                    },
                                    "resource_hints": {"oxygen_shortage": True, "hydrogen_shortage": False},
                                    "blocker_count": 1,
                                    "warning_count": 2,
                                    "warnings": ["oxygen_tank_depleted:O2 Tank", "oxygen_resource_shortage:oxygen_bottle"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_production",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "production warning",
                            "result": {
                                "sos_production": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "assemblers": {
                                        "damaged_or_offline_count": 1,
                                        "blocked_count": 0,
                                        "ready_count": 1,
                                        "total_count": 2,
                                    },
                                    "refineries": {
                                        "damaged_or_offline_count": 0,
                                        "blocked_count": 1,
                                        "ready_count": 0,
                                        "total_count": 1,
                                    },
                                    "survival_kits": {
                                        "present": True,
                                        "damaged_or_offline_count": 0,
                                        "blocked_count": 0,
                                        "ready_count": 1,
                                        "total_count": 1,
                                    },
                                    "queue": {
                                        "state": "blocked",
                                        "item_count": 2,
                                        "blocked_count": 1,
                                        "items": ["SteelPlate:10:queued"],
                                        "blocked_blueprints": ["ReactorComponent"],
                                    },
                                    "missing_materials": ["Iron"],
                                    "blockers": ["blocked_blueprint:ReactorComponent"],
                                    "warnings": ["assembler_damaged_or_offline:Aft Assembler"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_transit",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "transit warning",
                            "result": {
                                "sos_transit": {
                                    "state": "warning",
                                    "snapshot_status": "partial",
                                    "jump_drives": {
                                        "ready_count": 1,
                                        "total_count": 2,
                                        "charged_count": 1,
                                        "charging_count": 1,
                                        "disabled_count": 0,
                                        "damaged_count": 1,
                                    },
                                    "docking": {
                                        "blockers": ["connector_locked:Dock Connector"],
                                        "connected_count": 0,
                                        "anchored_count": 1,
                                        "merged_count": 0,
                                    },
                                    "power": {"state": "warning", "hints": ["battery_low:Main Battery"]},
                                    "comms": {"state": "ok", "hints": []},
                                    "blockers": ["jump_drive_damaged:Reserve Drive"],
                                    "warnings": ["jump_drive_damaged:Reserve Drive"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_defense",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "defense warning",
                            "result": {
                                "sos_defense": {
                                    "state": "warning",
                                    "snapshot_status": "ok",
                                    "turrets": {
                                        "ready_count": 1,
                                        "total_count": 2,
                                        "damaged_or_offline_count": 1,
                                        "disabled_count": 0,
                                    },
                                    "decoys": {"ready_count": 0, "total_count": 1, "damaged_or_offline_count": 0},
                                    "fixed_weapons": {"ready_count": 1, "total_count": 1, "damaged_or_offline_count": 0},
                                    "ammo": {"state": "shortage", "shortage_count": 1, "hints": ["ammo_shortage:NATO_25x184mm"]},
                                    "fuel": {"state": "ok", "shortage_count": 0, "hints": []},
                                    "power": {"state": "warning", "hints": ["battery_low:Main Battery"]},
                                    "comms_sensors": {"state": "ok", "hints": []},
                                    "shields": {"state": "warning", "ready_count": 0, "total_count": 1},
                                    "threats": {"hostile_count": 0, "threat_count": 1, "hints": ["threat_contact:drone"]},
                                    "blockers": ["turret_damaged_or_offline:Dorsal Turret"],
                                    "warnings": ["ammo_shortage:NATO_25x184mm"],
                                }
                            },
                        },
                        {
                            "script_id": "bridge-a-sos_environment",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "environment warning",
                            "result": {
                                "sos_environment": {
                                    "state": "warning",
                                    "snapshot_status": "partial",
                                    "context": {
                                        "zone": "orbit",
                                        "planet": "Earthlike",
                                        "gravity_g": 0.3,
                                        "atmosphere": "thin",
                                        "weather": "storm",
                                    },
                                    "hazards": {
                                        "state": "warning",
                                        "total_count": 2,
                                        "critical_count": 1,
                                        "warning_count": 1,
                                        "hints": ["radiation:critical:reactor leak"],
                                    },
                                    "exposure": {"state": "warning", "exterior_exposure_count": 1},
                                    "compartments": {
                                        "total_count": 2,
                                        "warning_count": 1,
                                        "critical_count": 1,
                                        "low_oxygen_count": 1,
                                        "depressurized_count": 1,
                                    },
                                    "warnings": ["radiation:critical:reactor leak"],
                                }
                            },
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_dashboard", "service_id": "dashboard"},
                            {"script_id": "bridge-a-sos_integrity", "service_id": "integrity"},
                            {"script_id": "bridge-a-sos_logistics", "service_id": "logistics"},
                            {"script_id": "bridge-a-sos_maintenance", "service_id": "maintenance"},
                            {"script_id": "bridge-a-sos_airlock", "service_id": "airlock"},
                            {"script_id": "bridge-a-sos_mobility", "service_id": "mobility"},
                            {"script_id": "bridge-a-sos_navigation", "service_id": "navigation"},
                            {"script_id": "bridge-a-sos_power", "service_id": "power"},
                            {"script_id": "bridge-a-sos_comms", "service_id": "comms"},
                            {"script_id": "bridge-a-sos_crew", "service_id": "crew"},
                            {"script_id": "bridge-a-sos_docking", "service_id": "docking"},
                            {"script_id": "bridge-a-sos_life_support", "service_id": "life_support"},
                            {"script_id": "bridge-a-sos_environment", "service_id": "environment"},
                            {"script_id": "bridge-a-sos_production", "service_id": "production"},
                            {"script_id": "bridge-a-sos_transit", "service_id": "transit"},
                            {"script_id": "bridge-a-sos_defense", "service_id": "defense"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", module.__name__, "", "", 1000, True),
        "bridge-a-sos_dashboard": WorkerScript("bridge-a-sos_dashboard", "manual", "Dashboard", module.__name__, "", "", 1000, True),
        "bridge-a-sos_integrity": WorkerScript("bridge-a-sos_integrity", "manual", "Integrity", module.__name__, "", "", 1000, True),
        "bridge-a-sos_logistics": WorkerScript("bridge-a-sos_logistics", "manual", "Logistics", module.__name__, "", "", 1000, True),
        "bridge-a-sos_maintenance": WorkerScript("bridge-a-sos_maintenance", "manual", "Maintenance", module.__name__, "", "", 1000, True),
        "bridge-a-sos_airlock": WorkerScript("bridge-a-sos_airlock", "manual", "Airlock", module.__name__, "", "", 1000, True),
        "bridge-a-sos_mobility": WorkerScript("bridge-a-sos_mobility", "manual", "Mobility", module.__name__, "", "", 1000, True),
        "bridge-a-sos_navigation": WorkerScript("bridge-a-sos_navigation", "manual", "Navigation", module.__name__, "", "", 1000, True),
        "bridge-a-sos_power": WorkerScript("bridge-a-sos_power", "manual", "Power", module.__name__, "", "", 1000, True),
        "bridge-a-sos_comms": WorkerScript("bridge-a-sos_comms", "manual", "Comms", module.__name__, "", "", 1000, True),
        "bridge-a-sos_crew": WorkerScript("bridge-a-sos_crew", "manual", "Crew", module.__name__, "", "", 1000, True),
        "bridge-a-sos_docking": WorkerScript("bridge-a-sos_docking", "manual", "Docking", module.__name__, "", "", 1000, True),
        "bridge-a-sos_life_support": WorkerScript("bridge-a-sos_life_support", "manual", "Life Support", module.__name__, "", "", 1000, True),
        "bridge-a-sos_environment": WorkerScript("bridge-a-sos_environment", "manual", "Environment", module.__name__, "", "", 1000, True),
        "bridge-a-sos_production": WorkerScript("bridge-a-sos_production", "manual", "Production", module.__name__, "", "", 1000, True),
        "bridge-a-sos_transit": WorkerScript("bridge-a-sos_transit", "manual", "Transit", module.__name__, "", "", 1000, True),
        "bridge-a-sos_defense": WorkerScript("bridge-a-sos_defense", "manual", "Defense", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 8,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    dashboard_request = next(item for item in captured if item["script_id"] == "bridge-a-sos_dashboard")
    telemetry = dashboard_request["runtime_telemetry"]
    assert telemetry["queue_pressure"] == {
        "queued": 3,
        "drained": 1,
        "remaining": 2,
        "by_source": {"bridge-a-sos_dashboard": {"queued": 1, "drained": 0, "remaining": 1}},
    }
    assert telemetry["child_services_by_service_id"]["dashboard"]["command_queue"] == {"queued": 1, "drained": 0, "remaining": 1}
    assert telemetry["child_services_by_service_id"]["status"]["result"]["sos_status"]["mode"] == "Combat"
    assert telemetry["child_services_by_service_id"]["integrity"]["result"]["sos_integrity"]["state"] == "degraded"
    assert telemetry["child_services_by_service_id"]["logistics"]["result"]["sos_logistics"]["state"] == "warning"
    maintenance = telemetry["child_services_by_service_id"]["maintenance"]["result"]["sos_maintenance"]
    assert maintenance["state"] == "warning"
    assert maintenance["damaged_block_count"] == 3
    assert maintenance["projectors"]["missing_block_count"] == 4
    assert maintenance["materials"]["state"] == "shortage"
    assert telemetry["child_services_by_service_id"]["airlock"]["result"]["sos_airlock"]["state"] == "warning"
    assert telemetry["child_services_by_service_id"]["airlock"]["result"]["sos_airlock"]["airlocks"]["unsafe_count"] == 1
    mobility = telemetry["child_services_by_service_id"]["mobility"]["result"]["sos_mobility"]
    assert mobility["state"] == "warning"
    assert mobility["thrusters"]["damaged_or_offline_count"] == 1
    assert mobility["jump_drives"]["not_ready_count"] == 1
    navigation = telemetry["child_services_by_service_id"]["navigation"]["result"]["sos_navigation"]
    assert navigation["state"] == "warning"
    assert navigation["motion"]["speed_mps"] == 14.2
    assert navigation["route"]["waypoint_count"] == 2
    assert navigation["dependencies"]["environment_state"] == "warning"
    power = telemetry["child_services_by_service_id"]["power"]["result"]["sos_power"]
    assert power["state"] == "warning"
    assert power["batteries"]["low_charge_count"] == 1
    assert power["reactors"]["fuel_shortage_count"] == 1
    comms = telemetry["child_services_by_service_id"]["comms"]["result"]["sos_comms"]
    assert comms["state"] == "warning"
    assert comms["antennas"]["low_or_no_range_count"] == 1
    assert comms["laser_antennas"]["disconnected_or_unlinked_count"] == 1
    crew = telemetry["child_services_by_service_id"]["crew"]["result"]["sos_crew"]
    assert crew["state"] == "warning"
    assert crew["control_stations"]["damaged_or_offline_count"] == 1
    assert crew["remote_controls"]["damaged_or_offline_count"] == 1
    docking = telemetry["child_services_by_service_id"]["docking"]["result"]["sos_docking"]
    assert docking["state"] == "warning"
    assert docking["connectors"]["damaged_or_offline_count"] == 1
    assert docking["merge_blocks"]["ready_count"] == 1
    life_support = telemetry["child_services_by_service_id"]["life_support"]["result"]["sos_life_support"]
    assert life_support["state"] == "warning"
    assert life_support["oxygen_tanks"]["depleted_count"] == 1
    assert life_support["resource_hints"]["oxygen_shortage"] is True
    production = telemetry["child_services_by_service_id"]["production"]["result"]["sos_production"]
    assert production["state"] == "warning"
    assert production["assemblers"]["damaged_or_offline_count"] == 1
    assert production["queue"]["blocked_count"] == 1
    transit = telemetry["child_services_by_service_id"]["transit"]["result"]["sos_transit"]
    assert transit["state"] == "warning"
    assert transit["jump_drives"]["damaged_count"] == 1
    assert transit["power"]["state"] == "warning"
    defense = telemetry["child_services_by_service_id"]["defense"]["result"]["sos_defense"]
    assert defense["state"] == "warning"
    assert defense["turrets"]["damaged_or_offline_count"] == 1
    assert defense["ammo"]["shortage_count"] == 1
    environment = telemetry["child_services_by_service_id"]["environment"]["result"]["sos_environment"]
    assert environment["state"] == "warning"
    assert environment["hazards"]["critical_count"] == 1
    assert environment["compartments"]["depressurized_count"] == 1


def test_execute_sos_dashboard_child_degrades_gracefully_without_child_history(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_dashboard", "service_id": "dashboard"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_dashboard": WorkerScript(
            "bridge-a-sos_dashboard",
            "manual",
            "Dashboard",
            "worker.scripts.sos_dashboard",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert result["result"]["child_results"][0]["summary"] == (
        "SOS Dashboard Ship A mode=Docked integrity=unknown logistics=unknown maintenance=unknown airlock=unknown mobility=unknown navigation=unknown power=unknown comms=unknown crew=unknown docking=unknown life_support=unknown environment=unknown production=unknown transit=unknown defense=unknown queue=0 blockers=none"
    )
    dashboard = result["result"]["child_results"][0]["result"]["sos_dashboard"]
    assert dashboard["integrity"]["snapshot_status"] == "missing_child_result"
    assert dashboard["logistics"]["snapshot_status"] == "missing_child_result"
    assert dashboard["maintenance"]["snapshot_status"] == "missing_child_result"
    assert dashboard["mobility"]["snapshot_status"] == "missing_child_result"
    assert dashboard["navigation"]["snapshot_status"] == "missing_child_result"
    assert dashboard["power"]["snapshot_status"] == "missing_child_result"
    assert dashboard["comms"]["snapshot_status"] == "missing_child_result"
    assert dashboard["crew"]["snapshot_status"] == "missing_child_result"
    assert dashboard["docking"]["snapshot_status"] == "missing_child_result"
    assert dashboard["life_support"]["snapshot_status"] == "missing_child_result"
    assert dashboard["environment"]["snapshot_status"] == "missing_child_result"
    assert dashboard["production"]["snapshot_status"] == "missing_child_result"
    assert dashboard["transit"]["snapshot_status"] == "missing_child_result"
    assert dashboard["defense"]["snapshot_status"] == "missing_child_result"
    assert result["result"]["commands"][0]["text"] == (
        "SOS Dashboard Ship A mode=Docked integrity=unknown logistics=unknown maintenance=unknown airlock=unknown mobility=unknown navigation=unknown power=unknown comms=unknown crew=unknown docking=unknown life_support=unknown environment=unknown production=unknown transit=unknown defense=unknown queue=0 blockers=none"
    )


def test_execute_sos_orchestrator_passes_airlock_snapshot_only_to_airlock_child(tmp_path: Path):
    captured: dict[str, dict] = {}

    def install_adapter(module_name: str) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            captured[request["script_id"]] = request
            return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_airlock_capture_children")
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_airlock", "service_id": "airlock"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_airlock": WorkerScript("bridge-a-sos_airlock", "manual", "Airlock", "tests.sos_airlock_capture_children", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_airlock_capture_children", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {
                        "entity_id": 101,
                        "name": "Port Outer",
                        "type": "Door",
                        "is_door": True,
                        "door_status": "Open",
                        "door_open_ratio": 1.0,
                        "is_exterior": True,
                        "functional": True,
                        "enabled": True,
                        "integrity_ratio": 0.82,
                        "airlock_id": "port",
                    },
                    {
                        "entity_id": 201,
                        "name": "Port Vent",
                        "type": "AirVent",
                        "is_air_vent": True,
                        "compartment_id": "port-compartment",
                        "compartment_name": "Port Lock",
                        "oxygen_level": 0.62,
                        "pressure_ratio": 0.7,
                        "pressurized": True,
                        "functional": True,
                        "enabled": True,
                        "integrity_ratio": 1.0,
                    },
                ],
                "airlocks": [
                    {
                        "airlock_id": "port",
                        "name": "Port Lock",
                        "inner_door_id": 100,
                        "outer_door_id": 101,
                        "inner_door_open": False,
                        "outer_door_open": True,
                        "safe": True,
                        "pressurized": True,
                    }
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_airlock"]["airlock_snapshot"] == {
        "doors": [
            {
                "entity_id": 101,
                "name": "Port Outer",
                "is_open": True,
                "is_exterior": True,
                "functional": True,
                "enabled": True,
                "integrity_ratio": 0.82,
                "airlock_id": "port",
            }
        ],
        "airlocks": [
            {
                "airlock_id": "port",
                "name": "Port Lock",
                "inner_door_id": 100,
                "outer_door_id": 101,
                "inner_door_open": False,
                "outer_door_open": True,
                "safe": True,
                "pressurized": True,
            }
        ],
        "vents": [
            {
                "vent_entity_id": 201,
                "name": "Port Vent",
                "compartment_id": "port-compartment",
                "compartment_name": "Port Lock",
                "oxygen_level": 0.62,
                "pressure_ratio": 0.7,
                "pressurized": True,
                "functional": True,
                "enabled": True,
                "integrity_ratio": 1.0,
            }
        ],
    }
    assert "airlock_snapshot" not in captured["bridge-a-doors"]
    assert "door_snapshot" not in captured["bridge-a-doors"]
    assert "ship_doors" not in captured["bridge-a-doors"]


def test_execute_sos_airlock_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_airlock", "service_id": "airlock"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_airlock": WorkerScript(
            "bridge-a-sos_airlock",
            "manual",
            "Airlock",
            "worker.scripts.sos_airlock",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    airlock_child = result["result"]["child_results"][0]
    assert airlock_child["summary"] == "SOS Airlock Ship A state=unknown snapshot=no_snapshot"
    assert airlock_child["result"]["sos_airlock"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Airlock Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_airlock",
            "source_priority": 14,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_mobility_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_mobility_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_mobility_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_mobility_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_mobility", "service_id": "mobility"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_mobility_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_mobility": WorkerScript(
            "bridge-a-sos_mobility",
            "manual",
            "Mobility",
            "worker.scripts.sos_mobility",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_mobility_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_mobility_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Main Thruster", "type": "LargeBlockLargeThrust", "functional": True},
                    {"name": "Main Gyro", "type": "Gyro", "functional": True},
                    {"name": "Cockpit", "type": "Cockpit", "functional": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_mobility",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    mobility_child = result["result"]["child_results"][1]
    assert mobility_child["summary"] == (
        "SOS Mobility Ship A state=ok thrusters=0/1 gyros=0/1 control=0/1 jump=0/0 power_fuel=0"
    )
    assert mobility_child["error_bucket"] == "none"
    assert mobility_child["result"]["sos_mobility"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_and_integrity_snapshot_to_mobility_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_mobility_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_mobility", "service_id": "mobility"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_mobility": WorkerScript("bridge-a-sos_mobility", "manual", "Mobility", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Main Thruster", "type": "LargeBlockLargeThrust", "integrity_ratio": 0.91, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_mobility"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_mobility"]["integrity_snapshot"] == {
        "blocks": [{"name": "Main Thruster", "type": "LargeBlockLargeThrust", "integrity_ratio": 0.91, "functional": True}],
        "critical_systems": [],
    }
    assert "mobility_snapshot" not in captured["bridge-a-sos_mobility"]
    assert "mobility_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_mobility_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_mobility", "service_id": "mobility"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_mobility": WorkerScript(
            "bridge-a-sos_mobility",
            "manual",
            "Mobility",
            "worker.scripts.sos_mobility",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    mobility_child = result["result"]["child_results"][0]
    assert mobility_child["summary"] == "SOS Mobility Ship A state=unknown snapshot=no_snapshot"
    assert mobility_child["result"]["sos_mobility"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Mobility Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_mobility",
            "source_priority": 13,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_power_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_power_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_power_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_power_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_power", "service_id": "power"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_power_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_power": WorkerScript(
            "bridge-a-sos_power",
            "manual",
            "Power",
            "worker.scripts.sos_power",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_power_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_power_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Main Battery", "type": "BatteryBlock", "functional": True, "charge_ratio": 0.8},
                    {"name": "Main Reactor", "type": "Reactor", "functional": True, "fuel_ratio": 0.8},
                    {"name": "Solar Array", "type": "SolarPanel", "functional": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_power",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    power_child = result["result"]["child_results"][1]
    assert power_child["summary"] == "SOS Power Ship A state=ok batteries=0/1 reactors=0/1 generators=0/1 blockers=0"
    assert power_child["error_bucket"] == "none"
    assert power_child["result"]["sos_power"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_integrity_and_inventory_data_to_power_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_power_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_power", "service_id": "power"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_power": WorkerScript("bridge-a-sos_power", "manual", "Power", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Main Battery", "type": "BatteryBlock", "integrity_ratio": 0.91, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    logistics_snapshot = {
        "fuel": {
            "Uranium": {"current": 0.2, "minimum": 1.0},
            "Ice": {"current": 20.0, "minimum": 5.0},
        }
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "logistics_snapshot": logistics_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_power"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_power"]["integrity_snapshot"] == {
        "blocks": [{"name": "Main Battery", "type": "BatteryBlock", "integrity_ratio": 0.91, "functional": True}],
        "critical_systems": [],
    }
    assert captured["bridge-a-sos_power"]["inventory_snapshot"] == logistics_snapshot
    assert "power_snapshot" not in captured["bridge-a-sos_power"]
    assert "power_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]
    assert "inventory_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_power_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_power", "service_id": "power"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_power": WorkerScript(
            "bridge-a-sos_power",
            "manual",
            "Power",
            "worker.scripts.sos_power",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    power_child = result["result"]["child_results"][0]
    assert power_child["summary"] == "SOS Power Ship A state=unknown snapshot=no_snapshot"
    assert power_child["result"]["sos_power"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Power Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_power",
            "source_priority": 15,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_comms_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_comms_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_comms_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_comms_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_comms", "service_id": "comms"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_comms_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_comms": WorkerScript(
            "bridge-a-sos_comms",
            "manual",
            "Comms",
            "worker.scripts.sos_comms",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_comms_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_comms_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Main Antenna", "type": "RadioAntenna", "functional": True, "enabled": True},
                    {"name": "Main Sensor", "type": "Sensor", "functional": True, "enabled": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_comms",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    comms_child = result["result"]["child_results"][1]
    assert comms_child["summary"] == (
        "SOS Comms Ship A state=ok antennas=0/1 lasers=0/0 beacons=0/0 cameras=0/0 sensors=0/1 detectors=0/0 blockers=0"
    )
    assert comms_child["error_bucket"] == "none"
    assert comms_child["result"]["sos_comms"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_and_integrity_snapshot_to_comms_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_comms_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_comms", "service_id": "comms"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_comms": WorkerScript("bridge-a-sos_comms", "manual", "Comms", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Main Antenna", "type": "RadioAntenna", "integrity_ratio": 0.91, "functional": True},
            {"name": "Main Sensor", "type": "Sensor", "integrity_ratio": 1.0, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_comms"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_comms"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Main Antenna", "type": "RadioAntenna", "integrity_ratio": 0.91, "functional": True},
            {"name": "Main Sensor", "type": "Sensor", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert "comms_snapshot" not in captured["bridge-a-sos_comms"]
    assert "comms_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_comms_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_comms", "service_id": "comms"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_comms": WorkerScript(
            "bridge-a-sos_comms",
            "manual",
            "Comms",
            "worker.scripts.sos_comms",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    comms_child = result["result"]["child_results"][0]
    assert comms_child["summary"] == "SOS Comms Ship A state=unknown snapshot=no_snapshot"
    assert comms_child["result"]["sos_comms"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Comms Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_comms",
            "source_priority": 16,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_docking_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_docking_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_docking_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_docking_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_docking", "service_id": "docking"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript("bridge-a-sos_status", "manual", "Status", "tests.sos_docking_registry_status_child", "", "", 1000, True),
        "bridge-a-sos_docking": WorkerScript(
            "bridge-a-sos_docking",
            "manual",
            "Docking",
            "worker.scripts.sos_docking",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", "tests.sos_docking_registry_inventory_child", "", "", 1000, True),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_docking_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Main Connector", "type": "ShipConnector", "functional": True, "status": "Connected"},
                    {"name": "Landing Gear", "type": "LandingGear", "functional": True, "locked": True},
                    {"name": "Merge Block", "type": "MergeBlock", "functional": True, "merged": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_docking",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    docking_child = result["result"]["child_results"][1]
    assert docking_child["summary"] == "SOS Docking Ship A state=ok connectors=1/1 anchors=1/1 merge=1/1 blockers=0"
    assert docking_child["error_bucket"] == "none"
    assert docking_child["result"]["sos_docking"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_and_integrity_snapshot_to_docking_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_docking_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_docking", "service_id": "docking"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_docking": WorkerScript("bridge-a-sos_docking", "manual", "Docking", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Main Connector", "type": "ShipConnector", "integrity_ratio": 0.91, "functional": True},
            {"name": "Landing Gear", "type": "LandingGear", "integrity_ratio": 1.0, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_docking"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_docking"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Main Connector", "type": "ShipConnector", "integrity_ratio": 0.91, "functional": True},
            {"name": "Landing Gear", "type": "LandingGear", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert "docking_snapshot" not in captured["bridge-a-sos_docking"]
    assert "anchoring_snapshot" not in captured["bridge-a-sos_docking"]
    assert "docking_snapshot" not in captured["bridge-a-inventory"]
    assert "anchoring_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_docking_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_docking", "service_id": "docking"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_docking": WorkerScript(
            "bridge-a-sos_docking",
            "manual",
            "Docking",
            "worker.scripts.sos_docking",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    docking_child = result["result"]["child_results"][0]
    assert docking_child["summary"] == "SOS Docking Ship A state=unknown snapshot=no_snapshot"
    assert docking_child["result"]["sos_docking"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Docking Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_docking",
            "source_priority": 11,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_life_support_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_life_support_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_life_support_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_life_support_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_life_support", "service_id": "life_support"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_life_support_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_life_support": WorkerScript(
            "bridge-a-sos_life_support",
            "manual",
            "Life Support",
            "worker.scripts.sos_life_support",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_life_support_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_life_support_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Med Bay", "type": "MedicalRoom", "functional": True},
                    {"name": "Survival Kit", "type": "SurvivalKit", "functional": True},
                    {"name": "Cryo Pod", "type": "CryoChamber", "functional": True},
                    {"name": "Oxygen Tank", "type": "OxygenTank", "functional": True, "fill_ratio": 0.8},
                    {"name": "Hydrogen Tank", "type": "HydrogenTank", "functional": True, "fill_ratio": 0.8},
                    {"name": "O2/H2 Generator", "type": "O2H2Generator", "functional": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_life_support",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    life_support_child = result["result"]["child_results"][1]
    assert life_support_child["summary"] == (
        "SOS Life Support Ship A state=ok medical=1/1 survival=1/1 cryo=1/1 o2=1/1 h2=1/1 generators=1/1 blockers=0"
    )
    assert life_support_child["error_bucket"] == "none"
    assert life_support_child["result"]["sos_life_support"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_integrity_and_inventory_data_to_life_support_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_life_support_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_life_support", "service_id": "life_support"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_life_support": WorkerScript("bridge-a-sos_life_support", "manual", "Life Support", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Med Bay", "type": "MedicalRoom", "integrity_ratio": 0.91, "functional": True},
            {"name": "Oxygen Tank", "type": "OxygenTank", "integrity_ratio": 1.0, "functional": True, "fill_ratio": 0.8},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    logistics_snapshot = {
        "resources": {
            "oxygen_bottle": {"current": 1.0, "minimum": 2.0},
            "hydrogen_bottle": {"current": 4.0, "minimum": 2.0},
        }
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "logistics_snapshot": logistics_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_life_support"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_life_support"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Med Bay", "type": "MedicalRoom", "integrity_ratio": 0.91, "functional": True},
            {"name": "Oxygen Tank", "type": "OxygenTank", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert captured["bridge-a-sos_life_support"]["inventory_snapshot"] == logistics_snapshot
    assert "life_support_snapshot" not in captured["bridge-a-sos_life_support"]
    assert "crew_snapshot" not in captured["bridge-a-sos_life_support"]
    assert "survival_snapshot" not in captured["bridge-a-sos_life_support"]
    assert "life_support_snapshot" not in captured["bridge-a-inventory"]
    assert "crew_snapshot" not in captured["bridge-a-inventory"]
    assert "survival_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]
    assert "inventory_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_life_support_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_life_support", "service_id": "life_support"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_life_support": WorkerScript(
            "bridge-a-sos_life_support",
            "manual",
            "Life Support",
            "worker.scripts.sos_life_support",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    life_support_child = result["result"]["child_results"][0]
    assert life_support_child["summary"] == "SOS Life Support Ship A state=unknown snapshot=no_snapshot"
    assert life_support_child["result"]["sos_life_support"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Life Support Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_life_support",
            "source_priority": 14,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_production_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_production_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_production_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_production_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_production", "service_id": "production"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_production_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_production": WorkerScript(
            "bridge-a-sos_production",
            "manual",
            "Production",
            "worker.scripts.sos_production",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_production_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_production_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Assembler", "type": "Assembler", "functional": True, "enabled": True},
                    {"name": "Refinery", "type": "Refinery", "functional": True, "enabled": True},
                    {"name": "Survival Kit", "type": "SurvivalKit", "functional": True, "enabled": True},
                ],
                "production": {"queue": [{"blueprint": "SteelPlate", "amount": 10}]},
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_production",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    production_child = result["result"]["child_results"][1]
    assert production_child["summary"] == (
        "SOS Production Ship A state=ok assemblers=0/1 refineries=0/1 survival=1/1 queue=1 blockers=0"
    )
    assert production_child["error_bucket"] == "none"
    assert production_child["result"]["sos_production"]["snapshot_status"] == "partial"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_integrity_and_inventory_data_to_production_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_production_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_production", "service_id": "production"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_production": WorkerScript("bridge-a-sos_production", "manual", "Production", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Assembler", "type": "Assembler", "integrity_ratio": 0.91, "functional": True},
            {"name": "Refinery", "type": "Refinery", "integrity_ratio": 1.0, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    logistics_snapshot = {
        "production": {
            "queue": [{"blueprint": "SteelPlate", "amount": 10}],
            "blockers": ["missing_material:Iron"],
        }
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "logistics_snapshot": logistics_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_production"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_production"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Assembler", "type": "Assembler", "integrity_ratio": 0.91, "functional": True},
            {"name": "Refinery", "type": "Refinery", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert captured["bridge-a-sos_production"]["inventory_snapshot"] == logistics_snapshot
    assert "production_snapshot" not in captured["bridge-a-sos_production"]
    assert "manufacturing_snapshot" not in captured["bridge-a-sos_production"]
    assert "factory_snapshot" not in captured["bridge-a-sos_production"]
    assert "production_snapshot" not in captured["bridge-a-inventory"]
    assert "manufacturing_snapshot" not in captured["bridge-a-inventory"]
    assert "factory_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]
    assert "inventory_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_production_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_production", "service_id": "production"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_production": WorkerScript(
            "bridge-a-sos_production",
            "manual",
            "Production",
            "worker.scripts.sos_production",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    production_child = result["result"]["child_results"][0]
    assert production_child["summary"] == "SOS Production Ship A state=unknown snapshot=no_snapshot"
    assert production_child["result"]["sos_production"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Production Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_production",
            "source_priority": 17,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_crew_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_crew_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_crew_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_crew_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_crew", "service_id": "crew"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_crew_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_crew": WorkerScript(
            "bridge-a-sos_crew",
            "manual",
            "Crew",
            "worker.scripts.sos_crew",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_crew_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_crew_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Main Cockpit", "type": "Cockpit", "functional": True, "enabled": True},
                    {"name": "Remote Control", "type": "RemoteControl", "functional": True, "enabled": True},
                    {"name": "Passenger Seat", "type": "PassengerSeat", "functional": True, "enabled": True, "occupied": True},
                    {"name": "Cryo Pod", "type": "CryoChamber", "functional": True, "enabled": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_crew",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    crew_child = result["result"]["child_results"][1]
    assert crew_child["summary"] == "SOS Crew Ship A state=ok stations=1/1 remote=1/1 occupied=1 blockers=0"
    assert crew_child["error_bucket"] == "none"
    assert crew_child["result"]["sos_crew"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_and_integrity_snapshot_to_crew_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_crew_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_crew", "service_id": "crew"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_crew": WorkerScript("bridge-a-sos_crew", "manual", "Crew", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Main Cockpit", "type": "Cockpit", "integrity_ratio": 0.91, "functional": True},
            {"name": "Remote Control", "type": "RemoteControl", "integrity_ratio": 1.0, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_crew"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_crew"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Main Cockpit", "type": "Cockpit", "integrity_ratio": 0.91, "functional": True},
            {"name": "Remote Control", "type": "RemoteControl", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert "crew_snapshot" not in captured["bridge-a-sos_crew"]
    assert "station_snapshot" not in captured["bridge-a-sos_crew"]
    assert "control_snapshot" not in captured["bridge-a-sos_crew"]
    assert "crew_snapshot" not in captured["bridge-a-inventory"]
    assert "station_snapshot" not in captured["bridge-a-inventory"]
    assert "control_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_crew_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_crew", "service_id": "crew"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_crew": WorkerScript(
            "bridge-a-sos_crew",
            "manual",
            "Crew",
            "worker.scripts.sos_crew",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    crew_child = result["result"]["child_results"][0]
    assert crew_child["summary"] == "SOS Crew Ship A state=unknown snapshot=no_snapshot"
    assert crew_child["result"]["sos_crew"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Crew Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_crew",
            "source_priority": 14,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_transit_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_transit_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_transit_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_transit_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_transit", "service_id": "transit"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_transit_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_transit": WorkerScript(
            "bridge-a-sos_transit",
            "manual",
            "Transit",
            "worker.scripts.sos_transit",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_transit_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_transit_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Jump Drive", "type": "JumpDrive", "functional": True, "enabled": True, "ready": True, "charge_ratio": 1.0},
                    {"name": "Hydrogen Tank", "type": "HydrogenTank", "functional": True, "enabled": True, "fill_ratio": 0.75},
                    {"name": "Gyro", "type": "Gyro", "functional": True, "enabled": True},
                    {"name": "Large Thruster", "type": "HydrogenThruster", "functional": True, "enabled": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_transit",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    transit_child = result["result"]["child_results"][1]
    assert transit_child["summary"] == "SOS Transit Ship A state=ok jump=1/1 charged=1 charging=0 blockers=0 warnings=0"
    assert transit_child["error_bucket"] == "none"
    assert transit_child["result"]["sos_transit"]["snapshot_status"] == "partial"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_integrity_and_inventory_data_to_transit_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_transit_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_transit", "service_id": "transit"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_transit": WorkerScript("bridge-a-sos_transit", "manual", "Transit", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Jump Drive", "type": "JumpDrive", "integrity_ratio": 0.91, "functional": True, "charge_ratio": 1.0},
            {"name": "Hydrogen Tank", "type": "HydrogenTank", "integrity_ratio": 1.0, "functional": True, "fill_ratio": 0.8},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    logistics_snapshot = {
        "fuel": {"hydrogen": {"current": 800.0, "minimum": 200.0}},
        "resources": {"uranium": {"current": 5.0, "minimum": 1.0}},
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "logistics_snapshot": logistics_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_transit"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_transit"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Jump Drive", "type": "JumpDrive", "integrity_ratio": 0.91, "functional": True},
            {"name": "Hydrogen Tank", "type": "HydrogenTank", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert captured["bridge-a-sos_transit"]["inventory_snapshot"] == logistics_snapshot
    assert "transit_snapshot" not in captured["bridge-a-sos_transit"]
    assert "jump_snapshot" not in captured["bridge-a-sos_transit"]
    assert "jump_drive_snapshot" not in captured["bridge-a-sos_transit"]
    assert "transit_snapshot" not in captured["bridge-a-inventory"]
    assert "jump_snapshot" not in captured["bridge-a-inventory"]
    assert "jump_drive_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]
    assert "inventory_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_transit_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [{"script_id": "bridge-a-sos_transit", "service_id": "transit"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_transit": WorkerScript(
            "bridge-a-sos_transit",
            "manual",
            "Transit",
            "worker.scripts.sos_transit",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"entity_id": 301, "name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    transit_child = result["result"]["child_results"][0]
    assert transit_child["summary"] == "SOS Transit Ship A state=unknown snapshot=no_snapshot"
    assert transit_child["result"]["sos_transit"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Transit Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_transit",
            "source_priority": 11,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_defense_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_defense_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_defense_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_defense_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_defense", "service_id": "defense"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_defense_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_defense": WorkerScript(
            "bridge-a-sos_defense",
            "manual",
            "Defense",
            "worker.scripts.sos_defense",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_defense_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_defense_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Gatling Turret", "type": "LargeGatlingTurret", "functional": True, "enabled": True, "has_ammo": True},
                    {"name": "Interior Turret", "type": "InteriorTurret", "functional": True, "enabled": True, "has_ammo": True},
                    {"name": "Decoy", "type": "Decoy", "functional": True, "enabled": True},
                    {"name": "Shield Controller", "type": "ShieldController", "functional": True, "enabled": True, "shield_ratio": 0.75},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_defense",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    defense_child = result["result"]["child_results"][1]
    assert defense_child["summary"] == (
        "SOS Defense Ship A state=ok turrets=2/2 decoys=1/1 fixed=0/0 ammo=unknown fuel=unknown power=unknown comms=unknown threats=0 snapshot=ok"
    )
    assert defense_child["error_bucket"] == "none"
    assert defense_child["result"]["sos_defense"]["snapshot_status"] == "ok"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_grid_integrity_and_inventory_data_to_defense_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_defense_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_defense", "service_id": "defense"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_defense": WorkerScript("bridge-a-sos_defense", "manual", "Defense", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Gatling Turret", "type": "LargeGatlingTurret", "integrity_ratio": 0.91, "functional": True},
            {"name": "Decoy", "type": "Decoy", "integrity_ratio": 1.0, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    logistics_snapshot = {
        "ammo": [{"name": "NATO_25x184mm", "current": 240.0, "minimum": 120.0}],
        "fuel": {"uranium": {"current": 5.0, "minimum": 1.0}},
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "logistics_snapshot": logistics_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_defense"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_defense"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Gatling Turret", "type": "LargeGatlingTurret", "integrity_ratio": 0.91, "functional": True},
            {"name": "Decoy", "type": "Decoy", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    assert captured["bridge-a-sos_defense"]["inventory_snapshot"] == logistics_snapshot
    assert "defense_snapshot" not in captured["bridge-a-sos_defense"]
    assert "threat_snapshot" not in captured["bridge-a-sos_defense"]
    assert "weapons_snapshot" not in captured["bridge-a-sos_defense"]
    assert "combat_snapshot" not in captured["bridge-a-sos_defense"]
    assert "defense_snapshot" not in captured["bridge-a-inventory"]
    assert "threat_snapshot" not in captured["bridge-a-inventory"]
    assert "weapons_snapshot" not in captured["bridge-a-inventory"]
    assert "combat_snapshot" not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]
    assert "inventory_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_defense_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "services": [{"script_id": "bridge-a-sos_defense", "service_id": "defense"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_defense": WorkerScript(
            "bridge-a-sos_defense",
            "manual",
            "Defense",
            "worker.scripts.sos_defense",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    defense_child = result["result"]["child_results"][0]
    assert defense_child["summary"] == "SOS Defense Ship A state=unknown snapshot=no_snapshot"
    assert defense_child["result"]["sos_defense"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Defense Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_defense",
            "source_priority": 13,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_environment_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_environment_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_environment_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_environment_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_environment", "service_id": "environment"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_environment_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_environment": WorkerScript(
            "bridge-a-sos_environment",
            "manual",
            "Environment",
            "worker.scripts.sos_environment",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_environment_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_environment_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "weather": {"state": "clear"},
                "hazards": [{"name": "meteor shower", "severity": "warning"}],
                "blocks": [
                    {
                        "name": "Air Vent",
                        "type": "AirVent",
                        "functional": True,
                        "enabled": True,
                        "oxygen_level": 0.9,
                        "pressure_ratio": 1.0,
                    }
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_environment",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    environment_child = result["result"]["child_results"][1]
    assert environment_child["summary"] == (
        "SOS Environment Ship A state=warning hazards=1 critical=0 compartments=0 low_o2=0 depressurized=0 exposure=0"
    )
    assert environment_child["error_bucket"] == "none"
    assert environment_child["result"]["sos_environment"]["snapshot_status"] == "partial"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_scoped_environment_data_to_environment_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_environment_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_environment", "service_id": "environment"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_environment": WorkerScript("bridge-a-sos_environment", "manual", "Environment", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Air Vent", "type": "AirVent", "integrity_ratio": 0.91, "functional": True},
            {"name": "Oxygen Tank", "type": "OxygenTank", "integrity_ratio": 1.0, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    environment_snapshot = {
        "weather": {"state": "storm"},
        "hazards": [{"name": "meteor shower", "severity": "warning"}],
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "environment_snapshot": environment_snapshot,
            "hazard_snapshot": {"hazards": [{"name": "radiation", "severity": "critical"}]},
            "weather_snapshot": {"weather": {"state": "storm"}},
            "external_snapshot": {"zone": "orbit"},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_environment"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_environment"]["environment_snapshot"] == environment_snapshot
    assert captured["bridge-a-sos_environment"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Air Vent", "type": "AirVent", "integrity_ratio": 0.91, "functional": True},
            {"name": "Oxygen Tank", "type": "OxygenTank", "integrity_ratio": 1.0, "functional": True},
        ],
        "critical_systems": [],
    }
    for key in ("environment_snapshot", "hazard_snapshot", "weather_snapshot", "external_snapshot"):
        assert key not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_environment_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "services": [{"script_id": "bridge-a-sos_environment", "service_id": "environment"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_environment": WorkerScript(
            "bridge-a-sos_environment",
            "manual",
            "Environment",
            "worker.scripts.sos_environment",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    environment_child = result["result"]["child_results"][0]
    assert environment_child["summary"] == "SOS Environment Ship A state=unknown snapshot=no_snapshot"
    assert environment_child["result"]["sos_environment"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Environment Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_environment",
            "source_priority": 14,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_navigation_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_navigation_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_navigation_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_navigation_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_navigation", "service_id": "navigation"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_navigation_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_navigation": WorkerScript(
            "bridge-a-sos_navigation",
            "manual",
            "Navigation",
            "worker.scripts.sos_navigation",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_navigation_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_navigation_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Remote Control", "type": "RemoteControl", "functional": True, "enabled": True},
                    {"name": "Gyro", "type": "Gyro", "functional": True, "enabled": True},
                    {"name": "Forward Thruster", "type": "HydrogenThruster", "functional": True, "enabled": True},
                    {"name": "Camera", "type": "Camera", "functional": True, "enabled": True},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_navigation",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    navigation_child = result["result"]["child_results"][1]
    assert navigation_child["summary"] == (
        "SOS Navigation Ship A state=ok speed=unknown motion=unknown route=0 hazards=0 blockers=0 warnings=0"
    )
    assert navigation_child["error_bucket"] == "none"
    assert navigation_child["result"]["sos_navigation"]["snapshot_status"] == "partial"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_scoped_navigation_data_to_navigation_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_navigation_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_navigation", "service_id": "navigation"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_navigation": WorkerScript("bridge-a-sos_navigation", "manual", "Navigation", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Remote Control", "type": "RemoteControl", "integrity_ratio": 0.8, "functional": True},
            {"name": "Gyro", "type": "Gyro", "integrity_ratio": 0.95, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    navigation_snapshot = {"speed_mps": 12.5, "route": {"waypoint_count": 2, "active_waypoint": "Rendezvous"}}
    environment_snapshot = {"hazards": [{"name": "asteroid", "severity": "warning"}]}

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "navigation_snapshot": navigation_snapshot,
            "nav_snapshot": {"speed_mps": 8.0},
            "flight_snapshot": {"motion_state": "coasting"},
            "motion_snapshot": {"speed_mps": 2.0},
            "mobility_snapshot": {"state": "warning"},
            "transit_snapshot": {"state": "ok"},
            "environment_snapshot": environment_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_navigation"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_navigation"]["navigation_snapshot"] == navigation_snapshot
    assert captured["bridge-a-sos_navigation"]["environment_snapshot"] == environment_snapshot
    assert captured["bridge-a-sos_navigation"]["mobility_snapshot"] == {"state": "warning"}
    assert captured["bridge-a-sos_navigation"]["transit_snapshot"] == {"state": "ok"}
    assert captured["bridge-a-sos_navigation"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Remote Control", "type": "RemoteControl", "integrity_ratio": 0.8, "functional": True},
            {"name": "Gyro", "type": "Gyro", "integrity_ratio": 0.95, "functional": True},
        ],
        "critical_systems": [],
    }
    for key in ("navigation_snapshot", "nav_snapshot", "flight_snapshot", "motion_snapshot", "environment_snapshot"):
        assert key not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_navigation_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "services": [{"script_id": "bridge-a-sos_navigation", "service_id": "navigation"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_navigation": WorkerScript(
            "bridge-a-sos_navigation",
            "manual",
            "Navigation",
            "worker.scripts.sos_navigation",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    navigation_child = result["result"]["child_results"][0]
    assert navigation_child["summary"] == "SOS Navigation Ship A state=unknown snapshot=no_snapshot"
    assert navigation_child["result"]["sos_navigation"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Navigation Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_navigation",
            "source_priority": 13,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_runs_maintenance_child_with_existing_services(tmp_path: Path):
    def install_adapter(module_name: str, summary: str, command: dict[str, object]) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {"summary": summary, "commands": [command]}

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.sos_maintenance_registry_status_child", "status ok", {"kind": "echo", "text": "status"})
    install_adapter("tests.sos_maintenance_registry_inventory_child", "inventory ok", {"kind": "echo", "text": "inventory"})
    install_adapter("tests.sos_maintenance_registry_door_child", "doors ok", {"kind": "echo", "text": "doors"})
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_status", "service_id": "status"},
                            {"script_id": "bridge-a-sos_maintenance", "service_id": "maintenance"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                            {"script_id": "bridge-a-doors", "service_id": "doors"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_status": WorkerScript(
            "bridge-a-sos_status", "manual", "Status", "tests.sos_maintenance_registry_status_child", "", "", 1000, True
        ),
        "bridge-a-sos_maintenance": WorkerScript(
            "bridge-a-sos_maintenance",
            "manual",
            "Maintenance",
            "worker.scripts.sos_maintenance",
            "",
            "",
            1000,
            True,
        ),
        "bridge-a-inventory": WorkerScript(
            "bridge-a-inventory", "manual", "Inventory", "tests.sos_maintenance_registry_inventory_child", "", "", 1000, True
        ),
        "bridge-a-doors": WorkerScript("bridge-a-doors", "manual", "Doors", "tests.sos_maintenance_registry_door_child", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Projector", "type": "Projector", "functional": True, "enabled": True, "is_projecting": True},
                    {"name": "Welder", "type": "ShipWelder", "functional": True, "enabled": True},
                    {"name": "Grinder", "type": "ShipGrinder", "functional": True, "enabled": True},
                    {"name": "Damaged Armor", "type": "ArmorBlock", "functional": False, "integrity_ratio": 0.4},
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert [child["script_id"] for child in result["result"]["child_results"]] == [
        "bridge-a-sos_status",
        "bridge-a-sos_maintenance",
        "bridge-a-inventory",
        "bridge-a-doors",
    ]
    maintenance_child = result["result"]["child_results"][1]
    assert maintenance_child["summary"] == (
        "SOS Maintenance Ship A state=unknown damaged=1 critical=0 missing_critical=0 projectors=1/1 welders=1/1 materials=unknown blockers=0"
    )
    assert maintenance_child["error_bucket"] == "none"
    assert maintenance_child["result"]["sos_maintenance"]["snapshot_status"] == "partial"
    assert {command["kind"] for command in result["result"]["commands"]} <= {"echo", "write_text_surface"}


def test_execute_sos_orchestrator_passes_scoped_maintenance_data_to_maintenance_child_only(tmp_path: Path):
    captured: dict[str, dict] = {}
    module = types.ModuleType("tests.sos_maintenance_capture_children")

    def run(request):
        captured[request["script_id"]] = request
        return {"summary": f"{request['script_id']} captured", "commands": [{"kind": "echo", "text": request["script_id"]}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
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
                        "services": [
                            {"script_id": "bridge-a-sos_maintenance", "service_id": "maintenance"},
                            {"script_id": "bridge-a-inventory", "service_id": "inventory"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_maintenance": WorkerScript("bridge-a-sos_maintenance", "manual", "Maintenance", module.__name__, "", "", 1000, True),
        "bridge-a-inventory": WorkerScript("bridge-a-inventory", "manual", "Inventory", module.__name__, "", "", 1000, True),
    }
    grid_snapshot = {
        "schema": "novali.client_side_pb.grid_snapshot.v1",
        "grid_entity_id": 10,
        "blocks": [
            {"name": "Welder", "type": "ShipWelder", "integrity_ratio": 0.8, "functional": True},
            {"name": "Projector", "type": "Projector", "integrity_ratio": 0.95, "functional": True},
            {"name": "LCD", "type": "TextPanel"},
        ],
    }
    maintenance_snapshot = {"projectors": [{"name": "Projector", "active": True, "missing_blocks": 4}]}
    logistics_snapshot = {
        "cargo": {"used_volume": 40.0, "max_volume": 100.0},
        "production": {"blockers": ["missing_material:SteelPlate"]},
    }
    production_snapshot = {"missing_materials": ["SteelPlate"], "queue": {"blocked_count": 1}}

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": grid_snapshot,
            "maintenance_snapshot": maintenance_snapshot,
            "repair_snapshot": {"damaged_blocks": [{"name": "Armor", "integrity_ratio": 0.5}]},
            "damage_control_snapshot": {"critical_systems": [{"name": "Reactor", "present": True}]},
            "projector_snapshot": {"projectors": [{"name": "Projector", "active": True}]},
            "logistics_snapshot": logistics_snapshot,
            "production_snapshot": production_snapshot,
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured["bridge-a-sos_maintenance"]["grid_snapshot"] == grid_snapshot
    assert captured["bridge-a-sos_maintenance"]["maintenance_snapshot"] == maintenance_snapshot
    assert captured["bridge-a-sos_maintenance"]["inventory_snapshot"] == logistics_snapshot
    assert captured["bridge-a-sos_maintenance"]["logistics_snapshot"] == logistics_snapshot
    assert captured["bridge-a-sos_maintenance"]["production_snapshot"] == production_snapshot
    assert captured["bridge-a-sos_maintenance"]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Welder", "type": "ShipWelder", "integrity_ratio": 0.8, "functional": True},
            {"name": "Projector", "type": "Projector", "integrity_ratio": 0.95, "functional": True},
        ],
        "critical_systems": [],
    }
    for key in ("maintenance_snapshot", "repair_snapshot", "damage_control_snapshot", "projector_snapshot"):
        assert key not in captured["bridge-a-inventory"]
    assert "integrity_snapshot" not in captured["bridge-a-inventory"]


def test_execute_sos_maintenance_child_degrades_gracefully_without_snapshot(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "display_name": "Ship A",
                        "services": [{"script_id": "bridge-a-sos_maintenance", "service_id": "maintenance"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_maintenance": WorkerScript(
            "bridge-a-sos_maintenance",
            "manual",
            "Maintenance",
            "worker.scripts.sos_maintenance",
            "",
            "",
            1000,
            True,
        ),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    maintenance_child = result["result"]["child_results"][0]
    assert maintenance_child["summary"] == "SOS Maintenance Ship A state=unknown snapshot=no_snapshot"
    assert maintenance_child["result"]["sos_maintenance"]["snapshot_status"] == "no_snapshot"
    assert result["result"]["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Maintenance Ship A state=unknown snapshot=no_snapshot",
            "source_script_id": "bridge-a-sos_maintenance",
            "source_priority": 16,
            "source_order": 0,
            "source_role": "status",
        }
    ]


def test_execute_sos_orchestrator_passes_logistics_snapshot_from_inventory_data_to_child_request(tmp_path: Path):
    captured: list[dict] = []
    module = types.ModuleType("tests.sos_logistics_capture_child")

    def run(request):
        captured.append(request)
        return {"summary": "logistics captured", "commands": [{"kind": "echo", "text": "logistics"}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [{"script_id": "bridge-a-sos_logistics", "service_id": "logistics"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_logistics": WorkerScript("bridge-a-sos_logistics", "manual", "Logistics", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "inventory_snapshot": {
                "schema": "novali.client_side_pb.inventory_snapshot.v1",
                "source": "plugin",
                "blocks": [
                    {
                        "name": "Cargo",
                        "type": "CargoContainer",
                        "inventories": [
                            {
                                "index": 0,
                                "current_volume": 90,
                                "max_volume": 100,
                                "items": [
                                    {
                                        "type_id": "MyObjectBuilder_AmmoMagazine",
                                        "subtype_id": "NATO_25x184mm",
                                        "amount": 20,
                                    },
                                    {"type_id": "MyObjectBuilder_Ingot", "subtype_id": "Uranium", "amount": 5},
                                    {"type_id": "MyObjectBuilder_Ore", "subtype_id": "Ice", "amount": 100},
                                ],
                            }
                        ],
                    }
                ],
            },
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {
                        "name": "Assembler",
                        "type": "Assembler",
                        "production_queue": [{"item": "Steel Plate", "remaining": 12}],
                    }
                ],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured[0]["inventory_snapshot"] == {
        "cargo": {"used_volume": 90.0, "max_volume": 100.0},
        "ammo": [{"name": "NATO_25x184mm", "current": 20.0, "minimum": None}],
        "fuel": {
            "ice": {"current": 100.0, "minimum": None},
            "uranium": {"current": 5.0, "minimum": None},
        },
        "production": {"queue": [{"item": "Steel Plate", "remaining": 12}], "blockers": []},
    }


def test_execute_sos_orchestrator_omits_logistics_snapshot_when_inventory_data_missing(tmp_path: Path):
    captured: list[dict] = []
    module = types.ModuleType("tests.sos_logistics_no_snapshot_child")

    def run(request):
        captured.append(request)
        return {"summary": "logistics no snapshot", "commands": [{"kind": "echo", "text": "logistics"}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [{"script_id": "bridge-a-sos_logistics", "service_id": "logistics"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_logistics": WorkerScript("bridge-a-sos_logistics", "manual", "Logistics", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "inventory_snapshot": {"schema": "novali.client_side_pb.inventory_snapshot.v1", "source": "plugin", "blocks": []},
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 10, "blocks": []},
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert "inventory_snapshot" not in captured[0]
    assert "ship_inventory" not in captured[0]
    assert "logistics_snapshot" not in captured[0]


def test_execute_sos_orchestrator_passes_integrity_snapshot_from_grid_snapshot_to_child_request(tmp_path: Path):
    captured: list[dict] = []
    module = types.ModuleType("tests.sos_integrity_capture_child")

    def run(request):
        captured.append(request)
        return {"summary": "integrity captured", "commands": [{"kind": "echo", "text": "integrity"}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [{"script_id": "bridge-a-sos_integrity", "service_id": "integrity"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_integrity": WorkerScript("bridge-a-sos_integrity", "manual", "Integrity", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [
                    {"name": "Main Reactor", "type": "Reactor", "integrity_ratio": 0.42, "functional": False},
                    {"name": "Cargo", "type": "CargoContainer", "integrity": 80, "max_integrity": 100, "functional": True},
                ],
                "critical_systems": [{"name": "Jump Drive", "type": "JumpDrive", "present": False}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert captured[0]["integrity_snapshot"] == {
        "blocks": [
            {"name": "Main Reactor", "type": "Reactor", "integrity_ratio": 0.42, "functional": False},
            {"name": "Cargo", "type": "CargoContainer", "integrity": 80, "max_integrity": 100, "functional": True},
        ],
        "critical_systems": [{"name": "Jump Drive", "type": "JumpDrive", "present": False}],
    }


def test_execute_sos_orchestrator_omits_integrity_snapshot_when_grid_snapshot_has_no_integrity_data(tmp_path: Path):
    captured: list[dict] = []
    module = types.ModuleType("tests.sos_integrity_no_snapshot_child")

    def run(request):
        captured.append(request)
        return {"summary": "integrity no snapshot", "commands": [{"kind": "echo", "text": "integrity"}]}

    module.run = run
    sys.modules[module.__name__] = module
    data = tmp_path / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": "ship-a",
                        "bridge_id": "bridge-a",
                        "expected_grid_entity_id": 10,
                        "services": [{"script_id": "bridge-a-sos_integrity", "service_id": "integrity"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator", "script_instance", "Bridge A SOS", "", "", "", 1000, True, base_script_id="bridge_orchestrator"
        ),
        "bridge-a-sos_integrity": WorkerScript("bridge-a-sos_integrity", "manual", "Integrity", module.__name__, "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {
                "schema": "novali.client_side_pb.grid_snapshot.v1",
                "grid_entity_id": 10,
                "blocks": [{"name": "LCD", "type": "TextPanel"}],
            },
            "state": {},
        },
        scripts,
        {},
        tmp_path,
    )

    assert result["status"] == "ok"
    assert "integrity_snapshot" not in captured[0]
    assert "ship_integrity" not in captured[0]
    assert "damage_snapshot" not in captured[0]


def test_execute_sample_adapter():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "sample_status_adapter",
            "state": {"block_count": 2, "inventory_count": 3},
        },
        scripts,
    )
    assert result["status"] == "ok"
    assert result["message_kind"] == "result"
    assert result["result"]["summary"] == "blocks=2;inventory=3"


def test_execute_rejects_bad_sequence():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 0,
            "script_id": "sample_status_adapter",
        },
        scripts,
    )
    assert result["status"] == "rejected"
    assert result["error_bucket"] == "sequence_invalid"


def test_worker_status_page_renders_container_ui_link_target(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "worker_status.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_status.v1",
                "updated_at": "2026-08-07T16:00:00+00:00",
                "processed": 3,
                "limiter_states": {"pb-bridge-001": "ok"},
            }
        ),
        encoding="utf-8",
    )
    (data / "virtual_pb_compatibility.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.virtual_pb_compatibility.v1",
                "scripts": {
                    "virtual_whip_auto_door": {
                        "status": "supported",
                        "emitted_command_kinds": ["set_door_open"],
                    },
                    "workshop_blocked_template": {
                        "status": "blocked_command_mapping",
                        "blocked_command_mappings": ["Dangerous.Property"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (data / "bridge_scripts.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridge_scripts.v1",
                "bridges": {
                    "pb-bridge-001": {
                        "selected_script_id": "pb-bridge-001-orchestrator",
                        "allowed_worker_scripts": ["pb-bridge-001-orchestrator", "pb-bridge-001-virtual_whip_auto_door"],
                        "child_worker_scripts": [
                            {"script_id": "pb-bridge-001-virtual_whip_auto_door", "enabled": True, "budget": 1, "priority": 10}
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    results = data / "bridge_results"
    results.mkdir()
    (results / "pb-bridge-001.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "result": {
                    "child_results": [
                        {
                            "script_id": "pb-bridge-001-virtual_whip_auto_door",
                            "status": "rejected",
                            "error_bucket": "virtual_pb_unsupported_api",
                            "summary": "Virtual PB script rejected by compatibility analysis.",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    html = render_status_page(tmp_path)

    assert "NOVALI Client-Side PB Gateway" in html
    assert "Processed requests" in html
    assert "pb-bridge-001" in html
    assert "virtual_whip_auto_door" in html
    assert "Open Configuration UI" in html
    assert "novali-client-side-pb-manager://open" in html
    assert "Launch Diagnostics" in html
    assert "/manager-launch.log" in html
    assert "Active Bridge Scripts" in html
    assert "pb-bridge-001-orchestrator" in html
    assert "pb-bridge-001-virtual_whip_auto_door" in html
    assert "rejected: virtual_pb_unsupported_api" in html
    assert "Virtual PB Compatibility Inventory" in html
    assert "Import compatibility reports are not active bridge failures unless the script is assigned above." in html


def test_docker_compose_publishes_worker_ui_port():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "8788:8788" in compose
    assert "NOVALI_CLIENT_SIDE_PB_UI_PORT" in compose


def test_worker_status_server_exposes_manager_launch_log_source():
    source = Path("worker/worker.py").read_text(encoding="utf-8")

    assert 'self.path == "/manager-launch.log"' in source
    assert 'manager_launch.log' in source
    assert "text/plain; charset=utf-8" in source


def test_update_bridge_health_marks_stale_bridge_as_concealed_suspected(tmp_path: Path):
    data = tmp_path / "data"
    processed = data / "bridge_requests" / "processed"
    results = data / "bridge_results"
    processed.mkdir(parents=True)
    results.mkdir(parents=True)
    (data / "bridges.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridges.v1",
                "bridges": {"bridge-a": {"bridge_id": "bridge-a", "display_name": "Bridge A"}},
            }
        ),
        encoding="utf-8",
    )
    request_path = processed / "bridge-a-1000.json"
    result_path = results / "bridge-a.json"
    request_path.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 4}), encoding="utf-8")
    result_path.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 4, "status": "ok"}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(request_path, (old, old))
    os.utime(result_path, (old, old))

    payload = update_bridge_health(tmp_path, stale_seconds=60)

    assert payload["bridges"]["bridge-a"]["status"] == "concealed_suspected"
    assert payload["bridges"]["bridge-a"]["queue_policy"] == "hold_until_fresh_heartbeat"


def test_update_bridge_health_marks_recovered_after_fresh_heartbeat(tmp_path: Path):
    data = tmp_path / "data"
    requests = data / "bridge_requests"
    results = data / "bridge_results"
    requests.mkdir(parents=True)
    results.mkdir(parents=True)
    (data / "bridges.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridges.v1",
                "bridges": {"bridge-a": {"bridge_id": "bridge-a", "display_name": "Bridge A"}},
            }
        ),
        encoding="utf-8",
    )
    (data / "bridge_health.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridge_health.v1",
                "bridges": {"bridge-a": {"status": "concealed_suspected"}},
            }
        ),
        encoding="utf-8",
    )
    (requests / "bridge-a.json").write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 5}), encoding="utf-8")
    (results / "bridge-a.json").write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 5, "status": "ok"}), encoding="utf-8")

    payload = update_bridge_health(tmp_path, stale_seconds=60)

    assert payload["bridges"]["bridge-a"]["status"] == "recovered"
    assert payload["bridges"]["bridge-a"]["queue_policy"] == "drain"


def test_latest_request_path_prefers_active_request_over_archived_history(tmp_path: Path):
    requests = tmp_path / "data" / "bridge_requests"
    processed = requests / "processed"
    processed.mkdir(parents=True)
    active = requests / "bridge-a.json"
    archived = processed / "bridge-a-9999999999999.json"
    active.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 2}), encoding="utf-8")
    archived.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    newer = time.time() + 60
    os.utime(archived, (newer, newer))

    assert latest_request_path(tmp_path, "bridge-a") == active


def test_latest_request_path_uses_archive_suffix_without_mtime_order(tmp_path: Path):
    processed = tmp_path / "data" / "bridge_requests" / "processed"
    processed.mkdir(parents=True)
    older_name = processed / "bridge-a-1000.json"
    latest_name = processed / "bridge-a-2000.json"
    older_name.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    latest_name.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 2}), encoding="utf-8")
    newer_mtime = time.time() + 60
    os.utime(older_name, (newer_mtime, newer_mtime))

    assert latest_request_path(tmp_path, "bridge-a") == latest_name


def test_cleanup_processed_requests_removes_files_older_than_retention(tmp_path: Path):
    processed = tmp_path / "data" / "bridge_requests" / "processed"
    processed.mkdir(parents=True)
    expired = processed / "bridge-a-1000.json"
    fresh = processed / "bridge-a-2000.json"
    non_json = processed / "notes.txt"
    expired.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    fresh.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 2}), encoding="utf-8")
    non_json.write_text("keep", encoding="utf-8")
    os.utime(expired, (1000, 1000))
    os.utime(fresh, (1190, 1190))

    stats = cleanup_processed_requests(tmp_path, retention_seconds=120, now=1200)

    assert stats["retention_seconds"] == 120
    assert stats["scanned"] == 2
    assert stats["removed"] == 1
    assert stats["failed"] == 0
    assert not expired.exists()
    assert fresh.exists()
    assert non_json.exists()


def test_cleanup_processed_requests_limits_deletions_per_pass(tmp_path: Path):
    processed = tmp_path / "data" / "bridge_requests" / "processed"
    processed.mkdir(parents=True)
    for index in range(5):
        path = processed / f"bridge-a-{index}.json"
        path.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": index}), encoding="utf-8")
        os.utime(path, (1000, 1000))

    stats = cleanup_processed_requests(tmp_path, retention_seconds=120, now=1200, max_files_per_pass=2)

    assert stats["removed"] == 2
    assert stats["limit_reached"] == 1
    assert (len(list(processed.glob("*.json")))) == 3


def test_process_pending_reports_processed_request_cleanup(tmp_path: Path):
    data = tmp_path / "data"
    requests = data / "bridge_requests"
    processed = requests / "processed"
    results = data / "bridge_results"
    requests.mkdir(parents=True)
    processed.mkdir(parents=True)
    results.mkdir(parents=True)
    expired = processed / "bridge-a-1000.json"
    expired.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    os.utime(expired, (1000, 1000))

    process_pending(tmp_path, {})

    status = json.loads((data / "worker_status.json").read_text(encoding="utf-8"))
    cleanup = status["processed_request_cleanup"]
    assert cleanup["retention_seconds"] == 300
    assert cleanup["removed"] == 1
    assert not expired.exists()


def test_execute_request_holds_stale_snapshot_without_running_adapter():
    scripts = load_manifest(Path("."))
    stale = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 9,
            "script_id": "sample_status_adapter",
            "state": {"requested_at_utc": "2000-01-01T00:00:00Z", "block_count": 99, "inventory_count": 99},
        },
        scripts,
    )

    assert stale["status"] == "stale_held"
    assert stale["error_bucket"] == "stale_request_held"
    assert stale["result"]["commands"] == []
    assert stale["result"]["bridge_health"]["status"] == "concealed_suspected"


def test_execute_rejects_script_not_allowed_for_bridge():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "sample_status_adapter",
        },
        scripts,
        {"bridge-a": BridgeScriptConfig("workshop_1216126863_adapter", ("workshop_1216126863_adapter",))},
    )
    assert result["status"] == "rejected"
    assert result["error_bucket"] == "script_not_allowed_for_bridge"


def test_bridge_script_config_parses_orchestrator_children(tmp_path: Path):
    from worker.worker import load_bridge_script_configs

    root = tmp_path
    data = root / "data"
    data.mkdir()
    (data / "bridge_scripts.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridge_scripts.v1",
                "bridges": {
                    "bridge-orch": {
                        "selected_script_id": "bridge_orchestrator",
                        "allowed_worker_scripts": ["bridge_orchestrator", "sample_status_adapter"],
                        "child_worker_scripts": [
                            {
                                "script_id": "sample_status_adapter",
                                "enabled": True,
                                "budget": 2,
                                "priority": 5,
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    configs = load_bridge_script_configs(root)

    assert configs["bridge-orch"].selected_script_id == "bridge_orchestrator"
    assert configs["bridge-orch"].child_worker_scripts[0]["script_id"] == "sample_status_adapter"
    assert configs["bridge-orch"].child_worker_scripts[0]["budget"] == 2


def test_load_manifest_exposes_script_instance_aliases(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "status-base-grid": {
                        "instance_id": "status-base-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Base Grid",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                        "config_id": "status-base-grid",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)

    assert scripts["status-base-grid"].script_id == "status-base-grid"
    assert scripts["status-base-grid"].base_script_id == "sample_status_adapter"
    assert scripts["status-base-grid"].module == scripts["sample_status_adapter"].module
    assert scripts["status-base-grid"].instance_bridge_id == "bridge-a"


def test_execute_instance_alias_preserves_instance_id_for_result_and_config(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "status-base-grid": {
                        "instance_id": "status-base-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Base Grid",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                        "config_id": "status-base-grid",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config_dir = data / "worker_configs"
    config_dir.mkdir()
    (config_dir / "status-base-grid.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "status-base-grid",
                "entries": [{"key": "instance_marker", "value": "base-grid"}],
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 2,
            "script_id": "status-base-grid",
            "state": {"block_count": 1, "inventory_count": 0},
        },
        scripts,
        {"bridge-a": BridgeScriptConfig("status-base-grid", ("status-base-grid",))},
        root,
    )

    assert result["status"] == "ok"
    assert result["script_id"] == "status-base-grid"
    assert result["result"]["summary"] == "blocks=1;inventory=0"


def test_worker_instance_inherits_base_worker_config_when_instance_config_missing(tmp_path: Path):
    config_dir = tmp_path / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "workshop_1216126863_adapter.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "workshop_1216126863_adapter",
                "entries": [
                    {"key": "maxApplyCommands", "value": 8},
                    {"key": "maxPlannedMachineCommands", "value": 12},
                ],
            }
        ),
        encoding="utf-8",
    )
    script = WorkerScript(
        "pb-bridge-001-workshop_1216126863_adapter",
        "script_instance",
        "Isy Base Grid",
        "worker.scripts.workshop_1216126863_adapter",
        "adapter_tick.v1",
        "compact_commands.v1",
        1000,
        True,
        base_script_id="workshop_1216126863_adapter",
        config_id="pb-bridge-001-workshop_1216126863_adapter",
    )

    config = load_effective_worker_config(tmp_path, script)

    assert config["maxApplyCommands"] == 8
    assert config["maxPlannedMachineCommands"] == 12


def test_execute_instance_alias_rejects_wrong_bridge_or_disabled(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "status-base-grid": {
                        "instance_id": "status-base-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Base Grid",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                    "status-disabled-grid": {
                        "instance_id": "status-disabled-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Disabled Grid",
                        "bridge_id": "bridge-a",
                        "enabled": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)
    wrong_bridge = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-b",
            "sequence": 1,
            "script_id": "status-base-grid",
        },
        scripts,
        {"bridge-b": BridgeScriptConfig("status-base-grid", ("status-base-grid",))},
        root,
    )
    disabled = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "status-disabled-grid",
        },
        scripts,
        {"bridge-a": BridgeScriptConfig("status-disabled-grid", ("status-disabled-grid",))},
        root,
    )

    assert wrong_bridge["status"] == "rejected"
    assert wrong_bridge["error_bucket"] == "script_instance_bridge_mismatch"
    assert disabled["status"] == "rejected"
    assert disabled["error_bucket"] == "script_disabled"


def test_bridge_orchestrator_merges_child_commands_with_source_metadata():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-orch",
            "sequence": 3,
            "script_id": "bridge_orchestrator",
            "state": {"block_count": 2, "inventory_count": 1},
        },
        scripts,
        {
            "bridge-orch": BridgeScriptConfig(
                "bridge_orchestrator",
                ("bridge_orchestrator", "sample_status_adapter"),
                (
                    {
                        "script_id": "sample_status_adapter",
                        "enabled": True,
                        "budget": 2,
                        "priority": 10,
                    },
                ),
            )
        },
    )

    assert result["status"] == "ok"
    assert result["result"]["orchestrator"]["status"] == "processed"
    assert result["result"]["child_results"][0]["script_id"] == "sample_status_adapter"
    assert result["result"]["commands"][0]["source_script_id"] == "sample_status_adapter"


def test_bridge_orchestrator_instance_runs_child_instances(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "bridge-a-orchestrator": {
                        "instance_id": "bridge-a-orchestrator",
                        "base_script_id": "bridge_orchestrator",
                        "display_name": "Bridge A Orchestrator",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                    "bridge-a-status": {
                        "instance_id": "bridge-a-status",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Bridge A Status",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "state": {"block_count": 2, "inventory_count": 1},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-status"),
                (
                    {
                        "script_id": "bridge-a-status",
                        "enabled": True,
                        "budget": 2,
                        "priority": 10,
                    },
                ),
            )
        },
        root,
    )

    assert result["status"] == "ok"
    assert result["script_id"] == "bridge-a-orchestrator"
    assert result["result"]["orchestrator"]["status"] == "processed"
    assert result["result"]["child_results"][0]["script_id"] == "bridge-a-status"
    assert result["result"]["commands"][0]["source_script_id"] == "bridge-a-status"


def test_virtual_pb_request_receives_custom_data_from_worker_config(tmp_path: Path, monkeypatch):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "virtual_fixture",
                        "source": "workshop_import",
                        "display_name": "Virtual Fixture",
                        "runtime": "virtual_pb_csharp",
                        "source_path": "data/imports/fixture/Script.cs",
                        "timeout_ms": 5000,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_dir = root / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "virtual_fixture.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "virtual_fixture",
                "entries": [
                    {
                        "key": "virtualPbCustomData",
                        "value": "station_mode;\nitemID;blueprintID\nMyObjectBuilder_Component/SteelPlate;MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0SteelPlate",
                        "value_type": "multiline_text",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    script_path = root / "data" / "imports" / "fixture" / "Script.cs"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("public Program() {} public void Main(string argument) {}", encoding="utf-8")

    def fake_run_virtual_pb(script_path: Path, request: dict, root: Path | None = None) -> dict:
        assert request["virtual_pb"]["custom_data"].startswith("station_mode;")
        assert request["virtual_pb"]["custom_data_source"] == "worker_config.virtualPbCustomData"
        return {"summary": "ok", "commands": []}

    monkeypatch.setattr("worker.virtual_pb.run_virtual_pb", fake_run_virtual_pb)

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "virtual_fixture",
            "grid_snapshot": {"blocks": []},
        },
        scripts,
        {},
        root,
    )

    assert result["status"] == "ok"


def test_bridge_orchestrator_reports_total_and_per_child_queue_counts(tmp_path: Path):
    def install_adapter(module_name: str, block_id: int) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": "planned one command",
                "commands": [
                    {
                        "kind": "set_block_enabled",
                        "block_entity_id": block_id,
                        "enabled": True,
                    }
                ],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.queue_child_a", 101)
    install_adapter("tests.queue_child_b", 202)

    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A Orchestrator",
            "",
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-child-a": WorkerScript("bridge-a-child-a", "manual", "Child A", "tests.queue_child_a", "", "", 1000, True),
        "bridge-a-child-b": WorkerScript("bridge-a-child-b", "manual", "Child B", "tests.queue_child_b", "", "", 1000, True),
    }
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 7,
            "script_id": "bridge-a-orchestrator",
            "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
            "state": {},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-child-a", "bridge-a-child-b"),
                (
                    {"script_id": "bridge-a-child-a", "enabled": True, "budget": 1, "priority": 10},
                    {"script_id": "bridge-a-child-b", "enabled": True, "budget": 1, "priority": 20},
                ),
            )
        },
        tmp_path,
    )

    assert result["status"] == "ok"
    assert result["result"]["command_queue"]["queued"] == 2
    assert result["result"]["command_queue"]["remaining"] == 1
    assert result["result"]["command_queue"]["by_source"]["bridge-a-child-a"] == {"queued": 1, "drained": 1, "remaining": 0}
    assert result["result"]["command_queue"]["by_source"]["bridge-a-child-b"] == {"queued": 1, "drained": 0, "remaining": 1}
    assert result["result"]["child_results"][0]["command_queue"] == {"queued": 1, "drained": 1, "remaining": 0}
    assert result["result"]["child_results"][1]["command_queue"] == {"queued": 1, "drained": 0, "remaining": 1}


def test_bridge_orchestrator_reports_scheduler_queue_pressure_and_operator_status(tmp_path: Path):
    def install_adapter(module_name: str, kind: str, block_id: int) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": "planned one command",
                "commands": [
                    {
                        "kind": kind,
                        "block_entity_id": block_id,
                        "open": True,
                    }
                ],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.scheduler_child_a", "set_door_open", 101)
    install_adapter("tests.scheduler_child_b", "set_door_open", 202)
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A Orchestrator",
            "",
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-door": WorkerScript("bridge-a-door", "manual", "Door", "tests.scheduler_child_a", "", "", 1000, True),
        "bridge-a-lcd": WorkerScript("bridge-a-lcd", "manual", "LCD", "tests.scheduler_child_b", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 7,
            "script_id": "bridge-a-orchestrator",
            "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
            "state": {},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-door", "bridge-a-lcd"),
                (
                    {
                        "script_id": "bridge-a-door",
                        "enabled": True,
                        "budget": 1,
                        "priority": 5,
                        "role": "reactive",
                        "reactive": True,
                        "expires_after_sequences": 1,
                        "fairness_weight": 3,
                        "operator_status": "ready_virtual_pb",
                    },
                    {
                        "script_id": "bridge-a-lcd",
                        "enabled": True,
                        "budget": 1,
                        "priority": 30,
                        "role": "display",
                        "fairness_weight": 1,
                        "operator_status": "ready_virtual_pb",
                    },
                ),
            )
        },
        tmp_path,
    )

    output = result["result"]
    assert output["scheduler"]["policy"] == "priority_fairness_v1"
    assert output["scheduler"]["fairness"][0]["fairness_weight"] == 3
    assert output["queue_pressure"]["remaining"] == 1
    assert output["child_results"][0]["operator_status"] == "ready_virtual_pb"
    assert output["commands"][0]["expires_after_sequences"] == 1
    assert output["commands"][0]["source_role"] == "reactive"


def test_bridge_orchestrator_reports_same_target_conflicts_and_keeps_highest_priority_command(tmp_path: Path):
    def install_adapter(module_name: str, open_value: bool) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": "planned conflicting door command",
                "commands": [
                    {
                        "kind": "set_door_open",
                        "block_entity_id": 777,
                        "open": open_value,
                    }
                ],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.conflict_child_fast", False)
    install_adapter("tests.conflict_child_slow", True)
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A Orchestrator",
            "",
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-fast": WorkerScript("bridge-a-fast", "manual", "Fast", "tests.conflict_child_fast", "", "", 1000, True),
        "bridge-a-slow": WorkerScript("bridge-a-slow", "manual", "Slow", "tests.conflict_child_slow", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 8,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-fast", "bridge-a-slow"),
                (
                    {"script_id": "bridge-a-fast", "enabled": True, "budget": 1, "priority": 5},
                    {"script_id": "bridge-a-slow", "enabled": True, "budget": 1, "priority": 50},
                ),
            )
        },
        tmp_path,
    )

    output = result["result"]
    assert len(output["commands"]) == 1
    assert output["commands"][0]["source_script_id"] == "bridge-a-fast"
    assert output["commands"][0]["open"] is False
    assert output["conflicts"][0]["target"] == "set_door_open:777"
    assert output["conflicts"][0]["kept_source_script_id"] == "bridge-a-fast"
    assert output["conflicts"][0]["suppressed_source_script_ids"] == ["bridge-a-slow"]


def test_bridge_orchestrator_persists_child_virtual_pb_compatibility(tmp_path: Path, monkeypatch):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "bridge_orchestrator",
                        "source": "local_worker",
                        "display_name": "Bridge Orchestrator",
                        "module": "worker.scripts.bridge_orchestrator",
                        "runtime": "python",
                        "timeout_ms": 3000,
                        "enabled": True,
                    },
                    {
                        "script_id": "virtual_fixture",
                        "source": "workshop_import",
                        "display_name": "Virtual Fixture",
                        "module": "",
                        "runtime": "virtual_pb_csharp",
                        "source_path": "data/imports/fixture/Script.cs",
                        "timeout_ms": 5000,
                        "enabled": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    script_path = root / "data" / "imports" / "fixture" / "Script.cs"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("public Program() {} public void Main(string argument) {}", encoding="utf-8")
    (root / "data" / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "bridge-a-orchestrator": {
                        "instance_id": "bridge-a-orchestrator",
                        "base_script_id": "bridge_orchestrator",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                    "bridge-a-virtual-fixture": {
                        "instance_id": "bridge-a-virtual-fixture",
                        "base_script_id": "virtual_fixture",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_virtual_pb(script_path: Path, request: dict, root: Path | None = None) -> dict:
        assert root == tmp_path
        return {
            "adapter_status": "rejected",
            "summary": "Virtual PB script rejected by compatibility analysis.",
            "commands": [{"kind": "echo", "text": "blocked"}],
            "error_bucket": "virtual_pb_unsupported_api",
            "compatibility": {
                "status": "unsupported",
                "compiled": False,
                "missing_members": ["IMyLightingBlock.BlinkIntervalSeconds"],
                "blocked_command_mappings": [],
                "available_command_kinds": ["set_door_open"],
            },
        }

    monkeypatch.setattr("worker.virtual_pb.run_virtual_pb", fake_run_virtual_pb)

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"blocks": []},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-virtual-fixture"),
                ({"script_id": "bridge-a-virtual-fixture", "enabled": True, "budget": 1, "priority": 10},),
            )
        },
        root,
    )

    report = json.loads((root / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert result["result"]["child_results"][0]["status"] == "rejected"
    assert report["scripts"]["bridge-a-virtual-fixture"]["status"] == "unsupported"
    assert report["scripts"]["bridge-a-virtual-fixture"]["missing_members"] == ["IMyLightingBlock.BlinkIntervalSeconds"]


def test_process_pending_writes_result(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    (requests / "bridge-a.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-a",
                "sequence": 7,
                "script_id": "sample_status_adapter",
                "runtime_telemetry": {
                    "last_runtime_ms": 0.01,
                    "max_runtime_ms": 0.02,
                    "current_instruction_count": 10,
                    "max_instruction_count": 50000,
                    "limiter_state": "ok",
                },
                "state": {},
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result = json.loads((root / "data" / "bridge_results" / "bridge-a.json").read_text(encoding="utf-8"))
    assert result["sequence"] == 7
    assert result["message_kind"] == "result"
    assert result["status"] == "ok"
    assert result["runtime_telemetry"]["last_runtime_ms"] == 0.01
    assert result["limiter_state"] == "ok"


def test_process_pending_accepts_utf8_bom_request(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    payload = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-bom",
        "sequence": 1,
        "script_id": "sample_status_adapter",
        "state": {},
    }
    (requests / "bridge-bom.json").write_text(json.dumps(payload), encoding="utf-8-sig")
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result = json.loads((root / "data" / "bridge_results" / "bridge-bom.json").read_text(encoding="utf-8"))
    assert result["status"] == "ok"


def test_process_pending_writes_compact_result_for_pb_parser(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    (requests / "bridge-compact.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-compact",
                "sequence": 1,
                "script_id": "sample_status_adapter",
                "state": {},
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result_text = (root / "data" / "bridge_results" / "bridge-compact.json").read_text(encoding="utf-8")
    assert '"message_kind":"result"' in result_text


def test_command_queue_drain_uses_dynamic_pb_apply_budget():
    request = {
        "worker_config": {"commandQueueDrainPerResult": 1, "dynamicCommandQueueDrain": True},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 3},
    }
    adapter_output = {"max_apply_commands": 5}

    assert command_queue_drain_count(request, adapter_output) == 3


def test_command_queue_drain_clamps_dynamic_budget_to_result_budget():
    request = {
        "worker_config": {"commandQueueDrainPerResult": 1, "dynamicCommandQueueDrain": True},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 4},
    }
    adapter_output = {"max_apply_commands": 2}

    assert command_queue_drain_count(request, adapter_output) == 2


def test_command_queue_drain_can_keep_static_budget():
    request = {
        "worker_config": {"commandQueueDrainPerResult": 2, "dynamicCommandQueueDrain": False},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 4},
    }
    adapter_output = {"max_apply_commands": 5}

    assert command_queue_drain_count(request, adapter_output) == 2


def test_process_pending_injects_worker_config(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    config_dir = root / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "sample_status_adapter.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "sample_status_adapter",
                "display_name": "Sample Status Adapter",
                "entries": [{"key": "example", "value": "enabled", "value_type": "string", "description": ""}],
            }
        ),
        encoding="utf-8",
    )
    (requests / "bridge-config.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-config",
                "sequence": 1,
                "script_id": "sample_status_adapter",
                "state": {},
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    assert (root / "data" / "bridge_results" / "bridge-config.json").exists()


def test_process_pending_writes_compact_isy_foundation_commands(tmp_path: Path, monkeypatch):
    root = tmp_path
    module_root = tmp_path / "modules"
    module_root.mkdir()
    (module_root / "isy_fixture_adapter.py").write_text(
        "from worker.isy_foundation import plan_isy_foundation\n\n"
        "def run(request):\n"
        "    return plan_isy_foundation(request)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(module_root))
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "workshop_1216126863_adapter",
                        "source": "workshop_import",
                        "display_name": "Isy's Inventory Manager",
                        "module": "isy_fixture_adapter",
                        "input_schema": "adapter_tick.v1",
                        "output_schema": "compact_commands.v1",
                        "timeout_ms": 1000,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_dir = root / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "workshop_1216126863_adapter.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "workshop_1216126863_adapter",
                "entries": [
                    {"key": "maxApplyCommands", "value": 4},
                    {"key": "maxPlannedMachineCommands", "value": 4},
                    {"key": "mainLCDKeyword", "value": "Main LCD"},
                    {"key": "enableAutocrafting", "value": True},
                    {"key": "enableOreBalancing", "value": False},
                    {"key": "enableIceBalancing", "value": False},
                    {"key": "enableUraniumBalancing", "value": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    (requests / "bridge-isy.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-isy",
                "sequence": 3,
                "script_id": "workshop_1216126863_adapter",
                "request_kind": "adapter_tick",
                "state": {},
                "inventory_snapshot": {"source": "plugin", "blocks": []},
                "grid_snapshot": {
                    "source": "plugin",
                    "blocks": [
                        {"entity_id": 100, "name": "Main LCD", "same_construct": True, "is_lcd": True, "surface_count": 1},
                        {"entity_id": 200, "name": "Assembler", "same_construct": True, "is_assembler": True},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result_text = (root / "data" / "bridge_results" / "bridge-isy.json").read_text(encoding="utf-8")
    assert any(kind in result_text for kind in ['"write_text_surface"', '"set_assembler_mode"', '"set_assembler_cooperative_mode"'])
    assert '"command_queue"' in result_text
    assert "\n" not in result_text


def test_worker_persists_modded_autocrafting_blueprints_from_manual_queue(tmp_path: Path):
    request = {
        "bridge_id": "bridge-mod",
        "script_id": "workshop_1216126863_adapter",
        "grid_snapshot": {
            "blocks": [
                {
                    "name": "Assembler",
                    "same_construct": True,
                    "is_assembler": True,
                    "production_queue": [
                        {
                            "item_id": 7,
                            "blueprint_id": "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent",
                            "amount": 1,
                        }
                    ],
                }
            ]
        },
    }
    learned = learn_autocrafting_blueprints(tmp_path, request)
    assert learned["items"]["quantumcore"]["component_subtype"] == "QuantumCore"
    assert learned["items"]["quantumcore"]["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent"
    persisted = json.loads(
        (tmp_path / "data" / "autocrafting_blueprints" / "bridge-mod-workshop_1216126863_adapter.json").read_text(encoding="utf-8")
    )
    assert persisted["items"]["quantumcore"]["aliases"] == ["QuantumCore", "QuantumCoreComponent"]


def test_worker_command_queue_drains_commands_in_steady_stream(tmp_path: Path):
    root = tmp_path
    request = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-queue",
        "sequence": 10,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 5,
        "commands": [
            {"kind": "set_use_conveyor", "block_entity_id": 1, "enabled": True, "command_id": "old:1"},
            {"kind": "set_use_conveyor", "block_entity_id": 2, "enabled": False, "command_id": "old:2"},
            {"kind": "set_gas_auto_refill", "block_entity_id": 3, "enabled": True, "command_id": "old:3"},
        ],
    }

    first = apply_command_queue(root, request, output)
    assert len(first["commands"]) == 1
    assert first["commands"][0]["block_entity_id"] == 1
    assert first["remaining_commands"] == 2
    assert first["command_queue"]["queued"] == 3

    request["sequence"] = 11
    request["state"] = {"last_apply": {"sequence": 10, "status": "processed", "applied": 1, "skipped": 0}}
    second = apply_command_queue(
        root,
        request,
        {
            **output,
            "commands": [
                {"kind": "set_use_conveyor", "block_entity_id": 2, "enabled": False, "command_id": "old:2"},
                {"kind": "set_gas_auto_refill", "block_entity_id": 3, "enabled": True, "command_id": "old:3"},
            ],
        },
    )
    assert len(second["commands"]) == 1
    assert second["commands"][0]["block_entity_id"] == 2
    assert second["remaining_commands"] == 1


def test_worker_command_queue_keeps_echo_passthrough(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 1,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {"kind": "echo", "text": "hello"},
            {"kind": "set_block_enabled", "block_entity_id": 7, "enabled": True},
        ],
    }

    result = apply_command_queue(tmp_path, request, output)
    assert [command["kind"] for command in result["commands"]] == ["echo", "set_block_enabled"]


def test_worker_command_queue_prunes_transfers_into_managed_machines(tmp_path: Path):
    queue_dir = tmp_path / "data" / "command_queues"
    queue_dir.mkdir(parents=True)
    stale_key = (
        '{"destination_entity_id":99,"destination_inventory_index":1,'
        '"item_subtype_id":"MealPack_KelpCrisp","item_type_id":"MyObjectBuilder_ConsumableItem",'
        '"kind":"transfer_item","source_entity_id":1,"source_inventory_index":0}'
    )
    (queue_dir / "bridge-queue.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.command_queue.v1",
                "bridge_id": "bridge-queue",
                "script_id": "script-a",
                "entries": [
                    {
                        "key": stale_key,
                        "command": {
                            "kind": "transfer_item",
                            "source_entity_id": 1,
                            "source_inventory_index": 0,
                            "destination_entity_id": 99,
                            "destination_inventory_index": 1,
                            "item_type_id": "MyObjectBuilder_ConsumableItem",
                            "item_subtype_id": "MealPack_KelpCrisp",
                            "amount": 33,
                        },
                        "first_seen_sequence": 1,
                        "last_seen_sequence": 1,
                    }
                ],
                "in_flight": [{"key": stale_key, "command": {}}],
                "delivered": {},
            }
        ),
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-queue",
        "script_id": "script-a",
        "sequence": 2,
        "inventory_snapshot": {
            "blocks": [
                {
                    "entity_id": 99,
                    "type": "MyAssembler",
                    "subtype": "",
                    "inventories": [{"index": 0, "items": []}, {"index": 1, "items": []}],
                }
            ]
        },
    }

    result = apply_command_queue(tmp_path, request, {"apply_mode": "immediate", "max_apply_commands": 5, "commands": []})

    assert result["commands"] == []
    assert result["command_queue"]["queued"] == 0


def test_worker_command_queue_coalesces_transfer_amount_updates():
    first = {
        "kind": "transfer_item",
        "source_entity_id": 1,
        "source_inventory_index": 0,
        "destination_entity_id": 2,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_Ore",
        "item_subtype_id": "Ice",
        "amount": 10,
    }
    second = {**first, "amount": 20}

    assert command_queue_key(first) == command_queue_key(second)
    assert command_queue_key(first) == command_queue_key({**second, "reason": "gas_generator_topup"})


def test_worker_command_queue_coalesces_autocrafting_enqueue_amount_updates():
    first = {
        "kind": "enqueue_assembler_blueprint",
        "block_entity_id": 1,
        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/Display",
        "reason": "autocrafting_goal",
        "amount": 100,
    }
    second = {**first, "amount": 80}

    assert command_queue_key(first) == command_queue_key(second)


def test_worker_command_queue_prioritizes_reactive_orchestrator_source(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 10,
        "script_id": "bridge_orchestrator",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {
                "kind": "write_text_surface",
                "block_entity_id": 9,
                "surface_index": 0,
                "append": False,
                "text": "maintenance",
                "source_script_id": "workshop_1216126863_adapter",
                "source_priority": 50,
            },
            {
                "kind": "set_door_open",
                "block_entity_id": 100,
                "open": False,
                "source_script_id": "virtual_whip_auto_door",
                "source_priority": 5,
            },
        ],
    }

    result = apply_command_queue(tmp_path, request, output)

    assert result["commands"][0]["kind"] == "set_door_open"
    assert result["commands"][0]["source_script_id"] == "virtual_whip_auto_door"


def test_worker_command_queue_expires_stale_reactive_commands(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 1,
        "script_id": "bridge_orchestrator",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 0},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {
                "kind": "set_door_open",
                "block_entity_id": 100,
                "open": False,
                "source_script_id": "virtual_whip_auto_door",
                "expires_after_sequences": 1,
            }
        ],
    }
    first = apply_command_queue(tmp_path, request, output)
    assert first["queued_commands"] == 1

    request["sequence"] = 3
    second = apply_command_queue(tmp_path, request, {"apply_mode": "immediate", "max_apply_commands": 1, "commands": []})

    assert second["queued_commands"] == 0


def test_worker_command_queue_prioritizes_setup_then_allows_lcd_refresh(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 20,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1, "lcdCommandQueueCooldownSequences": 6},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {"kind": "transfer_item", "source_entity_id": 1, "source_inventory_index": 0, "destination_entity_id": 2, "destination_inventory_index": 0, "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Ice", "amount": 10},
            {"kind": "set_use_conveyor", "block_entity_id": 7, "enabled": False},
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "fresh"},
        ],
    }

    first = apply_command_queue(tmp_path, request, output)
    assert first["commands"][0]["kind"] == "set_use_conveyor"

    request["sequence"] = 21
    request["state"] = {"last_apply": {"sequence": 20, "status": "processed", "applied": 1, "skipped": 0}}
    second_output = dict(output)
    second_output["commands"] = [output["commands"][0], output["commands"][2]]
    second = apply_command_queue(tmp_path, request, second_output)
    assert second["commands"][0]["kind"] == "write_text_surface"


def test_worker_command_queue_default_lcd_cooldown_allows_next_sequence_refresh(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 50,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "first"},
        ],
    }

    first = apply_command_queue(tmp_path, request, output)
    assert first["commands"][0]["kind"] == "write_text_surface"

    request["sequence"] = 51
    request["state"] = {"last_apply": {"sequence": 50, "status": "processed", "applied": 1, "skipped": 0}}
    second = apply_command_queue(tmp_path, request, {**output, "commands": [{**output["commands"][0], "text": "second"}]})

    assert second["commands"][0]["kind"] == "write_text_surface"
    assert second["commands"][0]["text"] == "second"


def test_worker_command_queue_reserves_lcd_refresh_in_busy_mixed_batch(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 60,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {
            "commandQueueDrainPerResult": 5,
            "dynamicCommandQueueDrain": False,
            "lcdCommandQueueCooldownSequences": 1,
        },
    }
    transfers = [
        {
            "kind": "transfer_item",
            "source_entity_id": index,
            "source_inventory_index": 0,
            "destination_entity_id": 100 + index,
            "destination_inventory_index": 0,
            "item_type_id": "MyObjectBuilder_Ingot",
            "item_subtype_id": "Magnesium",
            "reason": "refinery_output_cleanup",
            "amount": 1,
        }
        for index in range(7)
    ]
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 8,
        "commands": [
            *transfers,
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "19:47:46: Moved item"},
        ],
    }

    result = apply_command_queue(tmp_path, request, output)
    kinds = [command["kind"] for command in result["commands"]]

    assert kinds.count("write_text_surface") == 1
    assert kinds.count("transfer_item") == 4


def test_worker_command_queue_ages_lcd_refreshes_to_prevent_starvation(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 30,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {
            "commandQueueDrainPerResult": 1,
            "lcdCommandQueueCooldownSequences": 0,
            "lcdCommandQueueMaxWaitSequences": 3,
        },
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {
                "kind": "transfer_item",
                "source_entity_id": 1,
                "source_inventory_index": 0,
                "destination_entity_id": 2,
                "destination_inventory_index": 0,
                "item_type_id": "MyObjectBuilder_Ore",
                "item_subtype_id": "Iron",
                "reason": "refinery_ore_rebalance",
                "amount": 10,
            },
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "refresh"},
        ],
    }

    first = apply_command_queue(tmp_path, request, output)
    assert first["commands"][0]["kind"] == "transfer_item"

    emitted = []
    for offset in range(1, 5):
        request["sequence"] = 30 + offset
        request["state"] = {"last_apply": {"sequence": 29 + offset, "status": "processed", "applied": 1, "skipped": 0}}
        result = apply_command_queue(tmp_path, request, output)
        emitted.append(result["commands"][0]["kind"])

    assert "write_text_surface" in emitted


def test_worker_command_queue_prioritizes_critical_transfers_before_bulk_ice():
    uranium = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Uranium"}
    magnesium = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Magnesium"}
    gas_ice = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Ice", "reason": "gas_generator_topup"}
    refinery_ore = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Silver", "reason": "refinery_ore_input"}
    ice = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Ice"}

    assert command_priority(uranium) == command_priority(gas_ice)
    assert command_priority(gas_ice) == command_priority(refinery_ore)
    assert command_priority(refinery_ore) < command_priority(magnesium) < command_priority(ice)


def test_worker_command_queue_prioritizes_autocrafting_goal_before_reactive_transfers():
    assembler_mode = {"kind": "set_assembler_mode", "block_entity_id": 7, "mode": "assembly"}
    refinery_output = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Cobalt", "reason": "refinery_output_cleanup"}
    material = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Nickel", "reason": "autocrafting_material"}
    autocrafting_lcd = {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "title": "Craft item manually once to show up here"}
    output_cleanup = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Component", "item_subtype_id": "Display", "reason": "assembler_output_cleanup"}
    enqueue = {"kind": "enqueue_assembler_blueprint", "blueprint_id": "MyObjectBuilder_BlueprintDefinition/MetalGrid", "reason": "autocrafting_goal"}
    inventory_sorting = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Cobalt", "reason": "inventory_sorting"}
    lcd = {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0}
    refinery_ore = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Nickel", "reason": "refinery_ore_input"}
    refinery_unload = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Iron", "reason": "refinery_input_unload"}
    refinery_rebalance = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Iron", "reason": "refinery_ore_rebalance"}
    shortage_ore = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Nickel", "reason": "autocrafting_ore_refining"}
    queue_consolidation = {"kind": "move_assembler_queue_item", "block_entity_id": 7, "queue_item_id": 12, "target_index": 1, "reason": "assembler_queue_consolidation"}
    input_cleanup = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Nickel", "reason": "assembler_input_cleanup"}

    assert command_priority(assembler_mode) < command_priority(refinery_rebalance) < command_priority(enqueue)
    assert command_priority(enqueue) < command_priority(material) < command_priority(input_cleanup) < command_priority(queue_consolidation)
    assert command_priority(queue_consolidation) < command_priority(shortage_ore) < command_priority(refinery_output)
    assert command_priority(refinery_output) < command_priority(output_cleanup) < command_priority(refinery_unload)
    assert command_priority(refinery_unload) < command_priority(inventory_sorting) < command_priority(refinery_ore)
    assert command_priority(refinery_ore) < command_priority(lcd)
    assert command_priority(lcd) == command_priority(autocrafting_lcd)
