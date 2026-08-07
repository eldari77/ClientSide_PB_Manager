# Safety Boundary

## Allowed

- Read subscribed Space Engineers Workshop cache files.
- Copy selected PB script candidates into `data/imports`.
- Generate disabled adapter scaffolds for selected PB script candidates.
- Read and write local shared bridge files under this project.
- Store per-bridge pending command queues under `data/command_queues`.
- Mirror marked mailbox payloads for PBs/text panels that the local client can
  see and edit through normal game permissions.
- Run allowlisted worker adapters with timeouts.
- Restrict worker adapters per bridge through `data/bridge_scripts.json`.
- Enrich bridge requests with local, bounded inventory and grid snapshots from
  blocks visible to the local client.
- Apply allowlisted PB commands emitted by an allowlisted worker adapter:
  `transfer_item`, `rename_block`, `echo`, `write_text_surface`,
  `write_block_custom_data`, `set_block_enabled`, `set_use_conveyor`,
  `set_assembler_mode`, `set_assembler_cooperative_mode`, `set_gas_auto_refill`,
  `enqueue_assembler_blueprint`, `move_assembler_queue_item`,
  `remove_assembler_queue_item`, and `clear_assembler_queue`.
- Edit and clone only local worker adapter files under `worker/scripts`.
- Edit only local extracted worker config files under `data/worker_configs`.
- Configure conservative PB runtime limiter profiles through the local manager.

## Not Allowed

- Modify Steam Workshop cache files in place.
- Claim arbitrary PB C# can execute unchanged outside the game.
- Treat an adapter scaffold as a completed conversion without review.
- Bypass server settings, disabled programmable blocks, ownership checks, or
  social/server rules.
- Issue Torch/server admin commands.
- Run unrestricted keyboard/mouse automation.
- Execute mod/session code from `Data/Scripts/**/*.cs` as PB adapters.
- Edit Steam Workshop cache files in place from the manager.
- Apply worker commands targeting stale sequence ids, mismatched bridge/script
  ids, or non-visible blocks.
- Apply connected-grid inventory commands unless explicitly enabled in config.
- Apply text, machine, conveyor, assembler, gas, or reactor commands on
  connected-grid blocks unless explicitly enabled in config.
- Apply arbitrary terminal actions or generic terminal property writes. New Isy
  behavior must be represented as a named, reviewed command kind.

## Fail-Closed Rules

- Reject mismatched schema, bridge id, sequence, script id, or status.
- Reject mailbox direction mismatches; requests and results must carry the
  expected `message_kind`.
- Skip outbound PB work when `Runtime.LastRunTimeMs` approaches the configured
  runtime-ms limit.
- Enter cooldown instead of staging work when the hard runtime-ms limit is met
  or exceeded.
- Prefer minimal PB snapshots for live bridge transport; grid-wide summaries are
  opt-in because they cost more PB runtime.
- Treat missing text panels, missing scripts, invalid JSON, and timeouts as
  blockers rather than guessing.
- Treat invalid limiter config as blocking when `fail_closed=true`.
- Keep imported Workshop scripts as candidates until manually adapted and
  allowlisted in `worker/manifest.json`.
- Keep generated Workshop adapter scaffolds disabled by default.
- Reject worker requests when a bridge has an allowlist and the requested script
  is not on it.
- Reject Isy inventory sorting when the plugin-side inventory snapshot is
  missing or malformed.
- Report missing Isy grid snapshots with an explicit `grid_snapshot_missing`
  diagnostic before machine/LCD planning.
- Apply at most `max_apply_commands_per_tick` commands per PB run; default `1`.
- Drain queued worker commands steadily through `commandQueueDrainPerResult`,
  default `1`, instead of flooding the PB with every planned command at once.
- Resolve command targets by `EntityId`, re-check same-construct ownership
  scope, and re-find source inventory items at apply time.
- Skip LCD, functional-block, conveyor, assembler, gas-auto-refill, blueprint,
  and queue commands when the target block or required API surface is missing.
- Render inventory LCD output from IIM-style custom-data filters in the worker;
  set `writeInventoryLCDReports=false` to preserve manual surface text.
- Render autocrafting LCD text in the worker from simple panel custom-data
  target lines; PB-side application is still only a bounded text-surface write,
  not arbitrary autocrafting logic.
- Decode JSON string escapes and initialize Isy-style LCD font/alignment
  settings on PB-side `write_text_surface` only. The only extra LCD field is an
  optional text-panel public title; do not allow arbitrary style commands yet.
- Allow `write_block_custom_data` only for
  `reason=autocrafting_discovered_items`, with same-construct checks and a
  bounded text payload. Do not use it as a generic custom-data or terminal
  action channel.
- Skip commands that are not on the PB shim allowlist.
