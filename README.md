# NOVALI Client-Side PB Bridge

Client-Side PB Bridge is a local Space Engineers/Pulsar experiment for moving
expensive programmable block planning work off the server and onto the player's
machine.

V1 is adapter-based. It does not run arbitrary Workshop PB C# unchanged outside
the game. A small PB shim gathers bounded state, a local Pulsar plugin mirrors
mailbox data into shared files, and a Docker worker runs selected local adapters
before the PB shim applies compact returned commands.

The first real Workshop behavior slice is Isy's Inventory Manager. The PB shim
remains in `snapshot_mode=minimal`; the local Pulsar plugin enriches requests
with bounded inventory and grid snapshots, the Docker worker plans from the
extracted Isy config, and the PB shim applies a small allowlisted command
budget each tick.

## Project Shape

- `client_plugins/NOVALI.ClientSidePBBridge` contains the Pulsar local plugin.
- `pb_shim/ClientSidePBBridgeShim.cs` is the pasteable PB-side adapter.
- `worker/` contains the Docker worker and sample adapters.
- `workshop/` scans subscribed Steam Workshop scripts read-only.
- `manager/` contains the Windows WPF management app.
- `tools/` contains build, handoff, scanner, and smoke-test commands.
- `planning/` records architecture, safety boundaries, and runbook state.

The Windows manager keeps PB setup visible from the Bridges tab. Selecting a
bridge result/request row, or refreshing after a new bridge id appears, opens a
bottom CustomData prompt with the exact `[NOVALI.ClientSidePB]` block for the
currently selected bridge and worker script. The existing Worker Scripts `PB
Config` button uses the same generator and still mirrors the text into Logs.

## Isy Foundation

`workshop_1216126863_adapter` now implements the first Isy's Inventory Manager
behavior modules. Inventory sorting still uses the compatibility-preserving
`inventory_snapshot` and remains the first planner. The new foundation planners
use plugin-side `grid_snapshot` records for LCD/status output, assemblers,
refineries, O2/H2 generators, gas tanks, reactors, cargo, connectors, and
PB-adjacent terminal blocks.

