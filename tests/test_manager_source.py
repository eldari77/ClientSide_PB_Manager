import json
from pathlib import Path


MANAGER = Path("manager/MainWindow.xaml.cs")


def test_manager_mentions_orchestrator_and_virtual_pb_status():
    source = MANAGER.read_text(encoding="utf-8")

    assert "bridge_orchestrator" in source
    assert "child_worker_scripts" in source
    assert "virtual_pb_compatibility" in source


def test_manager_has_sos_mounting_surface_and_persistence_hooks():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    for token in [
        'TabItem Header="SOS"',
        "SosShipGrid",
        "SosBridgeIdBox",
        "SosShipIdBox",
        "SosModeBox",
        "Create SOS Ship",
        "Save SOS Ship",
        "Build SOS Services",
    ]:
        assert token in xaml

    for token in [
        "SosShipsPath",
        "novali.client_side_pb.sos_ships.v1",
        "LoadSosShips",
        "SaveSosShip_Click",
        "BuildSosServices_Click",
        "sos_status",
        "expected_grid_entity_id",
    ]:
        assert token in source


def test_manager_guided_setup_runs_discovery_and_local_repair_automation():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    for token in [
        "Guided Setup",
        "Run Guided Setup",
        "Run Discovery",
        "GuidedSetupSummaryText",
        "GuidedSetupActionsText",
        "GuidedSetupOutput",
    ]:
        assert token in xaml

    for token in [
        "RunGuidedSetup_Click",
        "RunActiveDiscovery_Click",
        "RunActiveDiscovery",
        "discovery_report.json",
        "discovery.active_discovery --root . --output data\\\\discovery_report.json --run-api-probe",
        "docker\", \"compose up --build -d client-side-pb-worker",
        "tools\\\\build_local_plugin.ps1",
        "tools\\\\handoff_plugin.ps1",
        "BuildMultiScriptBridge_Click",
        "ShowBridgePbConfigPrompt",
        "LoadDiscoverySummary",
        "harness_update_plan",
        "Harness next:",
        "read_only_stub_queue",
        "mapping_review_queue",
    ]:
        assert token in source


def test_manager_translates_compatibility_status_to_operator_language():
    source = MANAGER.read_text(encoding="utf-8")

    for token in [
        "DescribeCompatibilityForOperator",
        "virtual_pb_ready",
        "Virtual PB ready",
        "profile_adapter_ready",
        "Known profile ready",
        "virtual_pb_blocked",
        "Blocked command mapping",
        "adapter_scaffold_created",
        "Manual adapter required",
        "missing_snapshot_fields",
    ]:
        assert token in source


def test_manager_has_virtual_pb_custom_data_editor_in_worker_config():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    for token in [
        'TabItem Header="Custom Data"',
        "Virtual PB CustomData",
        "VirtualPbCustomDataBox",
        "Load From Config",
        "Paste From Clipboard",
        "Save CustomData",
        "Clear CustomData",
        "VirtualPbCustomDataLoad_Click",
        "VirtualPbCustomDataPaste_Click",
        "SaveVirtualPbCustomData_Click",
        "VirtualPbCustomDataClear_Click",
    ]:
        assert token in xaml

    config_tab = xaml[xaml.index('<TabItem Header="Config"'):xaml.index('<TabItem Header="Custom Data"')]
    assert "VirtualPbCustomDataBox" not in config_tab

    for token in [
        "virtualPbCustomData",
        "SyncVirtualPbCustomDataUiFromEntries",
        "SyncVirtualPbCustomDataEntryFromUi",
        "Clipboard.GetText",
        "Virtual PB CustomData saved",
        "Isy-style itemID;blueprintID",
    ]:
        assert token in source


def test_manager_has_worker_ui_launcher():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    assert "Open Worker UI" in xaml
    assert "OpenWorkerUi_Click" in xaml
    assert "http://localhost:8788" in source
    assert "tools\\open_worker_ui.ps1" in source


def test_prepare_adapter_guides_virtual_pb_workflow():
    source = MANAGER.read_text(encoding="utf-8")

    assert "virtual_pb_ready" in source
    assert "Virtual PB adapter ready" in source
    assert "profile_adapter_ready" in source
    assert "Profile adapter ready" in source
    assert "SelectPreparedWorkerScript" in source


