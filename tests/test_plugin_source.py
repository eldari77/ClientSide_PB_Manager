from pathlib import Path


PLUGIN = Path("client_plugins/NOVALI.ClientSidePBBridge/LocalPlugin/ClientSidePBBridgePlugin.cs")


def test_plugin_enriches_requests_with_grid_snapshot_and_status_counters():
    source = PLUGIN.read_text(encoding="utf-8")

    assert '"grid_snapshot"' in source
    assert "BuildGridSnapshotJson" in source
    assert "novali.client_side_pb.grid_snapshot.v1" in source
    assert '"grid_entity_id"' in source
    assert "last_grid_snapshot_state" in source
    assert "last_grid_snapshot_blocks" in source
    assert "last_grid_snapshot_lcds" in source
    assert "last_grid_snapshot_machines" in source
    assert "last_grid_snapshot_skipped_blocks" in source
    assert "last_grid_snapshot_truncated_blocks" in source
    assert "last_grid_snapshot_skip_samples" in source
    assert "last_integrity_snapshot_state" in source
    assert "last_integrity_snapshot_blocks" in source
    assert "visible_grid_scan_state" in source
    assert "visible_grid_scan_blocks" in source
    assert "visible_grid_scan_machines" in source
    assert "visible_grid_scan_active_assemblers" in source
    assert "visible_grid_scan_active_refineries" in source
    assert "visible_grid_scan_production_summary" in source
    assert "BuildGridBlockFallbackJson" in source
    assert '"autocrafting"' in source


def test_plugin_refreshes_visible_grid_status_before_request_filter():
    source = PLUGIN.read_text(encoding="utf-8")

    refresh = source.index("RefreshVisibleGridStatus(entity);")
    request_filter = source.index('if (!string.Equals(messageKind, "request", StringComparison.OrdinalIgnoreCase))')
    assert refresh < request_filter
    assert 'ResetVisibleGridStatus("no_marked_mailbox");' in source
    assert "RefreshVisibleGridBlockStatus" in source


def test_plugin_grid_snapshot_contains_isy_block_fields():
    source = PLUGIN.read_text(encoding="utf-8")

    for field in [
        "same_construct",
        "enabled",
        "use_conveyor",
        "inventories",
        "text",
        "custom_data",
        "assembler_mode",
        "assembler_cooperative_mode",
        "production_queue_count",
        "production_queue",
        "gas_auto_refill",
        "gas_auto_refill_supported",
        "stockpile",
        "gas_filled_ratio",
        "is_lcd",
        "is_assembler",
        "is_refinery",
        "is_gas_generator",
        "is_reactor",
        "is_gas_tank",
        "is_connector",
        "is_cargo",
        "is_door",
        "is_light",
        "is_sound",
        "is_hangar_door",
        "door_open_ratio",
        "door_status",
        "color",
        "font",
        "font_size",
        "text_padding",
        "alignment",
        "content_type",
        "surface_size",
        "texture_size",
        "custom_name_with_faction",
        "has_local_player_access",
        "terminal_actions",
        "terminal_properties",
    ]:
        assert f'Quote("{field}")' in source


def test_plugin_grid_snapshot_contains_integrity_fields_from_slim_blocks():
    source = PLUGIN.read_text(encoding="utf-8")

    assert '"integrity_snapshot"' in source
    assert "BuildIntegritySnapshotJson" in source
    assert "novali.client_side_pb.integrity_snapshot.v1" in source
    for field in [
        "integrity",
        "max_integrity",
        "integrity_ratio",
        "functional",
    ]:
        assert f'Quote("{field}")' in source
    assert "BuildGridBlockJson(slimBlock, includeTerminalMetadata)" in source
    assert 'ReadDoubleLikeMember(slimBlock, "Integrity")' in source
    assert 'ReadDoubleLikeMember(slimBlock, "MaxIntegrity")' in source
    assert 'ReadBoolMember(slimBlock, "IsFunctional", true)' in source


def test_plugin_reads_text_surface_metadata_for_virtual_pb_fidelity():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "AppendTextSurfaceSnapshotFields(builder, block);" in source
    assert 'ReadSurfaceString(surface, "Font", "Debug")' in source
    assert 'ReadSurfaceDouble(surface, "FontSize", 0.6)' in source
    assert 'ReadSurfaceVectorJson(surface, "SurfaceSize", 512, 512)' in source
    assert 'ReadSurfaceVectorJson(surface, "TextureSize", 512, 512)' in source


def test_plugin_fallback_preserves_lcd_custom_data_and_text():
    source = PLUGIN.read_text(encoding="utf-8")

    assert 'var customData = ReadStringMember(block, "CustomData");' in source
    assert "Quote(Limit(customData, 600))" in source
    assert "Quote(Limit(text, 600))" in source


