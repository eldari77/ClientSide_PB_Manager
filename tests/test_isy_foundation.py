from worker.isy_foundation import (
    parse_virtual_pb_custom_data_blueprints,
    plan_isy_foundation,
    render_main_lcd,
    rotate_commands,
    supports_custom_data_commands,
)


def test_isy_supports_neutral_baseline_shim_version():
    assert supports_custom_data_commands({"state": {"shim_version": "baseline-template-v1"}})
    assert supports_custom_data_commands({"state": {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}})


def inventory_block(entity_id=1, name="Cargo Components", items=None):
    return {
        "entity_id": entity_id,
        "name": name,
        "type": "MyCargoContainer",
        "subtype": "LargeBlockLargeContainer",
        "same_construct": True,
        "inventories": [
            {
                "index": 0,
                "current_volume": 0,
                "max_volume": 1000,
                "is_full": False,
                "items": items or [],
            }
        ],
    }


def grid_block(entity_id, name, **flags):
    block = {
        "entity_id": entity_id,
        "name": name,
        "type": flags.pop("type", "MyTerminalBlock"),
        "subtype": flags.pop("subtype", ""),
        "same_construct": flags.pop("same_construct", True),
        "enabled": flags.pop("enabled", True),
        "use_conveyor": flags.pop("use_conveyor", True),
        "inventories": flags.pop("inventories", []),
    }
    block.update(flags)
    return block


def grid_inventory_item(type_id, subtype_id, amount=1):
    return {"type_id": type_id, "subtype_id": subtype_id, "amount": amount}


def grid_inventory(items):
    return [{"index": 0, "items": items}]


def base_request(grid_blocks=None, config=None):
    return {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-a",
        "sequence": 11,
        "script_id": "workshop_1216126863_adapter",
        "request_kind": "adapter_tick",
        "worker_config": {
            "inventorySortingEnabled": True,
            "inventorySortingDryRun": False,
            "maxApplyCommands": 6,
            "maxPlannedTransfers": 2,
            "maxPlannedMachineCommands": 6,
            "mainLCDKeyword": "Main LCD",
            "inventoryLCDKeyword": "Inventory LCD",
            "warningsLCDKeyword": "Warnings LCD",
            "actionsLCDKeyword": "Actions LCD",
            "performanceLCDKeyword": "Performance LCD",
            **(config or {}),
        },
        "inventory_snapshot": {"source": "plugin", "blocks": [inventory_block()]},
        "grid_snapshot": {"source": "plugin", "blocks": grid_blocks or []},
    }


