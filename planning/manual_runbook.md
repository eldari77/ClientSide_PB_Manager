# Manual Runbook

## Scan Workshop Scripts

```powershell
cd C:\Users\eLDARi\Documents\VScode\.venv\ClientSide_PB_Script
.\tools\scan_workshop.ps1
```

Expected output: `data\workshop_catalog.json` with root-level PB script
candidates marked as `pb_script`. When Steam details are reachable, the catalog
also includes human-readable Workshop names.

To find Isy's Inventory Manager after refresh, filter by `Isy` or `inventory`
in the Workshop Scripts tab. The current known Workshop id is `1216126863`.

## Run Tests

```powershell
python -m pytest -q
```

## Worker Smoke Test

```powershell
.\tools\worker_smoke.ps1
```

Expected output: a result for `smoke-bridge` with `message_kind=result` and
`status=ok`.

## Isy Foundation Smoke Test

For `workshop_1216126863_adapter`, keep the PB config at:

```text
snapshot_mode=minimal
max_apply_commands_per_tick=8
dynamic_apply_commands=true
dynamic_min_apply_commands_per_tick=1
dynamic_max_apply_commands_per_tick=8
apply_worker_commands=true
allow_connected_grid_commands=false
sos_automation_enabled=false
sos_automation_approval_action_id=
sos_automation_approval_nonce=
sos_automation_approval_expires_sequence=0
```

In the manager, use the Bridges tab as the fastest PB setup path. Select the
bridge row, or press Refresh after a new PB bridge appears; the bottom prompt
shows the CustomData block to paste into that programmable block. The prompt is
also refreshed by the Worker Scripts tab `PB Config` button and follows the
current bridge/script/limit selections.

The new plugin build enriches the minimal request with `inventory_snapshot` and
`grid_snapshot`. If the loaded plugin is stale or the inventory snapshot cannot
be produced, the worker returns `status=rejected` with
`error_bucket=snapshot_missing`. If the grid snapshot is missing, the worker
falls back with an explicit `grid_snapshot_missing` diagnostic and skips the
LCD/machine planners.

Use the Worker Scripts tab, Config sub-tab, Inventory Sorting section to tune:

- Apply enabled
- Dry run
- Connected grids
- Apply/tick
- Plan/tick
- Machine plan/tick

## SOS One-Time Recovery Approval

`sos_automation_enabled` remains `false` by default. Do not enable it for a
normal SOS status or automation-plan run. For one future same-grid programmable
block recovery, enter a unique action id, approval nonce, and expiry sequence
directly in the shim PB CustomData, then set `sos_automation_enabled=true`.
The receipt is consumed only after a matching `set_block_enabled enabled=true`
result reaches the shim; it cannot enable connected-grid blocks or any other
block type or command kind.

Start with Dry run enabled if testing on a live ship you care about. Disable
Dry run only after the latest result summary shows the expected transfer plan.

For v10 dummy-grid validation, build a small directly conveyored grid with:

- one programmable block running the shim
- one named text panel or LCD for each configured LCD keyword you want to test
- one assembler
- one refinery
- one O2/H2 generator with ice access
- one gas tank
- one reactor with a small uranium inventory test case
- two cargo containers with a direct conveyor route between them
- one connector if connector visibility matters for the scenario

For v12 IIM action-parity validation, inspect the newest processed request and
result around a reset/no-argument loop:

- `grid_snapshot.blocks[]` should expose `production_queue`,
  `assembler_cooperative_mode`, `gas_auto_refill`, and `stockpile` for relevant
  machine blocks.
- Reactors managed by uranium balancing should receive
  `set_use_conveyor enabled=false` and, when uranium is available,
  `set_block_enabled enabled=true`. If an enabled reactor is below
  `uraniumAmountLargeGrid` and a same-construct uranium ingot source exists, the
  worker should also queue a `transfer_item` into the reactor inventory.
- Worker results should include `industry_input_mode=hybrid_conveyors` by
  default. In this mode, active assemblers, food processors, and refineries
  should stay `use_conveyor=true`; the worker should not emit
  `set_use_conveyor enabled=false` for those blocks. Set
  `industryInputMode=plugin_only` only when validating the older conveyor-off
  input-management workflow. Assemblers should still receive
  `set_assembler_mode mode=assembly` and `set_assembler_cooperative_mode` when
  needed.