def test_manager_can_remove_prepared_worker_scripts_and_cleanup_registries():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    assert "Remove Prepared Script" in xaml
    assert "RemovePreparedWorkerScript_Click" in xaml
    assert "CleanupPreparedScriptArtifacts" in source
    assert "RemoveScriptFromCompatibilitySummary" in source
    assert "RemoveScriptInstancesForBaseScript" in source
    assert "RemoveScriptFromBridgeAssignments" in source
    assert "RemovePreparedScriptStateFiles" in source
    assert "RemovePreparedScriptQueueState" in source
    assert "autocrafting_blueprints" in source
    assert "command_queues" in source
    assert "DeleteIfExists(WorkerConfigPath(script.ScriptId))" in source


def test_worker_ui_powershell_launcher_exists():
    script = Path("tools/open_worker_ui.ps1")
    source = script.read_text(encoding="utf-8")

    assert "docker compose up --build -d client-side-pb-worker" in source
    assert "http://localhost:8788" in source
    assert "[switch]$NoOpen" in source
    assert "register_manager_protocol.ps1" in source


def test_manager_protocol_launcher_scripts_exist():
    register = Path("tools/register_manager_protocol.ps1").read_text(encoding="utf-8")
    launch = Path("tools/launch_manager.ps1").read_text(encoding="utf-8")

    assert "novali-client-side-pb-manager" in register
    assert "URL Protocol" in register
    assert "tools\\launch_manager.ps1" in register
    assert '-ProjectRoot `"$ProjectRoot`" -ProtocolUrl `"%1`"' in register
    assert "NOVALI.ClientSidePBManager.csproj" in launch


def test_manager_protocol_registration_builds_before_launcher_uses_existing_exe():
    register = Path("tools/register_manager_protocol.ps1").read_text(encoding="utf-8")
    launch = Path("tools/launch_manager.ps1").read_text(encoding="utf-8")

    assert "dotnet build" in register
    assert "Manager build failed" in register
    assert "manager_current_exe.txt" in register
    assert "manager_builds" in register
    assert "-p:OutDir=" in register
    assert "dotnet build" not in launch
    assert "manager_current_exe.txt" in launch
    assert "Start-Process -FilePath $builtExe -WorkingDirectory $ProjectRoot -PassThru" in launch


def test_manager_protocol_launcher_logs_and_foregrounds_app():
    register = Path("tools/register_manager_protocol.ps1").read_text(encoding="utf-8")
    launch = Path("tools/launch_manager.ps1").read_text(encoding="utf-8")

    assert "-WindowStyle Hidden" in register
    assert "manager_launch.log" in launch
    assert "BringManagerToFront" in launch
    assert "Start-Process -FilePath $builtExe -WorkingDirectory $ProjectRoot -PassThru" in launch


def test_manager_bridges_tab_supports_first_class_bridge_workflow():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    for token in [
        "New Bridge",
        "Copy PB Shim Script",
        "Copy PB CustomData",
        "Verify Bridge",
        "Assign Script Instance",
        "Create Selected Instance",
        "Build Multi-Script Bridge",
        "Allowed scripts become child instances",
        "BridgeRegistryGrid",
        "ScriptInstanceGrid",
        "BridgeDiagnosticsText",
    ]:
        assert token in xaml

    for token in [
        "data\", \"bridges.json",
        "data\", \"script_instances.json",
        "novali.client_side_pb.bridges.v1",
        "novali.client_side_pb.script_instances.v1",
        "SyncBridgeScriptAssignment",
        "BuildBridgePbShimScript",
        "VerifySelectedBridge_Click",
        "UpdateBridgeDiagnostics",
        "bridge_health.json",
        "queue_policy",
        "CreateSelectedScriptInstance_Click",
        "BuildMultiScriptBridge_Click",
        "CreateOrUpdateScriptInstance",
        "EnsureBridgeOrchestratorInstance",
    ]:
        assert token in source


def test_manager_multi_script_bridge_syncs_orchestrator_child_instances():
    source = MANAGER.read_text(encoding="utf-8")

    assert "BridgeOrchestratorScriptId" in source
    assert "selectedBaseScriptId == BridgeOrchestratorScriptId" in source
    assert "BuildChildInstanceId" in source
    assert "childInstanceIds" in source
    assert "new ChildWorkerScriptAssignment(" in source
    assert "childInstanceId," in source
    assert "10 + index," in source
    assert "OperatorStatusForScript" in source
    assert "expires_after_sequences" in source
    assert "fairness_weight" in source
    assert "ExistingChildBaseScriptIdsForBridge" in source
    assert "payload.Instances.Values" in source