def test_lcd_planner_emits_write_text_surface_for_matching_panels():
    request = base_request(
        [
            grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
            grid_block(11, "Inventory LCD", is_lcd=True, surface_count=1),
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1),
        ],
        {
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    commands = [command for command in result["commands"] if command["kind"] == "write_text_surface"]
    assert {command["block_entity_id"] for command in commands} == {10, 11, 12}
    assert commands[0]["append"] is False
    assert any("Isy's Inventory Manager" in command["text"] for command in commands)
    assert any("This screen supports (partial) item or type names" in command["text"] for command in commands)
    assert any("IIM Autocrafting" in command["text"] for command in commands)
    assert next(command for command in commands if command["block_entity_id"] == 12)["title"] == "Craft item manually once to show up here"
    assert result["isy_foundation"]["lcd"]["proposed_commands"] == 3


def test_lcd_planner_matches_isy_surface_tags_in_custom_data():
    request = base_request(
        [
            grid_block(10, "LCD Panel ISY Main", is_lcd=True, surface_count=1, custom_data="@0 IIM-main\nshowWarnings=true"),
            grid_block(11, "LCD Panel Ore", is_lcd=True, surface_count=1, custom_data="@0 IIM-inventory\nOre 1000000"),
            grid_block(12, "LCD Panel Ingots", is_lcd=True, surface_count=1, custom_data="@0 IIM-inventory\nIngot 1000000"),
            grid_block(13, "Autocrafting LCD Panel", is_lcd=True, surface_count=1),
        ],
        {
            "mainLCDKeyword": "IIM-main",
            "inventoryLCDKeyword": "IIM-inventory",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}

    result = plan_isy_foundation(request)
    commands = [command for command in result["commands"] if command["kind"] == "write_text_surface"]

    assert {command["block_entity_id"] for command in commands} == {10, 11, 12, 13}
    assert any("Isy's Inventory Manager" in command["text"] for command in commands)
    assert result["isy_foundation"]["lcd"]["proposed_commands"] == 4


def test_main_lcd_uses_script_owned_status_instead_of_bridge_status():
    request = base_request(
        [
            grid_block(10, "IIM-main", is_lcd=True, surface_count=1),
            grid_block(
                20,
                "Ores Alpha",
                is_cargo=True,
                inventories=[
                    {
                        "index": 0,
                        "current_volume": 1700,
                        "max_volume": 10800,
                        "items": [grid_inventory_item("MyObjectBuilder_Ore", "Iron", 1200)],
                    }
                ],
            ),
            grid_block(
                21,
                "Ingots Alpha",
                is_cargo=True,
                inventories=[
                    {
                        "index": 0,
                        "current_volume": 67,
                        "max_volume": 14400,
                        "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 65000)],
                    }
                ],
            ),
            grid_block(
                22,
                "Components Alpha",
                is_cargo=True,
                inventories=[
                    {
                        "index": 0,
                        "current_volume": 1200,
                        "max_volume": 14400,
                        "items": [grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 65800)],
                    }
                ],
            ),
            grid_block(
                30,
                "Refinery 7",
                is_refinery=True,
                inventories=[
                    {"index": 0, "items": []},
                    {"index": 1, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Cobalt", 12)]},
                ],
            ),
            grid_block(40, "Assembler", is_assembler=True),
        ],
        {
            "mainLCDKeyword": "IIM-main",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )

    main_text = render_main_lcd(request, request["grid_snapshot"]["blocks"])

    assert "Isy's Inventory Manager" in main_text
    assert "Ores:" in main_text
    assert "Ingots:" in main_text
    assert "Components:" in main_text
    assert "Managed blocks:" in main_text
    assert "Refineries: Ore Balancing ON" in main_text
    assert "Assemblers: Craft ON" in main_text
    assert "Last Action:" in main_text
    assert "NOVALI" not in main_text
    assert "bridge planning" not in main_text
    assert "foundation / offloaded" not in main_text
    assert "Bridge sequence" not in main_text


def test_main_lcd_uses_pb_last_apply_action_text_instead_of_sequence_fallback():
    request = base_request(
        [grid_block(10, "IIM-main", is_lcd=True, surface_count=1)],
        {
            "mainLCDKeyword": "IIM-main",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {
            "last_apply": {
                "sequence": 51,
                "status": "processed",
                "last_action_time": "17:38:36",
                "last_action_at_utc": "2026-08-20T23:41:02.0000000Z",
                "last_action_text": "Moved: 288.29 Silicon\nfrom: 'Refinery 4'\nto: '7x11x3 Cargo Container Ingots (0%)'",
            }
        }

    main_text = render_main_lcd(request, request["grid_snapshot"]["blocks"])

    assert "17:38:36:" in main_text
    assert "Moved: 288.29 Silicon" in main_text
    assert "from: 'Refinery 4'" in main_text
    assert "to: '7x11x3 Cargo Container Ingots (0%)'" in main_text
    assert "Sequence 51: inventory action processed" not in main_text


def test_inventory_lcd_uses_isy_custom_data_filters():
    request = base_request(
        [
            grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
            grid_block(11, "Inventory LCD", is_lcd=True, surface_count=1, custom_data="@0 IIM-inventory\nIngot 100000 noBar\nEcho Inventory online"),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ingot", "Uranium", 1200),
                        grid_inventory_item("MyObjectBuilder_Ore", "Ice", 50),
                    ]
                ),
            ),
        ],
        {
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    inventory_text = next(command["text"] for command in result["commands"] if command.get("block_entity_id") == 11)
    assert "Itemfilter: 'Ingot'" in inventory_text
    assert "Uranium (Ingot) 1.2K / 100.0K" in inventory_text
    assert "Inventory online" in inventory_text
    assert "Ice" not in inventory_text


def test_inventory_lcd_initializes_all_matching_panels():
    request = base_request(
        [
            grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
            grid_block(11, "Ores IIM-inventory", is_lcd=True, surface_count=1),
            grid_block(12, "Ingots IIM-inventory", is_lcd=True, surface_count=1, custom_data="@0 IIM-inventory\nIngot"),
            grid_block(13, "Comps IIM-inventory", is_lcd=True, surface_count=1, custom_data="@0 IIM-inventory\nComponent"),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 1200),
                        grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 50),
                    ]
                ),
            ),
        ],
        {
            "inventoryLCDKeyword": "IIM-inventory",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    commands = [command for command in result["commands"] if command["kind"] == "write_text_surface"]
    inventory_commands = {command["block_entity_id"]: command["text"] for command in commands if command["block_entity_id"] in {11, 12, 13}}
    assert set(inventory_commands) == {11, 12, 13}
    assert "This screen supports (partial) item or type names" in inventory_commands[11]
    assert "Iron (Ingot)" in inventory_commands[12]
    assert "SteelPlate (Component)" in inventory_commands[13]
    assert result["isy_foundation"]["lcd"]["proposed_commands"] == 4


def test_lcd_planner_can_opt_out_of_inventory_lcd_report_writes():
    request = base_request(
        [
            grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
            grid_block(11, "Inventory LCD", is_lcd=True, surface_count=1),
        ],
        {
            "writeInventoryLCDReports": False,
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    commands = [command for command in result["commands"] if command["kind"] == "write_text_surface"]
    assert {command["block_entity_id"] for command in commands} == {10}
    assert result["isy_foundation"]["lcd"]["proposed_commands"] == 1
    assert result["isy_foundation"]["lcd"]["skipped_reasons"]["inventory_lcd_report_disabled"] == 1


def test_autocrafting_lcd_uses_isy_goal_custom_data():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=1000 A"),
            grid_block(20, "Assembler", is_assembler=True),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 250)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    autocrafting_text = next(command["text"] for command in result["commands"] if command["kind"] == "write_text_surface" and command.get("block_entity_id") == 12)
    assert "IIM Autocrafting" in autocrafting_text
    assert "$[A:Wait] SteelPlate: 250 / 1.0K" in autocrafting_text


def test_autocrafting_queues_missing_components_and_feeds_ingots():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=1000 A"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Components",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 250)]),
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    feed = next(command for command in result["commands"] if command.get("reason") == "autocrafting_material")
    assert enqueue == {
        "kind": "enqueue_assembler_blueprint",
        "block_entity_id": 20,
        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
        "amount": 100.0,
        "reason": "autocrafting_goal",
        "command_id": "bridge-a:11:autocrafting_enqueue:2",
    }
    assert feed == {
        "kind": "transfer_item",
        "source_entity_id": 61,
        "source_inventory_index": 0,
        "destination_entity_id": 20,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_Ingot",
        "item_subtype_id": "Iron",
        "reason": "autocrafting_material",
        "amount": 2100.0,
        "command_id": "bridge-a:11:autocrafting_material:3",
    }


def test_autocrafting_queues_new_lcd_component_goals():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nGirder=500\nSmallTube=5000"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 4,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    enqueues = [command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint"]
    assert {command["blueprint_id"] for command in enqueues} == {
        "MyObjectBuilder_BlueprintDefinition/GirderComponent",
        "MyObjectBuilder_BlueprintDefinition/SmallTube",
    }
    assert all(command["amount"] == 100.0 for command in enqueues)


def test_autocrafting_feeds_cumulative_materials_for_planned_lcd_goals():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=100\nInteriorPlate=100\nGirder=100"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[
                    {"index": 0, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 2100)]},
                    {"index": 1, "items": []},
                ],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    feed = next(command for command in result["commands"] if command.get("reason") == "autocrafting_material")
    assert feed["source_entity_id"] == 61
    assert feed["destination_entity_id"] == 20
    assert feed["item_subtype_id"] == "Iron"
    assert feed["amount"] == 900.0