- Food Processors may appear as `type=MyAssembler`; the plugin should tag them
  with `is_food_processor=true` when the current plugin is loaded. Autocrafting
  should queue Food Processor recipes such as
  `MyObjectBuilder_BlueprintDefinition/Position0030_MealPack_KelpCrisp` on the
  Food Processor, feed matching ingredients such as
  `MyObjectBuilder_PhysicalObject/Algae` into inventory index `0`, and move
  completed `MyObjectBuilder_ConsumableItem/MealPack_KelpCrisp` from inventory
  index `1` to a `Food` cargo container or normal cargo fallback.
- If same-construct cargo ore exists and refinery input is below its ore buffer,
  the worker should queue a `transfer_item` into refinery inventory index `0`.
  Generic ore balancing uses `reason=refinery_ore_input`; ore selected because
  assemblers are short on that ingot uses `reason=autocrafting_ore_refining`.
  If an active refinery is already filled with a different ore while a shortage
  ore exists in cargo, the worker may first queue
  `transfer_item reason=refinery_input_unload` from refinery input index `0`
  back to Ores cargo, then queue the shortage ore into that refinery.
  Ore already present in refinery input, refinery output, or the refinery's
  current production queue should count as covered, allowing the selector to
  move on to the next shortage ore source.
  If the shortage ore is not available but any same-construct non-machine cargo
  has non-Ice ore or stone, active refineries should still receive a
  `transfer_item reason=refinery_ore_input`, preferring the ore subtype already
  present in refinery input or queue before falling back to any available ore.
  Completed refinery ingots in inventory index `1` should also queue
  `transfer_item reason=refinery_output_cleanup` back to ingot cargo.
- O2/H2 generators should receive `set_gas_auto_refill enabled=true`.
  If same-construct cargo Ice exists and the generator inventory is below its
  Ice buffer, the worker should also queue a `transfer_item` into the generator
  inventory with `item_subtype_id=Ice`.
- With dynamic apply enabled, successive sequences should rotate through
  transfers, LCD writes, and machine setup commands while
  `runtime_telemetry.dynamic_apply_budget` rises or falls with PB runtime cost.
- With a low `maxPlannedMachineCommands`, successive result files should still
  include later machine families over time. If only LCD/assembler commands ever
  appear, the worker is stale or the pre-cap foundation rotation is not active.
- Check `data\command_queues\pb-bridge-001.json` when the result shows
  `remaining_commands`. The queue should drain by `commandQueueDrainPerResult`
  commands per processed request, and already-applied setup commands should stop
  reappearing once the plugin snapshot reports the desired block state. Transfer
  queue entries should coalesce by source/destination/item instead of multiplying
  as the planned amount changes, and LCD writes should get early turns without
  permanently starving setup or transfer entries. Reactor uranium transfers,
  refinery input unloads, assembler-shortage ore refining, autocrafting enqueue
  commands, food processor ingredient feeds, and refinery ore input fills should
  appear ahead of bulk ice balancing entries. `transfer_item
  reason=refinery_output_cleanup` and `transfer_item
  reason=assembler_output_cleanup` should get early turns before material feed
  work so completed ingots, components, and food leave managed machines before
  new ingredients are pulled in.
  Managed machine inventories should not appear as transfer sources or
  destinations in normal inventory sorting; reactor/gas/assembler/refinery/food
  processor contents are owned by their module planners.
  Disabled assemblers, food processors, and refineries should not receive new
  input inventory or queue work. Their completed output inventories may still
  drain to cargo so turning a device off does not strand finished items.

Before trusting transfer failures, manually verify the test cargo pair can move
the same item through the in-game inventory UI. A non-conveyored blueprint can
correctly produce `transfer_not_allowed` even when the bridge command is valid.

## Configure PB Runtime Limits

The default limiter file is:

```powershell
data\bridge_limits.json
```

The manager's Limits tab edits the default profile. For this client-side bridge
path, start with:

```text
runtime_ms_limit=0.25
runtime_ms_soft_ratio=0.75
cooldown_seconds=10
```

Paste the same values into the PB shim config block if manually editing the PB
before manager-to-PB profile sync exists.

## Command Throughput Tuning

The PB shim now treats the runtime cap as the primary throughput driver. Start
with:

```text
runtime_ms_limit=0.25
runtime_ms_soft_ratio=0.75
dynamic_apply_commands=true
dynamic_min_apply_commands_per_tick=1
dynamic_max_apply_commands_per_tick=8
```

and keep the worker config at:

```json
{"key": "dynamicCommandQueueDrain", "value": true}
```

in `data\worker_configs\workshop_1216126863_adapter.json`. The worker drains
queued commands from the PB-reported `runtime_telemetry.dynamic_apply_budget`
and still clamps to the result's `max_apply_commands`.