The foundation batch emits live commands by default, within the same worker and
PB budgets. New PB command kinds are `write_text_surface`,
`write_block_custom_data`, `set_block_enabled`, `set_use_conveyor`, `set_assembler_mode`,
`set_assembler_cooperative_mode`, `set_gas_auto_refill`,
`enqueue_assembler_blueprint`, `move_assembler_queue_item`,
`remove_assembler_queue_item`, and `clear_assembler_queue`. These are
foundation commands, not full behavior parity yet; the current parity state is
tracked in `planning/isy_parity_matrix.md`.
The worker now uses hybrid industry input stocking by default. Assemblers, food
processors, and refineries keep their conveyor pull enabled while the worker
continues to steer high-value behavior: queue goals, priority ore nudges,
fallback ore/stone filling, output cleanup, and cargo sorting. Set
`industryInputMode=plugin_only` to restore the older conveyor-off input
management for those industry blocks. Reactors and O2/H2 generators remain on
the safer explicit managed path for now.
Refineries can queue bounded non-Ice ore `transfer_item` top-ups from
same-construct non-machine cargo into their input inventory. When assembler
work is short on an ingot and matching ore is available, an active refinery can
also unload a non-priority ore stack back to Ores cargo and feed the shortage
ore so it does not stay stuck refining the wrong material. The selector treats
ore already in refinery input, output, or the refinery queue as already covered
before looking for the next shortage ore. If the prioritized shortage ore is not
available, active refineries fall back to available non-Ice ore or stone,
preferring the ore type already in their input or queue so they keep running.
O2/H2 generators also plan auto-refill setup through the explicit gas command,
and underfilled generators can queue bounded Ice `transfer_item` top-ups from
same-construct non-machine cargo so conveyor-off setup does not leave them dry.
LCD rendering now follows the IIM script shape more closely while keeping the
PB-side work tiny. The Docker worker builds the main LCD status text and writes
every LCD whose name matches `inventoryLCDKeyword`, parsing each panel's own
custom data using IIM-style item/type filters, `Echo` lines, and modifiers such
as `noHeading`, `noBar`, `hideEmpty`, `hideType`, and `singleLine`. If an
inventory LCD custom data is empty, the worker writes the same guidance text IIM
shows for configuring that panel. PB-side LCD writes
mimic Isy's default surface setup (`Debug`, font size `0.6`, padding `2`, left
alignment, text-and-image) and decode JSON escapes so `\n` renders as real line
breaks in game. The worker also writes the `Autocrafting` LCD with IIM-style
heading, observed component items, manually queued known component blueprints,
empty-panel/error text, and simple target lines parsed from custom data such as
`SteelPlate=1000 A`; the PB can set that
panel's public title. For known component recipes, autocrafting can queue a
bounded component batch from wanted stock, total the material demand from both
worker-planned and manually placed component queue entries per assembler, feed
the cumulative missing ingots, drain completed refinery ingots back to ingot
cargo, and move completed assembler output back to matching cargo for
components, ingots, tools, ammo, and bottles. Component assemblers also group
duplicate queue entries with safe queue-move commands and return input ingots
that are not needed by the first three known queue stacks, or are present in
excess of those stacks' known recipe demand, back to ingot cargo. If any of the
first three queue entries has an unknown material recipe, input cleanup for that
assembler is skipped so modded or newly discovered work is not starved. Food
processors are treated as a
separate autocrafting machine family even when the game exposes them as
`MyAssembler`: food goals such as `MealPack_KelpCrisp` queue on Food Processor
blocks, feed Algae into input inventory `0`, and drain completed
`ConsumableItem` output from inventory `1` to cargo matching
`foodContainerKeyword` (`Food` by default, with normal cargo fallback).
The current bounded recipe map is generated from the installed vanilla
component blueprints, including multi-ingot recipes such as MetalGrid, Motor,
Computer, Display, PowerCell, Thrust, Reactor, Medical, SolarCell, and
Prototech components, plus common assembler ammo/tool blueprints and the Food
Processor Kelp Crisp recipe.
Blueprints seen in manual assembler queues are also learned and persisted under
`data/autocrafting_blueprints`, so modded components can be added to the
Autocrafting LCD and queued later even when their material recipe is unknown.
Discovered known items are displayed at `/ 0` and added to the panel CustomData
as zero-wanted entries.
If the in-game Production tab shows a manual queue but the newest processed
request still has `production_queue: []`, rebuild and hand off the Pulsar
plugin, then reload Space Engineers/Pulsar. Queue learning depends on the local
plugin reading assembler `GetQueue`, including explicit-interface implementations
that do not appear as a plain public method on the concrete block type.
If the in-game LCD updates but the newest `grid_snapshot.blocks[].text` is
empty or stale, rebuild and hand off the Pulsar plugin. Snapshot text reads now
prefer `GetSurface(0).GetText()` to match the PB shim's `GetSurface(0).WriteText`
path, with direct `GetText()` kept only as a fallback.
When `data\plugin_status.json` reports `last_mailbox_kind=result`, the
`last_grid_snapshot_*` counters still describe the last PB request that was
enriched. Use `visible_grid_scan_*` for the current rendered-grid diagnostic;
it refreshes from the marked PB's grid before the plugin filters out result
mailboxes, so it can confirm newly built production blocks while the PB is
still waiting to consume a returned result.
Autocrafting goal enqueues are prioritized ahead of routine LCD refreshes and
cleanup transfers in the worker command queue, which keeps component production
from starving when refineries and inventories keep generating maintenance work.
Assembler input-ingot cleanup and queue consolidation are also prioritized
ahead of routine LCD and output cleanup work, but behind active autocrafting
enqueue/material-feed commands.
Refinery ore balancing also redistributes ore already sitting in online
refinery input inventories, so newly added refineries can receive load even
when there is no loose ore left in cargo.

Sorting is controlled from the Worker Scripts tab, Config sub-tab:

- `inventorySortingEnabled`: plan sorting work for this adapter.
- `inventorySortingDryRun`: report proposed commands without applying them.
- `maxApplyCommands`: worker-side apply budget, default `8`.
- `maxPlannedTransfers`: maximum planned transfer/rename commands per tick.
- `maxPlannedMachineCommands`: maximum planned LCD/machine commands per tick.
- `dynamicCommandQueueDrain`: let the Docker worker drain queued commands from
  the PB shim's runtime-derived `dynamic_apply_budget`; enabled by default.
- `commandQueueDrainPerResult`: fixed queued-command drain fallback when dynamic
  draining is disabled or old PB telemetry is missing.
- `writeInventoryLCDReports`: allow the worker to write IIM-style
  custom-data-driven inventory LCD output; enabled by default.