def test_autocrafting_routes_multiple_ingots_for_vanilla_component_recipes():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nMetalGrid=100"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000),
                        grid_inventory_item("MyObjectBuilder_Ingot", "Nickel", 5000),
                        grid_inventory_item("MyObjectBuilder_Ingot", "Cobalt", 5000),
                    ]
                ),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    feeds = {command["item_subtype_id"]: command["amount"] for command in result["commands"] if command.get("reason") == "autocrafting_material"}
    assert enqueue["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/MetalGrid"
    assert feeds == {"Iron": 1200.0, "Nickel": 500.0, "Cobalt": 300.0}


def test_autocrafting_queues_modded_goal_learned_from_manual_queue():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nQuantumCore=100"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 7,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent",
                        "amount": 1,
                    }
                ],
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    assert enqueue["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent"
    assert enqueue["amount"] == 99.0


def test_autocrafting_queues_modded_goal_from_persisted_blueprint_memory():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nQuantumCore=100"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[],
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    request["autocrafting_blueprints"] = {
        "items": {
            "quantumcore": {
                "component_subtype": "QuantumCore",
                "blueprint_id": "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent",
                "aliases": ["QuantumCore", "QuantumCoreComponent"],
            }
        }
    }
    result = plan_isy_foundation(request)
    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    assert enqueue["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent"
    assert enqueue["amount"] == 100.0


def test_autocrafting_uses_virtual_pb_custom_data_blueprint_map():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nsdx_componentTitaniumPlate=25"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[],
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    request["virtual_pb"] = {
        "custom_data": "\n".join(
            [
                "station_mode;",
                "itemID;blueprintID",
                "MyObjectBuilder_Component/sdx_componentTitaniumPlate;MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0TitaniumPlate",
                "MyObjectBuilder_Ingot/Titanium;noBP",
            ]
        )
    }

    result = plan_isy_foundation(request)

    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    assert enqueue["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0TitaniumPlate"
    assert enqueue["amount"] == 25.0
    assert result["isy_foundation"]["autocrafting"]["virtual_pb_custom_data"]["blueprint_map_entries"] == 1
    assert result["isy_foundation"]["autocrafting"]["virtual_pb_custom_data"]["no_bp_entries"] == 1


def test_parse_virtual_pb_custom_data_blueprint_map_preserves_no_bp_rows():
    parsed = parse_virtual_pb_custom_data_blueprints(
        "station_mode;\n"
        "itemID;blueprintID\n"
        "MyObjectBuilder_Component/SteelPlate;MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0SteelPlate\n"
        "MyObjectBuilder_Ingot/Iron;noBP\n"
    )

    assert parsed["items"]["steelplate"]["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0SteelPlate"
    assert parsed["no_bp_items"] == ["MyObjectBuilder_Ingot/Iron"]


def test_autocrafting_feeds_materials_for_manually_queued_components():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
                        "amount": 10,
                    }
                ],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 500)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    feed = next(command for command in result["commands"] if command.get("reason") == "autocrafting_material")
    assert feed == {
        "kind": "transfer_item",
        "source_entity_id": 61,
        "source_inventory_index": 0,
        "destination_entity_id": 20,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_Ingot",
        "item_subtype_id": "Iron",
        "reason": "autocrafting_material",
        "amount": 210.0,
        "command_id": "bridge-a:11:autocrafting_material:1",
    }
    assert not [command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint"]


def test_autocrafting_does_not_feed_or_queue_disabled_assemblers():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=1000 A"),
            grid_block(
                20,
                "Basic Assembler",
                is_assembler=True,
                enabled=False,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
                        "amount": 10,
                    }
                ],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    assert not [command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint"]
    assert not [command for command in result["commands"] if command.get("reason") == "autocrafting_material"]
    skipped = result["isy_foundation"]["autocrafting"]["skipped_reasons"]
    assert skipped["disabled_machine"] == 1
    assert skipped["active_assembler_missing"] == 1


def test_autocrafting_moves_completed_components_to_component_cargo():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=1000 A"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[
                    {"index": 0, "items": []},
                    {"index": 1, "items": [grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 25)]},
                ],
            ),
            grid_block(60, "Bulk Cargo Container Components", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    cleanup = next(command for command in result["commands"] if command.get("reason") == "assembler_output_cleanup")
    assert cleanup == {
        "kind": "transfer_item",
        "source_entity_id": 20,
        "source_inventory_index": 1,
        "destination_entity_id": 60,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_Component",
        "item_subtype_id": "SteelPlate",
        "reason": "assembler_output_cleanup",
        "amount": 25.0,
        "command_id": "bridge-a:11:assembler_output:2",
    }


def test_autocrafting_still_drains_disabled_assembler_outputs():
    request = base_request(
        [
            grid_block(
                20,
                "Basic Assembler",
                is_assembler=True,
                enabled=False,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[
                    {"index": 0, "items": []},
                    {"index": 1, "items": [grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 25)]},
                ],
            ),
            grid_block(60, "Bulk Cargo Container Components", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    cleanup = next(command for command in result["commands"] if command.get("reason") == "assembler_output_cleanup")
    assert cleanup["source_entity_id"] == 20
    assert cleanup["destination_entity_id"] == 60


def test_autocrafting_queues_food_processor_items_and_feeds_inputs():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nMealPack_KelpCrisp=100"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                30,
                "Food Processor",
                is_assembler=True,
                use_conveyor=False,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Food",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_PhysicalObject", "Algae", 500)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    feed = next(command for command in result["commands"] if command.get("reason") == "autocrafting_material")
    assert enqueue["block_entity_id"] == 30
    assert enqueue["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/Position0030_MealPack_KelpCrisp"
    assert enqueue["amount"] == 100.0
    assert feed == {
        "kind": "transfer_item",
        "source_entity_id": 61,
        "source_inventory_index": 0,
        "destination_entity_id": 30,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_PhysicalObject",
        "item_subtype_id": "Algae",
        "reason": "autocrafting_material",
        "amount": 100.0,
        "command_id": "bridge-a:11:autocrafting_material:3",
    }


def test_autocrafting_enqueue_survives_low_machine_command_cap():
    request = base_request(
        [
            grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
            grid_block(11, "Inventory LCD", is_lcd=True, surface_count=1),
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=1000"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=True,
                assembler_mode="assembly",
                assembler_cooperative_mode=False,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000)]),
            ),
        ],
        {
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 3,
            "autocraftingQueueBatchSize": 100,
        },
    )

    result = plan_isy_foundation(request)

    enqueue = next(command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint")
    assert enqueue["block_entity_id"] == 20
    assert enqueue["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/SteelPlate"
    assert enqueue["amount"] == 100.0


def test_autocrafting_routes_food_processor_outputs_to_food_cargo():
    request = base_request(
        [
            grid_block(
                30,
                "Food Processor",
                is_assembler=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "items": []},
                    {"index": 1, "items": [grid_inventory_item("MyObjectBuilder_ConsumableItem", "MealPack_KelpCrisp", 21)]},
                ],
            ),
            grid_block(61, "Bulk Cargo Container Food", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    cleanup = next(command for command in result["commands"] if command.get("reason") == "assembler_output_cleanup")
    assert cleanup["source_entity_id"] == 30
    assert cleanup["source_inventory_index"] == 1
    assert cleanup["destination_entity_id"] == 61
    assert cleanup["item_type_id"] == "MyObjectBuilder_ConsumableItem"
    assert cleanup["item_subtype_id"] == "MealPack_KelpCrisp"
    assert cleanup["amount"] == 21.0


def test_autocrafting_keeps_component_goals_off_food_processor():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=100"),
            grid_block(
                30,
                "Food Processor",
                is_assembler=True,
                use_conveyor=False,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
            ),
            grid_block(
                61,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 5000)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    assert not [command for command in result["commands"] if command["kind"] == "enqueue_assembler_blueprint"]
    assert result["isy_foundation"]["autocrafting"]["skipped_reasons"]["assembler_missing"] == 1


def test_autocrafting_routes_completed_assembler_ingots_to_ingot_cargo():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[
                    {"index": 0, "items": []},
                    {"index": 1, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Nickel", 40)]},
                ],
            ),
            grid_block(60, "Bulk Cargo Container Components", is_cargo=True, inventories=grid_inventory([])),
            grid_block(61, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    cleanup = next(command for command in result["commands"] if command.get("reason") == "assembler_output_cleanup")
    assert cleanup["source_entity_id"] == 20
    assert cleanup["source_inventory_index"] == 1
    assert cleanup["destination_entity_id"] == 61
    assert cleanup["item_type_id"] == "MyObjectBuilder_Ingot"
    assert cleanup["item_subtype_id"] == "Nickel"
    assert cleanup["amount"] == 40.0


def test_autocrafting_returns_excess_assembler_input_ingots_to_ingot_cargo():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[
                    {
                        "index": 0,
                        "items": [
                            grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 1000),
                            grid_inventory_item("MyObjectBuilder_Ingot", "Nickel", 50),
                        ],
                    },
                    {"index": 1, "items": []},
                ],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
                        "amount": 10,
                    }
                ],
            ),
            grid_block(61, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    result = plan_isy_foundation(request)

    cleanups = {command["item_subtype_id"]: command for command in result["commands"] if command.get("reason") == "assembler_input_cleanup"}
    assert cleanups["Iron"]["source_entity_id"] == 20
    assert cleanups["Iron"]["destination_entity_id"] == 61
    assert cleanups["Iron"]["amount"] == 790.0
    assert cleanups["Nickel"]["amount"] == 50.0


def test_autocrafting_keeps_assembler_input_when_first_three_queue_recipe_is_unknown():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[
                    {"index": 0, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 1000)]},
                    {"index": 1, "items": []},
                ],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/UnknownModPart",
                        "amount": 1,
                    }
                ],
            ),
            grid_block(61, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    result = plan_isy_foundation(request)

    assert not [command for command in result["commands"] if command.get("reason") == "assembler_input_cleanup"]
    assert result["isy_foundation"]["autocrafting"]["skipped_reasons"]["assembler_input_unknown_blueprint"] == 1


def test_autocrafting_groups_duplicate_assembler_queue_entries():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 10,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
                        "amount": 10,
                    },
                    {
                        "item_id": 11,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/InteriorPlate",
                        "amount": 5,
                    },
                    {
                        "item_id": 12,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
                        "amount": 8,
                    },
                ],
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    result = plan_isy_foundation(request)

    move = next(command for command in result["commands"] if command.get("reason") == "assembler_queue_consolidation")
    assert move["kind"] == "move_assembler_queue_item"
    assert move["block_entity_id"] == 20
    assert move["queue_item_id"] == 12
    assert move["target_index"] == 1


