from pathlib import Path


PLUGIN = Path("client_plugins/NOVALI.ClientSidePBBridge/LocalPlugin/ClientSidePBBridgePlugin.cs")


def test_plugin_enriches_requests_with_grid_snapshot_and_status_counters():
    source = PLUGIN.read_text(encoding="utf-8")

    assert '"grid_snapshot"' in source
    assert "BuildGridSnapshotJson" in source
    assert "novali.client_side_pb.grid_snapshot.v1" in source
    assert "last_grid_snapshot_state" in source
    assert "last_grid_snapshot_blocks" in source
    assert "last_grid_snapshot_lcds" in source
    assert "last_grid_snapshot_machines" in source
    assert "last_grid_snapshot_skipped_blocks" in source
    assert "last_grid_snapshot_truncated_blocks" in source
    assert "last_grid_snapshot_skip_samples" in source
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
    ]:
        assert f'Quote("{field}")' in source


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
    assert 'ReadBoolMember(block, "Stockpile", false)' in source


def test_plugin_json_quote_escapes_control_characters():
    source = PLUGIN.read_text(encoding="utf-8")

    assert 'builder.Append("\\\\n");' in source
    assert 'builder.Append("\\\\r");' in source
    assert 'builder.Append("\\\\t");' in source
    assert 'char.IsControl(c)' in source
    assert 'ToString("x4", CultureInfo.InvariantCulture)' in source