def test_manager_worker_script_save_preserves_instance_orchestrator_bridge_assignments():
    source = MANAGER.read_text(encoding="utf-8")
    save_handler = source[
        source.index("private void SaveBridgeScripts_Click"):
        source.index("private static List<ChildWorkerScriptAssignment> BuildDefaultChildWorkerScripts")
    ]

    assert "SyncBridgeInstancesFromAllowedBaseScripts" in source
    assert "Bridge script assignment saved as bridge instances" in source
    assert "selected_script_id\", \"pb-bridge-001-orchestrator" not in source
    assert "SyncBridgeInstancesFromAllowedBaseScripts(bridge, allowed)" in save_handler
    assert "AllowedBaseScriptIdsForBridgeConfig" in source


def test_manager_bridges_tab_shows_running_instances_summary():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    assert "Currently running on this bridge" in xaml
    assert "RunningInstancesText" in xaml
    assert "UpdateRunningInstancesText" in source
    assert "script_not_allowed_for_bridge" in source
    assert "child_results" in source
    assert "Child results:" in source


def test_manager_can_remove_child_instance_without_row_selection_changing_selected_bridge_instance():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")
    selection_handler = source[
        source.index("private void ScriptInstanceGrid_SelectionChanged"):
        source.index("private void NewBridge_Click")
    ]

    assert "Remove From Bridge" in xaml
    assert "RemoveScriptInstanceFromBridge_Click" in xaml
    assert "RemoveScriptInstanceFromBridge_Click" in source
    assert "bridge.AllowedScriptInstanceIds.RemoveAll" in source
    assert "instance.Enabled = false" in source
    assert "BridgeSelectedInstanceBox.SelectedValue = record.InstanceId" not in selection_handler


def test_manager_bridge_diagnostics_tolerates_worker_file_races():
    source = MANAGER.read_text(encoding="utf-8")
    diagnostics_handler = source[
        source.index("private void UpdateBridgeDiagnostics"):
        source.index("private void SaveBridgeRecord")
    ]

    assert "ReadBridgeDiagnosticJson" in source
    assert "catch (IOException)" in source
    assert "request=unavailable" in diagnostics_handler
    assert "result=unavailable" in diagnostics_handler


def test_manager_bridge_verification_waits_for_matching_result_and_explains_pending_sequence():
    source = MANAGER.read_text(encoding="utf-8")

    assert "VerifyBridgeWithWait" in source
    assert "Thread.Sleep(250)" in source
    assert "result_pending_for_request_sequence" in source
    assert "Run the in-game PB again or wait for the worker to process the latest request" in source


def test_manager_bridge_custom_data_includes_verification_nonce_and_instance_id():
    source = MANAGER.read_text(encoding="utf-8")

    assert "verification_nonce=" in source
    assert "SelectedScriptInstanceId" in source
    assert "AllowedScriptInstanceIds" in source
    assert "BridgeVerificationRecord" in source


def test_manager_pb_custom_data_includes_dynamic_latency_limiter_defaults():
    source = MANAGER.read_text(encoding="utf-8")

    assert '"max_apply_commands_per_tick=" + TextOrFallback(MaxApplyCommandsBox?.Text, "8")' in source
    assert '"dynamic_apply_commands=true"' in source
    assert '"dynamic_min_apply_commands_per_tick=1"' in source
    assert '"dynamic_max_apply_commands_per_tick=8"' in source
    assert "bridge.Shim.MaxApplyCommandsPerTick == 1" in source
    assert "bridge.Shim.MaxApplyCommandsPerTick == 4" in source


def test_manager_bridge_custom_data_includes_operator_instance_labels():
    source = MANAGER.read_text(encoding="utf-8")

    assert "BuildPbInstanceLabelLines" in source
    assert '"instance_label."' in source
    assert "AllowedScriptInstanceIds" in source
    assert "DisplayName" in source
    assert "CompactInstanceLabel" in source
    assert "Virtual PB" in source


def test_manager_uses_neutral_baseline_shim_version():
    source = MANAGER.read_text(encoding="utf-8")

    assert "baseline-template-v1" in source
    assert "iim-action-parity" not in source


def test_bridge_and_script_instance_registry_files_are_seeded():
    bridges = json.loads(Path("data/bridges.json").read_text(encoding="utf-8"))
    instances = json.loads(Path("data/script_instances.json").read_text(encoding="utf-8"))

    assert bridges["schema"] == "novali.client_side_pb.bridges.v1"
    assert "pb-bridge-001" in bridges["bridges"]
    assert instances["schema"] == "novali.client_side_pb.script_instances.v1"
    assert isinstance(instances["instances"], dict)
