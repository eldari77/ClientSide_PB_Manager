from pathlib import Path


SHIM = Path("pb_shim/ClientSidePBBridgeShim.cs")


def test_pb_shim_publishes_apply_telemetry_in_request_state():
    source = SHIM.read_text(encoding="utf-8")

    assert 'ShimVersion = "baseline-template-v1"' in source
    assert 'Quote("last_apply")' in source
    assert 'Quote("last_action_text")' in source
    assert 'Quote("applied")' in source
    assert 'Quote("skipped")' in source
    assert 'Quote("last_skip")' in source
    assert "RecordApplyTelemetry(resultSequence, resultStatus, \"processed\"" in source


def test_pb_shim_records_script_visible_last_action_text_for_non_lcd_commands():
    source = SHIM.read_text(encoding="utf-8")

    assert 'string lastApplyActionText = "";' in source
    assert 'string lastApplyActionTime = "";' in source
    assert 'string lastApplyActionAtUtc = "";' in source
    assert 'SaveField("last_apply_action_text", lastApplyActionText)' in source
    assert 'SaveField("last_apply_action_time", lastApplyActionTime)' in source
    assert 'SaveField("last_apply_action_at_utc", lastApplyActionAtUtc)' in source
    assert 'lastApplyActionText = value;' in source
    assert 'lastApplyActionTime = value;' in source
    assert 'lastApplyActionAtUtc = value;' in source
    assert 'Quote("last_action_time") + ":" + Quote(lastApplyActionTime)' in source
    assert 'Quote("last_action_at_utc") + ":" + Quote(lastApplyActionAtUtc)' in source
    assert 'lastApplyActionTime = DateTime.Now.ToString("HH:mm:ss");' in source
    assert 'lastApplyActionAtUtc = DateTime.UtcNow.ToString("o");' in source
    assert "DescribeTransferAction(command, sourceBlock, destinationBlock, moveAmount, subtypeId)" in source
    assert 'RecordActionText(DescribeCommandAction(kind, command));' in source
    assert 'if (kind == "write_text_surface")' in source


def test_pb_shim_emits_verification_nonce_in_request_state():
    source = SHIM.read_text(encoding="utf-8")

    assert "string verificationNonce" in source
    assert "verification_nonce=" in source
    assert 'if (key == "verification_nonce") verificationNonce = value;' in source
    assert 'Quote("verification_nonce") + ":" + Quote(verificationNonce)' in source
    assert 'Quote("requested_at_utc") + ":" + Quote(DateTime.UtcNow.ToString("o"))' in source


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

    assert "PrepareTextSurface(panel, command);" in source
    assert "PrepareTextSurface(surface, command);" in source
    assert 'ExtractString(command, "font")' in source
    assert 'ExtractDouble(command, "font_size")' in source
    assert 'ExtractDouble(command, "text_padding")' in source
    assert 'ExtractString(command, "alignment")' in source
    assert 'ExtractString(command, "content_type")' in source
    assert 'var title = ExtractString(command, "title");' in source
    assert "panel.WritePublicTitle(title);" in source


def test_pb_shim_decodes_json_string_escapes_before_lcd_write():
    source = SHIM.read_text(encoding="utf-8")

    assert "if (c == 'n') value += \"\\n\";" in source
    assert "else if (c == 'r') value += \"\\r\";" in source
    assert "Convert.ToInt32(text.Substring(i + 1, 4), 16)" in source


def test_pb_shim_runtime_limit_default_is_client_side_profile():
    source = SHIM.read_text(encoding="utf-8")

    assert "double runtimeMsLimit = 0.25;" in source
    assert "runtime_ms_limit=0.25" in source
    assert 'ReplaceLegacyConfigLine("runtime_ms_limit", "0.03", "0.25")' in source
    assert 'ReplaceLegacyConfigLine("runtime_ms_limit", "0.3", "0.25")' in source


def test_pb_shim_migrates_legacy_command_caps_to_latency_limited_defaults():
    source = SHIM.read_text(encoding="utf-8")

    assert "UpgradeLegacyConfigDefaults();" in source
    assert 'ReplaceLegacyConfigLine("max_commands_per_minute", "30", "60")' in source
    assert 'ReplaceLegacyConfigLine("max_apply_commands_per_tick", "1", "8")' in source
    assert 'ReplaceLegacyConfigLine("max_apply_commands_per_tick", "4", "8")' in source
    assert 'ReplaceLegacyConfigLine("dynamic_max_apply_commands_per_tick", "4", "8")' in source
    assert 'ReplaceLegacyConfigLine("cooldown_seconds", "10", "3")' in source


def test_pb_shim_uses_dynamic_apply_budget_from_runtime_profile():
    source = SHIM.read_text(encoding="utf-8")

    assert "bool dynamicApplyCommands = true;" in source
    assert "int dynamicMaxApplyCommandsPerTick = 8;" in source
    assert "bool includeTerminalMetadata = false;" in source
    assert "dynamic_apply_commands=true" in source
    assert "include_terminal_metadata=false" in source
    assert 'Quote("dynamic_apply_budget")' in source
    assert 'Quote("runtime_ms_limit")' in source
    assert 'Quote("include_terminal_metadata")' in source
    assert "var budget = ApplyCommandBudget(resultBudget);" in source
    assert 'limiterState == "soft_limited"' in source
    assert "last >= high" in source


def test_pb_shim_renders_operator_status_panel_with_queue_and_child_statuses():
    source = SHIM.read_text(encoding="utf-8")

    assert "RenderOperatorStatus(" in source
    assert "EchoOperatorStatus(" in source
    assert "iim-action-parity" not in source
    assert "request_pending=" not in source
    assert '"State "' in source
    assert '"Last seq "' in source
    assert '"Queue total="' in source
    assert '"Running:"' in source
    assert '" q="' in source
    assert "lastResultCompletedAt" in source
    assert "lastChildStatusLines" in source
    assert "instance_label." in source
    assert '"Pending request: seq "' not in source
