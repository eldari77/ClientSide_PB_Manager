from pathlib import Path


SHIM = Path("pb_shim/ClientSidePBBridgeShim.cs")


def test_pb_shim_publishes_apply_telemetry_in_request_state():
    source = SHIM.read_text(encoding="utf-8")

    assert 'ShimVersion = "2026-05-20-iim-action-parity-v13-customdata"' in source
    assert 'Quote("last_apply")' in source
    assert 'Quote("applied")' in source
    assert 'Quote("skipped")' in source
    assert 'Quote("last_skip")' in source
    assert "RecordApplyTelemetry(resultSequence, resultStatus, \"processed\"" in source


def test_pb_shim_uses_item_transfer_overload_with_permission_checks():
    source = SHIM.read_text(encoding="utf-8")

    assert "CanTransferItemTo(destinationInventory, item.Type)" in source
    assert "transfer_not_allowed" in source
    assert "CanItemsBeAdded((VRage.MyFixedPoint)moveAmount, item.Type)" in source
    assert "TransferItemTo(destinationInventory, item, transferAmount)" in source
    assert "TransferItemTo(destinationInventory, index, null, true, transferAmount)" in source


def test_pb_shim_allows_isy_foundation_commands_with_skip_reasons():
    source = SHIM.read_text(encoding="utf-8")

    for command_kind in [
        "write_text_surface",
        "write_block_custom_data",
        "set_block_enabled",
        "set_use_conveyor",
        "set_door_open",
        "set_light_color",
        "set_assembler_mode",
        "set_assembler_cooperative_mode",
        "set_gas_auto_refill",
        "move_assembler_queue_item",
        "remove_assembler_queue_item",
        "enqueue_assembler_blueprint",
        "clear_assembler_queue",
    ]:
        assert f'kind == "{command_kind}"' in source

    for skip_reason in [
        "text_surface_missing",
        "custom_data_invalid_fields",
        "custom_data_connected_grid_blocked",
        "block_not_functional",
        "conveyor_property_missing",
        "door_missing",
        "door_open_failed",
        "light_missing",
        "light_color_failed",
        "assembler_missing",
        "assembler_cooperative_failed",
        "gas_auto_refill_property_missing",
        "queue_move_failed",
        "queue_remove_failed",
        "blueprint_invalid",
        "queue_failed",
    ]:
        assert skip_reason in source


def test_pb_shim_sets_lcd_surfaces_to_text_mode_before_writing():
    source = SHIM.read_text(encoding="utf-8")

    assert "PrepareIsyTextSurface(panel);" in source
    assert "PrepareIsyTextSurface(surface);" in source
    assert 'surface.Font = "Debug";' in source
    assert "surface.FontSize = 0.6f;" in source
    assert "surface.TextPadding = 2f;" in source
    assert "surface.Alignment = TextAlignment.LEFT;" in source
    assert "surface.ContentType = ContentType.TEXT_AND_IMAGE;" in source
    assert 'var title = ExtractString(command, "title");' in source
    assert "panel.WritePublicTitle(title);" in source


def test_pb_shim_decodes_json_string_escapes_before_lcd_write():
    source = SHIM.read_text(encoding="utf-8")

    assert "if (c == 'n') value += \"\\n\";" in source
    assert "else if (c == 'r') value += \"\\r\";" in source
    assert "Convert.ToInt32(text.Substring(i + 1, 4), 16)" in source


def test_pb_shim_runtime_limit_default_is_client_side_profile():
    source = SHIM.read_text(encoding="utf-8")

    assert "double runtimeMsLimit = 0.3;" in source
    assert "runtime_ms_limit=0.3" in source
    assert 'Replace("runtime_ms_limit=0.03", "runtime_ms_limit=0.3")' in source


def test_pb_shim_uses_dynamic_apply_budget_from_runtime_profile():
    source = SHIM.read_text(encoding="utf-8")

    assert "bool dynamicApplyCommands = true;" in source
    assert "int dynamicMaxApplyCommandsPerTick = 4;" in source
    assert "dynamic_apply_commands=true" in source
    assert 'Quote("dynamic_apply_budget")' in source
    assert 'Quote("runtime_ms_limit")' in source
    assert "var budget = ApplyCommandBudget(resultBudget);" in source
    assert 'limiterState == "soft_limited"' in source
    assert "last >= high" in source
