# Bridge Contract

The bridge uses one JSON request and one JSON result per bridge id.

## Request

```json
{
  "schema": "novali.client_side_pb_bridge.v1",
  "message_kind": "request",
  "bridge_id": "pb-bridge-001",
  "sequence": 1,
  "script_id": "sample_status_adapter",
  "request_kind": "status_summary",
  "runtime_telemetry": {
    "last_runtime_ms": 0.01,
    "max_runtime_ms": 0.02,
    "current_instruction_count": 10,
    "max_instruction_count": 50000,
    "limiter_state": "ok"
  },
  "inventory_snapshot": {
    "schema": "novali.client_side_pb.inventory_snapshot.v1",
    "source": "plugin",
    "blocks": []
  },
  "grid_snapshot": {
    "schema": "novali.client_side_pb.grid_snapshot.v1",
    "source": "plugin",
    "grid_entity_id": 123456,
    "blocks": []
  },
  "state": {}
}
```

`inventory_snapshot` is added by the local plugin, not by the PB shim. It is
required for inventory-sorting adapters. If the snapshot is missing, the worker
must reject the request instead of asking the PB to perform a server-side grid
inventory scan.

`grid_snapshot` is also added by the local plugin. It is a separate enrichment
so existing inventory sorting consumers can keep using `inventory_snapshot`
unchanged. It includes `grid_entity_id` for the PB's owning cube grid so
ship-level modules can validate bridge-to-grid identity. Grid block records are
bounded and include visible same-grid LCD/text panels, assemblers, refineries,
O2/H2 generators, gas tanks, reactors, cargo, connectors, and PB-adjacent
terminal blocks. Each record should include:

- `entity_id`, `name`, `type`, `subtype`, `same_construct`
- `enabled`, `use_conveyor`, `inventory_count`, `surface_count`
- `inventories` with lightweight item summaries where available
- LCD fields such as `text` and `custom_data`
- machine fields such as `assembler_mode`, `assembler_cooperative_mode`,
  `production_queue_count`, `production_queue`, `gas_auto_refill`, `stockpile`,
  and `gas_filled_ratio`
- boolean helpers such as `is_lcd`, `is_assembler`, `is_refinery`,
  `is_gas_generator`, `is_reactor`, `is_gas_tank`, `is_connector`, and
  `is_cargo`

Plugin status exposes `last_grid_snapshot_state`,
`last_grid_snapshot_blocks`, `last_grid_snapshot_lcds`,
`last_grid_snapshot_machines`, `last_grid_snapshot_skipped_blocks`, and
`last_grid_snapshot_truncated_blocks`. Newer plugin builds also expose
`last_grid_snapshot_skip_samples` so reflected block failures can be diagnosed
without guessing which grid blocks were dropped.

The PB shim includes `state.shim_version` in live requests. Operators can use
that field, together with the reset echo, to verify the pasted in-game shim is
the same build as `pb_shim\ClientSidePBBridgeShim.cs`.

Requests also include `state.last_apply`, which records the previous PB-side
result application attempt. This is the durable place to inspect command
application from files:

```json
{
  "state": {
    "last_apply": {
      "sequence": 7,
      "result_status": "ok",
      "status": "processed",
      "command_count": 1,
      "applied": 0,
      "skipped": 1,
      "echo": 0,
      "last_skip": "transfer_failed"
    }
  }
}
```

## Result

```json
{
  "schema": "novali.client_side_pb_bridge.v1",
  "message_kind": "result",
  "bridge_id": "pb-bridge-001",
  "sequence": 1,
  "script_id": "sample_status_adapter",
  "status": "ok",
  "result": {
    "apply_mode": "immediate",
    "max_apply_commands": 1,
    "remaining_commands": 0,
    "commands": [
      {
        "kind": "echo",
        "text": "worker status"
      }
    ]
  },
  "error_bucket": "none"
}
```

For `apply_mode=immediate`, the Docker worker may store planned non-echo
commands in `data/command_queues/<bridge_id>.json` and emit only a small drain
batch in each result. Echo commands pass through immediately. Queue metadata is
reported in the result:

```json
{
  "result": {
    "queued_commands": 12,
    "drained_commands": 1,
    "remaining_commands": 11,
    "command_queue": {
      "state": "active",
      "queued": 12,
      "drained": 1,
      "remaining": 11
    }
  }
}
```

Queue acknowledgment is driven by the next request's `state.last_apply`.
Commands that already match the latest plugin snapshot should stop being
re-planned by the adapter, which lets the queued stream drain instead of
repeating already-applied setup commands.

Writers must reject stale sequence numbers and mismatched bridge ids. PB shims,
plugins, and workers must also honor `message_kind` so a PB does not treat its
own outbound request as a worker result.

`limiter_state` values are `ok`, `soft_limited`, `cooldown`, `disabled`, and
`config_invalid`. Requests normally reach the worker only while the PB-side
limiter is `ok` or `disabled`.

## Command Schema

The PB shim currently allowlists these command kinds:

```json
{
  "kind": "transfer_item",
  "command_id": "pb-bridge-001:7:1",
  "source_entity_id": 123,
  "source_inventory_index": 0,
  "destination_entity_id": 456,
  "destination_inventory_index": 0,
  "item_type_id": "MyObjectBuilder_Ore",
  "item_subtype_id": "Iron",
  "amount": 42.0
}
```

```json
{
  "kind": "rename_block",
  "command_id": "assign:456:ores",
  "block_entity_id": 456,
  "new_name": "Large Cargo Ores",
  "reason": "auto_container_assignment"
}
```

```json
{
  "kind": "echo",
  "text": "operator-visible status"
}
```

```json
{
  "kind": "write_text_surface",
  "command_id": "pb-bridge-001:7:lcd:1",
  "block_entity_id": 789,
  "surface_index": 0,
  "title": "Craft item manually once to show up here",
  "text": "status text",
  "append": false
}
```

The PB shim decodes JSON string escapes before writing, so command text with
`\n` becomes real LCD line breaks. It also initializes the target LCD/text
surface with Isy-style defaults before writing: `Font="Debug"`,
`FontSize=0.6`, `TextPadding=2`, left alignment, and `TEXT_AND_IMAGE`. The
optional `title` field is applied to text panels with `WritePublicTitle`; it is
used for the IIM-style autocrafting panel.

The Isy foundation worker performs the heavier LCD rendering work. Main LCD
output follows IIM's status-panel shape. Inventory LCD output is generated from
the target panel's custom data using IIM-style filters, `Echo` lines, and the
foundation-supported modifiers `noHeading`, `noBar`, `hideEmpty`, `hideType`,
and `singleLine`. Empty inventory LCD custom data returns the IIM setup/help
text. The `Autocrafting` LCD is rendered from the matching panel custom data,
including simple wanted-stock lines such as `SteelPlate=1000 A`. When component
items are observed but no matching custom-data entries exist yet, the worker can
prepopulate the autocrafting panel's custom data with zero-wanted entries for
those discovered items. It falls back to IIM-style empty/error text when no
goals, observed components, or usable assemblers are present.
Set `writeInventoryLCDReports=false` to preserve manual inventory LCD surface
text.

```json
{
  "kind": "write_block_custom_data",
  "command_id": "pb-bridge-001:7:autocrafting_custom_data:1",
  "block_entity_id": 789,
  "text": "@0 Autocrafting\nSteelPlate=0\n",
  "reason": "autocrafting_discovered_items",
  "append": false
}
```

`write_block_custom_data` is intentionally narrow. The PB shim accepts it only
for `reason=autocrafting_discovered_items`, applies same-construct checks, and
caps the text payload size. It is not a generic terminal-action escape hatch.

```json
{
  "kind": "set_block_enabled",
  "command_id": "pb-bridge-001:7:reactor:1",
  "block_entity_id": 789,
  "enabled": true
}
```

### SOS Programmable-Block Recovery Envelope

Existing non-SOS `set_block_enabled` commands retain their current behavior.
When `sos_action_family` is present, however, the shim treats the command as a
future SOS recovery request and fail-closes unless all receipt fields are
present and valid:

```json
{
  "kind": "set_block_enabled",
  "block_entity_id": 789,
  "enabled": true,
  "sos_action_id": "sos-ap-example",
  "sos_action_family": "programmable_block_recovery",
  "sos_approval_nonce": "operator-entered-once",
  "sos_target_grid_entity_id": 123456,
  "sos_expires_after_sequence": 42
}
```