def test_plugin_reads_same_text_surface_that_pb_shim_writes():
    source = PLUGIN.read_text(encoding="utf-8")

    surface_read = source.index("TryReadTextSurfaceText(block, out surfaceText)")
    direct_read = source.index('FindInstanceMethod(block, "GetText", Type.EmptyTypes)')
    assert surface_read < direct_read
    assert 'FindInstanceMethod(block, "GetSurface", new[] { typeof(int) })' in source
    assert 'FindInstanceMethod(surface, "GetText", Type.EmptyTypes)' in source
    assert 'method.Name.EndsWith("." + name, StringComparison.Ordinal)' in source


def test_plugin_mailbox_panel_write_keeps_direct_write_with_surface_fallback():
    source = PLUGIN.read_text(encoding="utf-8")

    direct_write = source.index("TryWriteTextSurface(entity, text)")
    fallback_surface = source.index("var surface = ReadTextSurface(entity, 0);")
    assert direct_write < fallback_surface
    assert 'FindInstanceMethod(target, "WriteText", new[] { typeof(string), typeof(bool) })' in source
    assert "return surface != null && TryWriteTextSurface(surface, text);" in source


def test_plugin_snapshot_reads_queue_and_machine_setup_state():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "BuildProductionQueueJson" in source
    assert "ReadProductionQueueItems" in source
    assert "GetQueue" in source
    assert 'method.Name.EndsWith(".GetQueue", StringComparison.Ordinal)' in source
    assert 'ReadBoolMember(block, "CooperativeMode", false)' in source
    assert 'ReadGasAutoRefill(block)' in source


def test_plugin_snapshot_reads_terminal_metadata_for_read_only_harness():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "ShouldIncludeTerminalMetadata(body)" in source
    assert "BuildGridSnapshotJson(programmableBlock, includeTerminalMetadata)" in source
    assert "BuildGridBlockJson(slimBlock, includeTerminalMetadata)" in source
    assert 'ReadStringMember(block, "CustomNameWithFaction", ReadStringMember(block, "CustomName"))' in source
    assert 'ReadBoolMethod(block, "HasLocalPlayerAccess", true)' in source
    assert 'ReadBoolMethod(block, "HasNobodyPlayerAccessToBlock", true)' in source
    assert 'if (includeTerminalMetadata)' in source
    assert "BuildTerminalActionsJson(block)" in source
    assert "BuildTerminalPropertiesJson(block)" in source
    assert 'ReadTerminalList(block, "GetActions")' in source
    assert 'ReadTerminalList(block, "GetProperties")' in source
    assert "HasGasAutoRefillProperty(block)" in source
    assert 'ReadBoolMember(block, "Stockpile", false)' in source


def test_plugin_reports_missing_gas_auto_refill_property_separately_from_false():
    source = PLUGIN.read_text(encoding="utf-8")

    assert 'Quote("gas_auto_refill_supported")' in source
    assert 'HasBoolTerminalProperty(block, "AutoRefill")' in source
    assert 'HasBoolTerminalProperty(block, "AutoRefillBottles")' in source


def test_plugin_json_quote_escapes_control_characters():
    source = PLUGIN.read_text(encoding="utf-8")

    assert 'builder.Append("\\\\n");' in source
    assert 'builder.Append("\\\\r");' in source
    assert 'builder.Append("\\\\t");' in source
    assert 'char.IsControl(c)' in source
    assert 'ToString("x4", CultureInfo.InvariantCulture)' in source


def test_plugin_distinguishes_expected_result_lag_from_sequence_mismatch():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "ReturnResultIfPresent(entity, customData, bridgeId, sequence, body)" in source
    assert 'var lastAppliedSequence = ExtractNestedJsonInt(requestBody, "last_apply", "sequence");' in source
    assert '_lastResultState = "result_already_applied";' in source
    assert '_lastResultState = "waiting_for_current_result";' in source
    assert '_lastResultState = "result_future_sequence";' in source
    assert "ExtractNestedJsonInt" in source


def test_plugin_compacts_large_result_before_returning_to_pb_custom_data():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "MaxMailboxResultChars" in source
    assert "BuildMailboxResultJson(result)" in source
    assert 'Quote("mailbox_compacted") + ":true,"' in source
    assert 'Quote("full_result_path")' in source
    assert 'Quote("commands") + ":[{"' in source
    assert 'Quote("text") + ":" + Quote(Limit(' in source


def test_plugin_clears_orphaned_marked_block_before_request_parsing():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "HasOrphanedMarkedBlock(customData)" in source
    assert "RemoveOrphanedMarkedBlock(customData)" in source
    assert '_lastResultState = "orphaned_mailbox_cleared";' in source


def test_plugin_does_not_overwrite_active_request_file_while_worker_processes():
    source = PLUGIN.read_text(encoding="utf-8")

    assert "if (File.Exists(path))" in source
    assert '_lastResultState = "request_file_pending";' in source
    assert "File.WriteAllText(path, body, Utf8NoBom);" in source
