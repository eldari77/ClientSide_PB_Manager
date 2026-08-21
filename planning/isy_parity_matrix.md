# Isy Action-Parity Matrix

This matrix tracks action-capability parity for the imported Isy's Inventory
Manager script. It is intentionally about mutations first. Behavior parity is
validated module by module after the bridge can safely observe and apply each
needed action.

Statuses:

- `supported`: command and snapshot support exist with tests.
- `partial`: some action path exists, but behavior is not fully equivalent yet.
- `primitive_ready`: the PB command primitive exists, but worker planning is not
  complete.
- `deferred`: intentionally not implemented yet.
- `api_verify`: likely possible, but needs live PB/API validation before being
  treated as supported.

| Module | Target | Isy operation | Snapshot requirement | Worker command | PB shim support | Test evidence | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Inventory sorting | Cargo and inventories | Move items between containers | `inventory_snapshot.blocks[].inventories[].items[]` | `transfer_item` | Re-finds source stack, checks transfer permission and capacity, same-construct guarded | `tests/test_isy_sorting.py`, `tests/test_pb_shim_source.py` | supported |
| Inventory sorting | Managed machine inventories | Avoid draining module-managed contents as normal cargo sorting sources | Block type helpers from snapshot | Planner skip, no command emitted | Dedicated modules own machine filling/cleanup | `test_inventory_sorting_does_not_drain_managed_machine_inventories` | supported |
| Auto container assignment | Cargo containers | Rename containers to role names | Block name/type and inventory summaries | `rename_block` | Allows only `reason=auto_container_assignment` and known assignment names | `tests/test_isy_sorting.py`, `tests/test_pb_shim_source.py` | supported |
| LCD reports | LCD/text surfaces | Write text, title, and Isy-style surface defaults | `grid_snapshot` LCD `text`, `custom_data`, `surface_count` | `write_text_surface` | Writes bounded text/title, sets Debug font, size, padding, left alignment, text-and-image | `tests/test_isy_foundation.py`, `tests/test_pb_shim_source.py` | supported |
| Machine setup | Functional blocks | Enable/disable managed blocks | `enabled`, block type helpers | `set_block_enabled` | Same-construct guarded functional-block enable | `tests/test_isy_foundation.py`, `tests/test_pb_shim_source.py` | supported |
| Machine setup | Conveyor-capable blocks | Set conveyor pull/use state | `use_conveyor`, block type helpers | `set_use_conveyor` | Tries `UseConveyorSystem`, then `UseConveyor`; same-construct guarded | `tests/test_isy_foundation.py`, `tests/test_pb_shim_source.py` | supported |
| Reactors | Reactors | Disable conveyor pull after uranium balancing | `is_reactor`, `use_conveyor`, uranium inventory | `set_use_conveyor enabled=false` | Same as conveyor handler | `test_refinery_gas_and_reactor_foundations_emit_isy_setup_commands` | supported |
| Reactors | Reactors | Enable reactors when uranium source exists | `is_reactor`, uranium inventory | `set_block_enabled enabled=true` | Same as functional handler | `test_refinery_gas_and_reactor_foundations_emit_isy_setup_commands` | partial |
| Reactors | Reactor inventory | Maintain target uranium amounts | Reactor inventory plus source uranium stacks | `transfer_item` | Transfer primitive exists and same-construct guarded | `test_reactor_balancing_tops_up_uranium_to_configured_target` | partial |
| Assemblers | Assemblers | Force assembly mode | `is_assembler`, `assembler_mode` | `set_assembler_mode mode=assembly` | Sets `IMyAssembler.Mode` | `test_autocrafting_planner_recognizes_assembler_and_emits_bounded_command` | supported |
| Assemblers | Assemblers | Disable automatic conveyor pull/push for managed assemblers | `is_assembler`, `use_conveyor` | `set_use_conveyor enabled=false` | Same as conveyor handler | `test_autocrafting_planner_recognizes_assembler_and_emits_bounded_command` | supported |
| Assemblers | Assemblers | Set cooperative mode | `assembler_cooperative_mode` | `set_assembler_cooperative_mode` | Sets `IMyAssembler.CooperativeMode` | `tests/test_pb_shim_source.py` and worker setup test | supported |
| Assemblers | Production queue | Add blueprint queue item for known vanilla and learned component goals, including modded blueprints learned from manual queue entries | `production_queue`, inventory totals, wanted stock, `data/autocrafting_blueprints` | `enqueue_assembler_blueprint reason=autocrafting_goal` | Parses `MyDefinitionId` and calls `AddQueueItem` | `test_autocrafting_queues_missing_components_and_feeds_ingots`, `test_autocrafting_queues_new_lcd_component_goals`, `test_autocrafting_queues_modded_goal_from_persisted_blueprint_memory`, PB source test | partial |
| Assemblers | Production queue | Clear queue | `production_queue` | `clear_assembler_queue` | Calls `ClearQueue` | PB source test only | primitive_ready |
| Assemblers | Production queue | Move queue item | `production_queue[].item_id` | `move_assembler_queue_item` | Calls `MoveQueueItemRequest` | PB source test only | api_verify |
| Assemblers | Production queue | Remove queue amount | `production_queue[]` | `remove_assembler_queue_item` with `queue_index` and `amount` | Calls `RemoveQueueItem` | PB source test only | api_verify |
| Autocrafting | Assemblers and LCD | Show learned/observed items, persist manual queue blueprints, prepopulate custom data, and plan known or learned component batches from wanted stock | `production_queue`, inventory totals, autocrafting LCD custom data, `data/autocrafting_blueprints` | LCD `write_text_surface`; `write_block_custom_data`; `enqueue_assembler_blueprint` | Custom-data write is reason-gated and same-construct guarded | LCD target, observed-component, custom-data prepopulate, manual queue discovery, modded queue memory, and component queue tests | partial |
| Autocrafting | Assembler input inventory | Feed cumulative missing ingots for known planned and manually queued component work, including multi-ingot vanilla component recipes | Assembler `production_queue`, planned LCD goals, input inventory, same-construct ingot source | `transfer_item reason=autocrafting_material` | Transfer primitive exists and same-construct guarded | `test_autocrafting_feeds_materials_for_manually_queued_components`, `test_autocrafting_feeds_cumulative_materials_for_planned_lcd_goals`, `test_autocrafting_routes_multiple_ingots_for_vanilla_component_recipes` | partial |
| Autocrafting | Assembler output inventory | Move completed components from assembler output to component cargo | Assembler output inventory plus component cargo | `transfer_item reason=assembler_output_cleanup` | Transfer primitive exists and same-construct guarded | `test_autocrafting_moves_completed_components_to_component_cargo` | partial |
| Refineries | Refineries | Disable automatic conveyor pull/push for managed refineries | `is_refinery`, `use_conveyor` | `set_use_conveyor enabled=false` | Same as conveyor handler | `test_refinery_gas_and_reactor_foundations_emit_isy_setup_commands` | supported |
| Refineries | Refinery input inventory | Keep a bounded non-Ice ore buffer in refinery input | Refinery input inventory plus same-construct non-machine ore source | `transfer_item reason=refinery_ore_input` | Transfer primitive exists and same-construct guarded | `test_refinery_balancing_tops_up_input_from_cargo_ore` | partial |
| Refineries | Refinery queue | Sort/move/remove refinery queue entries | Refinery production queue entries | None yet | Not implemented | Matrix entry only | deferred |
| Gas balancing | O2/H2 generators | Disable automatic conveyor pull/push for managed generators | `is_gas_generator`, `use_conveyor` | `set_use_conveyor enabled=false` | Same as conveyor handler | `test_refinery_gas_and_reactor_foundations_emit_isy_setup_commands` | supported |
| Gas balancing | O2/H2 generators | Enable auto refill behavior | `gas_auto_refill` | `set_gas_auto_refill enabled=true` | Tries `AutoRefill`, then `AutoRefillBottles` | Worker and PB source tests | api_verify |
| Gas balancing | O2/H2 generator inventory | Top up generator Ice from cargo | Generator inventory volume plus same-construct non-machine Ice source | `transfer_item` | Transfer primitive exists and same-construct guarded | `test_gas_balancing_tops_up_generators_from_cargo_ice` | partial |
| Gas balancing | Gas tanks | Observe stockpile/fill state | `stockpile`, `gas_filled_ratio` | None yet | Not implemented | Plugin source test | partial |
| Learning/markers | Autocrafting LCD | Write discovered item entries to custom data | `custom_data`, observed component inventory, known assembler queue blueprints | `write_block_custom_data reason=autocrafting_discovered_items` | Narrow allowlist only; not arbitrary marker writes | `test_autocrafting_custom_data_preserves_existing_goals_and_adds_new_items`, `test_autocrafting_discovers_components_from_manual_assembler_queue`, PB source test | partial |
| Learning/markers | Terminal blocks | General marker custom data writes | `custom_data` | None yet | Not implemented | Matrix entry only | deferred |
| Safety | All commands | Respect manual/exclusion keywords | Block name and custom data | Planner skip, no command emitted | PB still same-construct guards every command | `test_machine_setup_respects_manual_and_exclusion_keywords` | supported |

## Immediate Live Validation

After re-pasting shim `2026-05-20-iim-action-parity-v12` and handing off the
new plugin build, validate these before moving to deeper behavior parity:

1. Latest processed request contains `production_queue`,
   `assembler_cooperative_mode`, `gas_auto_refill`, and `stockpile` fields.
2. A reactor command appears as `set_use_conveyor enabled=false`.
3. Assembler and refinery setup commands appear as `set_use_conveyor
   enabled=false`.
4. If cargo ore exists and refinery input is below target, the worker queues a
   refinery-bound `transfer_item` with `reason=refinery_ore_input`.
5. The O2/H2 generator receives `set_gas_auto_refill enabled=true`.
6. If cargo Ice exists and the generator inventory is below target, the worker
   queues a generator-bound `transfer_item` with `item_subtype_id=Ice`.
7. If an assembler has a known component blueprint already in
   `production_queue` and cargo has the needed ingot, the worker queues
   `transfer_item reason=autocrafting_material` into assembler input.
8. If assembler output inventory contains completed components and component
   cargo exists, the worker queues `transfer_item
   reason=assembler_output_cleanup`.
9. Under latency-limited multi-command apply, `state.last_apply` rotates through LCD
   writes and machine setup over successive sequences.
