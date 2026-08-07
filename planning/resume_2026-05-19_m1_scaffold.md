# Resume: M1 Scaffold

Current state:

- Project scaffold created under `.venv\ClientSide_PB_Script`.
- Workshop scanner reads Steam libraries and `appworkshop_244850.acf`, detects
  root-level `Script.cs`/`script.cs`, and writes `data/workshop_catalog.json`.
- Workshop scanner now resolves human-readable Steam Workshop titles when
  network access is available.
- Workshop Scripts UI has text search, Kind filtering, and `Prepare Adapter`.
- `Prepare Adapter` creates disabled worker scaffolds and analysis reports for
  selected PB scripts.
- Docker worker processes `data/bridge_requests/*.json` through
  `worker/manifest.json` and writes `data/bridge_results/*.json`.
- PB shim stages compact requests and validates result bridge id, script id,
  sequence, and `message_kind=result` before applying.
- Pulsar plugin mirrors marked PB mailbox request payloads to local shared files
  and now exposes live discovery/staging counters in `data/plugin_status.json`.
- Live status showed top-level entities without direct PB candidates, so plugin
  discovery was updated to scan cube-grid fat blocks for programmable blocks and
  text panels.
- First live request reached `data/bridge_requests` but was rejected because
  the plugin wrote UTF-8 with a BOM. The worker now reads request files with
  `utf-8-sig`, and new plugin builds write UTF-8 without a BOM.
- Matching worker results initially stayed local because pretty JSON did not
  match the game-side string extractors. Worker results are now compact JSON.
- WPF manager scans Workshop scripts, imports candidates, shows bridge/worker
  state, and controls Docker Compose.
- Runtime limiter profile defaults are stored in `data/bridge_limits.json`.
- Worker script enablement is editable in the manager, and per-bridge script
  assignments are stored in `data/bridge_scripts.json`.
- Worker Scripts can now load/save local adapter files and clone them into new
  manifest entries for separate configurations.
- Worker Scripts now has a Config sub-tab. Isy's imported script produced 92
  extracted operator settings in `data/worker_configs`.
- PB shim `reset` now clears marked mailbox data, and the shim removes result
  envelopes after reading them so changed `script_id` values can stage cleanly.
- PB shim supports `snapshot_mode=minimal` to reduce runtime cost and
  `snapshot_mode=grid_summary` for the older block/inventory count snapshot.
- PB shim checks `Runtime.LastRunTimeMs` before grid scanning and emits runtime
  telemetry on outbound requests.
- Isy's Inventory Manager adapter now has a first behavior module for inventory
  sorting. The plugin enriches requests with bounded inventory snapshots, the
  worker plans `transfer_item` and conservative `rename_block` commands from
  extracted Isy config, and the PB shim applies allowlisted commands within a
  default one-command-per-tick budget.
- PB result-consuming ticks now return immediately after applying and clearing
  a worker result so command application is not combined with the next request
  stage in the same PB run.
- PB `reset` now seeds the next sequence from UTC time. This prevents stale
  result files with sequence `1` from being returned after a PB recompile or
  reset.
- Worker Scripts Config now exposes Inventory Sorting controls for apply
  enabled, dry run, connected grids, apply/tick, and plan/tick.

Next useful live step:

1. Run `python -m pytest -q`.
2. Run `.\tools\worker_smoke.ps1`.
3. Run `.\tools\build_local_plugin.ps1`.
4. Close Space Engineers/Pulsar, then run `.\tools\handoff_plugin.ps1` so the
   inventory snapshot plugin build replaces the locked DLL.
5. Validate a singleplayer PB/text-panel bridge and confirm
   `last_inventory_snapshot_state=ok` in `data\plugin_status.json`.
6. Confirm the Limits tab profile matches the target server threshold before
   testing on a multiplayer server with PB offlining rules.
7. Start Isy inventory sorting in dry-run mode, review the proposed transfer
   summary, then disable dry-run for one-command-per-tick live application.
