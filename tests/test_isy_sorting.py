from worker.isy_sorting import item_category, plan_inventory_sorting


def base_request(snapshot):
    return {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-a",
        "sequence": 3,
        "script_id": "workshop_1216126863_adapter",
        "request_kind": "adapter_tick",
        "worker_config": {
            "oreContainerKeyword": "Ores",
            "ingotContainerKeyword": "Ingots",
            "componentContainerKeyword": "Components",
            "toolContainerKeyword": "Tools",
            "ammoContainerKeyword": "Ammo",
            "bottleContainerKeyword": "Bottles",
            "lockedContainerKeywords": ["Locked"],
            "hiddenContainerKeywords": ["Hidden"],
            "noSortingKeyword": "[No Sorting]",
            "noIIMKeyword": "[No IIM]",
            "inventorySortingEnabled": True,
            "inventorySortingDryRun": False,
            "maxApplyCommands": 1,
            "maxPlannedTransfers": 4,
            "allowConnectedGrids": False,
            "inventoryFullBuffer": 0,
        },
        "inventory_snapshot": snapshot,
    }


def block(entity_id, name, items=None, current_volume=0.0, max_volume=1000.0, same_construct=True):
    return {
        "entity_id": entity_id,
        "name": name,
        "type": "MyCargoContainer",
        "subtype": "LargeBlockLargeContainer",
        "same_construct": same_construct,
        "inventories": [
            {
                "index": 0,
                "current_volume": current_volume,
                "max_volume": max_volume,
                "is_full": False,
                "items": items or [],
            }
        ],
    }


def machine_block(entity_id, name, block_type, items=None):
    payload = block(entity_id, name, items)
    payload["type"] = block_type
    payload["subtype"] = ""
    return payload


def item(type_id, subtype_id, amount):
    return {"type_id": type_id, "subtype_id": subtype_id, "amount": amount}


def test_missing_snapshot_is_rejected():
    result = plan_inventory_sorting(base_request({}) | {"inventory_snapshot": {}})
    assert result["adapter_status"] == "rejected"
    assert result["error_bucket"] == "snapshot_missing"


def test_classifies_common_item_types():
    assert item_category(item("MyObjectBuilder_Ore", "Iron", 1)) == "ores"
    assert item_category(item("MyObjectBuilder_Ingot", "Iron", 1)) == "ingots"
    assert item_category(item("MyObjectBuilder_Component", "SteelPlate", 1)) == "components"
    assert item_category(item("MyObjectBuilder_PhysicalGunObject", "WelderItem", 1)) == "tools"
    assert item_category(item("MyObjectBuilder_AmmoMagazine", "NATO_25x184mm", 1)) == "ammo"
    assert item_category(item("MyObjectBuilder_OxygenContainerObject", "OxygenBottle", 1)) == "bottles"
    assert item_category(item("MyObjectBuilder_ConsumableItem", "MealPack_KelpCrisp", 1)) == "food"


def test_generates_transfer_for_misplaced_ore():
    snapshot = {
        "source": "plugin",
        "blocks": [
            block(1, "Cargo Components", [item("MyObjectBuilder_Ore", "Iron", 42)]),
            block(2, "Cargo Ores", []),
        ],
    }
    result = plan_inventory_sorting(base_request(snapshot))
    assert result["apply_mode"] == "immediate"
    assert result["max_apply_commands"] == 1
    command = result["commands"][0]
    assert command["kind"] == "transfer_item"
    assert command["source_entity_id"] == 1
    assert command["destination_entity_id"] == 2
    assert command["item_type_id"] == "MyObjectBuilder_Ore"
    assert command["item_subtype_id"] == "Iron"
    assert command["reason"] == "inventory_sorting"


def test_skips_locked_hidden_full_and_connected_grid_targets():
    snapshot = {
        "source": "plugin",
        "blocks": [
            block(1, "Cargo Components", [item("MyObjectBuilder_Ore", "Iron", 42)]),
            block(2, "Cargo Ores Locked", []),
            block(3, "Cargo Ores Hidden", []),
            block(4, "Cargo Ores", [], current_volume=99, max_volume=100),
            block(5, "Cargo Ores", [], same_construct=False),
        ],
    }
    result = plan_inventory_sorting(base_request(snapshot))
    assert not [command for command in result["commands"] if command["kind"] == "transfer_item"]
    skipped = result["inventory_sorting"]["skipped_reasons"]
    assert skipped["destination_locked"] >= 1
    assert skipped["destination_hidden"] >= 1
    assert skipped["target_inventory_full"] >= 1
    assert skipped["no_target_ores"] >= 1


def test_inventory_full_buffer_does_not_mark_small_empty_container_full():
    snapshot = {
        "source": "plugin",
        "blocks": [
            block(1, "Cargo Components", [item("MyObjectBuilder_Ingot", "Iron", 8)], current_volume=1, max_volume=156.25),
            block(2, "Cargo Ingots", [], current_volume=0, max_volume=156.25),
        ],
    }
    request = base_request(snapshot)
    request["worker_config"]["inventoryFullBuffer"] = 500
    result = plan_inventory_sorting(request)
    assert result["commands"][0]["kind"] == "transfer_item"
    assert result["commands"][0]["destination_entity_id"] == 2


def test_dry_run_returns_echo_not_transfer_command():
    snapshot = {
        "source": "plugin",
        "blocks": [
            block(1, "Cargo Components", [item("MyObjectBuilder_Ingot", "Iron", 8)]),
            block(2, "Cargo Ingots", []),
        ],
    }
    request = base_request(snapshot)
    request["worker_config"]["inventorySortingDryRun"] = True
    result = plan_inventory_sorting(request)
    assert result["apply_mode"] == "dry_run"
    assert result["commands"][0]["kind"] == "echo"
    assert result["inventory_sorting"]["proposed_transfers"] == 1


def test_inventory_sorting_does_not_drain_managed_machine_inventories():
    snapshot = {
        "source": "plugin",
        "blocks": [
            machine_block(1, "Large Reactor", "MyReactor", [item("MyObjectBuilder_Ingot", "Uranium", 100)]),
            machine_block(2, "O2/H2 Generator", "MyGasGenerator", [item("MyObjectBuilder_Ore", "Ice", 1000)]),
            block(3, "Cargo Ingots", []),
            block(4, "Cargo Ores", []),
        ],
    }
    result = plan_inventory_sorting(base_request(snapshot))
    assert not [command for command in result["commands"] if command["kind"] == "transfer_item"]
    assert result["inventory_sorting"]["skipped_reasons"]["source_managed_machine"] == 2


def test_inventory_sorting_does_not_target_managed_machine_inventories():
    snapshot = {
        "source": "plugin",
        "blocks": [
            block(1, "Cargo Components", [item("MyObjectBuilder_ConsumableItem", "MealPack_KelpCrisp", 33)]),
            machine_block(2, "Food Processor Food", "MyAssembler", []),
        ],
    }
    result = plan_inventory_sorting(base_request(snapshot))
    assert not [command for command in result["commands"] if command["kind"] == "transfer_item"]
    skipped = result["inventory_sorting"]["skipped_reasons"]
    assert skipped["destination_managed_machine"] >= 1
    assert skipped["no_target_food"] >= 1
