# Client-Side PB Bridge Architecture

## Runtime Shape

- A Space Engineers client runs with Pulsar local plugin support.
- A pasteable PB shim stays on the server-authoritative programmable block.
- `NOVALI.ClientSidePBBridge` walks visible game entities, expands cube grids
  into fat blocks, and mirrors marked PB/text-panel mailbox payloads between
  terminal blocks and local shared files.
- For Isy requests, the plugin enriches the PB's minimal request with bounded
  local `inventory_snapshot` and `grid_snapshot` payloads. This keeps grid
  inventory and terminal-block scanning out of the PB shim while still giving
  the worker enough state to plan.
- The Docker worker reads `data/bridge_requests`, executes allowlisted adapter
  modules, and writes `data/bridge_results`.
- The WPF manager scans Workshop scripts, manages Docker, shows bridge state,
  and imports candidate scripts read-only into `data/imports`.
- The WPF manager persists PB runtime-limit profiles in
  `data/bridge_limits.json`.
- The WPF manager persists per-bridge worker-script selections and allowlists in
  `data/bridge_scripts.json`.

## Workshop Catalog

The scanner parses Steam `libraryfolders.vdf`, then checks each
`steamapps/workshop/content/244850/<workshop_id>` folder. Root-level
`Script.cs` or `script.cs` files are classified as PB script candidates.
`Data/Scripts/**/*.cs` files are classified as mod/session scripts and are not
offered as adapter-ready PB scripts.

During normal refresh, the scanner also queries Steam published-file details
for human-readable item titles. If the network lookup fails, the local cache
scan still succeeds with fallback titles.

Workshop files are never modified. Imported candidates are copied into
`data/imports/<workshop_id>/Script.cs` with a metadata snapshot.

The adapter-prep workflow copies a selected PB script, writes
`adapter_report.json`, generates a disabled worker adapter scaffold, and adds it
to `worker/manifest.json`. The disabled default is intentional: a scaffold is
not equivalent to a reviewed, behavior-preserving script conversion.

## Data Flow

1. PB shim writes a marked request into PB CustomData and optionally a text
   panel.
2. Before any grid scan, the PB shim checks `Runtime.LastRunTimeMs` against the
   configured runtime-ms limit. It skips work on soft-limit readings and enters
   cooldown on hard-limit readings.
3. Pulsar plugin discovers programmable blocks by scanning cube-grid fat blocks,
   sees the marked `message_kind=request` payload, enriches it with
   `inventory_snapshot` and `grid_snapshot`, and writes
   `data/bridge_requests/<bridge_id>.json`.
4. Docker worker validates schema, bridge id, sequence, script id, manifest
   status, and timeout.
5. Worker coalesces planned non-echo commands into
   `data/command_queues/<bridge_id>.json`, acknowledges prior emitted commands
   from `state.last_apply`, and writes `data/bridge_results/<bridge_id>.json`
   with only the current drain batch. Results can include `commands`,
   `apply_mode=immediate`, `max_apply_commands`, `queued_commands`,
   `drained_commands`, and `remaining_commands`.
6. Pulsar plugin returns the matching `message_kind=result` payload to the PB
   mailbox.
7. PB shim accepts only result payloads with the current bridge id, script id,
   and sequence, then applies only allowlisted commands within its per-tick
   budget. A result-consuming tick records `state.last_apply`, clears the
   mailbox, and may continue through the limiter path to stage the next request
   in the same run.

## Inventory Snapshot

Plugin-side snapshots use schema
`novali.client_side_pb.inventory_snapshot.v1`. Each block record contains the
block entity id, name, type/subtype, same-construct marker, inventory indexes,
volume/fullness data, and item type/subtype/amount records. Snapshot caps are
reported in the payload and plugin status exposes the latest block/item counts.

The PB-side `snapshot_mode=minimal` stays the default. If plugin enrichment is
unavailable, Isy inventory sorting rejects the request with
`snapshot_missing` instead of asking the PB to scan inventories server side.

Each PB request includes `state.last_apply`, which records the previous
PB-side result application attempt. That makes `applied`, `skipped`, `echo`,
and `last_skip` available in processed request files instead of relying on the
transient PB Echo surface.

PB `reset` uses a time-derived sequence seed rather than restarting at `1`.
This keeps old bridge-result files from being accepted after a recompile/reset
cycle.