- `autocraftingKeyword`: LCD keyword for the IIM-style autocrafting panel;
  default `Autocrafting`.
- `foodContainerKeyword`: cargo keyword for consumable food outputs; default
  `Food`.
- `industryInputMode`: `hybrid_conveyors` by default, which leaves assembler,
  food processor, and refinery conveyor pull enabled while the worker handles
  queues, output cleanup, and priority input nudges. Use `plugin_only` to make
  those industry blocks follow the older conveyor-off, explicit-input workflow.
- `allowConnectedGrids`: include connected grids; disabled by default.

The PB shim only applies allowlisted command kinds and keeps same-construct
sorting as the default. Its command apply rate is dynamic by default:
`dynamic_apply_commands=true`, `dynamic_min_apply_commands_per_tick=1`, and
`dynamic_max_apply_commands_per_tick=8`. The configured
`runtime_ms_limit=0.25` profile is the primary driver: the shim steps the apply
budget up while the last PB runtime is comfortably below the cap and steps it
down as the soft threshold approaches. The older `max_apply_commands_per_tick`
is still available as the fixed cap when dynamic apply is disabled.
The Docker worker now keeps a per-bridge command queue under
`data/command_queues`. Planned non-echo commands are coalesced into that queue,
acknowledged from the next request's `state.last_apply`, and emitted as a
steady stream. Transfer commands coalesce by source, destination, inventory, and
item identity so changing planned amounts update existing queue entries instead
of creating repeat work. LCD writes, including first-time main/inventory panel
initialization, are prioritized, then briefly cooled down after a successful
apply so setup and transfer commands keep draining. Echo
commands still pass through immediately. The foundation planner also rotates
machine/LCD candidates before applying `maxPlannedMachineCommands`, so later
machine families such as gas generators and reactors still get planning turns on
dense grids.
The queue prioritizes assembler mode setup, refinery output cleanup,
assembler/food processor output cleanup, refinery input unloads,
assembler-shortage ore refining, autocrafting enqueue commands, autocrafting
material feeds, inventory sorting corrections, reactor uranium top-ups, refinery
ore input fills, O2/H2 generator Ice top-ups, and misplaced non-ice ingots ahead
of bulk ice rebalancing so
critical/reactive work is not trapped behind steady O2/H2 generator churn. When
assembler work needs an ingot type that is short but matching ore is available,
refineries prefer that ore before generic ore balancing, including swapping out
already-loaded non-priority ore when needed.
General inventory sorting skips managed machine inventories as source and
destination containers, leaving reactor uranium, generator ice, assembler
contents, refinery contents, and food processor outputs to their dedicated
module behavior instead of sorting them back and forth with cargo.
Worker results include `industry_input_mode` both at the result top level and
inside `isy_foundation`, so live status shows whether the current run is hybrid
or plugin-only.
The foundation planners also respect operator power state for machine inputs:
disabled assemblers, food processors, and refineries are not selected for new
queue work or input transfers, though completed output can still be drained back
to cargo.

## Runtime Limiter

The companion manager has a Limits tab backed by `data/bridge_limits.json`.
The default profile treats `0.25` as the PB runtime-ms ceiling for this
client-side bridge:

- hard limit: `runtime_ms_limit=0.25`
- soft skip threshold: `runtime_ms_limit * runtime_ms_soft_ratio`
- dynamic apply budget: `dynamic_apply_budget`, clamped by
  `dynamic_min_apply_commands_per_tick` and
  `dynamic_max_apply_commands_per_tick`
- cooldown: `cooldown_seconds=10`

The PB shim checks `Runtime.LastRunTimeMs` before grid scanning or request
staging. If it is near the configured limit, the shim skips outbound work or
enters cooldown instead of risking a server-side PB limiter offlining the block.
Use `snapshot_mode=minimal` for the lowest PB-side runtime cost; opt into
`snapshot_mode=grid_summary` only when an adapter needs block/inventory counts.

Mailbox payloads include a direction field: `message_kind=request` for PB to
worker traffic and `message_kind=result` for worker to PB traffic. This prevents
the shim from echoing its own outbound request as a blank result during live
tests.

Live requests also include `state.last_apply`, the durable PB-side summary of
the previous result application attempt. Use it in processed request files to
confirm `applied`, `skipped`, and `last_skip` after inventory commands run.