def test_autocrafting_lcd_shows_known_components_when_no_goals_are_configured():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1),
            grid_block(20, "Assembler", is_assembler=True),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Component", "Construction", 100)]),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    autocrafting_text = next(command["text"] for command in result["commands"] if command["kind"] == "write_text_surface" and command.get("block_entity_id") == 12)
    assert "Known craftable items:" in autocrafting_text
    assert "$[OK] Construction: 100 / 0" in autocrafting_text
    assert "No items for crafting available" not in autocrafting_text
    custom_data_command = next(command for command in result["commands"] if command["kind"] == "write_block_custom_data")
    assert custom_data_command["block_entity_id"] == 12
    assert custom_data_command["reason"] == "autocrafting_discovered_items"
    assert "@0 Autocrafting" in custom_data_command["text"]
    assert "Construction=0" in custom_data_command["text"]


def test_autocrafting_custom_data_preserves_existing_goals_and_adds_new_items():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=100 A"),
            grid_block(20, "Assembler", is_assembler=True),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Component", "Construction", 100),
                        grid_inventory_item("MyObjectBuilder_Component", "SteelPlate", 25),
                    ]
                ),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "defaultModifier": "A",
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    custom_data_command = next(command for command in result["commands"] if command["kind"] == "write_block_custom_data")
    assert "SteelPlate=100 A" in custom_data_command["text"]
    assert "SteelPlate=0" not in custom_data_command["text"]
    assert "Construction=0 A" in custom_data_command["text"]


def test_autocrafting_discovers_components_from_manual_assembler_queue():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=100 A"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/InteriorPlate",
                        "amount": 10,
                    }
                ],
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "defaultModifier": "A",
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    autocrafting_text = next(command["text"] for command in result["commands"] if command["kind"] == "write_text_surface" and command.get("block_entity_id") == 12)
    custom_data_command = next(command for command in result["commands"] if command["kind"] == "write_block_custom_data")
    assert "$[A:Wait] SteelPlate: 0 / 100" in autocrafting_text
    assert "$[OK] InteriorPlate: 0 / 0" in autocrafting_text
    assert custom_data_command["reason"] == "autocrafting_discovered_items"
    assert "SteelPlate=100 A" in custom_data_command["text"]
    assert "InteriorPlate=0 A" in custom_data_command["text"]


def test_foundation_commands_rotate_under_one_command_apply_budget():
    request = base_request(
        [
            grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
            grid_block(11, "Inventory LCD", is_lcd=True, surface_count=1),
            grid_block(30, "Refinery", is_refinery=True),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ore", "Iron")]),
            ),
        ],
        {
            "maxApplyCommands": 1,
            "maxPlannedMachineCommands": 4,
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableAutocrafting": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
        },
    )
    request["sequence"] = 1
    first = plan_isy_foundation(request)["commands"][0]
    request["sequence"] = 2
    second = plan_isy_foundation(request)["commands"][0]
    assert first["command_id"] != second["command_id"]


