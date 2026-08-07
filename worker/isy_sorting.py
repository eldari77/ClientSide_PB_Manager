from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


CATEGORY_KEYS = {
    "ores": "oreContainerKeyword",
    "ingots": "ingotContainerKeyword",
    "components": "componentContainerKeyword",
    "tools": "toolContainerKeyword",
    "ammo": "ammoContainerKeyword",
    "bottles": "bottleContainerKeyword",
    "food": "foodContainerKeyword",
}

ASSIGN_KEYS = {
    "ores": "assignOres",
    "ingots": "assignIngots",
    "components": "assignComponents",
    "tools": "assignTools",
    "ammo": "assignAmmo",
    "bottles": "assignBottles",
    "food": "assignFood",
}


@dataclass(frozen=True)
class InventoryBlock:
    entity_id: int
    name: str
    block_type: str
    block_subtype: str
    same_construct: bool
    inventories: list[dict[str, Any]]


def plan_inventory_sorting(request: dict[str, Any]) -> dict[str, Any]:
    config = request.get("worker_config") if isinstance(request.get("worker_config"), dict) else {}
    snapshot = request.get("inventory_snapshot") if isinstance(request.get("inventory_snapshot"), dict) else {}
    blocks_payload = snapshot.get("blocks")
    if not isinstance(blocks_payload, list):
        return {
            "adapter_status": "rejected",
            "summary": "Inventory sorting rejected: inventory snapshot missing.",
            "commands": [{"kind": "echo", "text": "IIM inventory sorting rejected: snapshot_missing"}],
            "error_bucket": "snapshot_missing",
            "inventory_sorting": empty_summary("snapshot_missing"),
        }

    blocks = [parse_block(item) for item in blocks_payload if isinstance(item, dict)]
    enabled = as_bool(config.get("inventorySortingEnabled"), True)
    dry_run = as_bool(config.get("inventorySortingDryRun"), False)
    allow_connected = as_bool(config.get("allowConnectedGrids"), False)
    max_commands = max(0, as_int(config.get("maxApplyCommands"), 1))
    max_planned = max(1, as_int(config.get("maxPlannedTransfers"), max_commands if max_commands > 0 else 1))

    if not enabled:
        return {
            "summary": "Inventory sorting disabled by worker config.",
            "commands": [{"kind": "echo", "text": "IIM inventory sorting disabled"}],
            "apply_mode": "dry_run",
            "max_apply_commands": 0,
            "remaining_commands": 0,
            "inventory_sorting": empty_summary("disabled", len(blocks)),
        }

    keywords = keyword_config(config)
    skipped: Counter[str] = Counter()
    targets = build_targets(blocks, keywords, config, allow_connected, skipped)
    commands: list[dict[str, Any]] = []
    scanned_inventories = 0
    scanned_items = 0

    for block in blocks:
        if not allow_connected and not block.same_construct:
            skipped["connected_grid_disabled"] += 1
            continue
        if not is_sortable_source(block, keywords, skipped):
            continue
        source_categories = block_categories(block.name, keywords, config)
        for inventory in block.inventories:
            scanned_inventories += 1
            inventory_index = as_int(inventory.get("index"), 0)
            items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
            for item in items:
                scanned_items += 1
                category = item_category(item)
                if category == "unknown":
                    skipped["unknown_item_type"] += 1
                    continue
                if category in source_categories:
                    skipped["already_in_target_container"] += 1
                    continue
                target = choose_target(category, targets, block.entity_id, skipped)
                if target is None:
                    continue
                amount = as_float(item.get("amount"), 0.0)
                if amount <= 0:
                    skipped["empty_item_amount"] += 1
                    continue
                commands.append(
                    {
                        "kind": "transfer_item",
                        "command_id": f"{request.get('bridge_id', 'bridge')}:{request.get('sequence', 0)}:{len(commands) + 1}",
                        "source_entity_id": block.entity_id,
                        "source_inventory_index": inventory_index,
                        "destination_entity_id": target.entity_id,
                        "destination_inventory_index": target.inventory_index,
                        "item_type_id": str(item.get("type_id", "")),
                        "item_subtype_id": str(item.get("subtype_id", "")),
                        "reason": "inventory_sorting",
                        "amount": amount,
                    }
                )
                if len(commands) >= max_planned:
                    break
            if len(commands) >= max_planned:
                break
        if len(commands) >= max_planned:
            break

    rename_commands = plan_container_assignment(blocks, targets, keywords, config, allow_connected, skipped)
    for command in rename_commands:
        if len(commands) >= max_planned:
            break
        commands.append(command)

    proposed = len(commands)
    emitted_commands = commands if not dry_run else [{"kind": "echo", "text": f"IIM dry run: {proposed} sorting command(s) proposed"}]
    apply_budget = 0 if dry_run else max_commands
    summary = {
        "scanned_blocks": len(blocks),
        "scanned_inventories": scanned_inventories,
        "scanned_items": scanned_items,
        "proposed_transfers": sum(1 for command in commands if command.get("kind") == "transfer_item"),
        "proposed_renames": sum(1 for command in commands if command.get("kind") == "rename_block"),
        "applied_command_budget": apply_budget,
        "skipped_reasons": dict(skipped),
        "snapshot_source": str(snapshot.get("source", "unknown")),
        "dry_run": dry_run,
    }
    return {
        "summary": (
            "IIM inventory sorting planned: "
            f"transfers={summary['proposed_transfers']}; renames={summary['proposed_renames']}; "
            f"budget={apply_budget}; dry_run={str(dry_run).lower()}"
        ),
        "commands": emitted_commands,
        "apply_mode": "dry_run" if dry_run else "immediate",
        "max_apply_commands": apply_budget,
        "remaining_commands": max(0, proposed - apply_budget),
        "inventory_sorting": summary,
        "error_bucket": "none",
    }


