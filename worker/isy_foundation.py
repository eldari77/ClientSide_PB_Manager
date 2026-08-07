from __future__ import annotations

from collections import Counter
from typing import Any

ICE_VOLUME_PER_UNIT = 0.00037
ORE_VOLUME_PER_UNIT = 0.00037
DEFAULT_AUTOMATION_BATCH_SIZE = 100.0
DEFAULT_INDUSTRY_INPUT_MODE = "hybrid_conveyors"


def industry_input_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("industryInputMode") or DEFAULT_INDUSTRY_INPUT_MODE).strip().lower().replace("-", "_")
    if mode == "plugin_only":
        return "plugin_only"
    return DEFAULT_INDUSTRY_INPUT_MODE


def use_hybrid_industry_conveyors(config: dict[str, Any]) -> bool:
    return industry_input_mode(config) == DEFAULT_INDUSTRY_INPUT_MODE

def normalize_recipe_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def component_recipe_spec(component_subtype: str, blueprint_id: str, ingots: dict[str, float], aliases: list[str] | None = None) -> dict[str, Any]:
    return {
        "component_subtype": component_subtype,
        "blueprint_id": blueprint_id,
        "ingots": ingots,
        "machine_type": "assembler",
        "output_type_id": "MyObjectBuilder_Component",
        "aliases": sorted(set([component_subtype, *(aliases or [])])),
    }


def food_recipe_spec(food_subtype: str, blueprint_id: str, ingredients: list[dict[str, Any]], aliases: list[str] | None = None) -> dict[str, Any]:
    return {
        "component_subtype": food_subtype,
        "blueprint_id": blueprint_id,
        "materials": ingredients,
        "machine_type": "food_processor",
        "output_type_id": "MyObjectBuilder_ConsumableItem",
        "aliases": sorted(set([food_subtype, *(aliases or [])])),
    }


def assembler_recipe_spec(
    output_subtype: str,
    blueprint_id: str,
    ingots: dict[str, float],
    output_type_id: str,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "component_subtype": output_subtype,
        "blueprint_id": blueprint_id,
        "ingots": ingots,
        "machine_type": "assembler",
        "output_type_id": output_type_id,
        "aliases": sorted(set([output_subtype, *(aliases or [])])),
    }