## Grid Snapshot

Plugin-side grid snapshots use schema
`novali.client_side_pb.grid_snapshot.v1`. They sit alongside
`inventory_snapshot` rather than replacing it. The snapshot includes bounded
records for visible same-grid LCD/text panels, assemblers, refineries, O2/H2
generators, gas tanks, reactors, cargo, connectors, and PB-adjacent terminal
blocks. Records expose block identity, same-construct state, enabled/conveyor
flags where available, inventories, LCD text/custom data, assembler
mode/cooperative state, bounded production queue entries, gas auto-refill,
stockpile, gas fill ratio, and boolean type helpers. The fallback grid block
path also preserves LCD text/custom data so panels found through ambiguous game
interfaces still carry operator configuration into the worker.

Plugin status now reports grid snapshot state, block count, LCD count, machine
count, skipped blocks, and truncation so live tests can diagnose missing
surfaces from files before relying on PB Echo.

## Isy Inventory Sorting

`worker.scripts.workshop_1216126863_adapter` now delegates to
`worker.isy_foundation`. Inventory sorting remains the first module and still
delegates to `worker.isy_sorting`. Foundation modules then add LCD reporting,
autocrafting/assembler setup, refinery conveyor setup, gas/ice setup, and
reactor/uranium setup from `grid_snapshot`.
Current IIM setup parity explicitly sets managed assembler, refinery, O2/H2
generator, and reactor conveyor state off so automatic push/pull stays under
IIM-managed behavior. Gas auto-refill is managed separately, assembler mode is
set to assembly, and assembler cooperative mode follows `splitAssemblerTasks`.
Reactor balancing can also top up enabled same-construct reactors toward the
configured uranium target by queueing a bounded `transfer_item` from an observed
uranium ingot source.
Refinery balancing can top up empty or underfilled refinery input inventories
with bounded non-Ice ore transfers from same-construct sources that are not
managed machines.
Gas balancing can likewise top up underfilled enabled O2/H2 generators toward a
small Ice buffer by queueing bounded `transfer_item` commands from
same-construct Ice sources that are not managed machines.
General inventory sorting no longer treats managed machine inventories
(`MyReactor`, `MyGasGenerator`, `MyAssembler`, `MyRefinery`) as ordinary source
containers. Dedicated modules own filling or cleanup for those blocks so reactor
uranium and generator ice are not immediately sorted back into cargo.
LCD reporting is rendered in `worker.isy_foundation`, not in the PB shim. Main
LCD output follows IIM's status-panel shape. Inventory LCD output uses the
target panel custom data as the IIM script does: filter lines select item/type
totals, `Echo` lines are emitted directly, and foundation-supported modifiers
include `noHeading`, `noBar`, `hideEmpty`, `hideType`, and `singleLine`. Blank
custom data returns IIM's setup/help text. Operators can disable inventory LCD
writes with `writeInventoryLCDReports=false`.
The autocrafting LCD path uses `autocraftingKeyword`, renders the `IIM
Autocrafting` heading, parses simple target lines such as `SteelPlate=1000 A`,
shows observed component items and manually queued known component blueprints
when no wanted amounts are configured yet, and emits IIM-style
no-goal/no-assembler text when the panel or grid is not ready for real
autocrafting. When wanted goals are configured, the LCD also displays newly
discovered known items at `/ 0` so text updates in the same worker result that
queues the CustomData mutation. When discovered component items are missing
from the autocrafting panel's custom data, the worker can queue a narrow
`write_block_custom_data` command to add zero-wanted entries while preserving
existing configured goals.
For known component recipes, the same module can
queue bounded component batches from wanted stock, feed cumulative missing ingots
for both newly planned batches and known component entries already present in an
assembler queue, and move completed component output back to component cargo. The
bounded recipe table is populated from installed vanilla component blueprints, so
multi-ingot components can request Nickel, Cobalt, Silicon, Silver, Gold,
Platinum, Magnesium, Stone, and PrototechScrap where those materials are part of
the vanilla recipe. The Docker worker persists
blueprint ids learned from manual assembler queue entries under
`data/autocrafting_blueprints`; these learned entries allow modded component
LCD goals to enqueue the original blueprint even when no material recipe is
available for automatic input feeding.
PB-side LCD application mirrors Isy's surface initialization defaults (`Debug`,
`0.6`, padding `2`, left alignment, text-and-image) and decodes JSON string
escapes before `WriteText`, so worker result payloads can stay compact JSON
while in-game LCDs receive real line breaks. Text panel writes can also carry
an optional public title, used for the autocrafting panel.