@dataclass(frozen=True)
class TargetInventory:
    entity_id: int
    inventory_index: int
    free_ratio: float


def empty_summary(reason: str, block_count: int = 0) -> dict[str, Any]:
    return {
        "scanned_blocks": block_count,
        "scanned_inventories": 0,
        "scanned_items": 0,
        "proposed_transfers": 0,
        "proposed_renames": 0,
        "applied_command_budget": 0,
        "skipped_reasons": {reason: 1},
    }


def parse_block(item: dict[str, Any]) -> InventoryBlock:
    inventories = item.get("inventories") if isinstance(item.get("inventories"), list) else []
    return InventoryBlock(
        entity_id=as_int(item.get("entity_id"), 0),
        name=str(item.get("name", "")),
        block_type=str(item.get("type", "")),
        block_subtype=str(item.get("subtype", "")),
        same_construct=as_bool(item.get("same_construct"), True),
        inventories=[inv for inv in inventories if isinstance(inv, dict)],
    )


def keyword_config(config: dict[str, Any]) -> dict[str, Any]:
    keywords: dict[str, Any] = {
        "locked": as_list(config.get("lockedContainerKeywords"), ["Locked", "Control Station", "Control Seat", "Safe Zone"]),
        "hidden": as_list(config.get("hiddenContainerKeywords"), ["Hidden"]),
        "no_sorting": str(config.get("noSortingKeyword") or "[No Sorting]"),
        "no_iim": str(config.get("noIIMKeyword") or "[No IIM]"),
        "special": str(config.get("specialContainerKeyword") or "Special"),
    }
    for category, key in CATEGORY_KEYS.items():
        keywords[category] = str(config.get(key) or category.title())
    return keywords


def build_targets(
    blocks: list[InventoryBlock],
    keywords: dict[str, Any],
    config: dict[str, Any],
    allow_connected: bool,
    skipped: Counter[str],
) -> dict[str, list[TargetInventory]]:
    targets: dict[str, list[TargetInventory]] = {category: [] for category in CATEGORY_KEYS}
    for block in blocks:
        if not allow_connected and not block.same_construct:
            continue
        if not is_container_candidate(block):
            continue
        if not is_sortable_destination(block, keywords, skipped):
            continue
        categories = block_categories(block.name, keywords, config)
        for category in categories:
            for inventory in block.inventories:
                index = as_int(inventory.get("index"), 0)
                if is_inventory_full(inventory, config):
                    skipped["target_inventory_full"] += 1
                    continue
                targets.setdefault(category, []).append(TargetInventory(block.entity_id, index, free_ratio(inventory)))
    for category in targets:
        targets[category].sort(key=lambda item: item.free_ratio, reverse=True)
    return targets


def is_container_candidate(block: InventoryBlock) -> bool:
    name = (block.block_type + " " + block.block_subtype).lower()
    return "cargo" in name or "container" in name or bool(block.inventories)


def is_sortable_source(block: InventoryBlock, keywords: dict[str, Any], skipped: Counter[str]) -> bool:
    name = block.name.lower()
    if is_managed_machine_inventory(block):
        skipped["source_managed_machine"] += 1
        return False
    if contains_any(name, keywords["locked"]):
        skipped["source_locked"] += 1
        return False
    if contains_any(name, keywords["hidden"]):
        skipped["source_hidden"] += 1
        return False
    if keyword_in_name(name, keywords["no_sorting"]):
        skipped["source_no_sorting"] += 1
        return False
    if keyword_in_name(name, keywords["no_iim"]):
        skipped["source_no_iim"] += 1
        return False
    return True


def is_managed_machine_inventory(block: InventoryBlock) -> bool:
    block_type = (block.block_type + " " + block.block_subtype).lower()
    return any(
        marker in block_type
        for marker in (
            "myreactor",
            "mygasgenerator",
            "myassembler",
            "myrefinery",
        )
    )