For `transfer_item` commands, the PB shim checks whether Space Engineers allows
the source item to move into the destination inventory before applying. It
prefers the item overload for transfer, then falls back to the index overload.
For the v10 Isy foundation command surface, the next request's
`state.last_apply.last_skip` reports command-specific skip reasons such as
`text_surface_missing`, `block_not_functional`, `conveyor_property_missing`,
`assembler_missing`, `gas_auto_refill_property_missing`,
`queue_move_failed`, `queue_remove_failed`, `blueprint_invalid`, and
`queue_failed`.

## Workshop Names and Adapter Prep

The Workshop Scripts tab resolves human-readable Steam Workshop names during
refresh. It also supports a Kind filter so PB scripts can be separated from
mods, blueprints, and unknown cached items.

`manual_adapter_required` means the Workshop item is a programmable block
script, but it cannot be safely run unchanged in Docker. Use `Prepare Adapter`
to copy the script into `data/imports/<workshop_id>`, generate an analysis
report, create a worker adapter scaffold, and register that adapter disabled in
`worker/manifest.json` for review.

## Universal Gateway

The next gateway mode is `bridge_orchestrator`. A bridge can select that worker
script and store `child_worker_scripts` in `data/bridge_scripts.json`; each
child has a `script_id`, `enabled` flag, per-tick `budget`, and numeric
`priority`. The orchestrator runs allowed children against one request, tags
their commands with `source_script_id`, and drains one shared queue with
source-aware priority and expiry support so reactive scripts such as doors,
lights, alarms, or docking helpers can stay ahead of heavier maintenance work.

Workshop PB C# now has a first constrained import lane through manifest entries
with `runtime: "virtual_pb_csharp"` and a `source_path` under `data/imports`.
V1 is intentionally a compatibility subset, not a full Space Engineers runtime:
the virtual PB runner analyzes the imported `Script.cs`, rejects unsafe APIs,
executes a reviewed door/light/text-surface surface, and emits only allowlisted
commands such as `set_door_open`, `set_light_color`, `set_block_enabled`, and
`write_text_surface`. Compatibility results are written to
`data/virtual_pb_compatibility.json` for the manager to display.

## Quick Start

From this folder:

```powershell
python -m pytest -q
.\tools\scan_workshop.ps1
docker compose up --build
```

To build the local Pulsar plugin:

```powershell
.\tools\build_local_plugin.ps1
.\tools\handoff_plugin.ps1
```

To launch the manager:

```powershell
dotnet run --project .\manager\NOVALI.ClientSidePBManager.csproj
```

The Docker worker publishes a read-only status UI on
`http://localhost:8788`. Docker Desktop shows this as a clickable port link for
the `clientside_pb_script` container group.
If Docker Desktop does not show the link, use the manager's `Open Worker UI`
button or run:

```powershell
.\tools\open_worker_ui.ps1
```

The status page includes an `Open Configuration UI` button. The helper above
registers the per-user `novali-client-side-pb-manager://` URL protocol so that
button can launch the Windows WPF manager. To register the protocol directly:

```powershell
.\tools\register_manager_protocol.ps1
```

## Safety Defaults

- Workshop files are read-only inputs. Imports are copied into `data/imports`.
- Server-side PB work stays small: sequence checks, mailbox IO, minimal state, and
  compact command application.
- External worker scripts run with timeouts and explicit manifests.
- Worker adapters are enabled in `worker/manifest.json`, and per-bridge
  allowlists are stored in `data/bridge_scripts.json`.
- Local worker copies under `worker/scripts` can be edited or cloned from the
  manager to create separate adapter configurations without modifying Steam
  Workshop cache files.
- Operator settings extracted from imported PB scripts are stored under
  `data/worker_configs` and can be edited from the Worker Scripts tab.
- The bridge fails closed when sequence, identity, mailbox, or compatibility
  checks do not line up.
- The PB shim fails closed on invalid limiter configuration by default.
- Inventory sorting fails closed when plugin-side inventory snapshots are
  missing; the worker returns `status=rejected` with
  `error_bucket=snapshot_missing`.
- PB-side command application is allowlisted and rate-limited. The default is
  one immediate command per PB run.

## License

This repository is source-available under the [NOVALI Client-Side PB Bridge Proprietary Beta License](LICENSE.md). It is not open source.

You may view, download, install, and run it for evaluation, development testing, and approved private beta testing. Redistribution, commercial use, derivative publication, and public or live server use outside an approved beta require prior written permission.