This envelope never introduces a new command kind or a generic execution API.
The shim permits it only when its own CustomData enables SOS automation and the
operator-entered action id, nonce, and expiry exactly match. The target must be
an `IMyProgrammableBlock` on the shim PB's exact cube grid, `enabled` must be
`true`, and the receipt pair must not have been consumed. The shim records the
last outcome in request state and persists successful receipt consumption to
reject replay.

```json
{
  "kind": "set_use_conveyor",
  "command_id": "pb-bridge-001:7:refinery:1",
  "block_entity_id": 789,
  "enabled": true
}
```

```json
{
  "kind": "set_assembler_mode",
  "command_id": "pb-bridge-001:7:assembler:1",
  "block_entity_id": 789,
  "mode": "assembly"
}
```

```json
{
  "kind": "set_assembler_cooperative_mode",
  "command_id": "pb-bridge-001:7:assembler:2",
  "block_entity_id": 789,
  "enabled": true
}
```

```json
{
  "kind": "set_gas_auto_refill",
  "command_id": "pb-bridge-001:7:gas:1",
  "block_entity_id": 789,
  "enabled": true
}
```

```json
{
  "kind": "enqueue_assembler_blueprint",
  "command_id": "pb-bridge-001:7:assembler:2",
  "block_entity_id": 789,
  "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
  "amount": 10
}
```

```json
{
  "kind": "move_assembler_queue_item",
  "command_id": "pb-bridge-001:7:assembler:3",
  "block_entity_id": 789,
  "queue_item_id": 12,
  "target_index": 0
}
```

```json
{
  "kind": "remove_assembler_queue_item",
  "command_id": "pb-bridge-001:7:assembler:4",
  "block_entity_id": 789,
  "queue_index": 0,
  "amount": 5
}
```

```json
{
  "kind": "clear_assembler_queue",
  "command_id": "pb-bridge-001:7:assembler:3",
  "block_entity_id": 789
}
```

The PB shim applies at most `max_apply_commands_per_tick` commands per run,
default `1`, and also respects worker result `max_apply_commands`. It resolves
blocks by `EntityId`, defaults to same-construct targets only, and re-finds the
requested item type/subtype in the source inventory at apply time. It checks
game inventory transfer permission before applying and reports skip reasons
such as `transfer_not_allowed` or `transfer_destination_full`.
The v12 Isy foundation handlers also report skip reasons such as
`text_surface_missing`, `block_not_functional`, `conveyor_property_missing`,
`custom_data_invalid_fields`, `custom_data_block_missing`,
`custom_data_connected_grid_blocked`, `assembler_missing`,
`assembler_cooperative_failed`,
`gas_auto_refill_property_missing`, `queue_move_failed`,
`queue_remove_failed`, `blueprint_invalid`, and `queue_failed`.
After applying and clearing a current result, the PB may continue to the normal
limiter/request path and stage the next request in the same run.

If a command is skipped, the PB echo may include `last_skip` with the latest
skip reason. The next request's `state.last_apply` is the durable source for
that same PB-side application status.

The PB must not replace a pending `message_kind=request` envelope with a newer
sequence while waiting for a result. Automatic ticks should echo
`request_pending=<sequence>` and leave the mailbox intact until the plugin
returns a matching `message_kind=result`.

When `mailbox_mode=both`, PB `CustomData` is the primary mailbox because it is
the channel polled by the local plugin. The text panel is a mirror/fallback and
must not take precedence over a fresh PB `CustomData` envelope.

## SOS Ship Registry

SOS ships are configured in `data/sos_ships.json` with schema
`novali.client_side_pb.sos_ships.v1`. The registry maps one active `bridge_id`
to one ship instance, optional `expected_grid_entity_id`, current mode, mounted
service script instances, and status surfaces.

The worker expands SOS services into the existing bridge-orchestrator contract.
Registry validation rejects duplicate active bridge ids and duplicate active
expected grid ids. When `expected_grid_entity_id` is non-zero, the request's
`grid_snapshot.grid_entity_id` must match before control-oriented services
should apply commands.
