# Multi-Adapter Bridge Orchestrator Backlog

## Goal

Allow one in-game PB shim to request a single `bridge_orchestrator` worker
script while Docker runs multiple allowed child adapters for the same bridge.
The orchestrator owns global PB usage, merges child adapter command plans, and
drains one shared command queue into the server at a controlled rate.

Example target:

- Isy's Inventory Manager adapter plans inventory, LCD, assembler, refinery,
  gas, and reactor work.
- Whip's auto door adapter plans door open/close work.
- The PB shim still applies only explicit allowlisted command kinds through one
  sequence, one limiter, and one mailbox.

## Proposed Shape

1. PB config uses `script_id=bridge_orchestrator`.
2. `data/bridge_scripts.json` stores child adapter order and per-adapter budget
   for each bridge.
3. Worker loads the orchestrator, which dispatches the same enriched request to
   each enabled child adapter.
4. Child adapter outputs are normalized into command envelopes with:
   - `source_script_id`
   - `priority`
   - `coalesce_key`
   - `expires_after_sequences`
   - `command`
5. Docker merges envelopes into `data/command_queues/<bridge_id>.json`.
6. The queue drains by global bridge budget and per-source fairness rules.
7. PB shim receives one result for the orchestrator script id and applies the
   same explicit allowlisted command kinds it already knows.

## Design Rules

- No arbitrary terminal action execution.
- Child adapters cannot write directly to PB result files.
- Command primitives stay reviewed and narrow, for example `set_door_open`
  instead of a generic terminal property write.
- Safety-critical or freshness-sensitive commands can have higher priority and
  shorter expiry than slow maintenance commands like LCD refreshes.
- Conflicting writes to the same block/property must resolve deterministically.
- Queue metadata must preserve enough source information to debug which adapter
  planned each command.

## Whip Auto Door Notes

Whip's auto door behavior should be converted as a child adapter only after
snapshot requirements are explicit. Likely needed state:

- Door blocks and current open/closed state.
- Door enabled state.
- Sensor, airlock, room, or naming/custom-data relationships used by the
  original script.
- Optional timer/button/manual override signals if the script depends on them.

Likely new command primitive:

```json
{
  "kind": "set_door_open",
  "block_entity_id": 123,
  "open": true
}
```

The PB shim should implement that primitive against the door API only, with
same-construct guarding and skip reasons such as `door_missing`,
`door_connected_grid_blocked`, and `door_open_failed`.

## Acceptance Criteria

- One PB shim can request `bridge_orchestrator` and receive valid results.
- At least two child adapters can contribute commands to one bridge queue.
- Queue entries record `source_script_id`.
- Per-source budgets prevent one child adapter from starving another.
- Freshness expiry prevents old door commands from applying after the observed
  state has changed.
- Existing Isy single-adapter behavior remains available for direct testing.
- Docs and safety boundary list the orchestrator path and any new command
  primitives.