def test_lcd_commands_are_not_starved_by_inventory_transfers():
    request = {"bridge_id": "bridge-a", "sequence": 1}
    inventory_commands = [
        {"kind": "transfer_item", "command_id": "bridge-a:1:transfer:1"},
        {"kind": "transfer_item", "command_id": "bridge-a:1:transfer:2"},
    ]
    foundation_commands = [
        {"kind": "write_text_surface", "command_id": "bridge-a:1:lcd:1"},
        {"kind": "write_text_surface", "command_id": "bridge-a:1:lcd:2"},
    ]
    seen_kinds = set()
    for sequence in range(0, 8):
        request["sequence"] = sequence
        commands = rotate_commands(request, inventory_commands, foundation_commands, 1)
        if commands:
            seen_kinds.add(commands[0]["kind"])
    assert "write_text_surface" in seen_kinds
    assert "transfer_item" in seen_kinds


def test_foundation_prefers_refinery_output_cleanup_before_lcd_when_budget_is_tight():
    request = base_request(
        [
            grid_block(10, "IIM-main", is_lcd=True, surface_count=1),
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Cobalt", 12)]},
                ],
            ),
            grid_block(60, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "maxApplyCommands": 1,
            "maxPlannedMachineCommands": 1,
            "enableAutocrafting": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
        },
    )

    result = plan_isy_foundation(request)

    assert result["commands"][0]["kind"] == "transfer_item"
    assert result["commands"][0]["reason"] == "refinery_output_cleanup"