After changing throughput, watch the newest processed request for
`runtime_telemetry.last_runtime_ms`, `runtime_telemetry.dynamic_apply_budget`,
`limiter_state`, and `state.last_apply.skipped`. Lower
`dynamic_max_apply_commands_per_tick` or disable `dynamic_apply_commands` if
samples approach `0.25`, if the limiter enters `soft_limited`/`cooldown`, or if
budget skips appear.

## Build and Hand Off Plugin

```powershell
.\tools\build_local_plugin.ps1
.\tools\handoff_plugin.ps1
```

Close Space Engineers/Pulsar before handoff if the DLL is locked.

## First Live PB Loop

After changing the PB shim or plugin:

1. Re-paste `pb_shim\ClientSidePBBridgeShim.cs` into the in-game programmable
   block and recompile it.
2. Close Space Engineers/Pulsar, run `.\tools\handoff_plugin.ps1`, then reload
   the plugin.
3. Start Docker from the manager or run `docker compose up --build -d`.
4. Run the PB once with `reset`, then run it with no argument.
5. Check the Logs tab or `data\plugin_status.json` for
   `marked_mailboxes`, `staged_requests`, `returned_results`, `last_bridge_id`,
   `last_sequence`, `last_inventory_snapshot_state`,
   `last_inventory_snapshot_blocks`, `last_inventory_snapshot_items`,
   `last_grid_snapshot_state`, `last_grid_snapshot_blocks`,
   `last_grid_snapshot_lcds`, and `last_grid_snapshot_machines`. If grid
   blocks are skipped, check `last_grid_snapshot_skip_samples` for the block
   name/type and exception bucket.
   `last_grid_snapshot_*` describes the newest PB request that the plugin
   enriched. To confirm what the loaded client plugin can see right now, even
   while the PB mailbox is waiting on a returned result, check
   `visible_grid_scan_state`, `visible_grid_scan_blocks`,
   `visible_grid_scan_active_refineries`,
   `visible_grid_scan_active_assemblers`, and
   `visible_grid_scan_production_summary`.

The reset echo should begin with the shim version and include a seeded
sequence, for example
`NOVALI shim=2026-05-20-iim-action-parity-v12 reset_seq=200000000`. If it only shows
`NOVALI bridge sequence reset.` or the next request still has `sequence=1`, the
in-game PB is still running an older compiled program or the edit was not
recompiled.

If `entity_count` is nonzero but `programmable_block_candidates` remains zero,
the loaded plugin is probably an older build that only checks top-level
entities. Rebuild, hand off the plugin, and restart Space Engineers/Pulsar so
the grid fat-block discovery code is active.

If `staged_requests` increments but `returned_results` does not, inspect
`last_mailbox_kind` and `last_result_state` in `data\plugin_status.json`. A
matching result should eventually report `last_result_state=returned`.

If `last_mailbox_kind=result`, `last_grid_snapshot_*` can legitimately remain
stale until the PB consumes that result and stages the next request. In that
state, use the `visible_grid_scan_*` fields to separate "the client plugin can
see the current rendered grid" from "the Docker worker has processed a fresh PB
request."

If the PB shows `NOVALI bridge limiter: cooldown` during a local first test,
compare `last_ms` to `runtime_ms_limit`. The default bridge profile is `0.25`;
the shim migrates the old exact `runtime_ms_limit=0.03` default to
`runtime_ms_limit=0.25` when it sees an existing NOVALI config section.

