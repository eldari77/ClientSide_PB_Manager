import json
from pathlib import Path

from worker.worker import (
    BridgeScriptConfig,
    apply_command_queue,
    command_priority,
    command_queue_drain_count,
    command_queue_key,
    execute_request,
    learn_autocrafting_blueprints,
    load_manifest,
    render_status_page,
    process_pending,
)


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
                    }
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


def test_docker_compose_publishes_worker_ui_port():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "8788:8788" in compose
    assert "NOVALI_CLIENT_SIDE_PB_UI_PORT" in compose


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


def test_process_pending_writes_compact_isy_foundation_commands(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
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


def test_worker_command_queue_prioritizes_lcd_then_allows_setup_after_lcd_cooldown(tmp_path: Path):
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
    assert first["commands"][0]["kind"] == "write_text_surface"

    request["sequence"] = 21
    request["state"] = {"last_apply": {"sequence": 20, "status": "processed", "applied": 1, "skipped": 0}}
    second = apply_command_queue(tmp_path, request, output)
    assert second["commands"][0]["kind"] == "set_use_conveyor"


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
    assert command_priority(queue_consolidation) < command_priority(shortage_ore) < command_priority(lcd)
    assert command_priority(lcd) == command_priority(autocrafting_lcd)
    assert command_priority(autocrafting_lcd) < command_priority(refinery_output) < command_priority(output_cleanup)
    assert command_priority(output_cleanup) < command_priority(refinery_unload) < command_priority(inventory_sorting)
    assert command_priority(inventory_sorting) < command_priority(refinery_ore)