def test_lcd_refresh_gets_reserved_slot_when_maintenance_commands_are_continuous():
    blocks = [
        grid_block(10, "LCD Panel ISY Main [IsyLCD]", is_lcd=True, surface_count=1, custom_data="@0 IIM-main"),
        grid_block(
            30,
            "Refinery",
            is_refinery=True,
            use_conveyor=False,
            inventories=[
                {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                {"index": 1, "current_volume": 0, "max_volume": 75, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Cobalt", 12)]},
            ],
        ),
        grid_block(
            31,
            "Refinery 2",
            is_refinery=True,
            use_conveyor=False,
            inventories=[
                {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                {"index": 1, "current_volume": 0, "max_volume": 75, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Magnesium", 12)]},
            ],
        ),
        grid_block(60, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
    ]
    request = base_request(
        blocks,
        {
            "maxApplyCommands": 8,
            "maxPlannedMachineCommands": 2,
            "inventorySortingEnabled": False,
            "mainLCDKeyword": "IIM-main",
            "enableAutocrafting": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
        },
    )

    result = plan_isy_foundation(request)

    assert any(command["kind"] == "transfer_item" for command in result["commands"])
    assert any(command["kind"] == "write_text_surface" for command in result["commands"])


def test_foundation_command_priority_keeps_operational_maintenance_ahead_of_lcd_refreshes():
    from worker.isy_foundation import foundation_command_priority

    lcd = {"kind": "write_text_surface"}
    refinery_output = {"kind": "transfer_item", "reason": "refinery_output_cleanup"}
    assembler_output = {"kind": "transfer_item", "reason": "assembler_output_cleanup"}
    set_conveyor = {"kind": "set_use_conveyor"}

    assert foundation_command_priority(refinery_output) < foundation_command_priority(lcd)
    assert foundation_command_priority(assembler_output) < foundation_command_priority(lcd)
    assert foundation_command_priority(set_conveyor) < foundation_command_priority(lcd)


def test_machine_command_planning_rotates_before_machine_cap():
    blocks = [
        grid_block(10, "Main LCD", is_lcd=True, surface_count=1),
        grid_block(20, "Assembler", is_assembler=True, use_conveyor=True),
        grid_block(30, "Refinery", is_refinery=True, use_conveyor=True),
        grid_block(40, "O2/H2 Generator", is_gas_generator=True, use_conveyor=True, gas_auto_refill=False, gas_auto_refill_supported=True),
        grid_block(50, "Reactor", is_reactor=True),
        grid_block(
            60,
            "Source Cargo",
            is_cargo=True,
            inventories=grid_inventory(
                [
                    grid_inventory_item("MyObjectBuilder_Ore", "Iron"),
                    grid_inventory_item("MyObjectBuilder_Ore", "Ice"),
                    grid_inventory_item("MyObjectBuilder_Ingot", "Uranium"),
                ]
            ),
        ),
    ]
    seen_targets = set()
    for sequence in range(0, 20):
        request = base_request(
            blocks,
            {
                "maxApplyCommands": 1,
                "maxPlannedMachineCommands": 3,
                "inventorySortingEnabled": False,
                "inventoryLCDKeyword": "",
                "warningsLCDKeyword": "",
                "actionsLCDKeyword": "",
                "performanceLCDKeyword": "",
                "industryInputMode": "plugin_only",
            },
        )
        request["sequence"] = sequence
        result = plan_isy_foundation(request)
        seen_targets.update(command.get("block_entity_id") for command in result["commands"])

    assert {20, 30, 40, 50}.issubset(seen_targets)


def test_autocrafting_planner_recognizes_assembler_and_emits_bounded_command():
    request = base_request(
        [grid_block(20, "Assembler", is_assembler=True, use_conveyor=True, assembler_mode="disassembly")],
        {"enableOreBalancing": False, "enableIceBalancing": False, "enableUraniumBalancing": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    setup = [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled", "mode") if key in command}
        for command in result["commands"]
    ]
    assert {"kind": "set_use_conveyor", "block_entity_id": 20, "enabled": False} not in setup
    assert {"kind": "set_assembler_mode", "block_entity_id": 20, "mode": "assembly"} in setup
    assert {"kind": "set_assembler_cooperative_mode", "block_entity_id": 20, "enabled": True} in setup
    assert result["industry_input_mode"] == "hybrid_conveyors"
    assert result["isy_foundation"]["industry_input_mode"] == "hybrid_conveyors"


def test_plugin_only_industry_input_mode_turns_industry_conveyors_off():
    request = base_request(
        [
            grid_block(20, "Assembler", is_assembler=True, use_conveyor=True),
            grid_block(30, "Food Processor", is_assembler=True, is_food_processor=True, use_conveyor=True),
            grid_block(
                40,
                "Refinery",
                is_refinery=True,
                use_conveyor=True,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ore", "Iron")]),
            ),
        ],
        {
            "industryInputMode": "plugin_only",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "maxPlannedMachineCommands": 10,
        },
    )
    result = plan_isy_foundation(request)
    setup = [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in result["commands"]
    ]
    assert {"kind": "set_use_conveyor", "block_entity_id": 20, "enabled": False} in setup
    assert {"kind": "set_use_conveyor", "block_entity_id": 30, "enabled": False} in setup
    assert {"kind": "set_use_conveyor", "block_entity_id": 40, "enabled": False} in setup
    assert any(command.get("reason") == "refinery_ore_input" for command in result["commands"])
    assert result["industry_input_mode"] == "plugin_only"


def test_hybrid_industry_input_mode_leaves_food_processor_and_refinery_conveyors_on():
    request = base_request(
        [
            grid_block(20, "Assembler", is_assembler=True, use_conveyor=True),
            grid_block(30, "Food Processor", is_assembler=True, is_food_processor=True, use_conveyor=True),
            grid_block(
                40,
                "Refinery",
                is_refinery=True,
                use_conveyor=True,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                70,
                "Ingots",
                is_cargo=True,
                inventories=grid_inventory([]),
            ),
            grid_block(
                71,
                "Components",
                is_cargo=True,
                inventories=grid_inventory([]),
            ),
            grid_block(
                72,
                "Food",
                is_cargo=True,
                inventories=grid_inventory([]),
            ),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ore", "Iron")]),
            ),
        ],
        {
            "industryInputMode": "hybrid_conveyors",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "maxPlannedMachineCommands": 10,
        },
    )
    result = plan_isy_foundation(request)
    industry_conveyor_off = [
        command
        for command in result["commands"]
        if command.get("kind") == "set_use_conveyor"
        and command.get("enabled") is False
        and command.get("block_entity_id") in {20, 30, 40}
    ]
    assert industry_conveyor_off == []


def test_autocrafting_planner_does_not_repeat_mode_setup_when_mode_is_unknown():
    request = base_request(
        [grid_block(20, "Assembler", is_assembler=True, use_conveyor=False, assembler_mode="")],
        {"enableOreBalancing": False, "enableIceBalancing": False, "enableUraniumBalancing": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    assert "set_assembler_mode" not in [command["kind"] for command in result["commands"]]


def test_refinery_gas_and_reactor_foundations_emit_isy_setup_commands():
    request = base_request(
        [
            grid_block(30, "Refinery", is_refinery=True, use_conveyor=True),
            grid_block(40, "O2/H2 Generator", is_gas_generator=True, use_conveyor=True, gas_auto_refill=False, gas_auto_refill_supported=True),
            grid_block(50, "Reactor", is_reactor=True, enabled=False),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Iron"),
                        grid_inventory_item("MyObjectBuilder_Ore", "Ice"),
                        grid_inventory_item("MyObjectBuilder_Ingot", "Uranium"),
                    ]
                ),
            ),
        ],
        {"enableAutocrafting": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    commands = result["commands"]
    assert {"kind": "set_use_conveyor", "block_entity_id": 30, "enabled": False} not in [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in commands
    ]
    assert {"kind": "set_use_conveyor", "block_entity_id": 40, "enabled": False} in [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in commands
    ]
    assert {"kind": "set_gas_auto_refill", "block_entity_id": 40, "enabled": True} in [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in commands
    ]
    assert {"kind": "set_block_enabled", "block_entity_id": 50, "enabled": True} in [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in commands
    ]
    assert {"kind": "set_use_conveyor", "block_entity_id": 50, "enabled": False} in [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in commands
    ]


def test_gas_balancing_does_not_plan_auto_refill_when_property_is_unsupported():
    request = base_request(
        [
            grid_block(
                40,
                "O2/H20 Generator",
                is_gas_generator=True,
                use_conveyor=False,
                gas_auto_refill=False,
                gas_auto_refill_supported=False,
            )
        ],
        {"enableAutocrafting": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    commands = [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in result["commands"]
    ]

    assert {"kind": "set_gas_auto_refill", "block_entity_id": 40, "enabled": True} not in commands
    assert result["isy_foundation"]["gas"]["skipped_reasons"]["gas_auto_refill_unsupported"] == 1


def test_gas_balancing_does_not_plan_auto_refill_when_support_is_unknown():
    request = base_request(
        [
            grid_block(
                40,
                "O2/H20 Generator",
                is_gas_generator=True,
                use_conveyor=False,
                gas_auto_refill=False,
            )
        ],
        {"enableAutocrafting": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)

    assert "set_gas_auto_refill" not in [command["kind"] for command in result["commands"]]
    assert result["isy_foundation"]["gas"]["skipped_reasons"]["gas_auto_refill_unsupported"] == 1


def test_machine_setup_still_runs_without_matching_source_inventory():
    request = base_request(
        [
            grid_block(30, "Refinery", is_refinery=True, use_conveyor=True),
            grid_block(40, "O2/H2 Generator", is_gas_generator=True, use_conveyor=True, gas_auto_refill=False, gas_auto_refill_supported=True),
            grid_block(50, "Reactor", is_reactor=True),
        ],
        {"enableAutocrafting": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    commands = [
        {key: command[key] for key in ("kind", "block_entity_id", "enabled") if key in command}
        for command in result["commands"]
    ]
    assert {"kind": "set_use_conveyor", "block_entity_id": 30, "enabled": False} not in commands
    assert {"kind": "set_use_conveyor", "block_entity_id": 40, "enabled": False} in commands
    assert {"kind": "set_gas_auto_refill", "block_entity_id": 40, "enabled": True} in commands
    assert {"kind": "set_use_conveyor", "block_entity_id": 50, "enabled": False} in commands
    assert "set_block_enabled" not in [command["kind"] for command in commands]
    assert result["isy_foundation"]["refinery"]["skipped_reasons"]["ore_source_missing"] == 1
    assert result["isy_foundation"]["gas"]["skipped_reasons"]["ice_source_missing"] == 1
    assert result["isy_foundation"]["reactor"]["skipped_reasons"]["uranium_source_missing"] == 1


def test_gas_balancing_tops_up_generators_from_cargo_ice():
    request = base_request(
        [
            grid_block(
                40,
                "O2/H2 Generator",
                is_gas_generator=True,
                use_conveyor=False,
                gas_auto_refill=True,
                inventories=[{"index": 0, "current_volume": 0, "max_volume": 40, "items": []}],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ore", "Ice", 50000)]),
            ),
        ],
        {"enableAutocrafting": False, "enableOreBalancing": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    transfers = [command for command in result["commands"] if command["kind"] == "transfer_item"]
    assert transfers == [
        {
            "kind": "transfer_item",
            "source_entity_id": 60,
            "source_inventory_index": 0,
            "destination_entity_id": 40,
            "destination_inventory_index": 0,
            "item_type_id": "MyObjectBuilder_Ore",
            "item_subtype_id": "Ice",
            "reason": "gas_generator_topup",
            "amount": 32432.432432432433,
            "command_id": "bridge-a:11:gas_ice:1",
        }
    ]


def test_refinery_balancing_tops_up_input_from_cargo_ore():
    request = base_request(
        [
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ore", "Silver", 999999)]),
            ),
        ],
        {"enableAutocrafting": False, "enableIceBalancing": False, "enableUraniumBalancing": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    transfers = [command for command in result["commands"] if command["kind"] == "transfer_item"]
    assert transfers == [
        {
            "kind": "transfer_item",
            "source_entity_id": 60,
            "source_inventory_index": 0,
            "destination_entity_id": 30,
            "destination_inventory_index": 0,
            "item_type_id": "MyObjectBuilder_Ore",
            "item_subtype_id": "Silver",
            "reason": "refinery_ore_input",
            "amount": 60810.81081081081,
            "command_id": "bridge-a:11:refinery_ore:1",
        }
    ]


def test_refinery_balancing_does_not_top_up_disabled_refineries():
    request = base_request(
        [
            grid_block(
                30,
                "Basic Refinery",
                is_refinery=True,
                enabled=False,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ore", "Silver", 999999)]),
            ),
        ],
        {"enableAutocrafting": False, "enableIceBalancing": False, "enableUraniumBalancing": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    assert not [command for command in result["commands"] if command.get("destination_entity_id") == 30]
    assert result["isy_foundation"]["refinery"]["skipped_reasons"]["disabled_machine"] == 1


def test_refinery_output_cleanup_moves_completed_ingots_to_ingot_cargo():
    request = base_request(
        [
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {
                        "index": 1,
                        "current_volume": 0,
                        "max_volume": 75,
                        "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Cobalt", 12)],
                    },
                ],
            ),
            grid_block(60, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
        ],
        {"enableAutocrafting": False, "enableIceBalancing": False, "enableUraniumBalancing": False, "mainLCDKeyword": ""},
    )
    result = plan_isy_foundation(request)
    cleanup = next(command for command in result["commands"] if command.get("reason") == "refinery_output_cleanup")
    assert cleanup == {
        "kind": "transfer_item",
        "source_entity_id": 30,
        "source_inventory_index": 1,
        "destination_entity_id": 60,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_Ingot",
        "item_subtype_id": "Cobalt",
        "reason": "refinery_output_cleanup",
        "amount": 12.0,
        "command_id": "bridge-a:11:refinery_output:1",
    }


def test_refinery_rebalances_existing_ore_between_online_refineries():
    request = base_request(
        [
            grid_block(
                30,
                "Refinery 1",
                is_refinery=True,
                use_conveyor=True,
                inventories=[
                    {
                        "index": 0,
                        "current_volume": 22.2,
                        "max_volume": 75,
                        "items": [grid_inventory_item("MyObjectBuilder_Ore", "Iron", 60000)],
                    },
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                31,
                "Refinery 2",
                is_refinery=True,
                use_conveyor=True,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                32,
                "Refinery 3",
                is_refinery=True,
                use_conveyor=True,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
        ],
        {
            "enableAutocrafting": False,
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "maxPlannedMachineCommands": 10,
        },
    )

    result = plan_isy_foundation(request)

    rebalances = [command for command in result["commands"] if command.get("reason") == "refinery_ore_rebalance"]
    assert sorted(command["destination_entity_id"] for command in rebalances) == [31, 32]
    assert all(command["source_entity_id"] == 30 for command in rebalances)
    assert all(command["item_subtype_id"] == "Iron" for command in rebalances)
    assert [command["amount"] for command in rebalances] == [20000.0, 20000.0]


def test_refinery_prioritizes_ore_for_short_assembler_ingots():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/MetalGrid",
                        "amount": 10,
                    }
                ],
            ),
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Silver", 999999),
                        grid_inventory_item("MyObjectBuilder_Ore", "Cobalt", 500),
                    ]
                ),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    priority_refining = next(command for command in result["commands"] if command.get("reason") == "autocrafting_ore_refining")
    assert priority_refining["source_entity_id"] == 60
    assert priority_refining["destination_entity_id"] == 30
    assert priority_refining["item_type_id"] == "MyObjectBuilder_Ore"
    assert priority_refining["item_subtype_id"] == "Cobalt"
    assert priority_refining["amount"] == 500.0

    request["worker_config"]["industryInputMode"] = "plugin_only"
    plugin_only_result = plan_isy_foundation(request)
    plugin_only_priority = next(command for command in plugin_only_result["commands"] if command.get("reason") == "autocrafting_ore_refining")
    assert plugin_only_priority["source_entity_id"] == 60
    assert plugin_only_priority["destination_entity_id"] == 30
    assert plugin_only_priority["item_subtype_id"] == "Cobalt"
    assert plugin_only_result["industry_input_mode"] == "plugin_only"


def test_refinery_unloads_non_priority_ore_to_feed_shortage_ore():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=10000 A\nExplosives=100 A"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[],
            ),
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {
                        "index": 0,
                        "current_volume": 3.7,
                        "max_volume": 75,
                        "items": [grid_inventory_item("MyObjectBuilder_Ore", "Iron", 10000)],
                    },
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Iron", 487000),
                        grid_inventory_item("MyObjectBuilder_Ore", "Magnesium", 218000),
                    ]
                ),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    unload = next(command for command in result["commands"] if command.get("reason") == "refinery_input_unload")
    priority_refining = next(command for command in result["commands"] if command.get("reason") == "autocrafting_ore_refining")
    assert unload["source_entity_id"] == 30
    assert unload["destination_entity_id"] == 60
    assert unload["item_type_id"] == "MyObjectBuilder_Ore"
    assert unload["item_subtype_id"] == "Iron"
    assert unload["amount"] == 10000.0
    assert priority_refining["source_entity_id"] == 60
    assert priority_refining["destination_entity_id"] == 30
    assert priority_refining["item_type_id"] == "MyObjectBuilder_Ore"
    assert priority_refining["item_subtype_id"] == "Magnesium"
    assert priority_refining["amount"] == 60810.81081081081


def test_refinery_skips_ore_already_in_processing_queue_when_selecting_shortage_ore():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=10000 A\nExplosives=100 A"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[],
            ),
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0.05, "max_volume": 75, "items": [grid_inventory_item("MyObjectBuilder_Ingot", "Iron", 500)]},
                ],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/IronOreToIngot",
                        "amount": 50000,
                    }
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Iron", 487000),
                        grid_inventory_item("MyObjectBuilder_Ore", "Magnesium", 218000),
                    ]
                ),
            ),
            grid_block(61, "Bulk Cargo Container Ingots", is_cargo=True, inventories=grid_inventory([])),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    priority_refining = next(command for command in result["commands"] if command.get("reason") == "autocrafting_ore_refining")
    assert priority_refining["source_entity_id"] == 60
    assert priority_refining["destination_entity_id"] == 30
    assert priority_refining["item_subtype_id"] == "Magnesium"
    assert priority_refining["amount"] == 60810.81081081081


def test_refinery_continues_topping_selected_shortage_ore_input():
    request = base_request(
        [
            grid_block(12, "Autocrafting", is_lcd=True, surface_count=1, custom_data="@0 Autocrafting\nSteelPlate=10000 A\nExplosives=100 A"),
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[],
            ),
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {
                        "index": 0,
                        "current_volume": 3.3,
                        "max_volume": 75,
                        "items": [grid_inventory_item("MyObjectBuilder_Ore", "Magnesium", 8900)],
                    },
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/MagnesiumOreToIngot",
                        "amount": 8900,
                    }
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Iron", 487000),
                        grid_inventory_item("MyObjectBuilder_Ore", "Magnesium", 218000),
                    ]
                ),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
            "autocraftingQueueBatchSize": 100,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    priority_refining = next(command for command in result["commands"] if command.get("reason") == "autocrafting_ore_refining")
    assert priority_refining["source_entity_id"] == 60
    assert priority_refining["destination_entity_id"] == 30
    assert priority_refining["item_subtype_id"] == "Magnesium"
    assert priority_refining["amount"] == 51910.81081081081