Result-consuming PB ticks clear the worker result and continue to the normal
limiter/request path. This lets a single automatic tick apply one command and
stage the next request instead of requiring an extra manual no-argument run.
Worker commands rotate across request sequences, so the default one-command
budget can cycle through inventory transfers, the main LCD, inventory LCD,
autocrafting LCD, and conservative machine commands over successive ticks. The
worker prioritizes autocrafting goal enqueue commands ahead of routine LCD and
cleanup transfers so component targets do not starve behind steady refinery or
inventory cleanup.
When ore already sits inside refinery input inventories, refinery balancing can
emit `refinery_ore_rebalance` transfers between online refineries. This keeps
newly built refineries from staying empty just because cargo has no loose ore
left to feed them.
inventory LCD renderer follows IIM custom data: blank custom data shows the IIM
setup/help text, while lines such as
`Ingot 100000 noBar` or `Echo Cargo online` produce item/type displays. Every
same-construct LCD whose name matches `inventoryLCDKeyword` gets its own write
using that panel's own CustomData, so split Ores/Ingots/Components inventory
panels initialize independently. LCD writes get early command-queue priority and
then enter a short cooldown so setup and transfer work can continue. The
`Autocrafting` LCD uses the `autocraftingKeyword` panel, sets the public title,
shows observed component items and manually queued known component blueprints if
no wanted amounts are configured yet, and reads simple target lines such as
`SteelPlate=1000 A`. Shim
`2026-05-20-iim-action-parity-v13-customdata` can also prepopulate that panel's
custom data with discovered component entries such as `SteelPlate=0`, while
preserving existing goals. Discovery is triggered by either a component stack in
inventory or a known component blueprint already present in an assembler queue.
If wanted goals already exist, newly discovered known items should still appear
on the LCD at `/ 0` while the worker queues the CustomData mutation.
For known component recipes, worker results can also
include `enqueue_assembler_blueprint reason=autocrafting_goal`,
`transfer_item reason=autocrafting_material` for missing ingots on queued
component work, and `transfer_item reason=assembler_output_cleanup` for
completed assembler output inventory. Assembler output cleanup routes
components, ingots, tools, ammo, and bottles to matching cargo keywords when
present, with cargo fallback behavior matching the component cleanup path.
Component assemblers can also emit `move_assembler_queue_item
reason=assembler_queue_consolidation` to group duplicate blueprint queue entries
near their first matching entry, and `transfer_item
reason=assembler_input_cleanup` to return unneeded or excess input ingots to
ingot cargo. Input cleanup only counts the first three queue stacks and skips an
assembler when any of those stacks has an unknown material recipe. The
material-feed path totals
all known recipe demand per assembler, including worker-created batches and
manually placed known component blueprints, before subtracting ingots already in
the assembler input. That prevents one small input stack from being treated as
enough for every planned component line. The current bounded recipe map is based
on the installed vanilla component blueprints and includes multi-ingot recipes
such as MetalGrid, Motor, Computer, Display, PowerCell, Thrust, Reactor,
Medical, SolarCell, and Prototech components, plus common ammo/tool assembler
blueprints visible in live queues. Blueprints seen in manual
assembler queues are also persisted in `data/autocrafting_blueprints`, allowing
modded component LCD goals to queue later even when their material recipe is
unknown; material top-up only runs when the recipe is known. Set
`writeInventoryLCDReports=false` only when you intentionally want to preserve
manual inventory LCD surface text.
If LCD writes apply but `grid_snapshot.blocks[].text` remains empty or stale,
rebuild and hand off the Pulsar plugin. The validated path is PB
`GetSurface(0).WriteText(...)` and plugin `GetSurface(0).GetText()`, with
legacy direct `GetText()`/`WriteText()` only as fallbacks.

Pending request envelopes are preserved. If an automatic `Update100` tick runs
before the plugin returns a worker result, the PB echoes
`request_pending=<sequence>` and waits instead of overwriting the mailbox with a
newer sequence. The PB also persists `sequence` in PB `Storage`, so reset and
staged sequence values survive script instance churn.

The shim sets `Runtime.UpdateFrequency = UpdateFrequency.Update100` in both
`Program()` and `Main()`. A manual `reset` or no-argument run therefore
re-arms the scheduler even if the running PB instance lost its update flag.

The PB reads its own `CustomData` mailbox before the optional text panel mirror.
The local plugin polls PB `CustomData`, so a stale text panel envelope must not
block a fresh CustomData request from being staged.

When command application rejects a worker command, the PB echo includes
`last_skip=<reason>`. Common reasons are `budget`,
`transfer_block_missing`, `transfer_connected_grid_blocked`,
`transfer_inventory_missing`, `transfer_item_missing`, and `transfer_failed`.
The next staged request also persists the same PB-side application summary in
`state.last_apply`, including `applied`, `skipped`, `echo`, and `last_skip`.
Inspect the newest `data\bridge_requests\processed\<bridge>-<sequence>.json`
when the PB echo is too transient to read.

Shim `2026-05-19-item-transfer-overload-v9` checks `CanTransferItemTo` and
`CanItemsBeAdded`, then prefers the `TransferItemTo(destination, item, amount)`
overload before falling back to the index overload. If the cargo pair is not
game-transferable, `state.last_apply.last_skip` should report
`transfer_not_allowed` or `transfer_destination_full`.