Initial supported config flags include `autoContainerAssignment`,
`assign*`, `oresIngotsInOne`, `toolsAmmoBottlesInOne`,
`balanceTypeContainers`, `hiddenContainerKeywords`,
`lockedContainerKeywords`, `inventoryFullBuffer`, and NOVALI adapter controls
such as `inventorySortingDryRun`, `maxApplyCommands`, and
`allowConnectedGrids`. New foundation planning is bounded by
`maxPlannedMachineCommands` and the existing PB-side
`max_apply_commands_per_tick`. Returned worker commands rotate by request
sequence so a one-command PB budget does not permanently starve LCD or machine
commands behind a stable prefix of inventory transfer commands.
The Docker-side command queue further coalesces repeated commands before
draining them to the PB. Transfer identity ignores amount so a changing planner
amount updates one queue entry, and LCD writes are prioritized with a short
post-apply cooldown so display refreshes get seen without blocking setup and
transfer work indefinitely. Reactor uranium top-ups, refinery ore input fills,
generator Ice top-ups, and misplaced non-ice ingot transfers are prioritized
ahead of bulk ice balancing so critical and reactive inventory corrections are
not trapped behind steady gas-generator churn.
The full imported Isy mutation surface is tracked in
`planning/isy_parity_matrix.md`; the bridge grows by explicit command kinds and
snapshot fields rather than arbitrary terminal action execution.
Idempotent setup commands are only planned when the latest plugin snapshot does
not already match the desired state. This keeps the worker command queue from
repeating already-applied conveyor, mode, cooperative, and auto-refill setup.

## PB Runtime Limiter

The default limiter profile treats `0.3` as the PB runtime-ms ceiling for the
client-side bridge. The shim
emits `last_runtime_ms`, `max_runtime_ms`, `current_instruction_count`,
`max_instruction_count`, and `limiter_state` in each request that reaches the
worker. Limiter states are `ok`, `soft_limited`, `cooldown`, `disabled`, and
`config_invalid`.

The PB shim supports `snapshot_mode=minimal` and `snapshot_mode=grid_summary`.
Minimal mode avoids grid scans and is the safer default for strict PB runtime
limits. Grid-summary mode includes block and inventory counts but can be
expensive on large grids.

## Manager

The WPF manager is intentionally local-first and does not require a fixed
localhost port. It shells out to `python -m workshop.scan_workshop` for catalog
refreshes and `docker compose` for worker lifecycle. The main status surfaces
are local JSON files under `data/`.

The Limits tab edits the global default profile. Per-bridge overrides are
reserved in the JSON schema and can be added without changing the PB mailbox
contract.

The Workshop Scripts tab exposes text search, Kind filtering, Steam page open,
local import, and adapter scaffold preparation.

The Worker Scripts tab edits `worker/manifest.json` enablement, writes
per-bridge script assignments, edits/clones local `worker/scripts` adapter
files, and exposes extracted operator config files from `data/worker_configs`.
A bridge assignment can restrict a bridge to a specific set of worker adapters;
the Docker worker reloads these files while it runs.

The Worker Scripts Config sub-tab includes an Inventory Sorting section for the
operator-facing Isy controls that affect live command application: apply
enabled, dry run, connected grids, apply budget, and planning budget.

Worker config extraction handles common PB declaration forms such as strings,
booleans, numbers, string arrays, and string lists. Runtime behavior mapping is
still adapter-specific: a config value can be automated into a table, but moving
items, changing blocks, or writing displays must be represented as compact
commands that the PB shim knows how to apply.

The plugin status file includes discovery counters for live troubleshooting:
entity count, programmable block candidates, marked mailboxes, staged requests,
returned results, last bridge id, and last sequence.

Shared JSON files are treated as UTF-8. The worker accepts UTF-8 with or
without a byte-order mark, and new plugin builds write UTF-8 without a
byte-order mark.

Worker result files are written as compact JSON because the PB shim and local
plugin intentionally use tiny string extractors instead of a full JSON parser in
the game process.