def test_refinery_falls_back_to_available_ore_when_priority_shortage_ore_is_missing():
    request = base_request(
        [
            grid_block(
                20,
                "Assembler",
                is_assembler=True,
                use_conveyor=False,
                assembler_mode="assembly",
                assembler_cooperative_mode=True,
                inventories=[{"index": 0, "items": []}, {"index": 1, "items": []}],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/MetalGrid",
                        "amount": 10,
                    }
                ],
            ),
            grid_block(
                30,
                "Refinery",
                is_refinery=True,
                use_conveyor=False,
                inventories=[
                    {"index": 0, "current_volume": 0, "max_volume": 75, "items": []},
                    {"index": 1, "current_volume": 0, "max_volume": 75, "items": []},
                ],
                production_queue=[
                    {
                        "item_id": 1,
                        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/IronOreToIngot",
                        "amount": 100,
                    }
                ],
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ores",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Iron", 50000),
                        grid_inventory_item("MyObjectBuilder_Ore", "Stone", 50000),
                    ]
                ),
            ),
        ],
        {
            "mainLCDKeyword": "",
            "inventoryLCDKeyword": "",
            "autocraftingKeyword": "",
            "warningsLCDKeyword": "",
            "actionsLCDKeyword": "",
            "performanceLCDKeyword": "",
            "enableIceBalancing": False,
            "enableUraniumBalancing": False,
            "maxPlannedMachineCommands": 10,
        },
    )
    request["state"] = {"shim_version": "2026-05-20-iim-action-parity-v13-customdata"}
    result = plan_isy_foundation(request)
    fallback_refining = next(command for command in result["commands"] if command.get("reason") == "refinery_ore_input")
    assert fallback_refining["source_entity_id"] == 60
    assert fallback_refining["destination_entity_id"] == 30
    assert fallback_refining["item_type_id"] == "MyObjectBuilder_Ore"
    assert fallback_refining["item_subtype_id"] == "Iron"
    assert fallback_refining["amount"] == 50000.0


