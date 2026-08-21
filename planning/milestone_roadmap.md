# Milestone Roadmap

## M1: Scaffold and Local Contracts

- Project scaffold, docs, Docker worker, WPF manager, PB shim, Pulsar plugin,
  Workshop scanner, and tests.
- Sample adapter demonstrates request/result flow.

## M2: Live Singleplayer Bridge

- Validate PB CustomData and text-panel mailbox behavior in singleplayer.
- Confirm plugin can discover the PB and return matching worker results.
- Validate the runtime limiter at the `0.25` client-side bridge profile before trying
  a multiplayer server with PB offlining rules.
- Record exact live setup notes in this planning folder.

## M3: Private Multiplayer Bridge

- Validate replication behavior on a friend/private server.
- Decide whether CustomData remains a live mailbox or text panel becomes the
  default response surface.

## M4: Adapter Conversion Workflow

- Add per-script analysis for Workshop imports.
- Generate adapter stubs from selected candidates.
- Add compatibility notes and manual conversion checklists.
- Implemented first Isy behavior slice: inventory sorting through plugin-side
  snapshots, worker-side transfer planning, and PB-side command application.
- Added Isy foundation slice: plugin-side `grid_snapshot`, LCD reporting,
  assembler/autocrafting command plumbing, refinery conveyor setup, gas/ice
  setup, reactor/uranium setup, and v11 PB command handlers. LCD rendering now
  moves IIM-shaped status, inventory custom-data filter output, and
  autocrafting LCD target/error text into the worker, while PB-side LCD writes
  decode JSON escapes, optionally set a panel public title, and apply Isy-style
  surface defaults before `WriteText`.
- Added v12 IIM action-parity pass: managed machine conveyor-off setup for
  reactors, assemblers, refineries, and O2/H2 generators; gas auto-refill setup,
  assembler cooperative
  mode, assembler queue move/remove command primitives, queue/auto-refill
  snapshot fields, manual/exclusion keyword gates for machine setup, and
  `planning/isy_parity_matrix.md`.
- Added Docker-side per-bridge command queues so planned non-echo commands drain
  into the PB in a steady stream, with acknowledgments from `state.last_apply`
  and snapshot-gated idempotent setup planning to avoid repeat loops. The queue
  now coalesces changing transfer amounts, prioritizes LCD/setup work, and uses
  LCD cooldowns so display refreshes do not permanently block machine work.
  Reactor uranium top-ups, refinery ore input fills, generator Ice top-ups, and
  misplaced non-ice ingots are prioritized ahead of bulk ice balancing.
- Added gas-generator Ice top-ups from same-construct non-machine cargo sources
  so conveyor-off O2/H2 generator management can still keep generators supplied
  when cargo Ice is available.
- Added bounded refinery ore input fills from same-construct non-machine cargo
  sources so conveyor-off refinery management can still keep refinery input
  inventories fed when processable ore is available.
- Added the v13 autocrafting custom-data path: the worker can prepopulate the
  Autocrafting LCD custom data with discovered component entries through a
  narrow `write_block_custom_data` PB command gated to
  `reason=autocrafting_discovered_items`. Discovery now includes observed
  component stacks and known component blueprints manually placed in assembler
  queues.
- Added bounded known-component autocrafting behavior: wanted stock can enqueue
  component blueprint batches, manually queued known component work can receive
  missing ingot top-ups, planned and manual queue material demand is totaled per
  assembler before input ingots are subtracted, vanilla multi-ingot component
  recipes can request their non-Iron inputs, and completed assembler output
  components can move to component cargo.
- Added persisted blueprint learning for manual assembler queue entries so
  modded components can be discovered, written to the Autocrafting LCD custom
  data, and later queued from LCD goals even when their material recipe is
  unknown.
- Captured the future single-PB, multi-adapter orchestration path in
  `planning/multi_adapter_bridge_orchestrator.md`, including Isy plus Whip auto
  door as the motivating example.
- Next Isy work is live dummy-grid validation of the bounded autocrafting
  queue/material/output loop, reactor target uranium, refinery ore input, and
  generator Ice fills, then deeper behavior parity for gas bottle refill nuance
  and refinery queue ordering after the foundation command path is proven on a
  properly conveyored test grid.

## M5: Hardened Operations

- Add richer health status, worker logs, stale bridge detection, and backup
  export/import for manager state.
- Add UI editing for per-bridge limiter overrides once multiple bridges are in
  regular use.