def index_component_recipes(specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for spec in specs:
        for alias in spec.get("aliases", []):
            key = normalize_recipe_key(str(alias))
            if key:
                indexed[key] = spec
    return indexed


COMPONENT_RECIPE_SPECS = [
    component_recipe_spec("Construction", "MyObjectBuilder_BlueprintDefinition/ConstructionComponent", {"Iron": 8.0}, ["ConstructionComponent"]),
    component_recipe_spec("Girder", "MyObjectBuilder_BlueprintDefinition/GirderComponent", {"Iron": 6.0}, ["GirderComponent"]),
    component_recipe_spec("MetalGrid", "MyObjectBuilder_BlueprintDefinition/MetalGrid", {"Iron": 12.0, "Nickel": 5.0, "Cobalt": 3.0}),
    component_recipe_spec("InteriorPlate", "MyObjectBuilder_BlueprintDefinition/InteriorPlate", {"Iron": 3.0}),
    component_recipe_spec("SteelPlate", "MyObjectBuilder_BlueprintDefinition/SteelPlate", {"Iron": 21.0}),
    component_recipe_spec("SmallTube", "MyObjectBuilder_BlueprintDefinition/SmallTube", {"Iron": 5.0}, ["SmallSteelTube"]),
    component_recipe_spec("LargeTube", "MyObjectBuilder_BlueprintDefinition/LargeTube", {"Iron": 30.0}, ["LargeSteelTube"]),
    component_recipe_spec("Motor", "MyObjectBuilder_BlueprintDefinition/MotorComponent", {"Iron": 20.0, "Nickel": 5.0}, ["MotorComponent"]),
    component_recipe_spec("Display", "MyObjectBuilder_BlueprintDefinition/Display", {"Iron": 1.0, "Silicon": 5.0}),
    component_recipe_spec("BulletproofGlass", "MyObjectBuilder_BlueprintDefinition/BulletproofGlass", {"Silicon": 15.0}, ["BulletProofGlass"]),
    component_recipe_spec("Computer", "MyObjectBuilder_BlueprintDefinition/ComputerComponent", {"Iron": 0.5, "Silicon": 0.2}, ["ComputerComponent"]),
    component_recipe_spec("Reactor", "MyObjectBuilder_BlueprintDefinition/ReactorComponent", {"Stone": 20.0, "Iron": 15.0, "Silver": 5.0}, ["ReactorComponent"]),
    component_recipe_spec("Thrust", "MyObjectBuilder_BlueprintDefinition/ThrustComponent", {"Iron": 30.0, "Cobalt": 10.0, "Gold": 1.0, "Platinum": 0.4}, ["ThrustComponent", "Thruster", "ThrusterComponent"]),
    component_recipe_spec("GravityGenerator", "MyObjectBuilder_BlueprintDefinition/GravityGeneratorComponent", {"Iron": 600.0, "Cobalt": 220.0, "Silver": 5.0, "Gold": 10.0}, ["GravityGeneratorComponent"]),
    component_recipe_spec("Medical", "MyObjectBuilder_BlueprintDefinition/MedicalComponent", {"Iron": 60.0, "Nickel": 70.0, "Silver": 20.0}, ["MedicalComponent"]),
    component_recipe_spec("RadioCommunication", "MyObjectBuilder_BlueprintDefinition/RadioCommunicationComponent", {"Iron": 8.0, "Silicon": 1.0}, ["RadioCommunicationComponent", "Radio"]),
    component_recipe_spec("Detector", "MyObjectBuilder_BlueprintDefinition/DetectorComponent", {"Iron": 5.0, "Nickel": 15.0}, ["DetectorComponent"]),
    component_recipe_spec("Explosives", "MyObjectBuilder_BlueprintDefinition/ExplosivesComponent", {"Silicon": 0.5, "Magnesium": 2.0}, ["ExplosivesComponent"]),
    component_recipe_spec("SolarCell", "MyObjectBuilder_BlueprintDefinition/SolarCell", {"Nickel": 3.0, "Silicon": 6.0}),
    component_recipe_spec("PowerCell", "MyObjectBuilder_BlueprintDefinition/PowerCell", {"Iron": 10.0, "Silicon": 1.0, "Nickel": 2.0}),
    component_recipe_spec("Superconductor", "MyObjectBuilder_BlueprintDefinition/Superconductor", {"Iron": 10.0, "Gold": 2.0}),
    component_recipe_spec("Canvas", "MyObjectBuilder_BlueprintDefinition/Position0030_Canvas", {"Iron": 2.0, "Silicon": 35.0}, ["Position0030_Canvas"]),
    component_recipe_spec("PrototechPanel", "MyObjectBuilder_BlueprintDefinition/PrototechPanel", {"Iron": 35.0, "Nickel": 7.0, "Cobalt": 3.0, "Magnesium": 4.0}),
    component_recipe_spec("PrototechCapacitor", "MyObjectBuilder_BlueprintDefinition/PrototechCapacitor", {"Iron": 12.0, "Silicon": 4.0, "Silver": 3.0, "Gold": 6.0, "PrototechScrap": 1.5}),
    component_recipe_spec("PrototechPropulsionUnit", "MyObjectBuilder_BlueprintDefinition/PrototechPropulsionUnit", {"Iron": 60.0, "Cobalt": 24.0, "Gold": 6.0, "Platinum": 3.0, "PrototechScrap": 1.25}),
    component_recipe_spec("PrototechMachinery", "MyObjectBuilder_BlueprintDefinition/PrototechMachinery", {"Iron": 45.0, "Nickel": 12.0, "Silicon": 7.0, "Gold": 3.0, "PrototechScrap": 1.15}),
    component_recipe_spec("PrototechCircuitry", "MyObjectBuilder_BlueprintDefinition/PrototechCircuitry", {"Iron": 5.0, "Silicon": 8.0, "Gold": 2.0, "Platinum": 1.5, "PrototechScrap": 1.75}),
    component_recipe_spec("PrototechCoolingUnit", "MyObjectBuilder_BlueprintDefinition/PrototechCoolingUnit", {"Iron": 80.0, "Gold": 12.0, "Platinum": 3.25, "PrototechScrap": 2.5}),
]

COMPONENT_RECIPES = index_component_recipes(COMPONENT_RECIPE_SPECS)

FOOD_RECIPE_SPECS = [
    food_recipe_spec(
        "MealPack_KelpCrisp",
        "MyObjectBuilder_BlueprintDefinition/Position0030_MealPack_KelpCrisp",
        [{"type_id": "MyObjectBuilder_PhysicalObject", "subtype_id": "Algae", "amount": 1.0}],
        ["Position0030_MealPack_KelpCrisp", "KelpCrisp"],
    ),
]

FOOD_RECIPES = index_component_recipes(FOOD_RECIPE_SPECS)

ASSEMBLER_RECIPE_SPECS = [
    assembler_recipe_spec(
        "NATO_25x184mm",
        "MyObjectBuilder_BlueprintDefinition/Position0080_NATO_25x184mmMagazine",
        {"Iron": 40.0, "Nickel": 5.0, "Magnesium": 3.0},
        "MyObjectBuilder_AmmoMagazine",
        ["NATO_25x184mmMagazine"],
    ),
    assembler_recipe_spec(
        "MediumCalibreAmmo",
        "MyObjectBuilder_BlueprintDefinition/Position0110_MediumCalibreAmmo",
        {"Iron": 15.0, "Nickel": 2.0, "Magnesium": 1.2},
        "MyObjectBuilder_AmmoMagazine",
    ),
    assembler_recipe_spec(
        "LargeCalibreAmmo",
        "MyObjectBuilder_BlueprintDefinition/Position0120_LargeCalibreAmmo",
        {"Iron": 60.0, "Nickel": 8.0, "Magnesium": 5.0, "Uranium": 0.1},
        "MyObjectBuilder_AmmoMagazine",
    ),
    assembler_recipe_spec(
        "AngleGrinder4Item",
        "MyObjectBuilder_BlueprintDefinition/Position0040_AngleGrinder4",
        {"Platinum": 1.0},
        "MyObjectBuilder_PhysicalGunObject",
        ["AngleGrinder4"],
    ),
    assembler_recipe_spec(
        "HandDrill4Item",
        "MyObjectBuilder_BlueprintDefinition/Position0080_HandDrill4",
        {"Platinum": 1.0},
        "MyObjectBuilder_PhysicalGunObject",
        ["HandDrill4"],
    ),
    assembler_recipe_spec(
        "Welder4Item",
        "MyObjectBuilder_BlueprintDefinition/Position0120_Welder4",
        {"Platinum": 1.0},
        "MyObjectBuilder_PhysicalGunObject",
        ["Welder4"],
    ),
]

ASSEMBLER_RECIPES = index_component_recipes(ASSEMBLER_RECIPE_SPECS)

from worker.isy_sorting import as_bool, as_float, as_int, plan_inventory_sorting


LCD_KEYWORDS = {
    "main": "mainLCDKeyword",
    "inventory": "inventoryLCDKeyword",
    "autocrafting": "autocraftingKeyword",
    "warnings": "warningsLCDKeyword",
    "actions": "actionsLCDKeyword",
    "performance": "performanceLCDKeyword",
}

DEFAULT_LCD_KEYWORDS = {
    "main": "IIM-main",
    "inventory": "IIM-inventory",
    "autocrafting": "Autocrafting",
    "warnings": "IIM-warnings",
    "actions": "IIM-actions",
    "performance": "IIM-performance",
}


def plan_isy_foundation(request: dict[str, Any]) -> dict[str, Any]:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    input_mode = industry_input_mode(config)
    inventory_result = plan_inventory_sorting(request)
    commands = list(inventory_result.get("commands") if isinstance(inventory_result.get("commands"), list) else [])
    max_apply = max(0, as_int(config.get("maxApplyCommands"), 1))
    max_machine = max(0, as_int(config.get("maxPlannedMachineCommands"), max(max_apply, 1)))
    grid = request.get("grid_snapshot") if isinstance(request.get("grid_snapshot"), dict) else {}
    blocks_payload = grid.get("blocks")

    if not isinstance(blocks_payload, list):
        foundation = {
            "status": "grid_snapshot_missing",
            "grid_snapshot_source": str(grid.get("source", "missing")) if isinstance(grid, dict) else "missing",
            "industry_input_mode": input_mode,
            "lcd": empty_module("grid_snapshot_missing"),
            "autocrafting": empty_module("grid_snapshot_missing"),
            "refinery": empty_module("grid_snapshot_missing"),
            "gas": empty_module("grid_snapshot_missing"),
            "reactor": empty_module("grid_snapshot_missing"),
        }
        commands.append({"kind": "echo", "text": "IIM foundation skipped: grid_snapshot_missing"})
        return merge_results(inventory_result, commands, max_apply, foundation)

    blocks = [block for block in blocks_payload if isinstance(block, dict)]
    foundation_commands: list[dict[str, Any]] = []
    foundation_plan_cap = foundation_candidate_cap(blocks, max_machine)
    modules = {
        "lcd": plan_lcd_reports(request, blocks, config, foundation_commands, foundation_plan_cap),
        "autocrafting": plan_autocrafting(request, blocks, config, foundation_commands, foundation_plan_cap),
        "refinery": plan_refinery(request, blocks, config, foundation_commands, foundation_plan_cap),
        "gas": plan_gas_balancing(request, blocks, config, foundation_commands, foundation_plan_cap),
        "reactor": plan_reactor_balancing(request, blocks, config, foundation_commands, foundation_plan_cap),
    }
    foundation_candidate_count = len(foundation_commands)
    foundation_commands = rotate_foundation_commands(request, foundation_commands, max_machine)
    foundation = {
        "status": "processed",
        "grid_snapshot_source": str(grid.get("source", "unknown")),
        "industry_input_mode": input_mode,
        "scanned_blocks": len(blocks),
        "proposed_commands": len(foundation_commands),
        "candidate_commands": foundation_candidate_count,
    }
    foundation.update(modules)
    commands = rotate_commands(request, commands, foundation_commands, max_apply)
    return merge_results(inventory_result, commands, max_apply, foundation)


def merge_results(inventory_result: dict[str, Any], commands: list[dict[str, Any]], max_apply: int, foundation: dict[str, Any]) -> dict[str, Any]:
    result = dict(inventory_result)
    result["commands"] = commands
    result["apply_mode"] = "dry_run" if inventory_result.get("apply_mode") == "dry_run" else "immediate"
    result["max_apply_commands"] = max_apply
    result["remaining_commands"] = max(0, len(commands) - max_apply)
    result["isy_foundation"] = foundation
    result["industry_input_mode"] = str(foundation.get("industry_input_mode", DEFAULT_INDUSTRY_INPUT_MODE))
    result["summary"] = str(inventory_result.get("summary", "")) + "; Isy foundation " + str(foundation.get("status", "unknown"))
    if foundation.get("status") == "grid_snapshot_missing":
        result["error_bucket"] = "grid_snapshot_missing"
    return result


def plan_lcd_reports(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    commands: list[dict[str, Any]],
    max_machine: int,
) -> dict[str, Any]:
    skipped: Counter[str] = Counter()
    lcds = [block for block in blocks if same_construct(block) and (as_bool(block.get("is_lcd"), False) or as_int(block.get("surface_count"), 0) > 0)]
    proposed = 0
    for label, key in LCD_KEYWORDS.items():
        keyword = str(config.get(key) or DEFAULT_LCD_KEYWORDS.get(label, "")).strip()
        if not keyword:
            skipped[f"{label}_keyword_missing"] += 1
            continue
        if label == "inventory" and not as_bool(config.get("writeInventoryLCDReports"), True):
            skipped["inventory_lcd_report_disabled"] += 1
            continue
        target_lcds = named_blocks(lcds, keyword) if label == "inventory" else [block for block in [first_named(lcds, keyword)] if block is not None]
        if not target_lcds:
            skipped[f"{label}_lcd_missing"] += 1
            continue
        for block in target_lcds:
            if len(commands) >= max_machine:
                skipped["budget"] += 1
                break
            commands.append(
                {
                    "kind": "write_text_surface",
                    "command_id": command_id(request, "lcd", len(commands) + 1),
                    "block_entity_id": entity_id(block),
                    "surface_index": 0,
                    "append": False,
                    "text": report_text(label, request, blocks, block),
                }
            )
            if label == "autocrafting":
                commands[-1]["title"] = "Craft item manually once to show up here"
            proposed += 1
    return {
        "enabled": True,
        "apply_state": "immediate",
        "scanned_blocks": len(lcds),
        "proposed_commands": proposed,
        "skipped_reasons": dict(skipped),
    }


def plan_autocrafting(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    commands: list[dict[str, Any]],
    max_machine: int,
) -> dict[str, Any]:
    enabled = as_bool(config.get("enableAutocrafting"), True)
    hybrid_industry = use_hybrid_industry_conveyors(config)
    assemblers = managed_machine_blocks(blocks, config, lambda block: as_bool(block.get("is_assembler"), False))
    active_assemblers = [block for block in assemblers if machine_accepts_inventory(block)]
    food_processors = [block for block in active_assemblers if is_food_processor(block)]
    component_assemblers = [block for block in active_assemblers if not is_food_processor(block)]
    skipped: Counter[str] = Counter()
    proposed = 0

    def append_command(module: str, command: dict[str, Any]) -> bool:
        nonlocal proposed
        if len(commands) >= max_machine:
            skipped["budget"] += 1
            return False
        command["command_id"] = command_id(request, module, len(commands) + 1)
        commands.append(command)
        proposed += 1
        return True

    if not enabled:
        return module_summary(False, assemblers, proposed, {"disabled": 1})
    if len(active_assemblers) < len(assemblers):
        skipped["disabled_machine"] += len(assemblers) - len(active_assemblers)
    cooperative_mode = not as_bool(config.get("splitAssemblerTasks"), False)
    autocrafting_lcd = first_named(
        [block for block in blocks if same_construct(block) and (as_bool(block.get("is_lcd"), False) or as_int(block.get("surface_count"), 0) > 0)],
        str(config.get("autocraftingKeyword") or DEFAULT_LCD_KEYWORDS["autocrafting"]),
    )
    blueprint_specs = autocrafting_blueprint_specs(request, blocks)
    discovered_custom_data = autocrafting_discovered_custom_data(autocrafting_lcd, blocks, config, blueprint_specs) if autocrafting_lcd else ""
    if discovered_custom_data and supports_custom_data_commands(request):
        append_command(
            "autocrafting_custom_data",
            {
                "kind": "write_block_custom_data",
                "block_entity_id": entity_id(autocrafting_lcd or {}),
                "text": discovered_custom_data,
                "reason": "autocrafting_discovered_items",
            },
        )
    elif discovered_custom_data:
        skipped["shim_custom_data_command_missing"] += 1
    for block in active_assemblers:
        if not hybrid_industry and as_bool(block.get("use_conveyor"), False):
            if not append_command("assembler_conveyor", {"kind": "set_use_conveyor", "block_entity_id": entity_id(block), "enabled": False}):
                break
        if is_food_processor(block):
            continue
        assembler_mode = str(block.get("assembler_mode", "")).strip().lower()
        if assembler_mode and assembler_mode not in {"assembly", "assembling"}:
            if not append_command("assembler_mode", {"kind": "set_assembler_mode", "block_entity_id": entity_id(block), "mode": "assembly"}):
                break
        if as_bool(block.get("assembler_cooperative_mode"), False) != cooperative_mode:
            if not append_command(
                "assembler_cooperative",
                {"kind": "set_assembler_cooperative_mode", "block_entity_id": entity_id(block), "enabled": cooperative_mode},
            ):
                break
        if len(commands) >= max_machine:
            break
    assembler_targets = assembler_output_targets(blocks, config)
    for block in assemblers:
        for output_item in assembler_output_items(block):
            output_target = assembler_output_target(output_item, assembler_targets)
            if output_target is None:
                skipped["assembler_output_target_missing"] += 1
                continue
            if not append_command(
                "assembler_output",
                {
                    "kind": "transfer_item",
                    "source_entity_id": entity_id(block),
                    "source_inventory_index": 1,
                    "destination_entity_id": entity_id(output_target),
                    "destination_inventory_index": first_inventory_index(output_target),
                    "item_type_id": str(output_item.get("type_id", "")),
                    "item_subtype_id": str(output_item.get("subtype_id", "")),
                    "reason": "assembler_output_cleanup",
                    "amount": as_float(output_item.get("amount"), 0),
                },
            ):
                break
        if len(commands) >= max_machine:
            break
    material_needs_by_machine = {
        entity_id(assembler): queued_material_needs(assembler, blueprint_specs) for assembler in active_assemblers
    }
    consolidate_assembler_queues(component_assemblers, append_command, skipped)
    if active_assemblers and autocrafting_lcd:
        batch_size = max(1.0, as_float(config.get("autocraftingQueueBatchSize"), DEFAULT_AUTOMATION_BATCH_SIZE))
        goals = autocrafting_goals(str(autocrafting_lcd.get("custom_data") or ""))
        component_totals = autocrafting_item_amounts(blocks, blueprint_specs)
        queued_totals = queued_component_amounts(assemblers, blueprint_specs)
        for goal in goals:
            spec = component_blueprint_spec(str(goal.get("name", "")), blueprint_specs)
            if spec is None:
                skipped["blueprint_unknown"] += 1
                continue
            machine_pool = food_processors if recipe_machine_type(spec) == "food_processor" else component_assemblers
            if not machine_pool:
                skipped["food_processor_missing" if recipe_machine_type(spec) == "food_processor" else "assembler_missing"] += 1
                continue
            machine = machine_pool[as_int(request.get("sequence"), 0) % len(machine_pool)]
            component_subtype = str(spec["component_subtype"])
            wanted = as_float(goal.get("wanted"), 0)
            current = component_totals.get(normalize_recipe_key(component_subtype), 0.0)
            queued = queued_totals.get(normalize_recipe_key(component_subtype), 0.0)
            amount = min(batch_size, max(0.0, wanted - current - queued))
            if amount <= 0:
                continue
            if not append_command(
                "autocrafting_enqueue",
                {
                    "kind": "enqueue_assembler_blueprint",
                    "block_entity_id": entity_id(machine),
                    "blueprint_id": str(spec["blueprint_id"]),
                    "amount": amount,
                    "reason": "autocrafting_goal",
                },
            ):
                break
            add_material_needs(material_needs_by_machine, machine, spec, amount)
        feed_autocrafting_materials(blocks, active_assemblers, material_needs_by_machine, append_command, skipped)
    elif active_assemblers:
        feed_autocrafting_materials(blocks, active_assemblers, material_needs_by_machine, append_command, skipped)
    cleanup_assembler_input_ingots(blocks, component_assemblers, config, blueprint_specs, append_command, skipped)
    if len(commands) >= max_machine:
        return module_summary(True, assemblers, proposed, skipped)
    if not assemblers:
        skipped["assembler_missing"] += 1
    elif not active_assemblers:
        skipped["active_assembler_missing"] += 1
    return module_summary(True, assemblers, proposed, skipped)


def plan_refinery(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    commands: list[dict[str, Any]],
    max_machine: int,
) -> dict[str, Any]:
    enabled = as_bool(config.get("enableOreBalancing"), True)
    hybrid_industry = use_hybrid_industry_conveyors(config)
    refineries = managed_machine_blocks(blocks, config, lambda block: as_bool(block.get("is_refinery"), False))
    active_refineries = [block for block in refineries if machine_accepts_inventory(block)]
    assemblers = managed_machine_blocks(blocks, config, lambda block: as_bool(block.get("is_assembler"), False))
    active_assemblers = [block for block in assemblers if machine_accepts_inventory(block)]
    blueprint_specs = autocrafting_blueprint_specs(request, blocks)
    material_shortages = autocrafting_material_shortages(request, blocks, config, active_assemblers, blueprint_specs)
    ingot_target = find_ingot_target(blocks, config)
    ore_target = find_ore_target(blocks, config)
    skipped: Counter[str] = Counter()
    proposed = 0
    if not enabled:
        return module_summary(False, refineries, proposed, {"disabled": 1})
    if len(active_refineries) < len(refineries):
        skipped["disabled_machine"] += len(refineries) - len(active_refineries)
    if not has_item(blocks, is_refinery_ore_item):
        skipped["ore_source_missing"] += 1
    rebalance_commands = refinery_ore_rebalance_commands(request, active_refineries)
    for block in refineries:
        setup_commands = []
        active = machine_accepts_inventory(block)
        if active and not hybrid_industry and as_bool(block.get("use_conveyor"), False):
            setup_commands.append(
                (
                    "refinery_conveyor",
                    {
                        "kind": "set_use_conveyor",
                        "block_entity_id": entity_id(block),
                        "enabled": False,
                    },
                )
            )
        output_items = refinery_output_items(block)
        if output_items:
            if ingot_target is None:
                skipped["ingot_cargo_missing"] += 1
            else:
                for output_item in output_items:
                    setup_commands.append(
                        (
                            "refinery_output",
                            {
                                "kind": "transfer_item",
                                "source_entity_id": entity_id(block),
                                "source_inventory_index": 1,
                                "destination_entity_id": entity_id(ingot_target),
                                "destination_inventory_index": first_inventory_index(ingot_target),
                                "item_type_id": str(output_item.get("type_id", "MyObjectBuilder_Ingot")),
                                "item_subtype_id": str(output_item.get("subtype_id", "")),
                                "reason": "refinery_output_cleanup",
                                "amount": as_float(output_item.get("amount"), 0),
                            },
                        )
                    )
        refinery_input_index = first_inventory_index(block)
        current_ore = inventory_amount_in_inventory(block, refinery_input_index, is_refinery_ore_item)
        target_ore = refinery_target_ore(block) if active else 0.0
        if active and target_ore > 0:
            source = find_priority_refinery_ore_source_for_refinery(blocks, material_shortages, block)
            priority_source = source is not None
            priority_subtype = str(source[2].get("subtype_id", "")) if source is not None else ""
            priority_target_ore = refinery_target_fill_ore(block)
            planned_input_space = refinery_free_ore_capacity(block)
            if priority_source and priority_subtype:
                existing_priority_ore = inventory_amount_in_inventory(
                    block,
                    refinery_input_index,
                    lambda item, subtype=priority_subtype: is_ore_subtype(item, subtype),
                )
                blocking_item = refinery_input_blocking_ore(block, priority_subtype)
                if existing_priority_ore < priority_target_ore and blocking_item is not None:
                    if ore_target is None:
                        skipped["ore_cargo_missing"] += 1
                    else:
                        unload_amount = as_float(blocking_item.get("amount"), 0)
                        planned_input_space += unload_amount
                        setup_commands.append(
                            (
                                "refinery_input_unload",
                                {
                                    "kind": "transfer_item",
                                    "source_entity_id": entity_id(block),
                                    "source_inventory_index": refinery_input_index,
                                    "destination_entity_id": entity_id(ore_target),
                                    "destination_inventory_index": first_inventory_index(ore_target),
                                    "item_type_id": str(blocking_item.get("type_id", "MyObjectBuilder_Ore")),
                                    "item_subtype_id": str(blocking_item.get("subtype_id", "")),
                                    "reason": "refinery_input_unload",
                                    "amount": unload_amount,
                                },
                            )
                        )
                feed_amount = min(
                    max(0.0, priority_target_ore - existing_priority_ore),
                    as_float(source[2].get("amount"), 0),
                    planned_input_space if planned_input_space > 0 else as_float(source[2].get("amount"), 0),
                )
                if feed_amount > 0:
                    source_block, source_inventory, source_item = source
                    setup_commands.append(
                        (
                            "refinery_ore",
                            {
                                "kind": "transfer_item",
                                "source_entity_id": entity_id(source_block),
                                "source_inventory_index": as_int(source_inventory.get("index"), 0),
                                "destination_entity_id": entity_id(block),
                                "destination_inventory_index": refinery_input_index,
                                "item_type_id": str(source_item.get("type_id", "MyObjectBuilder_Ore")),
                                "item_subtype_id": str(source_item.get("subtype_id", "")),
                                "reason": "autocrafting_ore_refining",
                                "amount": feed_amount,
                            },
                        )
                    )
            elif current_ore < target_ore:
                source = find_refinery_fallback_ore_source(blocks, block)
                if source is None:
                    skipped["ore_source_missing"] += 1
                else:
                    source_block, source_inventory, source_item = source
                    setup_commands.append(
                        (
                            "refinery_ore",
                            {
                                "kind": "transfer_item",
                                "source_entity_id": entity_id(source_block),
                                "source_inventory_index": as_int(source_inventory.get("index"), 0),
                                "destination_entity_id": entity_id(block),
                                "destination_inventory_index": refinery_input_index,
                                "item_type_id": str(source_item.get("type_id", "MyObjectBuilder_Ore")),
                                "item_subtype_id": str(source_item.get("subtype_id", "")),
                                "reason": "refinery_ore_input",
                                "amount": min(target_ore - current_ore, as_float(source_item.get("amount"), 0)),
                            },
                        )
                    )
        for module, setup_command in setup_commands:
            if len(commands) >= max_machine:
                skipped["budget"] += 1
                break
            setup_command["command_id"] = command_id(request, module, len(commands) + 1)
            commands.append(setup_command)
            proposed += 1
        if len(commands) >= max_machine:
            break
    for setup_command in rebalance_commands:
        if len(commands) >= max_machine:
            skipped["budget"] += 1
            break
        setup_command["command_id"] = command_id(request, "refinery_rebalance", len(commands) + 1)
        commands.append(setup_command)
        proposed += 1
    if not refineries:
        skipped["refinery_missing"] += 1
    return module_summary(True, refineries, proposed, skipped)


def refinery_ore_rebalance_commands(request: dict[str, Any], active_refineries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(active_refineries) < 2:
        return []
    planned_totals = {entity_id(refinery): refinery_input_ore_amount(refinery) for refinery in active_refineries}
    total_ore = sum(planned_totals.values())
    if total_ore <= 0:
        return []
    target_per_refinery = total_ore / len(active_refineries)
    min_transfer = max(100.0, target_per_refinery * 0.02)
    source_items: dict[int, list[dict[str, Any]]] = {
        entity_id(refinery): [
            {"item": item, "remaining": as_float(item.get("amount"), 0)}
            for item in refinery_input_ore_items(refinery)
            if as_float(item.get("amount"), 0) > 0
        ]
        for refinery in active_refineries
    }
    commands: list[dict[str, Any]] = []
    receivers = sorted(active_refineries, key=lambda refinery: (planned_totals.get(entity_id(refinery), 0.0), str(refinery.get("name", ""))))
    for receiver in receivers:
        receiver_id = entity_id(receiver)
        receiver_deficit = target_per_refinery - planned_totals.get(receiver_id, 0.0)
        if receiver_deficit <= min_transfer:
            continue
        receiver_space = refinery_free_ore_capacity(receiver)
        if receiver_space <= 0:
            continue
        donor = refinery_rebalance_donor(active_refineries, planned_totals, source_items, target_per_refinery, receiver_id, min_transfer)
        if donor is None:
            break
        donor_refinery, source_entry = donor
        donor_id = entity_id(donor_refinery)
        source_item = source_entry["item"]
        donor_excess = planned_totals.get(donor_id, 0.0) - target_per_refinery
        amount = min(donor_excess, receiver_deficit, receiver_space, as_float(source_entry.get("remaining"), 0))
        if amount <= min_transfer:
            continue
        source_entry["remaining"] = max(0.0, as_float(source_entry.get("remaining"), 0) - amount)
        planned_totals[donor_id] = max(0.0, planned_totals.get(donor_id, 0.0) - amount)
        planned_totals[receiver_id] = planned_totals.get(receiver_id, 0.0) + amount
        commands.append(
            {
                "kind": "transfer_item",
                "source_entity_id": donor_id,
                "source_inventory_index": first_inventory_index(donor_refinery),
                "destination_entity_id": receiver_id,
                "destination_inventory_index": first_inventory_index(receiver),
                "item_type_id": str(source_item.get("type_id", "MyObjectBuilder_Ore")),
                "item_subtype_id": str(source_item.get("subtype_id", "")),
                "reason": "refinery_ore_rebalance",
                "amount": amount,
            }
        )
    return commands


def refinery_rebalance_donor(
    active_refineries: list[dict[str, Any]],
    planned_totals: dict[int, float],
    source_items: dict[int, list[dict[str, Any]]],
    target_per_refinery: float,
    receiver_id: int,
    min_transfer: float,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    donors = sorted(
        active_refineries,
        key=lambda refinery: (planned_totals.get(entity_id(refinery), 0.0), str(refinery.get("name", ""))),
        reverse=True,
    )
    for donor in donors:
        donor_id = entity_id(donor)
        if donor_id == receiver_id or planned_totals.get(donor_id, 0.0) - target_per_refinery <= min_transfer:
            continue
        items = [entry for entry in source_items.get(donor_id, []) if as_float(entry.get("remaining"), 0) > min_transfer]
        if not items:
            continue
        return donor, max(items, key=lambda entry: as_float(entry.get("remaining"), 0))
    return None


def plan_gas_balancing(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    commands: list[dict[str, Any]],
    max_machine: int,
) -> dict[str, Any]:
    enabled = as_bool(config.get("enableIceBalancing"), True)
    gas_blocks = managed_machine_blocks(
        blocks,
        config,
        lambda block: as_bool(block.get("is_gas_generator"), False) or as_bool(block.get("is_gas_tank"), False),
    )
    skipped: Counter[str] = Counter()
    proposed = 0
    if not enabled:
        return module_summary(False, gas_blocks, proposed, {"disabled": 1})
    if not has_item(blocks, lambda item: "ice" in str(item.get("subtype_id", "")).lower()):
        skipped["ice_source_missing"] += 1
    generators = [block for block in gas_blocks if as_bool(block.get("is_gas_generator"), False)]
    fill_offline = as_bool(config.get("fillOfflineGenerators"), False)
    for generator in generators:
        setup_commands = []
        if as_bool(generator.get("use_conveyor"), False):
            setup_commands.append(("gas_conveyor", {"kind": "set_use_conveyor", "block_entity_id": entity_id(generator), "enabled": False}))
        if not as_bool(generator.get("gas_auto_refill"), False):
            setup_commands.append(("gas_auto_refill", {"kind": "set_gas_auto_refill", "block_entity_id": entity_id(generator), "enabled": True}))
        current_ice = inventory_amount(generator, is_ice_item)
        target_ice = gas_generator_target_ice(generator)
        if target_ice > 0 and current_ice < target_ice and (as_bool(generator.get("enabled"), True) or fill_offline):
            source = find_item_source(
                blocks,
                is_ice_item,
                excluded_entity_id=entity_id(generator),
                source_block_predicate=lambda block: not is_managed_machine_block(block),
            )
            if source is None:
                skipped["ice_source_missing"] += 1
            else:
                source_block, source_inventory, source_item = source
                setup_commands.append(
                    (
                        "gas_ice",
                        {
                            "kind": "transfer_item",
                            "source_entity_id": entity_id(source_block),
                            "source_inventory_index": as_int(source_inventory.get("index"), 0),
                            "destination_entity_id": entity_id(generator),
                            "destination_inventory_index": first_inventory_index(generator),
                            "item_type_id": str(source_item.get("type_id", "MyObjectBuilder_Ore")),
                            "item_subtype_id": str(source_item.get("subtype_id", "Ice")),
                            "reason": "gas_generator_topup",
                            "amount": min(target_ice - current_ice, as_float(source_item.get("amount"), 0)),
                        },
                    )
                )
        for module, setup_command in setup_commands:
            if len(commands) >= max_machine:
                skipped["budget"] += 1
                break
            setup_command["command_id"] = command_id(request, module, len(commands) + 1)
            commands.append(setup_command)
            proposed += 1
        if len(commands) >= max_machine:
            break
    if not generators:
        skipped["gas_generator_missing"] += 1
    return module_summary(True, gas_blocks, proposed, skipped)


def plan_reactor_balancing(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    commands: list[dict[str, Any]],
    max_machine: int,
) -> dict[str, Any]:
    enabled = as_bool(config.get("enableUraniumBalancing"), True)
    reactors = managed_machine_blocks(blocks, config, lambda block: as_bool(block.get("is_reactor"), False))
    skipped: Counter[str] = Counter()
    proposed = 0
    if not enabled:
        return module_summary(False, reactors, proposed, {"disabled": 1})
    has_uranium = has_item(blocks, lambda item: "uranium" in str(item.get("subtype_id", "")).lower())
    if not has_uranium:
        skipped["uranium_source_missing"] += 1
    target_uranium = max(0.0, as_float(config.get("uraniumAmountLargeGrid"), 100))
    fill_offline = as_bool(config.get("fillOfflineReactors"), False)
    for reactor in reactors:
        setup_commands = []
        if has_uranium and not as_bool(reactor.get("enabled"), True):
            setup_commands.append(
                ("reactor_enable", {"kind": "set_block_enabled", "block_entity_id": entity_id(reactor), "enabled": True})
            )
        if as_bool(reactor.get("use_conveyor"), False):
            setup_commands.append(
                ("reactor_conveyor", {"kind": "set_use_conveyor", "block_entity_id": entity_id(reactor), "enabled": False})
            )
        current_uranium = inventory_amount(reactor, lambda item: "uranium" in str(item.get("subtype_id", "")).lower())
        if has_uranium and target_uranium > 0 and current_uranium < target_uranium and (as_bool(reactor.get("enabled"), True) or fill_offline):
            source = find_item_source(
                blocks,
                lambda item: "uranium" in str(item.get("subtype_id", "")).lower(),
                excluded_entity_id=entity_id(reactor),
            )
            if source is None:
                skipped["uranium_source_missing"] += 1
            else:
                source_block, source_inventory, source_item = source
                setup_commands.append(
                    (
                        "reactor_uranium",
                        {
                            "kind": "transfer_item",
                            "source_entity_id": entity_id(source_block),
                            "source_inventory_index": as_int(source_inventory.get("index"), 0),
                            "destination_entity_id": entity_id(reactor),
                            "destination_inventory_index": first_inventory_index(reactor),
                            "item_type_id": str(source_item.get("type_id", "MyObjectBuilder_Ingot")),
                            "item_subtype_id": str(source_item.get("subtype_id", "Uranium")),
                            "amount": min(target_uranium - current_uranium, as_float(source_item.get("amount"), 0)),
                        },
                    )
                )
        for module, setup_command in setup_commands:
            if len(commands) >= max_machine:
                skipped["budget"] += 1
                break
            setup_command["command_id"] = command_id(request, module, len(commands) + 1)
            commands.append(setup_command)
            proposed += 1
        if len(commands) >= max_machine:
            break
    if not reactors:
        skipped["reactor_missing"] += 1
    return module_summary(True, reactors, proposed, skipped)


def empty_module(reason: str) -> dict[str, Any]:
    return {"enabled": False, "apply_state": "skipped", "scanned_blocks": 0, "proposed_commands": 0, "skipped_reasons": {reason: 1}}


def module_summary(enabled: bool, blocks: list[dict[str, Any]], proposed: int, skipped: Counter[str] | dict[str, int]) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "apply_state": "immediate" if enabled else "disabled",
        "scanned_blocks": len(blocks),
        "proposed_commands": proposed,
        "skipped_reasons": dict(skipped),
    }


def foundation_candidate_cap(blocks: list[dict[str, Any]], max_machine: int) -> int:
    if max_machine <= 0:
        return 0
    return max(max_machine, len(blocks) * 4 + len(LCD_KEYWORDS))


def report_text(
    label: str,
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    target_lcd: dict[str, Any] | None = None,
) -> str:
    if label == "inventory":
        return render_inventory_lcd(request, blocks, target_lcd)
    if label == "autocrafting":
        return render_autocrafting_lcd(request, blocks)
    if label == "main":
        return render_main_lcd(request, blocks)
    return render_auxiliary_lcd(label, blocks)


def render_main_lcd(request: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    cargo = count_blocks(blocks, "is_cargo")
    refineries = count_blocks(blocks, "is_refinery")
    generators = count_blocks(blocks, "is_gas_generator")
    reactors = count_blocks(blocks, "is_reactor")
    assemblers = count_blocks(blocks, "is_assembler")
    inventories = sum(len(block.get("inventories") or []) for block in blocks if isinstance(block.get("inventories"), list))
    items = 0
    for block in blocks:
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if isinstance(inventory, dict):
                items += len(inventory.get("items") or [])
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    lines = [
        "Isy's Inventory Manager",
        "========================",
        "",
        "Script is running in station mode",
        "",
        "Task: NOVALI bridge planning",
        "Script step: foundation / offloaded",
        "",
        "Managed blocks:",
        f"  {cargo} Cargo Containers",
        f"  {inventories} inventories contain {items} item stacks",
    ]
    if refineries:
        lines.append(f"  {refineries} Refineries: Ore Balancing {'ON' if as_bool(config.get('enableOreBalancing'), True) else 'OFF'}")
    if generators:
        lines.append(f"  {generators} O2/H2 Generators: Ice Balancing {'ON' if as_bool(config.get('enableIceBalancing'), True) else 'OFF'}")
    if reactors:
        lines.append(f"  {reactors} Reactors: Uranium Balancing {'ON' if as_bool(config.get('enableUraniumBalancing'), True) else 'OFF'}")
    if assemblers:
        lines.append(
            f"  {assemblers} Assemblers: Craft {'ON' if as_bool(config.get('enableAutocrafting'), True) else 'OFF'} | "
            f"Uncraft {'ON' if as_bool(config.get('enableAutodisassembling'), False) else 'OFF'} | "
            f"Cleanup {'ON' if as_bool(config.get('enableAssemblerCleanup'), False) else 'OFF'}"
        )
    lines.extend(["", "Last Action:", f"Bridge sequence {request.get('sequence', 0)} processed"])
    return "\n".join(lines).rstrip() + "\n"


def render_inventory_lcd(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    target_lcd: dict[str, Any] | None = None,
) -> str:
    lcd_keyword = str((request.get("worker_config") or {}).get("inventoryLCDKeyword") or DEFAULT_LCD_KEYWORDS["inventory"])
    inventory_lcd = target_lcd or first_named(blocks, lcd_keyword)
    custom_data = str((inventory_lcd or {}).get("custom_data") or "")
    instructions = inventory_lcd_instructions(custom_data)
    if not instructions:
        return inventory_lcd_help_text()
    items = summarize_inventory_items(blocks)
    lines: list[str] = []
    for instruction in instructions:
        rendered = render_inventory_instruction(instruction, items)
        if rendered:
            lines.extend(rendered)
    return "\n".join(lines).strip() + "\n" if lines else "Nothing to show at the moment..."


def render_autocrafting_lcd(request: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    lcd_keyword = str(config.get("autocraftingKeyword") or DEFAULT_LCD_KEYWORDS["autocrafting"])
    autocrafting_lcd = first_named(blocks, lcd_keyword)
    custom_data = str((autocrafting_lcd or {}).get("custom_data") or "")
    assemblers = [block for block in blocks if same_construct(block) and as_bool(block.get("is_assembler"), False)]
    blueprint_specs = autocrafting_blueprint_specs(request, blocks)
    lines = ["IIM Autocrafting", "================", ""]
    if not assemblers:
        lines.extend(["Autocrafting error!", "", "No usable assemblers found!", "Build or enable assemblers to enable autocrafting!"])
        return "\n".join(lines).rstrip() + "\n"

    goals = autocrafting_goals(custom_data)
    if not goals:
        known_items = autocrafting_known_items(blocks, blueprint_specs)
        if known_items:
            lines.append("Known craftable items:")
            for item in known_items:
                lines.append(f"$[OK] {item['name']}: {format_isy_amount(item['amount'])} / 0")
            lines.extend(["", "Add wanted amounts in this LCD's custom data to enable queue planning."])
            if as_bool(config.get("showAutocraftingModifiers"), True):
                lines.extend(["", "---", "", autocrafting_modifiers_text()])
            return "\n".join(lines).rstrip() + "\n"
        lines.extend(
            [
                "Autocrafting error!",
                "",
                "No items for crafting available!",
                "",
                "If you hid all items, check the custom data of the first autocrafting panel and reenable some of them.",
                "",
                "Otherwise, store or build new items manually!",
            ]
        )
        if as_bool(config.get("showAutocraftingModifiers"), True):
            lines.extend(["", "---", "", autocrafting_modifiers_text()])
        return "\n".join(lines).rstrip() + "\n"

    item_totals = autocrafting_item_amounts(blocks, blueprint_specs)
    lines.append("Current autocrafting targets:")
    for goal in autocrafting_display_entries(custom_data, blocks, blueprint_specs):
        spec = component_blueprint_spec(str(goal.get("name", "")), blueprint_specs)
        display_name = str((spec or {}).get("component_subtype") or goal["name"])
        current_key = normalize_recipe_key(display_name)
        current = item_totals.get(current_key, 0)
        wanted = as_float(goal.get("wanted"), 0)
        marker = "$[A:Wait]" if current < wanted else "$[OK]"
        lines.append(f"{marker} {display_name}: {format_isy_amount(current)} / {format_isy_amount(wanted)}")
    if as_bool(config.get("showAutocraftingModifiers"), True):
        lines.extend(["", "---", "", autocrafting_modifiers_text()])
    return "\n".join(lines).rstrip() + "\n"


def autocrafting_goals(custom_data: str) -> list[dict[str, Any]]:
    goals: list[dict[str, Any]] = []
    for entry in autocrafting_configured_entries(custom_data):
        if as_float(entry.get("wanted"), 0) > 0:
            goals.append(entry)
    return goals


def autocrafting_configured_entries(custom_data: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in custom_data.splitlines():
        line = raw.strip()
        if not line or line.startswith("@") or line.startswith("-") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        wanted_text = value.strip().split()[0] if value.strip() else ""
        try:
            wanted = float(wanted_text)
        except ValueError:
            continue
        if name and wanted >= 0:
            entries.append({"name": name, "wanted": wanted})
    return entries


def autocrafting_display_entries(custom_data: str, blocks: list[dict[str, Any]], blueprint_specs: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    entries = autocrafting_configured_entries(custom_data)
    seen = {str(entry.get("name", "")).lower() for entry in entries}
    for item in autocrafting_known_items(blocks, blueprint_specs):
        name = str(item.get("name", "")).strip()
        if name and name.lower() not in seen:
            entries.append({"name": name, "wanted": 0.0})
            seen.add(name.lower())
    return entries


def autocrafting_known_items(blocks: list[dict[str, Any]], blueprint_specs: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    known: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in summarize_inventory_items(blocks):
        if str(item.get("category", "")).lower() not in {"component", "consumableitem"}:
            continue
        spec = component_blueprint_spec(str(item.get("name", "")), blueprint_specs)
        name = str((spec or {}).get("component_subtype") or item.get("name", "")).strip()
        if not name:
            continue
        known.append({**item, "name": name, "category": "Component" if recipe_machine_type(spec or {}) != "food_processor" else "ConsumableItem"})
        seen.add(name.lower())
    for block in blocks:
        if not same_construct(block) or not as_bool(block.get("is_assembler"), False):
            continue
        for queued in block.get("production_queue") if isinstance(block.get("production_queue"), list) else []:
            if not isinstance(queued, dict):
                continue
            subtype = component_subtype_from_blueprint(str(queued.get("blueprint_id", "")), blueprint_specs)
            if not subtype or subtype.lower() in seen:
                continue
            known.append({"name": subtype, "category": "Component", "amount": 0.0, "search": subtype})
            seen.add(subtype.lower())
    has_food_context = any(same_construct(block) and is_food_processor(block) for block in blocks) or has_item(blocks, is_consumable_item)
    recipe_specs = list(FOOD_RECIPES.values()) if has_food_context else []
    recipe_specs.extend(list((blueprint_specs or {}).values()))
    for spec in recipe_specs:
        name = str(spec.get("component_subtype", "")).strip()
        if not name or name.lower() in seen:
            continue
        category = "ConsumableItem" if recipe_machine_type(spec) == "food_processor" else "Component"
        known.append({"name": name, "category": category, "amount": 0.0, "search": name})
        seen.add(name.lower())
    return known


def autocrafting_discovered_custom_data(
    autocrafting_lcd: dict[str, Any] | None,
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    blueprint_specs: dict[str, dict[str, Any]] | None = None,
) -> str:
    if autocrafting_lcd is None:
        return ""
    known_items = autocrafting_known_items(blocks, blueprint_specs)
    if not known_items:
        return ""
    current = str(autocrafting_lcd.get("custom_data") or "")
    existing = {line.split("=", 1)[0].strip().lower() for line in current.splitlines() if "=" in line}
    existing_keys = {normalize_recipe_key(name) for name in existing}
    default_modifier = str(config.get("defaultModifier") or "").strip()
    additions = []
    for item in known_items:
        name = str(item.get("name", "")).strip()
        spec = component_blueprint_spec(name, blueprint_specs)
        aliases = [name]
        if isinstance((spec or {}).get("aliases"), list):
            aliases.extend(str(alias) for alias in (spec or {}).get("aliases", []))
        if not name or name.lower() in existing or any(normalize_recipe_key(alias) in existing_keys for alias in aliases):
            continue
        suffix = f" {default_modifier}" if default_modifier else ""
        additions.append(f"{name}=0{suffix}")
    if not additions:
        return ""
    lines = [line.rstrip() for line in current.splitlines()]
    if not any(line.strip().startswith("@") for line in lines):
        lines.insert(0, "@0 " + str(config.get("autocraftingKeyword") or DEFAULT_LCD_KEYWORDS["autocrafting"]))
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(additions)
    return "\n".join(lines).strip() + "\n"


def supports_custom_data_commands(request: dict[str, Any]) -> bool:
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    version = str(state.get("shim_version", "")).lower()
    return "v13" in version or "customdata" in version


def autocrafting_modifiers_text() -> str:
    return (
        "Modifiers (append after wanted amount):\n"
        "'A' - Assemble only\n"
        "'D' - Disassemble only\n"
        "'P' - Add to priority queue\n"
        "'H' - Hide this item\n"
        "'I' - Ignore stock level"
    )


def render_auxiliary_lcd(label: str, blocks: list[dict[str, Any]]) -> str:
    if label == "warnings":
        return "- No problems detected -"
    if label == "actions":
        return "- Nothing to show yet -"
    if label == "performance":
        return "Isy's Inventory Manager Performance\n====================================\n\nWorker planning active\n"
    return ""


def inventory_lcd_help_text() -> str:
    return (
        "This screen supports (partial) item or type names, regex and Echo commands. All settings are done in the custom data.\n"
        "Examples:\n"
        "  @0 IIM-inventory\n"
        "  Component\n"
        "  SteelPlate\n"
        "  Iron\\W\n"
        "  Echo My cool text\n\n"
        "Optionally, add a max amount for the bars as a 2nd parameter.\n"
        "Example:\n"
        "  @0 IIM-inventory\n"
        "  Ingot 100000\n\n"
        "At last, add any of these 6 modifiers (optional):\n"
        "  'noHeading' to hide the heading\n"
        "  'singleLine' to force one line per item\n"
        "  'noBar' to hide the bars\n"
        "  'noScroll' to prevent the screen from scrolling\n"
        "  'hideEmpty' to hide items that have an amount of 0\n"
        "  'hideType' to hide the type behind the item name\n\n"
        "Example:\n"
        "  @0 IIM-inventory\n"
        "  Component 100000 noBar noHeading hideEmpty hideType\n\n"
        "Full guide: https://steamcommunity.com/sharedfiles/filedetails/?id=1226261795"
    )


def inventory_lcd_instructions(custom_data: str) -> list[str]:
    lines = []
    for raw in custom_data.splitlines():
        line = raw.strip()
        if not line or line.startswith("@"):
            continue
        lines.append(line)
    return lines


def render_inventory_instruction(instruction: str, items: list[dict[str, Any]]) -> list[str]:
    lowered = instruction.lower()
    if lowered.startswith("echoc"):
        return [instruction[5:].strip()]
    if lowered.startswith("echor"):
        return [instruction[5:].strip()]
    if lowered.startswith("echo"):
        return [instruction[4:].strip()]
    parts = instruction.split()
    if not parts:
        return []
    filter_text = parts[0]
    max_amount = -1.0
    if len(parts) >= 2:
        try:
            max_amount = float(parts[1])
        except ValueError:
            max_amount = -1.0
    no_heading = "noheading" in lowered
    no_bar = "nobar" in lowered
    hide_empty = "hideempty" in lowered
    hide_type = "hidetype" in lowered
    single_line = "singleline" in lowered
    matches = [item for item in items if filter_text.lower() in item["search"].lower()]
    if hide_empty:
        matches = [item for item in matches if item["amount"] > 0]
    if not matches:
        return [
            "Error!",
            "",
            f"No items containing '{filter_text}' found!",
            "",
            "Check the custom data of this LCD and enter a valid type, item name or regex expression!",
        ]
    lines: list[str] = []
    if not no_heading:
        lines.extend([f"Itemfilter: '{filter_text}'", ""])
    for item in matches:
        display_name = item["name"] if hide_type else f"{item['name']} ({item['category']})"
        target = max_amount if max_amount > 0 else max(item["amount"], 1)
        if no_bar or single_line:
            lines.append(f"{display_name} {format_isy_amount(item['amount'])} / {format_isy_amount(target)}")
        else:
            percent = min(1.0, item["amount"] / target) if target > 0 else 0
            bar = "[" + ("|" * int(percent * 20)).ljust(20, ".") + "]"
            lines.append(f"{display_name}")
            lines.append(f"  {bar} {format_isy_amount(item['amount'])} / {format_isy_amount(target)}")
    return lines


def format_isy_amount(value: float) -> str:
    if value >= 1000000:
        return f"{value / 1000000:0.1f}M"
    if value >= 1000:
        return f"{value / 1000:0.1f}K"
    return f"{value:0.0f}"


def count_blocks(blocks: list[dict[str, Any]], key: str) -> int:
    return sum(1 for block in blocks if same_construct(block) and as_bool(block.get(key), False))


def is_food_processor(block: dict[str, Any]) -> bool:
    if as_bool(block.get("is_food_processor"), False):
        return True
    haystack = " ".join(str(block.get(key, "")) for key in ("name", "type", "subtype")).lower()
    if "food" in haystack and "processor" in haystack:
        return True
    for queued in block.get("production_queue") if isinstance(block.get("production_queue"), list) else []:
        if isinstance(queued, dict) and "mealpack" in str(queued.get("blueprint_id", "")).lower():
            return True
    for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
        if not isinstance(inventory, dict):
            continue
        for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
            if isinstance(item, dict) and (is_consumable_item(item) or str(item.get("subtype_id", "")).lower() == "algae"):
                return True
    return False


def first_named(blocks: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    lowered = keyword.lower()
    for block in blocks:
        if lowered in str(block.get("name", "")).lower():
            return block
    return None


def named_blocks(blocks: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    lowered = keyword.lower()
    return [block for block in blocks if lowered in str(block.get("name", "")).lower()]


def command_id(request: dict[str, Any], module: str, index: int) -> str:
    return f"{request.get('bridge_id', 'bridge')}:{request.get('sequence', 0)}:{module}:{index}"


def entity_id(block: dict[str, Any]) -> int:
    return as_int(block.get("entity_id"), 0)


def is_ice_item(item: dict[str, Any]) -> bool:
    return "ice" in str(item.get("subtype_id", "")).lower()


def is_component_item(item: dict[str, Any]) -> bool:
    return "component" in str(item.get("type_id", "")).lower()


def is_ingot_item(item: dict[str, Any]) -> bool:
    return "ingot" in str(item.get("type_id", "")).lower()


def is_ammo_item(item: dict[str, Any]) -> bool:
    return "ammo" in str(item.get("type_id", "")).lower()


def is_tool_item(item: dict[str, Any]) -> bool:
    type_id = str(item.get("type_id", "")).lower()
    return "physicalgunobject" in type_id


def is_bottle_item(item: dict[str, Any]) -> bool:
    type_id = str(item.get("type_id", "")).lower()
    return "oxygencontainerobject" in type_id or "gascontainerobject" in type_id


def is_consumable_item(item: dict[str, Any]) -> bool:
    return "consumableitem" in str(item.get("type_id", "")).lower()


def item_matches_material(item: dict[str, Any], material: dict[str, Any]) -> bool:
    expected_type = str(material.get("type_id", "")).lower()
    expected_subtype = str(material.get("subtype_id", "")).lower()
    actual_type = str(item.get("type_id", "")).lower()
    actual_subtype = str(item.get("subtype_id", "")).lower()
    return actual_type == expected_type and actual_subtype == expected_subtype


def is_ingot_subtype(item: dict[str, Any], subtype: str) -> bool:
    return "ingot" in str(item.get("type_id", "")).lower() and str(item.get("subtype_id", "")).lower() == subtype.lower()


def is_refinery_ore_item(item: dict[str, Any]) -> bool:
    return "ore" in str(item.get("type_id", "")).lower() and not is_ice_item(item)


def is_ore_subtype(item: dict[str, Any], subtype: str) -> bool:
    return is_refinery_ore_item(item) and str(item.get("subtype_id", "")).lower() == subtype.lower()


def normalize_component_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def component_recipe(name: str) -> dict[str, Any] | None:
    key = normalize_component_key(name)
    return COMPONENT_RECIPES.get(key)


def food_recipe(name: str) -> dict[str, Any] | None:
    key = normalize_component_key(name)
    return FOOD_RECIPES.get(key)


def built_in_recipe_by_blueprint(blueprint_id: str) -> dict[str, Any] | None:
    lowered = blueprint_id.lower()
    for spec in list(COMPONENT_RECIPES.values()) + list(FOOD_RECIPES.values()) + list(ASSEMBLER_RECIPES.values()):
        if str(spec.get("blueprint_id", "")).lower() == lowered:
            return spec
    return None


def component_blueprint_spec(name: str, blueprint_specs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    recipe = component_recipe(name)
    if recipe is not None:
        return recipe
    recipe = food_recipe(name)
    if recipe is not None:
        return recipe
    recipe = ASSEMBLER_RECIPES.get(normalize_component_key(name))
    if recipe is not None:
        return recipe
    key = normalize_component_key(name)
    if not key:
        return None
    return (blueprint_specs or {}).get(key)


def component_recipe_by_subtype(subtype: str) -> dict[str, Any] | None:
    lowered = subtype.lower()
    for spec in list(COMPONENT_RECIPES.values()) + list(FOOD_RECIPES.values()) + list(ASSEMBLER_RECIPES.values()):
        if str(spec["component_subtype"]).lower() == lowered:
            return spec
    return None


def recipe_machine_type(spec: dict[str, Any]) -> str:
    return str(spec.get("machine_type") or "assembler")


def autocrafting_blueprint_specs(request: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    learned = request.get("autocrafting_blueprints") if isinstance(request.get("autocrafting_blueprints"), dict) else {}
    items = learned.get("items") if isinstance(learned.get("items"), dict) else {}
    for item in items.values():
        if not isinstance(item, dict):
            continue
        add_blueprint_spec(specs, item)
    for block in blocks:
        if not same_construct(block) or not as_bool(block.get("is_assembler"), False):
            continue
        for queued in block.get("production_queue") if isinstance(block.get("production_queue"), list) else []:
            if not isinstance(queued, dict):
                continue
            blueprint_id = str(queued.get("blueprint_id", "")).strip()
            if not blueprint_id:
                continue
            name = component_name_from_blueprint(blueprint_id)
            if not name:
                continue
            add_blueprint_spec(specs, {"component_subtype": name, "blueprint_id": blueprint_id, "aliases": [name, blueprint_suffix(blueprint_id)]})
    return specs


def add_blueprint_spec(specs: dict[str, dict[str, Any]], spec: dict[str, Any]) -> None:
    component_subtype = str(spec.get("component_subtype", "")).strip()
    blueprint_id = str(spec.get("blueprint_id", "")).strip()
    builtin = built_in_recipe_by_blueprint(blueprint_id)
    if builtin is not None:
        spec = builtin
        component_subtype = str(spec.get("component_subtype", "")).strip()
        blueprint_id = str(spec.get("blueprint_id", "")).strip()
    if not component_subtype or not blueprint_id:
        return
    aliases = [component_subtype]
    if isinstance(spec.get("aliases"), list):
        aliases.extend(str(alias).strip() for alias in spec["aliases"] if str(alias).strip())
    suffix = blueprint_suffix(blueprint_id)
    if suffix:
        aliases.append(suffix)
    normalized = {
        "component_subtype": component_subtype,
        "blueprint_id": blueprint_id,
        "aliases": sorted(set(aliases)),
    }
    for key in ("ingots", "materials", "machine_type", "output_type_id"):
        if key in spec:
            normalized[key] = spec[key]
    for alias in normalized["aliases"]:
        key = normalize_component_key(alias)
        if key:
            specs[key] = normalized


def component_amounts(blocks: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for block in blocks:
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if not isinstance(inventory, dict):
                continue
            for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
                if isinstance(item, dict) and is_component_item(item):
                    subtype = str(item.get("subtype_id", "")).lower()
                    totals[subtype] = totals.get(subtype, 0.0) + as_float(item.get("amount"), 0)
    return totals


def autocrafting_item_amounts(blocks: list[dict[str, Any]], blueprint_specs: dict[str, dict[str, Any]] | None = None) -> dict[str, float]:
    totals: dict[str, float] = {}
    specs_by_output = {
        normalize_recipe_key(str(spec.get("component_subtype", ""))): spec
        for spec in list(COMPONENT_RECIPES.values())
        + list(FOOD_RECIPES.values())
        + list(ASSEMBLER_RECIPES.values())
        + list((blueprint_specs or {}).values())
        if str(spec.get("component_subtype", "")).strip()
    }
    for block in blocks:
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if not isinstance(inventory, dict):
                continue
            for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
                if not isinstance(item, dict):
                    continue
                subtype = str(item.get("subtype_id", ""))
                key = normalize_recipe_key(subtype)
                if is_component_item(item) or is_consumable_item(item) or key in specs_by_output:
                    totals[key] = totals.get(key, 0.0) + as_float(item.get("amount"), 0)
    return totals


def queued_component_amounts(assemblers: list[dict[str, Any]], blueprint_specs: dict[str, dict[str, Any]] | None = None) -> dict[str, float]:
    totals: dict[str, float] = {}
    for assembler in assemblers:
        for item in assembler.get("production_queue") if isinstance(assembler.get("production_queue"), list) else []:
            if not isinstance(item, dict):
                continue
            blueprint = str(item.get("blueprint_id", ""))
            component_subtype = component_subtype_from_blueprint(blueprint, blueprint_specs)
            if not component_subtype:
                continue
            key = normalize_recipe_key(component_subtype)
            totals[key] = totals.get(key, 0.0) + as_float(item.get("amount"), 0)
    return totals


def queued_material_needs(
    assembler: dict[str, Any],
    blueprint_specs: dict[str, dict[str, Any]] | None = None,
    queue_limit: int | None = None,
) -> dict[str, float]:
    totals, _unknown_count = queued_material_needs_with_unknowns(assembler, blueprint_specs, queue_limit)
    return totals


def queued_material_needs_with_unknowns(
    assembler: dict[str, Any],
    blueprint_specs: dict[str, dict[str, Any]] | None = None,
    queue_limit: int | None = None,
) -> tuple[dict[str, float], int]:
    totals: dict[str, float] = {}
    unknown_count = 0
    queue = assembler.get("production_queue") if isinstance(assembler.get("production_queue"), list) else []
    if queue_limit is not None:
        queue = queue[: max(0, queue_limit)]
    for item in queue:
        if not isinstance(item, dict):
            continue
        spec = recipe_spec_from_blueprint(str(item.get("blueprint_id", "")), blueprint_specs)
        if spec is None:
            unknown_count += 1
            continue
        amount = as_float(item.get("amount"), 0)
        if amount <= 0:
            continue
        for material in recipe_materials(spec):
            needed = amount * as_float(material.get("amount"), 0)
            if needed > 0:
                key = material_key(material)
                totals[key] = totals.get(key, 0.0) + needed
    return totals, unknown_count


def recipe_spec_from_blueprint(blueprint_id: str, blueprint_specs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    spec = built_in_recipe_by_blueprint(blueprint_id)
    if spec is not None:
        return spec
    lowered = blueprint_id.lower()
    for candidate in (blueprint_specs or {}).values():
        if str(candidate.get("blueprint_id", "")).lower() == lowered:
            if recipe_materials(candidate):
                return candidate
            return None
    component_subtype = component_subtype_from_blueprint(blueprint_id, blueprint_specs)
    if not component_subtype:
        return None
    return component_recipe_by_subtype(component_subtype)


def recipe_materials(spec: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(spec.get("materials"), list):
        return [material for material in spec["materials"] if isinstance(material, dict)]
    ingots = spec.get("ingots") if isinstance(spec.get("ingots"), dict) else {}
    return [
        {"type_id": "MyObjectBuilder_Ingot", "subtype_id": str(ingot_subtype), "amount": as_float(per_item, 0)}
        for ingot_subtype, per_item in ingots.items()
    ]


def material_key(material: dict[str, Any]) -> str:
    return str(material.get("type_id") or "") + "/" + str(material.get("subtype_id") or "")


def material_from_key(key: str) -> dict[str, Any]:
    type_id, _, subtype_id = key.partition("/")
    return {"type_id": type_id, "subtype_id": subtype_id}


def add_material_needs(
    material_needs_by_assembler: dict[int, dict[str, float]],
    assembler: dict[str, Any],
    spec: dict[str, Any],
    amount: float,
) -> None:
    materials = recipe_materials(spec)
    if amount <= 0 or not materials:
        return
    bucket = material_needs_by_assembler.setdefault(entity_id(assembler), {})
    for material in materials:
        needed = amount * as_float(material.get("amount"), 0)
        if needed > 0:
            key = material_key(material)
            bucket[key] = bucket.get(key, 0.0) + needed


def feed_autocrafting_materials(
    blocks: list[dict[str, Any]],
    assemblers: list[dict[str, Any]],
    material_needs_by_assembler: dict[int, dict[str, float]],
    append_command: Any,
    skipped: Counter[str],
) -> None:
    for assembler in assemblers:
        material_needs = material_needs_by_assembler.get(entity_id(assembler), {})
        for key, total_need in material_needs.items():
            material = material_from_key(key)
            input_amount = inventory_amount_in_inventory(
                assembler,
                first_inventory_index(assembler),
                lambda item, expected=material: item_matches_material(item, expected),
            )
            needed = max(0.0, as_float(total_need, 0) - input_amount)
            if needed <= 0:
                continue
            source = find_item_source(
                blocks,
                lambda item, expected=material: item_matches_material(item, expected),
                excluded_entity_id=entity_id(assembler),
                source_block_predicate=lambda source_block: not is_managed_machine_block(source_block),
            )
            if source is None:
                skipped["material_source_missing"] += 1
                continue
            source_block, source_inventory, source_item = source
            if not append_command(
                "autocrafting_material",
                {
                    "kind": "transfer_item",
                    "source_entity_id": entity_id(source_block),
                    "source_inventory_index": as_int(source_inventory.get("index"), 0),
                    "destination_entity_id": entity_id(assembler),
                    "destination_inventory_index": first_inventory_index(assembler),
                    "item_type_id": str(source_item.get("type_id", material.get("type_id", ""))),
                    "item_subtype_id": str(source_item.get("subtype_id", material.get("subtype_id", ""))),
                    "reason": "autocrafting_material",
                    "amount": min(needed, as_float(source_item.get("amount"), 0)),
                },
            ):
                return


def cleanup_assembler_input_ingots(
    blocks: list[dict[str, Any]],
    assemblers: list[dict[str, Any]],
    config: dict[str, Any],
    blueprint_specs: dict[str, dict[str, Any]] | None,
    append_command: Any,
    skipped: Counter[str],
) -> None:
    ingot_target = find_ingot_target(blocks, config)
    if ingot_target is None:
        if any(assembler_input_ingot_items(assembler) for assembler in assemblers):
            skipped["ingot_cargo_missing"] += 1
        return
    for assembler in assemblers:
        input_index = first_inventory_index(assembler)
        input_items = assembler_input_ingot_items(assembler)
        if not input_items:
            continue
        needed, unknown_count = queued_material_needs_with_unknowns(assembler, blueprint_specs, 3)
        if unknown_count > 0:
            skipped["assembler_input_unknown_blueprint"] += unknown_count
            continue
        kept: dict[str, float] = {}
        for item in input_items:
            material = {"type_id": str(item.get("type_id", "")), "subtype_id": str(item.get("subtype_id", ""))}
            key = material_key(material)
            available = as_float(item.get("amount"), 0)
            required_remaining = max(0.0, needed.get(key, 0.0) - kept.get(key, 0.0))
            keep_amount = min(available, required_remaining)
            excess = max(0.0, available - keep_amount)
            kept[key] = kept.get(key, 0.0) + keep_amount
            if excess <= 0:
                continue
            if not append_command(
                "assembler_input",
                {
                    "kind": "transfer_item",
                    "source_entity_id": entity_id(assembler),
                    "source_inventory_index": input_index,
                    "destination_entity_id": entity_id(ingot_target),
                    "destination_inventory_index": first_inventory_index(ingot_target),
                    "item_type_id": str(item.get("type_id", "MyObjectBuilder_Ingot")),
                    "item_subtype_id": str(item.get("subtype_id", "")),
                    "reason": "assembler_input_cleanup",
                    "amount": excess,
                },
            ):
                return


def assembler_input_ingot_items(assembler: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = inventory_by_index(assembler, first_inventory_index(assembler))
    if inventory is None:
        return []
    return [
        item
        for item in (inventory.get("items") if isinstance(inventory.get("items"), list) else [])
        if isinstance(item, dict) and is_ingot_item(item) and as_float(item.get("amount"), 0) > 0
    ]


def consolidate_assembler_queues(assemblers: list[dict[str, Any]], append_command: Any, skipped: Counter[str]) -> None:
    for assembler in assemblers:
        queue = assembler.get("production_queue") if isinstance(assembler.get("production_queue"), list) else []
        first_index_by_blueprint: dict[str, int] = {}
        next_target_by_blueprint: dict[str, int] = {}
        for index, item in enumerate(queue):
            if not isinstance(item, dict):
                continue
            blueprint_id = str(item.get("blueprint_id", "")).strip()
            if not blueprint_id:
                continue
            if blueprint_id not in first_index_by_blueprint:
                first_index_by_blueprint[blueprint_id] = index
                next_target_by_blueprint[blueprint_id] = index + 1
                continue
            target_index = next_target_by_blueprint.get(blueprint_id, first_index_by_blueprint[blueprint_id] + 1)
            next_target_by_blueprint[blueprint_id] = target_index + 1
            if index == target_index:
                continue
            queue_item_id = as_int(item.get("item_id"), -1)
            if queue_item_id < 0:
                skipped["assembler_queue_item_id_missing"] += 1
                continue
            if not append_command(
                "assembler_queue",
                {
                    "kind": "move_assembler_queue_item",
                    "block_entity_id": entity_id(assembler),
                    "queue_item_id": queue_item_id,
                    "target_index": target_index,
                    "reason": "assembler_queue_consolidation",
                },
            ):
                return


def autocrafting_material_shortages(
    request: dict[str, Any],
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    assemblers: list[dict[str, Any]],
    blueprint_specs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, float]:
    component_assemblers = [block for block in assemblers if not is_food_processor(block)]
    material_needs_by_assembler = {
        entity_id(assembler): queued_material_needs(assembler, blueprint_specs) for assembler in assemblers
    }
    autocrafting_lcd = first_named(
        [block for block in blocks if same_construct(block) and (as_bool(block.get("is_lcd"), False) or as_int(block.get("surface_count"), 0) > 0)],
        str(config.get("autocraftingKeyword") or DEFAULT_LCD_KEYWORDS["autocrafting"]),
    )
    if component_assemblers and autocrafting_lcd:
        batch_size = max(1.0, as_float(config.get("autocraftingQueueBatchSize"), DEFAULT_AUTOMATION_BATCH_SIZE))
        component_totals = autocrafting_item_amounts(blocks, blueprint_specs)
        queued_totals = queued_component_amounts(assemblers, blueprint_specs)
        assembler = component_assemblers[as_int(request.get("sequence"), 0) % len(component_assemblers)]
        for goal in autocrafting_goals(str(autocrafting_lcd.get("custom_data") or "")):
            spec = component_blueprint_spec(str(goal.get("name", "")), blueprint_specs)
            if spec is None or recipe_machine_type(spec) != "assembler":
                continue
            component_subtype = str(spec["component_subtype"])
            wanted = as_float(goal.get("wanted"), 0)
            current = component_totals.get(normalize_recipe_key(component_subtype), 0.0)
            queued = queued_totals.get(normalize_recipe_key(component_subtype), 0.0)
            amount = min(batch_size, max(0.0, wanted - current - queued))
            add_material_needs(material_needs_by_assembler, assembler, spec, amount)

    needs: dict[str, float] = {}
    assembler_input: dict[str, float] = {}
    for assembler in assemblers:
        input_inventory_index = first_inventory_index(assembler)
        material_needs = material_needs_by_assembler.get(entity_id(assembler), {})
        for key, amount in material_needs.items():
            material = material_from_key(key)
            if "ingot" not in str(material.get("type_id", "")).lower():
                continue
            ingot_subtype = str(material.get("subtype_id", ""))
            needs[ingot_subtype] = needs.get(ingot_subtype, 0.0) + as_float(amount, 0)
            assembler_input[ingot_subtype] = assembler_input.get(ingot_subtype, 0.0) + inventory_amount_in_inventory(
                assembler,
                input_inventory_index,
                lambda item, subtype=ingot_subtype: is_ingot_subtype(item, subtype),
            )

    source_ingots: dict[str, float] = {}
    for block in blocks:
        if not same_construct(block) or is_managed_machine_block(block):
            continue
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if not isinstance(inventory, dict):
                continue
            for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
                if not isinstance(item, dict) or "ingot" not in str(item.get("type_id", "")).lower():
                    continue
                subtype = str(item.get("subtype_id", ""))
                source_ingots[subtype] = source_ingots.get(subtype, 0.0) + as_float(item.get("amount"), 0)

    shortages: dict[str, float] = {}
    for ingot_subtype, total_need in needs.items():
        missing = as_float(total_need, 0) - assembler_input.get(ingot_subtype, 0.0) - source_ingots.get(ingot_subtype, 0.0)
        if missing > 0:
            shortages[ingot_subtype] = missing
    return shortages


def find_priority_refinery_ore_source(
    blocks: list[dict[str, Any]],
    material_shortages: dict[str, float],
    excluded_entity_id: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    for ingot_subtype, _missing in sorted(material_shortages.items(), key=lambda entry: (-entry[1], entry[0].lower())):
        source = find_item_source(
            blocks,
            lambda item, subtype=ingot_subtype: is_ore_subtype(item, subtype),
            excluded_entity_id=excluded_entity_id,
            source_block_predicate=lambda source_block: not is_managed_machine_block(source_block),
        )
        if source is not None:
            return source
    return None


def find_priority_refinery_ore_source_for_refinery(
    blocks: list[dict[str, Any]],
    material_shortages: dict[str, float],
    refinery: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    refinery_id = entity_id(refinery)
    target_ore = refinery_target_fill_ore(refinery)
    refinery_input_index = first_inventory_index(refinery)
    for ingot_subtype, _missing in sorted(material_shortages.items(), key=lambda entry: (-entry[1], entry[0].lower())):
        existing_priority_ore = inventory_amount_in_inventory(
            refinery,
            refinery_input_index,
            lambda item, subtype=ingot_subtype: is_ore_subtype(item, subtype),
        )
        if existing_priority_ore > 0 and existing_priority_ore < target_ore and refinery_has_queued_ore(refinery, ingot_subtype):
            source = find_item_source(
                blocks,
                lambda item, subtype=ingot_subtype: is_ore_subtype(item, subtype),
                excluded_entity_id=refinery_id,
                source_block_predicate=lambda source_block: not is_managed_machine_block(source_block),
            )
            if source is not None:
                return source
    for ingot_subtype, _missing in sorted(material_shortages.items(), key=lambda entry: (-entry[1], entry[0].lower())):
        existing_priority_ore = inventory_amount_in_inventory(
            refinery,
            refinery_input_index,
            lambda item, subtype=ingot_subtype: is_ore_subtype(item, subtype),
        )
        existing_output_ingot = inventory_amount_in_inventory(
            refinery,
            1,
            lambda item, subtype=ingot_subtype: is_ingot_item(item) and str(item.get("subtype_id", "")).lower() == subtype.lower(),
        )
        if existing_priority_ore > 0 or existing_priority_ore >= target_ore or existing_output_ingot > 0 or refinery_has_queued_ore(refinery, ingot_subtype):
            continue
        source = find_item_source(
            blocks,
            lambda item, subtype=ingot_subtype: is_ore_subtype(item, subtype),
            excluded_entity_id=refinery_id,
            source_block_predicate=lambda source_block: not is_managed_machine_block(source_block),
        )
        if source is not None:
            return source
    return None


def find_refinery_fallback_ore_source(
    blocks: list[dict[str, Any]],
    refinery: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    refinery_id = entity_id(refinery)
    for subtype in refinery_active_ore_subtypes(refinery):
        source = find_item_source(
            blocks,
            lambda item, wanted=subtype: is_ore_subtype(item, wanted),
            excluded_entity_id=refinery_id,
            source_block_predicate=lambda source_block: not is_managed_machine_block(source_block),
        )
        if source is not None:
            return source
    return find_item_source(
        blocks,
        is_refinery_ore_item,
        excluded_entity_id=refinery_id,
        source_block_predicate=lambda source_block: not is_managed_machine_block(source_block),
    )


def component_subtype_from_blueprint(blueprint_id: str, blueprint_specs: dict[str, dict[str, Any]] | None = None) -> str:
    lowered = blueprint_id.lower()
    for spec in list(COMPONENT_RECIPES.values()) + list(FOOD_RECIPES.values()):
        if str(spec["blueprint_id"]).lower() == lowered:
            return str(spec["component_subtype"])
    for spec in (blueprint_specs or {}).values():
        if str(spec.get("blueprint_id", "")).lower() == lowered:
            return str(spec.get("component_subtype", ""))
    return ""


def refinery_has_queued_ore(refinery: dict[str, Any], ingot_subtype: str) -> bool:
    expected = f"{normalize_recipe_key(ingot_subtype)}oretoingot"
    queue = refinery.get("production_queue") if isinstance(refinery.get("production_queue"), list) else []
    for entry in queue:
        if not isinstance(entry, dict):
            continue
        suffix = normalize_recipe_key(blueprint_suffix(str(entry.get("blueprint_id", ""))))
        if suffix == expected:
            return True
    return False


def refinery_has_any_queued_ore(refinery: dict[str, Any]) -> bool:
    queue = refinery.get("production_queue") if isinstance(refinery.get("production_queue"), list) else []
    for entry in queue:
        if not isinstance(entry, dict):
            continue
        suffix = normalize_recipe_key(blueprint_suffix(str(entry.get("blueprint_id", ""))))
        if suffix.endswith("oretoingot"):
            return True
    return False


def refinery_active_ore_subtypes(refinery: dict[str, Any]) -> list[str]:
    subtypes: list[str] = []
    seen: set[str] = set()
    input_inventory = inventory_by_index(refinery, first_inventory_index(refinery))
    if input_inventory is not None:
        items = input_inventory.get("items") if isinstance(input_inventory.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict) or not is_refinery_ore_item(item) or as_float(item.get("amount"), 0) <= 0:
                continue
            subtype = str(item.get("subtype_id", ""))
            key = subtype.lower()
            if key and key not in seen:
                seen.add(key)
                subtypes.append(subtype)
    queue = refinery.get("production_queue") if isinstance(refinery.get("production_queue"), list) else []
    for entry in queue:
        if not isinstance(entry, dict):
            continue
        subtype = ore_subtype_from_refinery_blueprint(str(entry.get("blueprint_id", "")))
        key = subtype.lower()
        if key and key not in seen:
            seen.add(key)
            subtypes.append(subtype)
    return subtypes


def ore_subtype_from_refinery_blueprint(blueprint_id: str) -> str:
    suffix = blueprint_suffix(blueprint_id)
    normalized = normalize_recipe_key(suffix)
    marker = "oretoingot"
    if normalized.endswith(marker) and len(normalized) > len(marker):
        return suffix[: -len("OreToIngot")]
    return ""


def component_name_from_blueprint(blueprint_id: str) -> str:
    suffix = blueprint_suffix(blueprint_id)
    if suffix.endswith("Component") and len(suffix) > len("Component"):
        suffix = suffix[: -len("Component")]
    if suffix.endswith("Blueprint") and len(suffix) > len("Blueprint"):
        suffix = suffix[: -len("Blueprint")]
    return suffix


def blueprint_suffix(blueprint_id: str) -> str:
    return str(blueprint_id).split("/")[-1].strip()


def find_inventory_target(
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    keyword_key: str,
    default_keyword: str,
) -> dict[str, Any] | None:
    keyword = str(config.get(keyword_key) or default_keyword).lower()
    fallback = None
    for block in blocks:
        if not same_construct(block) or is_managed_machine_block(block):
            continue
        if not block.get("inventories"):
            continue
        if keyword in str(block.get("name", "")).lower():
            return block
        if fallback is None and as_bool(block.get("is_cargo"), False):
            fallback = block
    return fallback


def find_component_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "componentContainerKeyword", "Components")


def find_ingot_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "ingotContainerKeyword", "Ingots")


def find_ore_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "oreContainerKeyword", "Ores")


def find_tool_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "toolContainerKeyword", "Tools")


def find_ammo_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "ammoContainerKeyword", "Ammo")


def find_bottle_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "bottleContainerKeyword", "Bottles")


def find_food_target(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    return find_inventory_target(blocks, config, "foodContainerKeyword", "Food")


def assembler_output_targets(blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    return {
        "components": find_component_target(blocks, config),
        "ingots": find_ingot_target(blocks, config),
        "tools": find_tool_target(blocks, config),
        "ammo": find_ammo_target(blocks, config),
        "bottles": find_bottle_target(blocks, config),
        "food": find_food_target(blocks, config),
    }


def assembler_output_target(
    item: dict[str, Any],
    targets: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    if is_component_item(item):
        return targets.get("components")
    if is_ingot_item(item):
        return targets.get("ingots")
    if is_tool_item(item):
        return targets.get("tools")
    if is_ammo_item(item):
        return targets.get("ammo")
    if is_bottle_item(item):
        return targets.get("bottles")
    if is_consumable_item(item):
        return targets.get("food")
    return None


def assembler_output_items(assembler: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = inventory_by_index(assembler, 1)
    if inventory is None:
        return []
    items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and as_float(item.get("amount"), 0) > 0
        and not is_refinery_ore_item(item)
        and not is_ice_item(item)
    ]


def refinery_output_items(refinery: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = inventory_by_index(refinery, 1)
    if inventory is None:
        return []
    items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
    return [item for item in items if isinstance(item, dict) and is_ingot_item(item) and as_float(item.get("amount"), 0) > 0]


def refinery_input_ore_items(refinery: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = inventory_by_index(refinery, first_inventory_index(refinery))
    if inventory is None:
        return []
    items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
    return [item for item in items if isinstance(item, dict) and is_refinery_ore_item(item) and as_float(item.get("amount"), 0) > 0]


def refinery_input_ore_amount(refinery: dict[str, Any]) -> float:
    return sum(as_float(item.get("amount"), 0) for item in refinery_input_ore_items(refinery))


def refinery_input_blocking_ore(refinery: dict[str, Any], priority_subtype: str) -> dict[str, Any] | None:
    inventory = inventory_by_index(refinery, first_inventory_index(refinery))
    if inventory is None:
        return None
    items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
    for item in items:
        if (
            isinstance(item, dict)
            and is_refinery_ore_item(item)
            and as_float(item.get("amount"), 0) > 0
            and str(item.get("subtype_id", "")).lower() != priority_subtype.lower()
        ):
            return item
    return None


def refinery_free_ore_capacity(refinery: dict[str, Any]) -> float:
    inventory = inventory_by_index(refinery, first_inventory_index(refinery))
    if inventory is None:
        return 0.0
    max_volume = as_float(inventory.get("max_volume"), 0)
    current_volume = max(0.0, as_float(inventory.get("current_volume"), 0))
    if max_volume <= 0:
        return 10000.0
    return max(0.0, (max_volume - current_volume) / ORE_VOLUME_PER_UNIT)


def is_managed_machine_block(block: dict[str, Any]) -> bool:
    return any(
        as_bool(block.get(key), False)
        for key in ("is_gas_generator", "is_reactor", "is_assembler", "is_refinery")
    )


def gas_generator_target_ice(generator: dict[str, Any]) -> float:
    inventory = first_inventory(generator)
    if inventory is None:
        return 0.0
    max_volume = as_float(inventory.get("max_volume"), 0)
    if max_volume <= 0:
        return 10000.0
    current_volume = max(0.0, as_float(inventory.get("current_volume"), 0))
    target_volume = max_volume * 0.30
    if current_volume >= target_volume:
        return inventory_amount(generator, is_ice_item)
    return max(10000.0, target_volume / ICE_VOLUME_PER_UNIT)


def refinery_target_ore(refinery: dict[str, Any]) -> float:
    inventory = first_inventory(refinery)
    if inventory is None:
        return 0.0
    current_volume = max(0.0, as_float(inventory.get("current_volume"), 0))
    target_volume = as_float(inventory.get("max_volume"), 0) * 0.30
    if current_volume >= target_volume:
        return inventory_amount_in_inventory(refinery, first_inventory_index(refinery), is_refinery_ore_item)
    return refinery_target_fill_ore(refinery)


def refinery_target_fill_ore(refinery: dict[str, Any]) -> float:
    inventory = first_inventory(refinery)
    if inventory is None:
        return 0.0
    max_volume = as_float(inventory.get("max_volume"), 0)
    if max_volume <= 0:
        return 10000.0
    return max(10000.0, (max_volume * 0.30) / ORE_VOLUME_PER_UNIT)


def same_construct(block: dict[str, Any]) -> bool:
    return as_bool(block.get("same_construct"), True)


def machine_accepts_inventory(block: dict[str, Any]) -> bool:
    return as_bool(block.get("enabled"), True)


def managed_machine_blocks(blocks: list[dict[str, Any]], config: dict[str, Any], predicate) -> list[dict[str, Any]]:
    return [block for block in blocks if same_construct(block) and predicate(block) and not is_machine_excluded(block, config)]


def is_machine_excluded(block: dict[str, Any], config: dict[str, Any]) -> bool:
    haystack = (str(block.get("name", "")) + "\n" + str(block.get("custom_data", ""))).lower()
    for keyword in machine_exclusion_keywords(config):
        if keyword and keyword.lower() in haystack:
            return True
    return False


def machine_exclusion_keywords(config: dict[str, Any]) -> list[str]:
    keywords: list[str] = ["!manual"]
    for key in ("manualMachineKeyword", "manualMachineKeywords", "noIIMKeyword", "noSortingKeyword"):
        value = config.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            keywords.extend(str(item).strip() for item in value if str(item).strip())
            continue
        text = str(value).strip()
        if not text:
            continue
        for part in text.replace(";", ",").replace("|", ",").split(","):
            part = part.strip()
            if part:
                keywords.append(part)
    return keywords


def rotate_commands(
    request: dict[str, Any],
    inventory_commands: list[dict[str, Any]],
    foundation_commands: list[dict[str, Any]],
    max_apply: int,
) -> list[dict[str, Any]]:
    commands = list(inventory_commands) + list(foundation_commands)
    if max_apply <= 0 or not commands:
        return commands
    non_echo = [command for command in commands if command.get("kind") != "echo"]
    if not non_echo:
        return commands
    offset = as_int(request.get("sequence"), 0) % len(non_echo)
    rotated_non_echo = non_echo[offset:] + non_echo[:offset]
    echo_commands = [command for command in commands if command.get("kind") == "echo"]
    return echo_commands + rotated_non_echo


def rotate_foundation_commands(request: dict[str, Any], commands: list[dict[str, Any]], max_machine: int) -> list[dict[str, Any]]:
    if max_machine <= 0 or len(commands) <= max_machine:
        return commands
    offset = as_int(request.get("sequence"), 0) % len(commands)
    rotated = commands[offset:] + commands[:offset]
    prioritized = sorted(rotated, key=foundation_command_priority)
    return prioritized[:max_machine]


def foundation_command_priority(command: dict[str, Any]) -> int:
    kind = str(command.get("kind", ""))
    reason = str(command.get("reason", ""))
    if kind == "set_assembler_mode":
        return 0
    if kind == "transfer_item" and reason == "refinery_ore_rebalance":
        return 1
    if kind == "enqueue_assembler_blueprint" and reason == "autocrafting_goal":
        return 2
    if kind == "transfer_item" and reason == "autocrafting_material":
        return 3
    if kind == "transfer_item" and reason == "assembler_input_cleanup":
        return 4
    if kind == "move_assembler_queue_item" and reason == "assembler_queue_consolidation":
        return 5
    if kind == "transfer_item" and reason == "autocrafting_ore_refining":
        return 6
    if kind == "write_text_surface":
        return 7
    if kind == "transfer_item" and reason == "refinery_output_cleanup":
        return 8
    if kind == "transfer_item" and reason == "assembler_output_cleanup":
        return 9
    if kind == "transfer_item" and reason == "refinery_input_unload":
        return 10
    if kind in {"set_use_conveyor", "set_assembler_cooperative_mode"}:
        return 11
    if kind == "transfer_item":
        return 12
    if kind == "write_block_custom_data":
        return 13
    return 14


def has_item(blocks: list[dict[str, Any]], predicate: Any) -> bool:
    for block in blocks:
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if not isinstance(inventory, dict):
                continue
            for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
                if isinstance(item, dict) and predicate(item):
                    return True
    return False


def inventory_amount(block: dict[str, Any], predicate: Any) -> float:
    total = 0.0
    for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
        if not isinstance(inventory, dict):
            continue
        for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
            if isinstance(item, dict) and predicate(item):
                total += as_float(item.get("amount"), 0)
    return total


def inventory_amount_in_inventory(block: dict[str, Any], inventory_index: int, predicate: Any) -> float:
    total = 0.0
    for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
        if not isinstance(inventory, dict) or as_int(inventory.get("index"), 0) != inventory_index:
            continue
        for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
            if isinstance(item, dict) and predicate(item):
                total += as_float(item.get("amount"), 0)
    return total


def find_item_source(
    blocks: list[dict[str, Any]],
    predicate: Any,
    excluded_entity_id: int = 0,
    source_block_predicate: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    for block in blocks:
        if entity_id(block) == excluded_entity_id:
            continue
        if not same_construct(block):
            continue
        if source_block_predicate is not None and not source_block_predicate(block):
            continue
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if not isinstance(inventory, dict):
                continue
            for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
                if isinstance(item, dict) and predicate(item) and as_float(item.get("amount"), 0) > 0:
                    return block, inventory, item
    return None


def first_inventory_index(block: dict[str, Any]) -> int:
    first = first_inventory(block)
    if first is None:
        return 0
    return as_int(first.get("index"), 0)


def first_inventory(block: dict[str, Any]) -> dict[str, Any] | None:
    inventories = block.get("inventories") if isinstance(block.get("inventories"), list) else []
    if not inventories:
        return None
    first = inventories[0]
    return first if isinstance(first, dict) else None


def inventory_by_index(block: dict[str, Any], index: int) -> dict[str, Any] | None:
    for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
        if isinstance(inventory, dict) and as_int(inventory.get("index"), 0) == index:
            return inventory
    return None


def summarize_inventory_items(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str, str], float] = {}
    for block in blocks:
        for inventory in block.get("inventories") if isinstance(block.get("inventories"), list) else []:
            if not isinstance(inventory, dict):
                continue
            for item in inventory.get("items") if isinstance(inventory.get("items"), list) else []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("subtype_id") or item.get("type_id") or "Unknown")
                type_id = str(item.get("type_id") or "")
                category = type_id.split("_")[-1] if "_" in type_id else type_id.split("/")[-1]
                key = (name, category, f"{type_id}/{name}")
                totals[key] = totals.get(key, 0.0) + as_float(item.get("amount"), 0)
    return [
        {"name": name, "category": category, "search": search, "amount": amount}
        for (name, category, search), amount in sorted(totals.items(), key=lambda entry: (-entry[1], entry[0][0]))
    ]