def test_reactor_balancing_tops_up_uranium_to_configured_target():
    request = base_request(
        [
            grid_block(
                50,
                "Reactor",
                is_reactor=True,
                use_conveyor=False,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Uranium", 25)]),
            ),
            grid_block(
                60,
                "Bulk Cargo Container Ingots",
                is_cargo=True,
                inventories=grid_inventory([grid_inventory_item("MyObjectBuilder_Ingot", "Uranium", 250)]),
            ),
        ],
        {
            "enableAutocrafting": False,
            "enableOreBalancing": False,
            "enableIceBalancing": False,
            "mainLCDKeyword": "",
            "uraniumAmountLargeGrid": 100,
        },
    )
    result = plan_isy_foundation(request)
    transfers = [command for command in result["commands"] if command["kind"] == "transfer_item"]
    assert transfers == [
        {
            "kind": "transfer_item",
            "source_entity_id": 60,
            "source_inventory_index": 0,
            "destination_entity_id": 50,
            "destination_inventory_index": 0,
            "item_type_id": "MyObjectBuilder_Ingot",
            "item_subtype_id": "Uranium",
            "amount": 75.0,
            "command_id": "bridge-a:11:reactor_uranium:1",
        }
    ]


def test_machine_setup_respects_manual_and_exclusion_keywords():
    request = base_request(
        [
            grid_block(20, "Assembler !manual", is_assembler=True),
            grid_block(30, "Refinery", is_refinery=True, custom_data="!no_iim"),
            grid_block(50, "Reactor", is_reactor=True),
            grid_block(
                60,
                "Source Cargo",
                is_cargo=True,
                inventories=grid_inventory(
                    [
                        grid_inventory_item("MyObjectBuilder_Ore", "Iron"),
                        grid_inventory_item("MyObjectBuilder_Ingot", "Uranium"),
                    ]
                ),
            ),
        ],
        {
            "noIIMKeyword": "!no_iim",
            "enableIceBalancing": False,
            "mainLCDKeyword": "",
        },
    )
    result = plan_isy_foundation(request)
    command_targets = {command.get("block_entity_id") for command in result["commands"]}
    assert 20 not in command_targets
    assert 30 not in command_targets
    assert 50 in command_targets


def test_missing_grid_snapshot_falls_back_with_clear_diagnostic():
    request = base_request()
    request.pop("grid_snapshot")
    result = plan_isy_foundation(request)
    assert result["error_bucket"] == "grid_snapshot_missing"
    assert result["isy_foundation"]["status"] == "grid_snapshot_missing"
    assert any(command["kind"] == "echo" and "grid_snapshot_missing" in command["text"] for command in result["commands"])