def is_sortable_destination(block: InventoryBlock, keywords: dict[str, Any], skipped: Counter[str]) -> bool:
    name = block.name.lower()
    if is_managed_machine_inventory(block):
        skipped["destination_managed_machine"] += 1
        return False
    if contains_any(name, keywords["locked"]):
        skipped["destination_locked"] += 1
        return False
    if contains_any(name, keywords["hidden"]):
        skipped["destination_hidden"] += 1
        return False
    if keyword_in_name(name, keywords["no_sorting"]):
        skipped["destination_no_sorting"] += 1
        return False
    if keyword_in_name(name, keywords["no_iim"]):
        skipped["destination_no_iim"] += 1
        return False
    return True


def block_categories(name: str, keywords: dict[str, Any], config: dict[str, Any]) -> set[str]:
    lowered = name.lower()
    categories = {category for category in CATEGORY_KEYS if keyword_in_name(lowered, keywords[category])}
    if as_bool(config.get("oresIngotsInOne"), False):
        if "ores" in categories:
            categories.add("ingots")
        if "ingots" in categories:
            categories.add("ores")
    if as_bool(config.get("toolsAmmoBottlesInOne"), False):
        combined = {"tools", "ammo", "bottles"}
        if categories & combined:
            categories |= combined
    return categories


def choose_target(category: str, targets: dict[str, list[TargetInventory]], source_entity_id: int, skipped: Counter[str]) -> TargetInventory | None:
    candidates = [target for target in targets.get(category, []) if target.entity_id != source_entity_id]
    if not candidates:
        skipped[f"no_target_{category}"] += 1
        return None
    return candidates[0]


def item_category(item: dict[str, Any]) -> str:
    type_id = str(item.get("type_id", "")).lower()
    subtype = str(item.get("subtype_id", "")).lower()
    if "ore" in type_id:
        return "ores"
    if "ingot" in type_id:
        return "ingots"
    if "component" in type_id:
        return "components"
    if "physicalgunobject" in type_id:
        return "tools"
    if "ammomagazine" in type_id:
        return "ammo"
    if "oxygencontainerobject" in type_id or "gascontainerobject" in type_id or "bottle" in subtype:
        return "bottles"
    if "consumableitem" in type_id or "mealpack" in subtype:
        return "food"
    return "unknown"


def plan_container_assignment(
    blocks: list[InventoryBlock],
    targets: dict[str, list[TargetInventory]],
    keywords: dict[str, Any],
    config: dict[str, Any],
    allow_connected: bool,
    skipped: Counter[str],
) -> list[dict[str, Any]]:
    if not as_bool(config.get("autoContainerAssignment"), False) or not as_bool(config.get("assignNewContainers"), True):
        return []
    commands: list[dict[str, Any]] = []
    available = [
        block for block in blocks
        if (allow_connected or block.same_construct)
        and is_container_candidate(block)
        and is_sortable_destination(block, keywords, skipped)
        and not block_categories(block.name, keywords, config)
        and inventories_empty(block)
    ]
    for category in CATEGORY_KEYS:
        if targets.get(category) or not as_bool(config.get(ASSIGN_KEYS[category]), True):
            continue
        if not available:
            skipped["no_empty_container_for_assignment"] += 1
            break
        block = available.pop(0)
        new_name = (block.name + " " + str(keywords[category])).strip()
        commands.append(
            {
                "kind": "rename_block",
                "command_id": f"assign:{block.entity_id}:{category}",
                "block_entity_id": block.entity_id,
                "new_name": new_name,
                "reason": "auto_container_assignment",
            }
        )
    return commands


def inventories_empty(block: InventoryBlock) -> bool:
    for inventory in block.inventories:
        items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
        if items:
            return False
    return True


def is_inventory_full(inventory: dict[str, Any], config: dict[str, Any]) -> bool:
    if as_bool(inventory.get("is_full"), False):
        return True
    current = as_float(inventory.get("current_volume"), 0.0)
    maximum = as_float(inventory.get("max_volume"), 0.0)
    if maximum <= 0:
        return False
    free_liters = max(0.0, maximum - current)
    buffer_liters = max(0.0, as_float(config.get("inventoryFullBuffer"), 500.0))
    threshold = min(maximum * 0.02, buffer_liters) if buffer_liters > 0 else maximum * 0.02
    return free_liters <= threshold


def free_ratio(inventory: dict[str, Any]) -> float:
    current = as_float(inventory.get("current_volume"), 0.0)
    maximum = as_float(inventory.get("max_volume"), 0.0)
    if maximum <= 0:
        return 1.0
    return max(0.0, (maximum - current) / maximum)


def keyword_in_name(name: str, keyword: Any) -> bool:
    value = str(keyword or "").strip().lower()
    return bool(value) and value in name


def contains_any(name: str, keywords: Any) -> bool:
    return any(keyword_in_name(name, keyword) for keyword in as_list(keywords, []))


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return list(default)