Shim `2026-05-20-iim-action-parity-v12` adds the first IIM action-parity setup
surface: assembler cooperative mode, gas auto-refill, assembler queue move,
assembler queue remove, and the managed-block conveyor correction. Managed
O2/H2 generators and reactors should now converge to `use_conveyor=false`; gas
auto-refill is still managed separately. Assemblers, food processors, and
refineries use `industryInputMode=hybrid_conveyors` by default, leaving
conveyor pull enabled while the worker handles output cleanup, queue steering,
priority refinery ore nudges, and fallback ore/stone filling. New skip reasons
include `assembler_cooperative_failed`,
`gas_auto_refill_property_missing`, `queue_move_failed`, and
`queue_remove_failed`. LCD writes still decode JSON string escapes before
applying, so `\n` becomes real line breaks, and initialize the target surface
with Isy-style defaults: `Debug`, `0.6`, `TextPadding=2`, left alignment, and
text-and-image mode. Text panel writes can also set an optional public title
for the autocrafting panel.

If the Isy adapter reports `snapshot_missing`, close Space Engineers/Pulsar,
run `.\tools\handoff_plugin.ps1`, restart the game, and verify
`last_inventory_snapshot_state=ok` in `data\plugin_status.json`.
`ok_with_skips` means the plugin produced a snapshot but skipped one or more
blocks whose inventory API could not be reflected safely; check
`last_inventory_snapshot_skipped_blocks` before live application.

If a manual assembler queue is visible in the in-game Production tab but the
newest processed request still shows each assembler with `production_queue: []`,
the running Pulsar plugin is not exposing queue items to the worker. Rebuild and
hand off the local plugin, reload Space Engineers/Pulsar, then check the newest
`data\bridge_requests\processed\<bridge>-<sequence>.json` for non-empty
`grid_snapshot.blocks[].production_queue` before debugging worker-side
autocrafting logic. The plugin queue reader must handle explicit-interface
`GetQueue` methods, not only plain public methods.

`reset` also clears any marked mailbox result from PB CustomData and the text
panel. This is useful after changing `script_id`, because stale result envelopes
from the previous worker script would otherwise leave the plugin seeing
`message_kind=result` instead of a fresh request.

`reset` seeds the next sequence from UTC time instead of returning to `1`.
This avoids a stale `data\bridge_results\<bridge_id>.json` with an old sequence
being returned again after a PB recompile or manual reset.

For live v10 validation after paste/handoff/reload, run reset/no-argument and
inspect the newest processed request for `state.shim_version`, `grid_snapshot`,
and `result.isy_foundation` summaries before relying on in-game Echo.

## Launch Manager

```powershell
dotnet run --project .\manager\NOVALI.ClientSidePBManager.csproj
```

Use the Workshop Scripts tab to scan/import candidates and the Docker tab to
start or stop the worker.

Use the Limits tab before live tests so the PB shim avoids server-side PB
offlining thresholds.

Use `Prepare Adapter` on a selected `pb_script` when Compatibility is
`manual_adapter_required`. This creates a local copy, analysis report, and
disabled worker scaffold; it does not automatically prove the full Workshop
script has been ported.

## Associate Worker Scripts With A Bridge

Use the Worker Scripts tab:

1. Set `Bridge` to the PB bridge id, for example `pb-bridge-001`.
2. Check `Enabled` for adapters Docker may run.
3. Check `Allowed For Bridge` for adapters this bridge may request.
4. Pick the selected script in `Selected Script`.
5. Click `Save Manifest`, then `Save Bridge`.
6. Click `PB Config` and paste or mirror the shown `script_id` into the PB shim
   CustomData.

Use `snapshot_mode=minimal` for transport and adapter smoke tests. Use
`snapshot_mode=grid_summary` only when the adapter needs block and inventory
counts from the PB side, because scanning large grids can push
`Runtime.LastRunTimeMs` above strict server limits.

For Isy inventory sorting, keep `snapshot_mode=minimal`; inventory state is
provided by the local plugin, not by the PB.

Generated Workshop scaffolds, including Isy's Inventory Manager, start disabled
because they still need manual behavior mapping before they are equivalent to
the original PB script.

To create separate configurations, select a worker script, click `Load Local
Copy`, edit the Python adapter, enter a new `Clone Id` and `Name`, then click
`Clone`. The clone creates a new local file under `worker\scripts` and a new
manifest entry; it does not modify the original Workshop cache.

Use the `Config` sub-tab to extract and edit operator settings. For Workshop
adapters, `Extract Config` reads the imported `Script.cs` and writes
`data\worker_configs\<script_id>.json`. The worker passes those values to the
adapter as `worker_config`.
