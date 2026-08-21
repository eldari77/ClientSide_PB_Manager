using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;

namespace NOVALI.ClientSidePBManager;

public partial class MainWindow : Window
{
    private const string BridgeOrchestratorScriptId = "bridge_orchestrator";
    private const string ChildWorkerScriptsJsonField = "child_worker_scripts";
    private const string ExpiresAfterSequencesJsonField = "expires_after_sequences";
    private const string FairnessWeightJsonField = "fairness_weight";
    private const string ExpectedShimVersion = "baseline-template-v1";
    private const string WorkerUiUrl = "http://localhost:8788";
    private const string WorkerUiLauncherRelativePath = @"tools\open_worker_ui.ps1";
    private readonly string _root;
    private readonly ObservableCollection<WorkshopRecord> _workshopRecords = new();
    private readonly ObservableCollection<FileRecord> _bridgeFiles = new();
    private readonly ObservableCollection<BridgeUiRecord> _bridges = new();
    private readonly ObservableCollection<ScriptInstanceUiRecord> _scriptInstances = new();
    private readonly ObservableCollection<WorkerScriptRecord> _workerScripts = new();
    private readonly ObservableCollection<WorkerConfigEntry> _workerConfigEntries = new();
    private readonly HashSet<string> _knownBridgeIds = new(StringComparer.OrdinalIgnoreCase);
    private ICollectionView? _workshopView;

    public MainWindow()
    {
        _root = ResolveRoot();
        InitializeComponent();
        RootText.Text = _root;
        WorkshopGrid.ItemsSource = _workshopRecords;
        BridgeGrid.ItemsSource = _bridgeFiles;
        BridgeRegistryGrid.ItemsSource = _bridges;
        ScriptInstanceGrid.ItemsSource = _scriptInstances;
        WorkerGrid.ItemsSource = _workerScripts;
        BridgeSelectedScriptBox.ItemsSource = _workerScripts;
        BridgeSetupScriptBox.ItemsSource = _workerScripts;
        ScriptInstanceBaseScriptBox.ItemsSource = _workerScripts;
        BridgeSelectedInstanceBox.ItemsSource = _scriptInstances;
        WorkerConfigGrid.ItemsSource = _workerConfigEntries;
        _workshopView = CollectionViewSource.GetDefaultView(_workshopRecords);
        _workshopView.Filter = FilterWorkshop;
        RefreshAll();
    }

    private static string ResolveRoot()
    {
        var current = AppContext.BaseDirectory;
        var dir = new DirectoryInfo(current);
        while (dir != null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "docker-compose.yml")) &&
                Directory.Exists(Path.Combine(dir.FullName, "worker")) &&
                Directory.Exists(Path.Combine(dir.FullName, "workshop")))
            {
                return dir.FullName;
            }
            dir = dir.Parent;
        }
        return Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));
    }

    private void RefreshAll()
    {
        LoadWorkshopCatalog();
        LoadWorkerScripts();
        LoadBridgeFiles();
        LoadScriptInstances();
        LoadBridgeRegistry();
        LoadLimits();
        RefreshLogs();
        LoadDiscoverySummary();
        StatusText.Text = "Ready";
    }

    private async void RunActiveDiscovery_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "Running active discovery...";
        var result = await RunActiveDiscovery();
        GuidedSetupOutput.Text = result;
        LoadDiscoverySummary();
        RefreshLogs();
        StatusText.Text = "Discovery report refreshed";
    }

    private async void RunGuidedSetup_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "Running guided setup...";
        var lines = new List<string>
        {
            "== Workshop scan ==",
            await RunProcess("python", "-m workshop.scan_workshop --output data\\workshop_catalog.json"),
            "== Discovery ==",
            await RunActiveDiscovery(),
            "== Docker ==",
            await RunProcess("docker", "compose up --build -d client-side-pb-worker"),
            "== Build Pulsar plugin ==",
            await RunProcess("powershell", "-ExecutionPolicy Bypass -File tools\\build_local_plugin.ps1"),
            "== Handoff Pulsar plugin ==",
            await RunProcess("powershell", "-ExecutionPolicy Bypass -File tools\\handoff_plugin.ps1"),
        };
        GuidedSetupOutput.Text = string.Join(Environment.NewLine, lines);
        RefreshAll();
        BuildMultiScriptBridge_Click(sender, e);
        ShowBridgePbConfigPrompt("Guided setup generated PB CustomData; paste/recompile remains in-game");
        LoadDiscoverySummary();
        StatusText.Text = "Guided setup local automation complete";
    }

    private Task<string> RunActiveDiscovery()
    {
        return RunProcess("python", "-m discovery.active_discovery --root . --output data\\discovery_report.json --run-api-probe");
    }

    private void LoadDiscoverySummary()
    {
        var path = Path.Combine(_root, "data", "discovery_report.json");
        if (!File.Exists(path))
        {
            if (GuidedSetupSummaryText != null) GuidedSetupSummaryText.Text = "No discovery report loaded.";
            if (GuidedSetupActionsText != null) GuidedSetupActionsText.Text = "Run Discovery to inspect local bridge readiness.";
            return;
        }
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            var bridges = root.TryGetProperty("bridges", out var bridgeList) && bridgeList.ValueKind == JsonValueKind.Array
                ? bridgeList.EnumerateArray().ToList()
                : new List<JsonElement>();
            var scripts = root.TryGetProperty("workshop_scripts", out var scriptList) && scriptList.ValueKind == JsonValueKind.Array
                ? scriptList.EnumerateArray().ToList()
                : new List<JsonElement>();
            var readyScripts = scripts.Count(item =>
            {
                var status = GetString(item, "operator_status");
                return status == "ready_profile" || status == "ready_virtual_pb";
            });
            var blockedScripts = scripts.Count(item =>
            {
                var status = GetString(item, "operator_status");
                return status == "blocked_needs_command_mapping" || status == "missing_snapshot_fields";
            });
            var harnessSummary = "";
            if (root.TryGetProperty("harness_update_plan", out var harnessPlan) && harnessPlan.ValueKind == JsonValueKind.Object)
            {
                var nextAction = GetString(harnessPlan, "next_recommended_action");
                var readOnlyCount = 0;
                var mappingCount = 0;
                if (harnessPlan.TryGetProperty("summary", out var harnessCounts) && harnessCounts.ValueKind == JsonValueKind.Object)
                {
                    readOnlyCount = GetInt(harnessCounts, "read_only_stub_queue");
                    mappingCount = GetInt(harnessCounts, "mapping_review_queue");
                }
                harnessSummary = "; Harness next: " + DescribeHarnessAction(nextAction) +
                    " (" + readOnlyCount + " read-only, " + mappingCount + " mappings)";
            }
            GuidedSetupSummaryText.Text =
                "Bridges: " + bridges.Count + "; scripts ready to offload: " + readyScripts + "; scripts needing review: " + blockedScripts + harnessSummary;
            GuidedSetupActionsText.Text = root.TryGetProperty("repair_actions", out var actions) && actions.ValueKind == JsonValueKind.Array
                ? string.Join(", ", actions.EnumerateArray().Select(item => item.GetString()).Where(item => !string.IsNullOrWhiteSpace(item)))
                : "No repair actions reported.";
        }
        catch (JsonException)
        {
            GuidedSetupSummaryText.Text = "Discovery report is not valid JSON.";
            GuidedSetupActionsText.Text = "Run Discovery again.";
        }
        catch (IOException)
        {
            GuidedSetupSummaryText.Text = "Discovery report is busy.";
            GuidedSetupActionsText.Text = "Try refresh again.";
        }
    }

    private static string DescribeHarnessAction(string action)
    {
        return action switch
        {
            "add_read_only_stubs" => "add read-only API stubs",
            "review_command_mappings" => "review command mappings",
            "keep_blocked_until_design_review" => "blocked API review",
            "run_api_probe" => "run API probe",
            "none" => "aligned",
            _ => string.IsNullOrWhiteSpace(action) ? "not reported" : action.Replace("_", " "),
        };
    }

    private async void RefreshWorkshop_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "Scanning Workshop...";
        var result = await RunProcess("python", "-m workshop.scan_workshop --output data\\workshop_catalog.json");
        LogOutput.Text = result;
        LoadWorkshopCatalog();
        StatusText.Text = "Workshop scan complete";
    }

    private void LoadWorkshopCatalog()
    {
        _workshopRecords.Clear();
        var path = Path.Combine(_root, "data", "workshop_catalog.json");
        if (!File.Exists(path))
        {
            return;
        }
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        if (!doc.RootElement.TryGetProperty("records", out var records))
        {
            return;
        }
        foreach (var item in records.EnumerateArray())
        {
            _workshopRecords.Add(new WorkshopRecord(
                GetString(item, "workshop_id"),
                GetString(item, "workshop_title"),
                GetString(item, "source_path"),
                GetString(item, "source_hash"),
                GetString(item, "steam_library"),
                GetString(item, "time_updated"),
                GetString(item, "detected_title"),
                GetString(item, "detected_kind"),
                DescribeCompatibilityForOperator(GetString(item, "compatibility"))));
        }
        _workshopView?.Refresh();
    }

    private bool FilterWorkshop(object obj)
    {
        if (obj is not WorkshopRecord record)
        {
            return false;
        }
        var filter = WorkshopFilterBox.Text?.Trim();
        var kind = SelectedKindFilter();
        if (!string.Equals(kind, "all", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(record.DetectedKind, kind, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (string.IsNullOrWhiteSpace(filter))
        {
            return true;
        }
        return record.WorkshopId.Contains(filter, StringComparison.OrdinalIgnoreCase) ||
               record.HumanName.Contains(filter, StringComparison.OrdinalIgnoreCase) ||
               record.DetectedTitle.Contains(filter, StringComparison.OrdinalIgnoreCase) ||
               record.DetectedKind.Contains(filter, StringComparison.OrdinalIgnoreCase) ||
               record.Compatibility.Contains(filter, StringComparison.OrdinalIgnoreCase) ||
               record.SourcePath.Contains(filter, StringComparison.OrdinalIgnoreCase);
    }

    private void WorkshopFilterBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        _workshopView?.Refresh();
    }

    private void KindFilterBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _workshopView?.Refresh();
    }

    private string SelectedKindFilter()
    {
        return KindFilterBox.SelectedItem is ComboBoxItem item && item.Content is string content ? content : "all";
    }

    private void OpenWorkshop_Click(object sender, RoutedEventArgs e)
    {
        if (WorkshopGrid.SelectedItem is not WorkshopRecord record)
        {
            return;
        }
        Process.Start(new ProcessStartInfo
        {
            FileName = "https://steamcommunity.com/sharedfiles/filedetails/?id=" + record.WorkshopId,
            UseShellExecute = true
        });
    }

    private void ImportWorkshop_Click(object sender, RoutedEventArgs e)
    {
        if (WorkshopGrid.SelectedItem is not WorkshopRecord record || record.DetectedKind != "pb_script")
        {
            StatusText.Text = "Select a PB script record to import";
            return;
        }
        var targetDir = Path.Combine(_root, "data", "imports", record.WorkshopId);
        Directory.CreateDirectory(targetDir);
        File.Copy(record.SourcePath, Path.Combine(targetDir, "Script.cs"), overwrite: true);
        File.WriteAllText(Path.Combine(targetDir, "metadata.json"), JsonSerializer.Serialize(record, new JsonSerializerOptions { WriteIndented = true }));
        StatusText.Text = "Imported " + record.WorkshopId;
        RefreshLogs();
    }

    private void OpenWorkerUi_Click(object sender, RoutedEventArgs e)
    {
        var launcher = Path.Combine(_root, WorkerUiLauncherRelativePath);
        if (File.Exists(launcher))
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + launcher + "\"",
                WorkingDirectory = _root,
                UseShellExecute = false,
                CreateNoWindow = true
            });
            StatusText.Text = "Opening worker UI...";
            return;
        }
        Process.Start(new ProcessStartInfo
        {
            FileName = WorkerUiUrl,
            UseShellExecute = true
        });
    }

    private async void PrepareAdapter_Click(object sender, RoutedEventArgs e)
    {
        if (WorkshopGrid.SelectedItem is not WorkshopRecord record || record.DetectedKind != "pb_script")
        {
            StatusText.Text = "Select a PB script record to prepare";
            return;
        }
        StatusText.Text = "Preparing adapter for " + record.WorkshopId;
        var result = await RunProcess(
            "python",
            "-m workshop.adapter_tool --root . --catalog data\\workshop_catalog.json --workshop-id " + record.WorkshopId);
        LogOutput.Text = result;
        LoadWorkshopCatalog();
        LoadWorkerScripts();
        RefreshLogs();
        var (status, scriptId) = ParseAdapterPrepResult(result);
        if (string.Equals(status, "virtual_pb_ready", StringComparison.OrdinalIgnoreCase))
        {
            SelectPreparedWorkerScript(scriptId);
            StatusText.Text = "Virtual PB adapter ready: " + scriptId;
        }
        else if (string.Equals(status, "profile_adapter_ready", StringComparison.OrdinalIgnoreCase))
        {
            SelectPreparedWorkerScript(scriptId);
            StatusText.Text = "Profile adapter ready: " + scriptId;
        }
        else if (!string.IsNullOrWhiteSpace(scriptId))
        {
            SelectPreparedWorkerScript(scriptId);
            StatusText.Text = "Manual adapter scaffold prepared: " + scriptId;
        }
        else
        {
            StatusText.Text = "Adapter scaffold prepared";
        }
    }

    private static (string Status, string ScriptId) ParseAdapterPrepResult(string output)
    {
        try
        {
            using var doc = JsonDocument.Parse(output);
            return (GetString(doc.RootElement, "status"), GetString(doc.RootElement, "script_id"));
        }
        catch (JsonException)
        {
            return ("", "");
        }
    }

    private static string DescribeCompatibilityForOperator(string status)
    {
        return status switch
        {
            "virtual_pb_ready" => "Virtual PB ready",
            "profile_adapter_ready" => "Known profile ready",
            "virtual_pb_blocked" => "Blocked command mapping",
            "adapter_scaffold_created" => "Manual adapter required",
            "manual_adapter_required" => "Manual adapter required",
            "missing_snapshot_fields" => "Missing snapshot fields",
            _ => string.IsNullOrWhiteSpace(status) ? "Not checked" : status
        };
    }

    private void SelectPreparedWorkerScript(string scriptId)
    {
        if (string.IsNullOrWhiteSpace(scriptId))
        {
            return;
        }
        var script = _workerScripts.FirstOrDefault(item => string.Equals(item.ScriptId, scriptId, StringComparison.OrdinalIgnoreCase));
        if (script == null)
        {
            return;
        }
        script.AllowedForBridge = true;
        WorkerGrid.SelectedItem = script;
        BridgeSelectedScriptBox.SelectedValue = script.ScriptId;
        MainTabs.SelectedItem = WorkerScriptsTab;
    }

    private void RefreshFiles_Click(object sender, RoutedEventArgs e)
    {
        LoadBridgeFiles();
        LoadScriptInstances();
        LoadBridgeRegistry();
    }

    private void LoadBridgeFiles()
    {
        var records = new List<FileRecord>();
        var newBridgeIds = new List<string>();
        _bridgeFiles.Clear();
        foreach (var folder in new[] { "bridge_requests", "bridge_results" })
        {
            var dir = Path.Combine(_root, "data", folder);
            if (!Directory.Exists(dir))
            {
                continue;
            }
            foreach (var file in Directory.EnumerateFiles(dir, "*.json"))
            {
                var info = new FileInfo(file);
                var record = new FileRecord(folder + "/" + info.Name, info.LastWriteTime.ToString("s"), info.Length, info.FullName);
                records.Add(record);
                var bridgeId = BridgeIdFromFileRecord(record);
                if (!string.IsNullOrWhiteSpace(bridgeId) &&
                    !_knownBridgeIds.Contains(bridgeId) &&
                    !newBridgeIds.Contains(bridgeId, StringComparer.OrdinalIgnoreCase))
                {
                    newBridgeIds.Add(bridgeId);
                }
            }
        }
        foreach (var record in records.OrderByDescending(record => File.GetLastWriteTime(record.FullPath)))
        {
            _bridgeFiles.Add(record);
            var bridgeId = BridgeIdFromFileRecord(record);
            if (!string.IsNullOrWhiteSpace(bridgeId))
            {
                _knownBridgeIds.Add(bridgeId);
            }
        }
        if (newBridgeIds.Count > 0)
        {
            var bridgeId = newBridgeIds[0];
            SelectBridgeFile(bridgeId);
            SetCurrentWorkerBridgeId(bridgeId);
            ShowBridgePbConfigPrompt("New PB bridge detected: " + bridgeId);
        }
    }

    private void OpenData_Click(object sender, RoutedEventArgs e)
    {
        Directory.CreateDirectory(Path.Combine(_root, "data"));
        Process.Start(new ProcessStartInfo { FileName = Path.Combine(_root, "data"), UseShellExecute = true });
    }

    private void BridgeGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (BridgeGrid.SelectedItem is not FileRecord record)
        {
            return;
        }
        var bridgeId = BridgeIdFromFileRecord(record);
        if (string.IsNullOrWhiteSpace(bridgeId))
        {
            return;
        }
        SetCurrentWorkerBridgeId(bridgeId);
        ShowBridgePbConfigPrompt("PB CustomData for selected bridge: " + bridgeId);
    }

    private void LoadBridgeRegistry()
    {
        _bridges.Clear();
        var payload = LoadBridgeRegistryPayload();
        foreach (var item in payload.Bridges.Values.OrderBy(bridge => bridge.BridgeId, StringComparer.OrdinalIgnoreCase))
        {
            _bridges.Add(BridgeUiRecord.FromRecord(NormalizeBridgeRecord(item)));
        }
        if (BridgeRegistryGrid.SelectedItem is null && _bridges.Count > 0)
        {
            BridgeRegistryGrid.SelectedItem = _bridges[0];
        }
        if (BridgeRegistryGrid.SelectedItem is BridgeUiRecord selected)
        {
            ApplyBridgeToForm(selected);
        }
    }

    private void LoadScriptInstances()
    {
        _scriptInstances.Clear();
        var payload = LoadScriptInstancesPayload();
        foreach (var item in payload.Instances.Values.OrderBy(instance => instance.InstanceId, StringComparer.OrdinalIgnoreCase))
        {
            _scriptInstances.Add(ScriptInstanceUiRecord.FromRecord(NormalizeScriptInstanceRecord(item)));
        }
        if (BridgeRegistryGrid.SelectedItem is BridgeUiRecord selected)
        {
            UpdateRunningInstancesText(selected.BridgeId);
        }
    }

    private void BridgeRegistryGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (BridgeRegistryGrid.SelectedItem is not BridgeUiRecord record)
        {
            return;
        }
        ApplyBridgeToForm(record);
        SetCurrentWorkerBridgeId(record.BridgeId);
        SelectBridgeFile(record.BridgeId);
        RefreshBridgePbConfigPromptText();
    }

    private void ScriptInstanceGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ScriptInstanceGrid.SelectedItem is not ScriptInstanceUiRecord record)
        {
            return;
        }
        ScriptInstanceIdBox.Text = record.InstanceId;
        ScriptInstanceBaseScriptBox.SelectedValue = record.BaseScriptId;
        ScriptInstanceDisplayNameBox.Text = record.DisplayName;
        ScriptInstanceEnabledBox.IsChecked = record.Enabled;
        RefreshBridgePbConfigPromptText();
    }

    private void NewBridge_Click(object sender, RoutedEventArgs e)
    {
        var bridgeId = NextBridgeId();
        BridgeIdBox.Text = bridgeId;
        BridgeDisplayNameBox.Text = "Bridge " + bridgeId;
        BridgeMailboxModeBox.SelectedIndex = 0;
        BridgeTextPanelNameBox.Text = "NOVALI PB Bridge";
        BridgeSnapshotModeBox.SelectedIndex = 0;
        BridgeSetupScriptBox.SelectedValue = _workerScripts.FirstOrDefault(script => script.ScriptId == "sample_status_adapter")?.ScriptId
            ?? _workerScripts.FirstOrDefault(script => script.Enabled)?.ScriptId
            ?? "";
        BridgeSelectedInstanceBox.SelectedValue = null;
        BridgeVerificationNonceBox.Text = NewNonce();
        SaveBridgeFromForm("created");
        StatusText.Text = "Bridge object created";
    }

    private void SaveBridge_Click(object sender, RoutedEventArgs e)
    {
        SaveBridgeFromForm(null);
        StatusText.Text = "Bridge object saved";
    }

    private void CopyBridgeShimScript_Click(object sender, RoutedEventArgs e)
    {
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        var script = BuildBridgePbShimScript(bridge);
        try
        {
            Clipboard.SetText(script);
            LogOutput.Text = script;
            StatusText.Text = "PB shim script copied";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Clipboard unavailable: " + ex.Message;
        }
    }

    private void CopyBridgeCustomData_Click(object sender, RoutedEventArgs e)
    {
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        var customData = BuildPbCustomData(bridge);
        try
        {
            Clipboard.SetText(customData);
            BridgePbConfigBox.Text = customData;
            BridgePbConfigPromptTitle.Text = "PB CustomData for bridge: " + bridge.BridgeId;
            BridgePbConfigPrompt.Visibility = Visibility.Visible;
            LogOutput.Text = customData;
            StatusText.Text = "PB CustomData copied";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Clipboard unavailable: " + ex.Message;
        }
    }

    private void VerifySelectedBridge_Click(object sender, RoutedEventArgs e)
    {
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        var verification = VerifyBridgeWithWait(bridge);
        bridge.Status = verification.Verified ? "verified" : "pending";
        bridge.Verification = verification;
        bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
        SaveBridgeRecord(bridge);
        LoadBridgeRegistry();
        StatusText.Text = verification.Verified ? "Bridge verified" : "Bridge verification pending: " + BridgeVerificationOperatorMessage(verification);
    }

    private void CreateSelectedScriptInstance_Click(object sender, RoutedEventArgs e)
    {
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        var baseScriptId = ScriptInstanceBaseScriptBox.SelectedValue as string
            ?? BridgeSetupScriptBox.SelectedValue as string
            ?? _workerScripts.FirstOrDefault(script => script.Enabled)?.ScriptId
            ?? "";
        if (string.IsNullOrWhiteSpace(baseScriptId))
        {
            StatusText.Text = "Base script required";
            return;
        }
        var instanceId = NormalizeScriptId(TextOrFallback(ScriptInstanceIdBox.Text, bridge.BridgeId + "-" + baseScriptId));
        var displayName = TextOrFallback(ScriptInstanceDisplayNameBox.Text, bridge.DisplayName + " - " + baseScriptId);
        var payload = LoadScriptInstancesPayload();
        CreateOrUpdateScriptInstance(payload, bridge.BridgeId, instanceId, baseScriptId, displayName, ScriptInstanceEnabledBox.IsChecked != false);
        SaveScriptInstancesPayload(payload);
        if (!bridge.AllowedScriptInstanceIds.Contains(instanceId, StringComparer.OrdinalIgnoreCase))
        {
            bridge.AllowedScriptInstanceIds.Add(instanceId);
        }
        bridge.SelectedScriptInstanceId = instanceId;
        bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
        SaveBridgeRecord(bridge);
        SyncBridgeScriptAssignment(bridge);
        LoadScriptInstances();
        LoadBridgeRegistry();
        LoadWorkerScripts();
        StatusText.Text = string.Equals(bridge.Status, "verified", StringComparison.OrdinalIgnoreCase)
            ? "Script instance created and assigned"
            : "Script instance staged; copy CustomData after verifying or when ready to run";
    }

    private void BuildMultiScriptBridge_Click(object sender, RoutedEventArgs e)
    {
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        var childBaseScriptIds = LoadBridgeAllowedBaseScriptIds(bridge)
            .Where(scriptId => !string.Equals(scriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            .ToList();
        childBaseScriptIds.AddRange(ExistingChildBaseScriptIdsForBridge(bridge));
        if (childBaseScriptIds.Count > 1)
        {
            childBaseScriptIds = childBaseScriptIds
                .Where(scriptId => !string.Equals(scriptId, bridge.Shim.SetupScriptId, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }
        if (childBaseScriptIds.Count == 0)
        {
            var selectedBaseScriptId = ScriptInstanceBaseScriptBox.SelectedValue as string ?? "";
            if (!string.IsNullOrWhiteSpace(selectedBaseScriptId) &&
                !string.Equals(selectedBaseScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            {
                childBaseScriptIds.Add(selectedBaseScriptId);
            }
        }
        childBaseScriptIds = childBaseScriptIds
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (childBaseScriptIds.Count == 0)
        {
            StatusText.Text = "Allow at least one base script for this bridge before building multi-script instances";
            return;
        }

        var payload = LoadScriptInstancesPayload();
        var childInstanceIds = new List<string>();
        foreach (var baseScriptId in childBaseScriptIds)
        {
            var childInstanceId = BuildChildInstanceId(bridge.BridgeId, baseScriptId);
            var scriptName = _workerScripts.FirstOrDefault(script => string.Equals(script.ScriptId, baseScriptId, StringComparison.OrdinalIgnoreCase))?.DisplayName;
            CreateOrUpdateScriptInstance(
                payload,
                bridge.BridgeId,
                childInstanceId,
                baseScriptId,
                bridge.DisplayName + " - " + TextOrFallback(scriptName, baseScriptId),
                true);
            childInstanceIds.Add(childInstanceId);
        }

        var orchestratorInstanceId = EnsureBridgeOrchestratorInstance(payload, bridge);
        SaveScriptInstancesPayload(payload);
        bridge.SelectedScriptInstanceId = orchestratorInstanceId;
        bridge.AllowedScriptInstanceIds = new[] { orchestratorInstanceId }
            .Concat(childInstanceIds)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
        SaveBridgeRecord(bridge);
        LoadScriptInstances();
        LoadBridgeRegistry();
        LoadWorkerScripts();
        BridgeSelectedInstanceBox.SelectedValue = orchestratorInstanceId;
        StatusText.Text = string.Equals(bridge.Status, "verified", StringComparison.OrdinalIgnoreCase)
            ? "Multi-script bridge assigned to orchestrator instance"
            : "Multi-script bridge staged; copy PB CustomData so the in-game PB runs the orchestrator instance";
    }

    private void AssignScriptInstance_Click(object sender, RoutedEventArgs e)
    {
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        if (!string.Equals(bridge.Status, "verified", StringComparison.OrdinalIgnoreCase))
        {
            StatusText.Text = "Verify bridge before assigning script instances";
            return;
        }
        var instanceId = (ScriptInstanceGrid.SelectedItem as ScriptInstanceUiRecord)?.InstanceId
            ?? BridgeSelectedInstanceBox.SelectedValue as string
            ?? "";
        if (string.IsNullOrWhiteSpace(instanceId))
        {
            StatusText.Text = "Script instance required";
            return;
        }
        bridge.SelectedScriptInstanceId = instanceId;
        if (!bridge.AllowedScriptInstanceIds.Contains(instanceId, StringComparer.OrdinalIgnoreCase))
        {
            bridge.AllowedScriptInstanceIds.Add(instanceId);
        }
        bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
        SaveBridgeRecord(bridge);
        SyncBridgeScriptAssignment(bridge);
        LoadBridgeRegistry();
        LoadWorkerScripts();
        StatusText.Text = bridge.Status == "verified" ? "Script instance assigned" : "Script instance assigned; verify bridge before running in-game";
    }

    private void RemoveScriptInstanceFromBridge_Click(object sender, RoutedEventArgs e)
    {
        var selected = ScriptInstanceGrid.SelectedItem as ScriptInstanceUiRecord;
        if (selected == null || string.IsNullOrWhiteSpace(selected.InstanceId))
        {
            StatusText.Text = "Select an instance to remove from this bridge";
            return;
        }
        var bridge = SaveBridgeFromForm(null, syncAssignment: false);
        if (bridge == null)
        {
            return;
        }
        if (string.Equals(selected.InstanceId, bridge.SelectedScriptInstanceId, StringComparison.OrdinalIgnoreCase))
        {
            StatusText.Text = "Cannot remove the selected bridge runtime; assign another instance first";
            return;
        }

        var instances = LoadScriptInstancesPayload();
        if (instances.Instances.TryGetValue(selected.InstanceId, out var instance))
        {
            instance.Enabled = false;
            instance.UpdatedAt = DateTime.UtcNow.ToString("o");
            instances.Instances[selected.InstanceId] = instance;
            SaveScriptInstancesPayload(instances);
        }
        bridge.AllowedScriptInstanceIds.RemoveAll(instanceId => string.Equals(instanceId, selected.InstanceId, StringComparison.OrdinalIgnoreCase));
        bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
        SaveBridgeRecord(bridge);
        SyncBridgeScriptAssignment(bridge);
        LoadScriptInstances();
        LoadBridgeRegistry();
        LoadWorkerScripts();
        StatusText.Text = "Script instance removed from bridge";
    }

    private void ApplyBridgeToForm(BridgeUiRecord record)
    {
        BridgeIdBox.Text = record.BridgeId;
        BridgeDisplayNameBox.Text = record.DisplayName;
        BridgeMailboxModeBox.Text = record.Shim.MailboxMode;
        BridgeTextPanelNameBox.Text = record.Shim.TextPanelName;
        BridgeSnapshotModeBox.Text = record.Shim.SnapshotMode;
        BridgeSetupScriptBox.SelectedValue = record.Shim.SetupScriptId;
        BridgeSelectedInstanceBox.SelectedValue = record.SelectedScriptInstanceId;
        BridgeVerificationNonceBox.Text = record.Shim.VerificationNonce;
        UpdateScriptInstanceControls(true);
        UpdateRunningInstancesText(record.BridgeId);
        UpdateBridgeDiagnostics(record.BridgeId);
    }

    private void UpdateScriptInstanceControls(bool enabled)
    {
        if (CreateScriptInstanceButton != null) CreateScriptInstanceButton.IsEnabled = enabled;
        if (BuildMultiScriptBridgeButton != null) BuildMultiScriptBridgeButton.IsEnabled = enabled;
        if (AssignScriptInstanceButton != null) AssignScriptInstanceButton.IsEnabled = enabled;
        if (RemoveScriptInstanceButton != null) RemoveScriptInstanceButton.IsEnabled = enabled;
        if (ScriptInstanceGrid != null) ScriptInstanceGrid.IsEnabled = enabled;
        if (ScriptInstanceIdBox != null) ScriptInstanceIdBox.IsEnabled = enabled;
        if (ScriptInstanceBaseScriptBox != null) ScriptInstanceBaseScriptBox.IsEnabled = enabled;
        if (ScriptInstanceDisplayNameBox != null) ScriptInstanceDisplayNameBox.IsEnabled = enabled;
        if (ScriptInstanceEnabledBox != null) ScriptInstanceEnabledBox.IsEnabled = enabled;
        if (BridgeSelectedInstanceBox != null) BridgeSelectedInstanceBox.IsEnabled = enabled;
    }

    private BridgeRegistryRecord? SaveBridgeFromForm(string? statusOverride, bool syncAssignment = true)
    {
        var bridgeId = NormalizeScriptId(BridgeIdBox.Text);
        if (string.IsNullOrWhiteSpace(bridgeId))
        {
            StatusText.Text = "Bridge id required";
            return null;
        }
        var payload = LoadBridgeRegistryPayload();
        payload.Bridges.TryGetValue(bridgeId, out var existing);
        var now = DateTime.UtcNow.ToString("o");
        var selectedInstanceId = BridgeSelectedInstanceBox.SelectedValue as string ?? existing?.SelectedScriptInstanceId ?? "";
        var allowed = existing?.AllowedScriptInstanceIds?.ToList() ?? new List<string>();
        if (!string.IsNullOrWhiteSpace(selectedInstanceId) &&
            !allowed.Contains(selectedInstanceId, StringComparer.OrdinalIgnoreCase))
        {
            allowed.Add(selectedInstanceId);
        }
        var bridge = new BridgeRegistryRecord
        {
            BridgeId = bridgeId,
            DisplayName = TextOrFallback(BridgeDisplayNameBox.Text, bridgeId),
            Status = statusOverride ?? existing?.Status ?? "created",
            Shim = new BridgeShimSettings
            {
                MailboxMode = SelectedComboText(BridgeMailboxModeBox, "both"),
                TextPanelName = TextOrFallback(BridgeTextPanelNameBox.Text, "NOVALI PB Bridge"),
                SnapshotMode = SelectedComboText(BridgeSnapshotModeBox, "minimal"),
                SetupScriptId = BridgeSetupScriptBox.SelectedValue as string ?? "sample_status_adapter",
                VerificationNonce = TextOrFallback(BridgeVerificationNonceBox.Text, NewNonce()),
                MaxCommandsPerMinute = GetLimitInt(LimitMaxCommandsBox?.Text, 60),
                MaxApplyCommandsPerTick = GetLimitInt(MaxApplyCommandsBox?.Text, 8),
                ApplyWorkerCommands = true,
                AllowConnectedGridCommands = AllowConnectedGridsBox?.IsChecked == true,
                RuntimeMsLimit = GetLimitDouble(RuntimeMsLimitBox?.Text, 0.25),
                RuntimeMsSoftRatio = GetLimitDouble(RuntimeMsSoftRatioBox?.Text, 0.75),
                CooldownSeconds = GetLimitInt(CooldownSecondsBox?.Text, 3),
                FailClosed = LimitFailClosedCheckBox?.IsChecked != false
            },
            Verification = existing?.Verification ?? new BridgeVerificationRecord(),
            SelectedScriptInstanceId = selectedInstanceId,
            AllowedScriptInstanceIds = allowed.Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
            CreatedAt = existing?.CreatedAt ?? now,
            UpdatedAt = now
        };
        payload.Bridges[bridgeId] = bridge;
        SaveBridgeRegistryPayload(payload);
        var bridgeScriptAssignments = LoadBridgeScriptsPayload();
        var hasInstanceAssignment = !string.IsNullOrWhiteSpace(bridge.SelectedScriptInstanceId) || bridge.AllowedScriptInstanceIds.Count > 0;
        var hasExistingWorkerTabAssignment = bridgeScriptAssignments.Bridges.ContainsKey(bridgeId);
        if (syncAssignment && (hasInstanceAssignment || !hasExistingWorkerTabAssignment))
        {
            SyncBridgeScriptAssignment(bridge);
        }
        LoadBridgeRegistry();
        return bridge;
    }

    private List<string> LoadBridgeAllowedBaseScriptIds(BridgeRegistryRecord bridge)
    {
        var bridgeAssignments = LoadBridgeScriptsPayload();
        if (bridgeAssignments.Bridges.TryGetValue(bridge.BridgeId, out var bridgeConfig))
        {
            return bridgeConfig.AllowedWorkerScripts
                .Where(scriptId => !string.IsNullOrWhiteSpace(scriptId))
                .Where(scriptId => _workerScripts.Any(script => string.Equals(script.ScriptId, scriptId, StringComparison.OrdinalIgnoreCase)))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
        }
        return _workerScripts
            .Where(script => script.AllowedForBridge)
            .Select(script => script.ScriptId)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private List<string> ExistingChildBaseScriptIdsForBridge(BridgeRegistryRecord bridge)
    {
        var payload = LoadScriptInstancesPayload();
        return payload.Instances.Values
            .Where(instance => string.Equals(instance.BridgeId, bridge.BridgeId, StringComparison.OrdinalIgnoreCase))
            .Where(instance => instance.Enabled)
            .Select(instance => instance.BaseScriptId)
            .Where(baseScriptId => !string.Equals(baseScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            .Where(baseScriptId => !string.Equals(baseScriptId, "sample_status_adapter", StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private ScriptInstanceRecord CreateOrUpdateScriptInstance(
        ScriptInstancesPayload payload,
        string bridgeId,
        string instanceId,
        string baseScriptId,
        string displayName,
        bool enabled)
    {
        instanceId = NormalizeScriptId(instanceId);
        baseScriptId = NormalizeScriptId(baseScriptId);
        payload.Instances.TryGetValue(instanceId, out var existing);
        var now = DateTime.UtcNow.ToString("o");
        var instance = new ScriptInstanceRecord
        {
            InstanceId = instanceId,
            BaseScriptId = baseScriptId,
            DisplayName = TextOrFallback(displayName, instanceId),
            BridgeId = bridgeId,
            Enabled = enabled,
            ConfigId = TextOrFallback(existing?.ConfigId, instanceId),
            CreatedAt = existing?.CreatedAt ?? now,
            UpdatedAt = now
        };
        payload.Instances[instanceId] = instance;
        return instance;
    }

    private string EnsureBridgeOrchestratorInstance(ScriptInstancesPayload payload, BridgeRegistryRecord bridge)
    {
        var instanceId = BuildOrchestratorInstanceId(bridge.BridgeId);
        CreateOrUpdateScriptInstance(
            payload,
            bridge.BridgeId,
            instanceId,
            BridgeOrchestratorScriptId,
            bridge.DisplayName + " - Orchestrator",
            true);
        return instanceId;
    }

    private static string BuildChildInstanceId(string bridgeId, string baseScriptId)
    {
        return NormalizeScriptId(bridgeId + "-" + baseScriptId);
    }

    private static string BuildOrchestratorInstanceId(string bridgeId)
    {
        return NormalizeScriptId(bridgeId + "-orchestrator");
    }


    private void RefreshWorkerScripts_Click(object sender, RoutedEventArgs e) => LoadWorkerScripts();

    private void WorkerBridgeIdBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_root) || BridgeSelectedScriptBox == null)
        {
            return;
        }
        ApplyBridgeScriptSelection();
        UpdateLatestWorkerSummary();
        RefreshBridgePbConfigPromptText();
    }

    private void LoadWorkerScripts()
    {
        _workerScripts.Clear();
        var path = Path.Combine(_root, "worker", "manifest.json");
        if (!File.Exists(path))
        {
            return;
        }
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        if (!doc.RootElement.TryGetProperty("scripts", out var scripts))
        {
            return;
        }
        var bridgeAssignments = LoadBridgeScriptsPayload();
        var bridgeId = CurrentWorkerBridgeId();
        bridgeAssignments.Bridges.TryGetValue(bridgeId, out var bridgeConfig);
        foreach (var item in scripts.EnumerateArray())
        {
            var scriptId = GetString(item, "script_id");
            _workerScripts.Add(new WorkerScriptRecord(
                scriptId,
                GetString(item, "display_name"),
                GetString(item, "source"),
                GetString(item, "module"),
                GetString(item, "runtime"),
                GetString(item, "source_path"),
                GetString(item, "input_schema"),
                GetString(item, "output_schema"),
                GetBool(item, "enabled"),
                bridgeConfig?.AllowedWorkerScripts.Contains(scriptId, StringComparer.OrdinalIgnoreCase) == true,
                GetInt(item, "timeout_ms")));
        }
        ApplyBridgeScriptSelection(bridgeAssignments);
        if (WorkerGrid.SelectedItem is null && _workerScripts.Count > 0)
        {
            WorkerGrid.SelectedItem = _workerScripts[0];
        }
        UpdateLatestWorkerSummary();
        RefreshBridgePbConfigPromptText();
    }

    private void WorkerGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord script)
        {
            WorkerScriptPathText.Text = "Select a worker script to edit its local copy.";
            _workerConfigEntries.Clear();
            return;
        }
        var path = TryGetWorkerScriptPath(script, out var scriptPathError);
        WorkerScriptPathText.Text = path ?? scriptPathError;
        if (string.IsNullOrWhiteSpace(CloneScriptIdBox.Text))
        {
            CloneScriptIdBox.Text = script.ScriptId + "_copy";
        }
        if (string.IsNullOrWhiteSpace(CloneDisplayNameBox.Text))
        {
            CloneDisplayNameBox.Text = script.DisplayName + " Copy";
        }
        LoadWorkerConfig(script);
    }

    private void LoadWorkerLocalCopy_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord script)
        {
            StatusText.Text = "Select a worker script first";
            return;
        }
        var path = TryGetWorkerScriptPath(script, out var error);
        if (path == null)
        {
            StatusText.Text = error;
            return;
        }
        WorkerScriptEditor.Text = File.ReadAllText(path);
        WorkerScriptPathText.Text = path;
        StatusText.Text = "Loaded local copy";
    }

    private void SaveWorkerLocalCopy_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord script)
        {
            StatusText.Text = "Select a worker script first";
            return;
        }
        var path = TryGetWorkerScriptPath(script, out var error);
        if (path == null)
        {
            StatusText.Text = error;
            return;
        }
        File.WriteAllText(path, WorkerScriptEditor.Text);
        WorkerScriptPathText.Text = path;
        StatusText.Text = "Saved local worker copy";
    }

    private void CloneWorkerScript_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord source)
        {
            StatusText.Text = "Select a worker script first";
            return;
        }
        var cloneId = NormalizeScriptId(CloneScriptIdBox.Text);
        if (string.IsNullOrWhiteSpace(cloneId))
        {
            StatusText.Text = "Clone id required";
            return;
        }
        if (_workerScripts.Any(script => string.Equals(script.ScriptId, cloneId, StringComparison.OrdinalIgnoreCase)))
        {
            StatusText.Text = "Clone id already exists";
            return;
        }
        var sourcePath = TryGetWorkerScriptPath(source, out var error);
        if (sourcePath == null)
        {
            StatusText.Text = error;
            return;
        }
        var cloneModule = "worker.scripts." + NormalizeModuleName(cloneId);
        var clonePath = TryGetWorkerScriptPath(cloneModule, out error);
        if (clonePath == null)
        {
            StatusText.Text = error;
            return;
        }
        if (File.Exists(clonePath))
        {
            StatusText.Text = "Clone file already exists";
            return;
        }
        var cloneText = string.IsNullOrWhiteSpace(WorkerScriptEditor.Text)
            ? File.ReadAllText(sourcePath)
            : WorkerScriptEditor.Text;
        File.WriteAllText(clonePath, cloneText);
        var cloneName = string.IsNullOrWhiteSpace(CloneDisplayNameBox.Text)
            ? source.DisplayName + " Copy"
            : CloneDisplayNameBox.Text.Trim();
        var clone = new WorkerScriptRecord(
            cloneId,
            cloneName,
            source.Source,
            cloneModule,
            source.Runtime,
            source.SourcePath,
            source.InputSchema,
            source.OutputSchema,
            false,
            false,
            source.TimeoutMs);
        _workerScripts.Add(clone);
        WorkerGrid.SelectedItem = clone;
        WorkerScriptEditor.Text = cloneText;
        SaveWorkerManifest_Click(sender, e);
        StatusText.Text = "Cloned worker script";
    }

    private void RemovePreparedWorkerScript_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord script)
        {
            StatusText.Text = "Select a prepared worker script first";
            return;
        }
        if (!IsPreparedWorkerScript(script))
        {
            StatusText.Text = "Only prepared Workshop scripts can be removed here";
            return;
        }
        var answer = MessageBox.Show(
            "Remove prepared script '" + script.ScriptId + "' and its imported copy, config, compatibility report, bridge instances, and assignments? The original Steam Workshop file will not be changed.",
            "Remove Prepared Script",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning);
        if (answer != MessageBoxResult.Yes)
        {
            StatusText.Text = "Remove prepared script canceled";
            return;
        }
        CleanupPreparedScriptArtifacts(script);
        LoadWorkshopCatalog();
        LoadWorkerScripts();
        LoadScriptInstances();
        LoadBridgeRegistry();
        RefreshLogs();
        StatusText.Text = "Removed prepared script: " + script.ScriptId;
    }

    private void CleanupPreparedScriptArtifacts(WorkerScriptRecord script)
    {
        var removedInstanceIds = RemoveScriptInstancesForBaseScript(script.ScriptId);
        RemoveScriptFromBridgeAssignments(script.ScriptId, removedInstanceIds);
        RemoveScriptFromCompatibilitySummary(script.ScriptId, removedInstanceIds);
        RemovePreparedScriptStateFiles(script.ScriptId, removedInstanceIds);
        RemovePreparedScriptQueueState(script.ScriptId, removedInstanceIds);
        RemoveScriptFromManifest(script.ScriptId);
        DeleteIfExists(WorkerConfigPath(script.ScriptId));
        DeleteWorkerScriptFileIfPrepared(script);
        var workshopId = WorkshopIdForPreparedScript(script);
        if (!string.IsNullOrWhiteSpace(workshopId))
        {
            DeleteDirectoryIfExists(Path.Combine(_root, "data", "imports", workshopId));
            MarkWorkshopRecordUnprepared(workshopId);
        }
    }

    private static bool IsPreparedWorkerScript(WorkerScriptRecord script)
    {
        return string.Equals(script.Source, "workshop_import", StringComparison.OrdinalIgnoreCase) ||
            script.ScriptId.StartsWith("workshop_", StringComparison.OrdinalIgnoreCase) ||
            script.ScriptId.StartsWith("virtual_workshop_", StringComparison.OrdinalIgnoreCase);
    }

    private void RemoveScriptFromManifest(string scriptId)
    {
        foreach (var script in _workerScripts.Where(script => string.Equals(script.ScriptId, scriptId, StringComparison.OrdinalIgnoreCase)).ToList())
        {
            _workerScripts.Remove(script);
        }
        SaveWorkerManifest_Click(this, new RoutedEventArgs());
    }

    private List<string> RemoveScriptInstancesForBaseScript(string baseScriptId)
    {
        var payload = LoadScriptInstancesPayload();
        var removed = payload.Instances
            .Where(item => string.Equals(item.Value.BaseScriptId, baseScriptId, StringComparison.OrdinalIgnoreCase))
            .Select(item => item.Key)
            .ToList();
        foreach (var instanceId in removed)
        {
            if (payload.Instances.TryGetValue(instanceId, out var instance))
            {
                DeleteIfExists(WorkerConfigPath(TextOrFallback(instance.ConfigId, instance.InstanceId)));
            }
            payload.Instances.Remove(instanceId);
        }
        if (removed.Count > 0)
        {
            SaveScriptInstancesPayload(payload);
        }
        return removed;
    }

    private void RemoveScriptFromBridgeAssignments(string scriptId, List<string> removedInstanceIds)
    {
        var removedIds = new HashSet<string>(removedInstanceIds, StringComparer.OrdinalIgnoreCase) { scriptId };
        var bridges = LoadBridgeRegistryPayload();
        var changedBridges = false;
        foreach (var bridge in bridges.Bridges.Values)
        {
            var originalCount = bridge.AllowedScriptInstanceIds.Count;
            bridge.AllowedScriptInstanceIds.RemoveAll(removedIds.Contains);
            if (removedIds.Contains(bridge.SelectedScriptInstanceId))
            {
                bridge.SelectedScriptInstanceId = "";
            }
            if (bridge.AllowedScriptInstanceIds.Count != originalCount)
            {
                bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
                changedBridges = true;
            }
        }
        if (changedBridges)
        {
            SaveBridgeRegistryPayload(bridges);
        }

        var assignments = LoadBridgeScriptsPayload();
        var changedAssignments = false;
        foreach (var bridgeId in assignments.Bridges.Keys.ToList())
        {
            var assignment = assignments.Bridges[bridgeId];
            var selectedScriptId = removedIds.Contains(assignment.SelectedScriptId) ? "" : assignment.SelectedScriptId;
            var allowed = assignment.AllowedWorkerScripts.Where(id => !removedIds.Contains(id)).ToList();
            var children = assignment.ChildWorkerScripts.Where(child => !removedIds.Contains(child.ScriptId)).ToList();
            if (!string.Equals(selectedScriptId, assignment.SelectedScriptId, StringComparison.OrdinalIgnoreCase) ||
                allowed.Count != assignment.AllowedWorkerScripts.Count ||
                children.Count != assignment.ChildWorkerScripts.Count)
            {
                assignments.Bridges[bridgeId] = new BridgeScriptAssignment(selectedScriptId, allowed, children, DateTime.UtcNow.ToString("o"));
                changedAssignments = true;
            }
        }
        if (changedAssignments)
        {
            var path = BridgeScriptsPath();
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(assignments, JsonOptions()));
        }
    }

    private void RemoveScriptFromCompatibilitySummary(string scriptId, List<string> removedInstanceIds)
    {
        var path = Path.Combine(_root, "data", "virtual_pb_compatibility.json");
        if (!File.Exists(path))
        {
            return;
        }
        var node = JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
        var scripts = node?["scripts"] as JsonObject;
        if (scripts == null)
        {
            return;
        }
        var removedIds = new HashSet<string>(removedInstanceIds, StringComparer.OrdinalIgnoreCase) { scriptId };
        var changed = false;
        foreach (var id in removedIds)
        {
            changed = scripts.Remove(id) || changed;
        }
        if (changed && node != null)
        {
            node["updated_at"] = DateTime.UtcNow.ToString("o");
            File.WriteAllText(path, node.ToJsonString(JsonOptions()) + Environment.NewLine);
        }
    }

    private void DeleteWorkerScriptFileIfPrepared(WorkerScriptRecord script)
    {
        var path = TryGetWorkerScriptPath(script, out _);
        if (path != null)
        {
            DeleteIfExists(path);
        }
    }

    private void RemovePreparedScriptStateFiles(string scriptId, List<string> removedInstanceIds)
    {
        var ids = new HashSet<string>(removedInstanceIds, StringComparer.OrdinalIgnoreCase) { scriptId };
        foreach (var folder in new[] { "autocrafting_blueprints", "virtual_pb_cache" })
        {
            var directory = Path.Combine(_root, "data", folder);
            if (!Directory.Exists(directory))
            {
                continue;
            }
            foreach (var file in Directory.EnumerateFiles(directory, "*.json"))
            {
                var name = Path.GetFileNameWithoutExtension(file);
                if (ids.Any(id => name.Contains(id, StringComparison.OrdinalIgnoreCase)))
                {
                    DeleteIfExists(file);
                }
            }
        }
    }

    private void RemovePreparedScriptQueueState(string scriptId, List<string> removedInstanceIds)
    {
        var ids = new HashSet<string>(removedInstanceIds, StringComparer.OrdinalIgnoreCase) { scriptId };
        var directory = Path.Combine(_root, "data", "command_queues");
        if (!Directory.Exists(directory))
        {
            return;
        }
        foreach (var file in Directory.EnumerateFiles(directory, "*.json"))
        {
            var node = JsonNode.Parse(File.ReadAllText(file)) as JsonObject;
            if (node == null)
            {
                continue;
            }
            var changed = RemoveMatchingQueueCommands(node["entries"] as JsonArray, ids);
            changed = RemoveMatchingQueueCommands(node["in_flight"] as JsonArray, ids) || changed;
            changed = RemoveMatchingDeliveredKeys(node["delivered"] as JsonObject, ids) || changed;
            if (changed)
            {
                node["updated_at"] = DateTime.UtcNow.ToString("o");
                File.WriteAllText(file, node.ToJsonString(JsonOptions()) + Environment.NewLine);
            }
        }
    }

    private static bool RemoveMatchingQueueCommands(JsonArray? commands, HashSet<string> ids)
    {
        if (commands == null)
        {
            return false;
        }
        var removed = false;
        for (var index = commands.Count - 1; index >= 0; index--)
        {
            if (NodeMentionsAnyId(commands[index], ids))
            {
                commands.RemoveAt(index);
                removed = true;
            }
        }
        return removed;
    }

    private static bool RemoveMatchingDeliveredKeys(JsonObject? delivered, HashSet<string> ids)
    {
        if (delivered == null)
        {
            return false;
        }
        var keys = delivered.Select(item => item.Key).Where(key => MentionsAnyId(key, ids)).ToList();
        foreach (var key in keys)
        {
            delivered.Remove(key);
        }
        return keys.Count > 0;
    }

    private static bool NodeMentionsAnyId(JsonNode? node, HashSet<string> ids)
    {
        if (node is JsonObject obj &&
            obj.TryGetPropertyValue("source_script_id", out var sourceScriptId) &&
            sourceScriptId != null &&
            ids.Contains(sourceScriptId.ToString()))
        {
            return true;
        }
        return node != null && MentionsAnyId(node.ToJsonString(), ids);
    }

    private static bool MentionsAnyId(string value, HashSet<string> ids)
    {
        return ids.Any(id => value.Contains(id, StringComparison.OrdinalIgnoreCase));
    }

    private string WorkshopIdForPreparedScript(WorkerScriptRecord script)
    {
        var workshopId = WorkshopIdFromScriptId(script.ScriptId);
        if (!string.IsNullOrWhiteSpace(workshopId))
        {
            return workshopId;
        }
        var virtualPrefix = "virtual_workshop_";
        if (script.ScriptId.StartsWith(virtualPrefix, StringComparison.OrdinalIgnoreCase))
        {
            return script.ScriptId[virtualPrefix.Length..];
        }
        var normalizedSource = script.SourcePath.Replace("\\", "/");
        var match = System.Text.RegularExpressions.Regex.Match(normalizedSource, @"data/imports/([^/]+)/Script\.cs$", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        return match.Success ? match.Groups[1].Value : "";
    }

    private void MarkWorkshopRecordUnprepared(string workshopId)
    {
        var path = Path.Combine(_root, "data", "workshop_catalog.json");
        if (!File.Exists(path))
        {
            return;
        }
        var node = JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
        var records = node?["records"] as JsonArray;
        if (records == null)
        {
            return;
        }
        foreach (var record in records.OfType<JsonObject>())
        {
            if (string.Equals((string?)record["workshop_id"], workshopId, StringComparison.OrdinalIgnoreCase))
            {
                record["compatibility"] = "manual_adapter_required";
                record["notes"] = "Prepared adapter removed; run Prepare Adapter to rebuild from the Workshop source.";
                File.WriteAllText(path, node!.ToJsonString(JsonOptions()) + Environment.NewLine);
                return;
            }
        }
    }

    private static void DeleteIfExists(string path)
    {
        if (File.Exists(path))
        {
            File.Delete(path);
        }
    }

    private static void DeleteDirectoryIfExists(string path)
    {
        if (Directory.Exists(path))
        {
            Directory.Delete(path, recursive: true);
        }
    }

    private void LoadWorkerConfig_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is WorkerScriptRecord script)
        {
            LoadWorkerConfig(script);
        }
    }

    private void VirtualPbCustomDataLoad_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is WorkerScriptRecord script)
        {
            LoadWorkerConfig(script);
            StatusText.Text = "Virtual PB CustomData loaded for " + script.ScriptId;
        }
    }

    private void VirtualPbCustomDataPaste_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            VirtualPbCustomDataBox.Text = Clipboard.GetText();
            SyncVirtualPbCustomDataEntryFromUi();
            StatusText.Text = "Virtual PB CustomData pasted; save to persist";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Clipboard unavailable: " + ex.Message;
        }
    }

    private void SaveVirtualPbCustomData_Click(object sender, RoutedEventArgs e)
    {
        SaveWorkerConfig_Click(sender, e);
    }

    private void VirtualPbCustomDataClear_Click(object sender, RoutedEventArgs e)
    {
        VirtualPbCustomDataBox.Text = "";
        SyncVirtualPbCustomDataEntryFromUi();
        StatusText.Text = "Virtual PB CustomData cleared; save config to persist";
    }

    private void LoadWorkerConfig(WorkerScriptRecord script)
    {
        _workerConfigEntries.Clear();
        VirtualPbCustomDataBox.Text = "";
        var path = WorkerConfigPath(script.ScriptId);
        if (!File.Exists(path))
        {
            StatusText.Text = "No config file for " + script.ScriptId;
            return;
        }
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        if (!doc.RootElement.TryGetProperty("entries", out var entries))
        {
            return;
        }
        foreach (var item in entries.EnumerateArray())
        {
            _workerConfigEntries.Add(new WorkerConfigEntry(
                GetString(item, "key"),
                ValueToText(item.TryGetProperty("value", out var value) ? value : default),
                GetString(item, "value_type"),
                GetString(item, "description")));
        }
        EnsureInventorySortingConfigEntries();
        SyncInventorySortingUiFromEntries();
        SyncVirtualPbCustomDataUiFromEntries();
        StatusText.Text = "Loaded config for " + script.ScriptId;
    }

    private void SaveWorkerConfig_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord script)
        {
            StatusText.Text = "Select a worker script first";
            return;
        }
        SyncInventorySortingEntriesFromUi();
        SyncVirtualPbCustomDataEntryFromUi();
        var payload = new WorkerConfigPayload(
            "novali.client_side_pb.worker_config.v1",
            script.ScriptId,
            script.DisplayName,
            _workerConfigEntries.Select(entry => new WorkerConfigManifestEntry(
                entry.Key,
                TextToValue(entry.ValueText, entry.ValueType),
                entry.ValueType,
                entry.Description)).ToList());
        var path = WorkerConfigPath(script.ScriptId);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
        StatusText.Text = "Saved config for " + script.ScriptId + "; Virtual PB CustomData saved";
        RefreshLogs();
    }

    private async void ExtractWorkerConfig_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is not WorkerScriptRecord script)
        {
            StatusText.Text = "Select a worker script first";
            return;
        }
        var workshopId = WorkshopIdFromScriptId(script.ScriptId);
        if (string.IsNullOrWhiteSpace(workshopId))
        {
            StatusText.Text = "Config extraction is available for workshop adapters";
            return;
        }
        var source = Path.Combine(_root, "data", "imports", workshopId, "Script.cs");
        if (!File.Exists(source))
        {
            StatusText.Text = "Imported Script.cs not found";
            return;
        }
        var output = Path.Combine(_root, "data", "worker_configs", script.ScriptId + ".json");
        StatusText.Text = "Extracting config...";
        LogOutput.Text = await RunProcess(
            "python",
            "-m workshop.config_extractor --source " + QuoteArg(source) +
            " --script-id " + QuoteArg(script.ScriptId) +
            " --display-name " + QuoteArg(script.DisplayName) +
            " --output " + QuoteArg(output));
        LoadWorkerConfig(script);
        StatusText.Text = "Config extracted";
    }

    private void EnsureInventorySortingConfigEntries()
    {
        EnsureWorkerConfigEntry("inventorySortingEnabled", "true", "bool", "Enable Isy inventory sorting command planning for this worker.");
        EnsureWorkerConfigEntry("inventorySortingDryRun", "false", "bool", "Report planned sorting commands without applying them.");
        EnsureWorkerConfigEntry("maxApplyCommands", "8", "int", "Maximum commands the PB shim may apply from one result when runtime budget allows.");
        EnsureWorkerConfigEntry("maxPlannedTransfers", "16", "int", "Maximum transfer or rename commands the worker plans per tick.");
        EnsureWorkerConfigEntry("maxPlannedMachineCommands", "12", "int", "Maximum machine, LCD, and setup commands planned per tick.");
        EnsureWorkerConfigEntry("allowConnectedGrids", "false", "bool", "Allow planning and applying commands across connected grids.");
    }

    private void EnsureWorkerConfigEntry(string key, string valueText, string valueType, string description)
    {
        if (_workerConfigEntries.Any(entry => string.Equals(entry.Key, key, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }
        _workerConfigEntries.Insert(0, new WorkerConfigEntry(key, valueText, valueType, description));
    }

    private void SyncInventorySortingUiFromEntries()
    {
        InventorySortingEnabledBox.IsChecked = GetConfigBool("inventorySortingEnabled", true);
        InventorySortingDryRunBox.IsChecked = GetConfigBool("inventorySortingDryRun", false);
        AllowConnectedGridsBox.IsChecked = GetConfigBool("allowConnectedGrids", false);
        MaxApplyCommandsBox.Text = GetConfigText("maxApplyCommands", "8");
        MaxPlannedTransfersBox.Text = GetConfigText("maxPlannedTransfers", "16");
    }

    private void SyncInventorySortingEntriesFromUi()
    {
        EnsureInventorySortingConfigEntries();
        SetConfigText("inventorySortingEnabled", InventorySortingEnabledBox.IsChecked == true ? "true" : "false");
        SetConfigText("inventorySortingDryRun", InventorySortingDryRunBox.IsChecked == true ? "true" : "false");
        SetConfigText("allowConnectedGrids", AllowConnectedGridsBox.IsChecked == true ? "true" : "false");
        SetConfigText("maxApplyCommands", string.IsNullOrWhiteSpace(MaxApplyCommandsBox.Text) ? "8" : MaxApplyCommandsBox.Text.Trim());
        SetConfigText("maxPlannedTransfers", string.IsNullOrWhiteSpace(MaxPlannedTransfersBox.Text) ? "16" : MaxPlannedTransfersBox.Text.Trim());
    }

    private void SyncVirtualPbCustomDataUiFromEntries()
    {
        VirtualPbCustomDataBox.Text = GetConfigText("virtualPbCustomData", "");
    }

    private void SyncVirtualPbCustomDataEntryFromUi()
    {
        EnsureWorkerConfigEntry(
            "virtualPbCustomData",
            "",
            "multiline_text",
            "Virtual PB CustomData, including Isy-style itemID;blueprintID mappings used by scripts that read Me.CustomData.");
        SetConfigText("virtualPbCustomData", VirtualPbCustomDataBox.Text ?? "");
    }

    private bool GetConfigBool(string key, bool fallback)
    {
        var text = GetConfigText(key, fallback ? "true" : "false");
        return bool.TryParse(text, out var value) ? value : fallback;
    }

    private string GetConfigText(string key, string fallback)
    {
        return _workerConfigEntries.FirstOrDefault(entry => string.Equals(entry.Key, key, StringComparison.OrdinalIgnoreCase))?.ValueText ?? fallback;
    }

    private void SetConfigText(string key, string value)
    {
        var entry = _workerConfigEntries.FirstOrDefault(item => string.Equals(item.Key, key, StringComparison.OrdinalIgnoreCase));
        if (entry != null)
        {
            entry.ValueText = value;
        }
    }

    private string WorkerConfigPath(string scriptId) => Path.Combine(_root, "data", "worker_configs", scriptId + ".json");

    private static string WorkshopIdFromScriptId(string scriptId)
    {
        const string prefix = "workshop_";
        const string suffix = "_adapter";
        if (!scriptId.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
            !scriptId.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
        {
            return "";
        }
        return scriptId[prefix.Length..^suffix.Length];
    }

    private static string ValueToText(JsonElement value)
    {
        return value.ValueKind switch
        {
            JsonValueKind.Array => string.Join(", ", value.EnumerateArray().Select(ValueToText)),
            JsonValueKind.String => value.GetString() ?? "",
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            JsonValueKind.Number => value.ToString(),
            _ => ""
        };
    }

    private static object TextToValue(string value, string valueType)
    {
        if (string.Equals(valueType, "bool", StringComparison.OrdinalIgnoreCase))
        {
            return bool.TryParse(value, out var result) && result;
        }
        if (string.Equals(valueType, "int", StringComparison.OrdinalIgnoreCase))
        {
            return int.TryParse(value, out var result) ? result : 0;
        }
        if (string.Equals(valueType, "float", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(valueType, "double", StringComparison.OrdinalIgnoreCase))
        {
            return double.TryParse(value, out var result) ? result : 0.0;
        }
        if (string.Equals(valueType, "string_list", StringComparison.OrdinalIgnoreCase))
        {
            return value.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).ToList();
        }
        return value;
    }

    private static string QuoteArg(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private string? TryGetWorkerScriptPath(WorkerScriptRecord script, out string error)
    {
        return TryGetWorkerScriptPath(script.Module, out error);
    }

    private string? TryGetWorkerScriptPath(string module, out string error)
    {
        error = "";
        const string prefix = "worker.scripts.";
        if (!module.StartsWith(prefix, StringComparison.Ordinal))
        {
            error = "Only local worker.scripts modules can be edited";
            return null;
        }
        var moduleName = module[prefix.Length..];
        if (moduleName.Length == 0 || moduleName.Any(c => !(char.IsLetterOrDigit(c) || c == '_')))
        {
            error = "Worker script module name is not editable";
            return null;
        }
        var scriptsRoot = Path.GetFullPath(Path.Combine(_root, "worker", "scripts"));
        var path = Path.GetFullPath(Path.Combine(scriptsRoot, moduleName + ".py"));
        if (!path.StartsWith(scriptsRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        {
            error = "Worker script path escaped scripts folder";
            return null;
        }
        if (!File.Exists(path) && module.StartsWith(prefix, StringComparison.Ordinal))
        {
            Directory.CreateDirectory(scriptsRoot);
        }
        return path;
    }

    private static string NormalizeScriptId(string value)
    {
        var chars = value.Trim().Select(c => char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_').ToArray();
        return new string(chars).Trim('_');
    }

    private static string NormalizeModuleName(string scriptId)
    {
        var normalized = NormalizeScriptId(scriptId).Replace("-", "_");
        if (normalized.Length > 0 && char.IsDigit(normalized[0]))
        {
            normalized = "script_" + normalized;
        }
        return normalized;
    }

    private void SaveWorkerManifest_Click(object sender, RoutedEventArgs e)
    {
        var payload = new WorkerManifestPayload(
            "novali.client_side_pb.worker_manifest.v1",
            _workerScripts.Select(script => new WorkerScriptManifestRecord(
                script.ScriptId,
                script.Source,
                script.DisplayName,
                script.Module,
                script.Runtime,
                script.SourcePath,
                script.InputSchema,
                script.OutputSchema,
                script.TimeoutMs,
                script.Enabled)).ToList());
        var path = Path.Combine(_root, "worker", "manifest.json");
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
        StatusText.Text = "Worker manifest saved";
        RefreshLogs();
    }

    private void SaveBridgeScripts_Click(object sender, RoutedEventArgs e)
    {
        var bridgeId = CurrentWorkerBridgeId();
        if (string.IsNullOrWhiteSpace(bridgeId))
        {
            StatusText.Text = "Bridge id required";
            return;
        }
        var selectedScriptId = BridgeSelectedScriptBox.SelectedValue as string ?? "";
        foreach (var script in _workerScripts)
        {
            if (string.Equals(script.ScriptId, selectedScriptId, StringComparison.OrdinalIgnoreCase))
            {
                script.AllowedForBridge = true;
            }
        }
        var allowed = _workerScripts
            .Where(script => script.AllowedForBridge)
            .Select(script => script.ScriptId)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        var bridgeRegistry = LoadBridgeRegistryPayload();
        if (bridgeRegistry.Bridges.TryGetValue(bridgeId, out var bridge))
        {
            SyncBridgeInstancesFromAllowedBaseScripts(bridge, allowed);
            StatusText.Text = "Bridge script assignment saved as bridge instances";
            RefreshLogs();
            ShowBridgePbConfigPrompt("PB CustomData for saved bridge: " + bridgeId);
            return;
        }
        var payload = LoadBridgeScriptsPayload();
        payload.Bridges[bridgeId] = new BridgeScriptAssignment(
            selectedScriptId,
            allowed,
            BuildDefaultChildWorkerScripts(selectedScriptId, allowed),
            DateTime.UtcNow.ToString("o"));
        var path = BridgeScriptsPath();
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
        StatusText.Text = "Bridge script assignment saved";
        RefreshLogs();
        ShowBridgePbConfigPrompt("PB CustomData for saved bridge: " + bridgeId);
    }

    private void SyncBridgeInstancesFromAllowedBaseScripts(BridgeRegistryRecord bridge, List<string> allowedBaseScriptIds)
    {
        var payload = LoadScriptInstancesPayload();
        var childBaseScriptIds = allowedBaseScriptIds
            .Where(scriptId => !string.Equals(scriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            .Where(scriptId => !string.Equals(scriptId, bridge.Shim.SetupScriptId, StringComparison.OrdinalIgnoreCase))
            .Concat(ExistingChildBaseScriptIdsForBridge(bridge))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        var childInstanceIds = new List<string>();
        foreach (var baseScriptId in childBaseScriptIds)
        {
            var childInstanceId = BuildChildInstanceId(bridge.BridgeId, baseScriptId);
            var scriptName = _workerScripts.FirstOrDefault(script => string.Equals(script.ScriptId, baseScriptId, StringComparison.OrdinalIgnoreCase))?.DisplayName;
            CreateOrUpdateScriptInstance(
                payload,
                bridge.BridgeId,
                childInstanceId,
                baseScriptId,
                bridge.DisplayName + " - " + TextOrFallback(scriptName, baseScriptId),
                true);
            childInstanceIds.Add(childInstanceId);
        }
        var orchestratorInstanceId = EnsureBridgeOrchestratorInstance(payload, bridge);
        SaveScriptInstancesPayload(payload);
        bridge.SelectedScriptInstanceId = orchestratorInstanceId;
        bridge.AllowedScriptInstanceIds = new[] { orchestratorInstanceId }
            .Concat(childInstanceIds)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        bridge.UpdatedAt = DateTime.UtcNow.ToString("o");
        SaveBridgeRecord(bridge);
        LoadScriptInstances();
        LoadBridgeRegistry();
        LoadWorkerScripts();
        UpdateRunningInstancesText(bridge.BridgeId);
    }

    private static List<ChildWorkerScriptAssignment> BuildDefaultChildWorkerScripts(string selectedScriptId, List<string> allowed)
    {
        _ = ChildWorkerScriptsJsonField;
        if (!string.Equals(selectedScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
        {
            return new List<ChildWorkerScriptAssignment>();
        }
        return allowed
            .Where(scriptId => !string.Equals(scriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            .Select((scriptId, index) => new ChildWorkerScriptAssignment(
                scriptId,
                true,
                1,
                10 + index,
                RoleForScript(scriptId),
                IsReactiveScript(scriptId),
                ExpiresAfterSequencesForScript(scriptId),
                FairnessWeightForScript(scriptId),
                OperatorStatusForScript(scriptId)))
            .ToList();
    }

    private static string RoleForScript(string scriptId)
    {
        if (scriptId.Contains("whip", StringComparison.OrdinalIgnoreCase) || scriptId.Contains("416932930", StringComparison.OrdinalIgnoreCase))
        {
            return "reactive";
        }
        if (scriptId.Contains("lcd", StringComparison.OrdinalIgnoreCase) || scriptId.Contains("822950976", StringComparison.OrdinalIgnoreCase))
        {
            return "display";
        }
        if (scriptId.Contains("1216126863", StringComparison.OrdinalIgnoreCase) || scriptId.Contains("isy", StringComparison.OrdinalIgnoreCase))
        {
            return "maintenance";
        }
        return "worker";
    }

    private static bool IsReactiveScript(string scriptId) => RoleForScript(scriptId) == "reactive";

    private static int ExpiresAfterSequencesForScript(string scriptId) => IsReactiveScript(scriptId) ? 1 : 0;

    private static int FairnessWeightForScript(string scriptId) => IsReactiveScript(scriptId) ? 3 : 1;

    private static string OperatorStatusForScript(string scriptId)
    {
        if (scriptId.Contains("2831096030", StringComparison.OrdinalIgnoreCase))
        {
            return "blocked_needs_command_mapping";
        }
        if (scriptId.Contains("1216126863", StringComparison.OrdinalIgnoreCase) || scriptId.Contains("isy", StringComparison.OrdinalIgnoreCase))
        {
            return "ready_profile";
        }
        if (scriptId.Contains("416932930", StringComparison.OrdinalIgnoreCase) ||
            scriptId.Contains("822950976", StringComparison.OrdinalIgnoreCase) ||
            scriptId.Contains("virtual_", StringComparison.OrdinalIgnoreCase))
        {
            return "ready_virtual_pb";
        }
        return "manual_adapter_required";
    }

    private void ShowPbConfig_Click(object sender, RoutedEventArgs e)
    {
        var bridgeId = CurrentWorkerBridgeId();
        if (string.IsNullOrWhiteSpace(bridgeId))
        {
            StatusText.Text = "Bridge id required";
            return;
        }
        LogOutput.Text = BuildPbCustomData(bridgeId);
        ShowBridgePbConfigPrompt("PB CustomData for selected bridge: " + bridgeId);
        StatusText.Text = "PB config shown in Logs and Bridges tab";
    }

    private void CopyBridgePbConfig_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(BridgePbConfigBox.Text))
        {
            StatusText.Text = "No PB config to copy";
            return;
        }
        try
        {
            Clipboard.SetText(BridgePbConfigBox.Text);
            StatusText.Text = "PB config copied";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Clipboard unavailable: " + ex.Message;
        }
    }

    private void DismissBridgePbConfig_Click(object sender, RoutedEventArgs e)
    {
        BridgePbConfigPrompt.Visibility = Visibility.Collapsed;
    }

    private void ShowBridgePbConfigPrompt(string title)
    {
        if (BridgePbConfigPrompt == null || BridgePbConfigBox == null || BridgePbConfigPromptTitle == null)
        {
            return;
        }
        RefreshBridgePbConfigPromptText();
        if (string.IsNullOrWhiteSpace(BridgePbConfigBox.Text))
        {
            return;
        }
        BridgePbConfigPromptTitle.Text = title;
        BridgePbConfigPrompt.Visibility = Visibility.Visible;
    }

    private void RefreshBridgePbConfigPromptText()
    {
        if (BridgePbConfigPrompt == null ||
            BridgePbConfigBox == null ||
            BridgeSelectedScriptBox == null ||
            LimitMaxCommandsBox == null ||
            MaxApplyCommandsBox == null ||
            AllowConnectedGridsBox == null ||
            RuntimeMsLimitBox == null ||
            RuntimeMsSoftRatioBox == null ||
            CooldownSecondsBox == null ||
            LimitFailClosedCheckBox == null)
        {
            return;
        }
        var bridgeId = CurrentWorkerBridgeId();
        if (string.IsNullOrWhiteSpace(bridgeId))
        {
            BridgePbConfigBox.Text = "";
            BridgePbConfigPrompt.Visibility = Visibility.Collapsed;
            return;
        }
        var bridge = LoadBridgeRegistryPayload().Bridges.TryGetValue(bridgeId, out var existing)
            ? NormalizeBridgeRecord(existing)
            : null;
        BridgePbConfigBox.Text = bridge == null ? BuildPbCustomData(bridgeId) : BuildPbCustomData(bridge);
    }

    private string BuildPbCustomData(string bridgeId)
    {
        return string.Join(Environment.NewLine, new[]
        {
            "[NOVALI.ClientSidePB]",
            "bridge_id=" + bridgeId,
            "mailbox_mode=both",
            "text_panel_name=NOVALI PB Bridge",
            "script_id=" + CurrentSelectedScriptId(),
            "snapshot_mode=minimal",
            "max_commands_per_minute=" + TextOrFallback(LimitMaxCommandsBox?.Text, "60"),
            "max_apply_commands_per_tick=" + TextOrFallback(MaxApplyCommandsBox?.Text, "8"),
            "dynamic_apply_commands=true",
            "dynamic_min_apply_commands_per_tick=1",
            "dynamic_max_apply_commands_per_tick=8",
            "dynamic_runtime_low_ratio=0.45",
            "dynamic_runtime_high_ratio=0.75",
            "apply_worker_commands=true",
            "allow_connected_grid_commands=" + ((AllowConnectedGridsBox?.IsChecked == true) ? "true" : "false"),
            "runtime_ms_limit=" + TextOrFallback(RuntimeMsLimitBox?.Text, "0.25"),
            "runtime_ms_soft_ratio=" + TextOrFallback(RuntimeMsSoftRatioBox?.Text, "0.75"),
            "cooldown_seconds=" + TextOrFallback(CooldownSecondsBox?.Text, "3"),
            "fail_closed=" + ((LimitFailClosedCheckBox?.IsChecked == true) ? "true" : "false")
        });
    }

    private string BuildPbCustomData(BridgeRegistryRecord bridge)
    {
        var shim = bridge.Shim;
        var lines = new List<string>
        {
            "[NOVALI.ClientSidePB]",
            "bridge_id=" + bridge.BridgeId,
            "mailbox_mode=" + TextOrFallback(shim.MailboxMode, "both"),
            "text_panel_name=" + TextOrFallback(shim.TextPanelName, "NOVALI PB Bridge"),
            "script_id=" + BridgeScriptIdForShim(bridge),
            "verification_nonce=" + TextOrFallback(shim.VerificationNonce, NewNonce()),
            "snapshot_mode=" + TextOrFallback(shim.SnapshotMode, "minimal"),
            "max_commands_per_minute=" + shim.MaxCommandsPerMinute.ToString(),
            "max_apply_commands_per_tick=" + shim.MaxApplyCommandsPerTick.ToString(),
            "dynamic_apply_commands=true",
            "dynamic_min_apply_commands_per_tick=1",
            "dynamic_max_apply_commands_per_tick=8",
            "dynamic_runtime_low_ratio=0.45",
            "dynamic_runtime_high_ratio=0.75",
            "apply_worker_commands=" + (shim.ApplyWorkerCommands ? "true" : "false"),
            "allow_connected_grid_commands=" + (shim.AllowConnectedGridCommands ? "true" : "false"),
            "runtime_ms_limit=" + shim.RuntimeMsLimit.ToString("0.###"),
            "runtime_ms_soft_ratio=" + shim.RuntimeMsSoftRatio.ToString("0.###"),
            "cooldown_seconds=" + shim.CooldownSeconds.ToString(),
            "fail_closed=" + (shim.FailClosed ? "true" : "false")
        };
        lines.AddRange(BuildPbInstanceLabelLines(bridge));
        return string.Join(Environment.NewLine, lines);
    }

    private List<string> BuildPbInstanceLabelLines(BridgeRegistryRecord bridge)
    {
        var instances = LoadScriptInstancesPayload().Instances;
        var ids = bridge.AllowedScriptInstanceIds
            .Concat(new[] { BridgeScriptIdForShim(bridge) })
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => id, StringComparer.OrdinalIgnoreCase);
        return ids
            .Select(id =>
            {
                var label = instances.TryGetValue(id, out var instance)
                    ? CompactInstanceLabel(bridge, instance)
                    : id;
                return "instance_label." + id + "=" + CleanCustomDataValue(label);
            })
            .ToList();
    }

    private static string CompactInstanceLabel(BridgeRegistryRecord bridge, ScriptInstanceRecord instance)
    {
        var label = TextOrFallback(instance.DisplayName, instance.InstanceId);
        var prefix = TextOrFallback(bridge.DisplayName, bridge.BridgeId) + " - ";
        if (label.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            label = label.Substring(prefix.Length);
        }
        label = label
            .Replace(" (Virtual PB)", "", StringComparison.OrdinalIgnoreCase)
            .Replace(" Adapter", "", StringComparison.OrdinalIgnoreCase);
        if (label.Length > 34)
        {
            label = label.Substring(0, 31).TrimEnd() + "...";
        }
        return TextOrFallback(label, instance.InstanceId);
    }

    private static string CleanCustomDataValue(string value)
    {
        return (value ?? "").Replace("\r", " ").Replace("\n", " ").Trim();
    }

    private string BuildBridgePbShimScript(BridgeRegistryRecord bridge)
    {
        var sourcePath = Path.Combine(_root, "pb_shim", "ClientSidePBBridgeShim.cs");
        var source = File.ReadAllText(sourcePath);
        return source
            .Replace("string bridgeId = \"pb-bridge-001\";", "string bridgeId = \"" + EscapeCSharpString(bridge.BridgeId) + "\";")
            .Replace("string mailboxMode = \"both\";", "string mailboxMode = \"" + EscapeCSharpString(TextOrFallback(bridge.Shim.MailboxMode, "both")) + "\";")
            .Replace("string textPanelName = \"NOVALI PB Bridge\";", "string textPanelName = \"" + EscapeCSharpString(TextOrFallback(bridge.Shim.TextPanelName, "NOVALI PB Bridge")) + "\";")
            .Replace("string scriptId = \"sample_status_adapter\";", "string scriptId = \"" + EscapeCSharpString(BridgeScriptIdForShim(bridge)) + "\";")
            .Replace("string verificationNonce = \"\";", "string verificationNonce = \"" + EscapeCSharpString(TextOrFallback(bridge.Shim.VerificationNonce, NewNonce())) + "\";")
            .Replace("string snapshotMode = \"minimal\";", "string snapshotMode = \"" + EscapeCSharpString(TextOrFallback(bridge.Shim.SnapshotMode, "minimal")) + "\";");
    }

    private string BridgeScriptIdForShim(BridgeRegistryRecord bridge)
    {
        if (!string.IsNullOrWhiteSpace(bridge.SelectedScriptInstanceId))
        {
            return bridge.SelectedScriptInstanceId.Trim();
        }
        return TextOrFallback(bridge.Shim.SetupScriptId, "sample_status_adapter");
    }

    private BridgeVerificationRecord VerifyBridge(BridgeRegistryRecord bridge)
    {
        var requestPath = FindLatestBridgeRequestPath(bridge.BridgeId);
        var resultPath = Path.Combine(_root, "data", "bridge_results", bridge.BridgeId + ".json");
        var now = DateTime.UtcNow;
        var verification = new BridgeVerificationRecord
        {
            VerificationNonce = bridge.Shim.VerificationNonce,
            ShimVersion = ExpectedShimVersion,
            CheckedAt = now.ToString("o")
        };
        if (requestPath == null || !File.Exists(resultPath))
        {
            verification.LastError = "request_or_result_missing";
            return verification;
        }
        if (File.GetLastWriteTimeUtc(requestPath) < now.AddMinutes(-10) || File.GetLastWriteTimeUtc(resultPath) < now.AddMinutes(-10))
        {
            verification.LastError = "request_or_result_stale";
            return verification;
        }
        try
        {
            using var requestDoc = JsonDocument.Parse(File.ReadAllText(requestPath));
            using var resultDoc = JsonDocument.Parse(File.ReadAllText(resultPath));
            var requestRoot = requestDoc.RootElement;
            var resultRoot = resultDoc.RootElement;
            var requestState = requestRoot.TryGetProperty("state", out var state) ? state : default;
            var requestNonce = requestState.ValueKind == JsonValueKind.Object ? GetString(requestState, "verification_nonce") : "";
            var requestShimVersion = requestState.ValueKind == JsonValueKind.Object ? GetString(requestState, "shim_version") : "";
            var lastApply = requestState.ValueKind == JsonValueKind.Object && requestState.TryGetProperty("last_apply", out var apply)
                ? apply
                : default;
            var lastApplySequence = lastApply.ValueKind == JsonValueKind.Object ? GetInt(lastApply, "sequence") : 0;
            var lastApplyStatus = lastApply.ValueKind == JsonValueKind.Object ? GetString(lastApply, "status") : "";
            var sequence = GetInt(requestRoot, "sequence");
            var resultSequence = GetInt(resultRoot, "sequence");
            var resultStatus = GetString(resultRoot, "status");
            verification.LastSequence = resultSequence;
            verification.LastResultStatus = resultStatus;
            verification.ShimVersion = requestShimVersion;
            if (!string.Equals(GetString(requestRoot, "bridge_id"), bridge.BridgeId, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(GetString(resultRoot, "bridge_id"), bridge.BridgeId, StringComparison.OrdinalIgnoreCase))
            {
                verification.LastError = "bridge_id_mismatch";
                return verification;
            }
            if (!string.Equals(requestNonce, bridge.Shim.VerificationNonce, StringComparison.Ordinal))
            {
                verification.LastError = "verification_nonce_mismatch";
                return verification;
            }
            if (!string.Equals(requestShimVersion, ExpectedShimVersion, StringComparison.Ordinal))
            {
                verification.LastError = "shim_version_mismatch";
                return verification;
            }
            var currentResultMatches = sequence > 0 && resultSequence == sequence;
            var previousResultWasApplied = sequence > 0 &&
                resultSequence > 0 &&
                lastApplySequence == resultSequence &&
                string.Equals(lastApplyStatus, "processed", StringComparison.OrdinalIgnoreCase);
            if (!currentResultMatches && !previousResultWasApplied)
            {
                verification.LastError = resultSequence > 0 && resultSequence < sequence
                    ? "result_pending_for_request_sequence"
                    : "sequence_mismatch";
                return verification;
            }
            if (string.Equals(resultStatus, "rejected", StringComparison.OrdinalIgnoreCase))
            {
                verification.LastError = "worker_rejected:" + GetString(resultRoot, "error_bucket");
                return verification;
            }
            verification.Verified = true;
            verification.LastError = "none";
            return verification;
        }
        catch (JsonException)
        {
            verification.LastError = "invalid_json";
            return verification;
        }
    }

    private BridgeVerificationRecord VerifyBridgeWithWait(BridgeRegistryRecord bridge)
    {
        BridgeVerificationRecord verification = VerifyBridge(bridge);
        for (var attempt = 0; attempt < 8 && string.Equals(verification.LastError, "result_pending_for_request_sequence", StringComparison.OrdinalIgnoreCase); attempt++)
        {
            Thread.Sleep(250);
            verification = VerifyBridge(bridge);
        }
        return verification;
    }

    private static string BridgeVerificationOperatorMessage(BridgeVerificationRecord verification)
    {
        return verification.LastError switch
        {
            "result_pending_for_request_sequence" => "Run the in-game PB again or wait for the worker to process the latest request, then click Verify Bridge again.",
            "request_or_result_missing" => "No complete PB request/result loop was found yet. Run the in-game PB once, then verify.",
            "request_or_result_stale" => "The PB loop is stale. Move near the grid, run the PB again, then verify.",
            "verification_nonce_mismatch" => "The PB CustomData does not match this bridge. Copy PB CustomData again, paste it in-game, run the PB, then verify.",
            "shim_version_mismatch" => "The in-game PB shim is older than the manager expects. Copy PB Shim Script again, recompile it in-game, then verify.",
            "sequence_mismatch" => "The request/result sequence did not line up. Run the in-game PB again, wait for the worker result, then verify.",
            "none" => "none",
            _ => verification.LastError
        };
    }

    private string? FindLatestBridgeRequestPath(string bridgeId)
    {
        var active = Path.Combine(_root, "data", "bridge_requests", bridgeId + ".json");
        var candidates = new List<string>();
        if (File.Exists(active))
        {
            candidates.Add(active);
        }
        var processed = Path.Combine(_root, "data", "bridge_requests", "processed");
        if (Directory.Exists(processed))
        {
            candidates.AddRange(Directory.EnumerateFiles(processed, bridgeId + "-*.json"));
        }
        return candidates
            .OrderByDescending(File.GetLastWriteTimeUtc)
            .FirstOrDefault();
    }

    private void UpdateBridgeDiagnostics(string bridgeId)
    {
        if (BridgeDiagnosticsText == null)
        {
            return;
        }
        var requestPath = FindLatestBridgeRequestPath(bridgeId);
        var resultPath = Path.Combine(_root, "data", "bridge_results", bridgeId + ".json");
        var requestSummary = "request=missing";
        var resultSummary = "result=missing";
        var healthSummary = "health=unknown";
        if (requestPath != null)
        {
            try
            {
                using var doc = ReadBridgeDiagnosticJson(requestPath);
                var root = doc.RootElement;
                var state = root.TryGetProperty("state", out var stateElement) ? stateElement : default;
                var shimVersion = state.ValueKind == JsonValueKind.Object ? GetString(state, "shim_version") : "";
                var lastApply = state.ValueKind == JsonValueKind.Object && state.TryGetProperty("last_apply", out var applyElement)
                    ? applyElement
                    : default;
                var applyStatus = lastApply.ValueKind == JsonValueKind.Object ? GetString(lastApply, "status") : "";
                requestSummary = "request seq=" + GetInt(root, "sequence").ToString() +
                    " shim=" + TextOrFallback(shimVersion, "unknown") +
                    " last_apply=" + TextOrFallback(applyStatus, "unknown");
            }
            catch (JsonException)
            {
                requestSummary = "request=invalid_json";
            }
            catch (IOException)
            {
                requestSummary = "request=unavailable";
            }
            catch (UnauthorizedAccessException)
            {
                requestSummary = "request=unavailable";
            }
        }
        if (File.Exists(resultPath))
        {
            try
            {
                using var doc = ReadBridgeDiagnosticJson(resultPath);
                var root = doc.RootElement;
                resultSummary = "result seq=" + GetInt(root, "sequence").ToString() +
                    " status=" + TextOrFallback(GetString(root, "status"), "unknown") +
                    " error=" + TextOrFallback(GetString(root, "error_bucket"), "none");
            }
            catch (JsonException)
            {
                resultSummary = "result=invalid_json";
            }
            catch (IOException)
            {
                resultSummary = "result=unavailable";
            }
            catch (UnauthorizedAccessException)
            {
                resultSummary = "result=unavailable";
            }
        }
        var healthPath = Path.Combine(_root, "data", "bridge_health.json");
        if (File.Exists(healthPath))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(healthPath));
                if (doc.RootElement.TryGetProperty("bridges", out var bridges) &&
                    bridges.ValueKind == JsonValueKind.Object &&
                    bridges.TryGetProperty(bridgeId, out var health) &&
                    health.ValueKind == JsonValueKind.Object)
                {
                    healthSummary = "health=" + TextOrFallback(GetString(health, "status"), "unknown") +
                        " queue_policy=" + TextOrFallback(GetString(health, "queue_policy"), "unknown");
                }
            }
            catch (JsonException)
            {
                healthSummary = "health=invalid_json";
            }
        }
        BridgeDiagnosticsText.Text = "Bridge diagnostics: " + requestSummary + "; " + resultSummary + "; " + healthSummary;
    }

    private void UpdateRunningInstancesText(string bridgeId)
    {
        if (RunningInstancesText == null)
        {
            return;
        }
        var bridgeAssignments = LoadBridgeScriptsPayload();
        var instances = LoadScriptInstancesPayload().Instances;
        if (!bridgeAssignments.Bridges.TryGetValue(bridgeId, out var bridgeConfig))
        {
            RunningInstancesText.Text = "Currently running on this bridge: no worker assignment saved yet.";
            return;
        }
        var selected = DescribeInstanceForSummary(bridgeConfig.SelectedScriptId, instances);
        var childInstances = bridgeConfig.ChildWorkerScripts
            .Where(child => child.Enabled)
            .Select(child => DescribeInstanceForSummary(child.ScriptId, instances))
            .Where(text => !string.IsNullOrWhiteSpace(text))
            .ToList();
        var resultPath = Path.Combine(_root, "data", "bridge_results", bridgeId + ".json");
        var resultSummary = "";
        if (File.Exists(resultPath))
        {
            try
            {
                using var doc = ReadBridgeDiagnosticJson(resultPath);
                var root = doc.RootElement;
                var status = TextOrFallback(GetString(root, "status"), "unknown");
                var error = TextOrFallback(GetString(root, "error_bucket"), "none");
                resultSummary = " Last worker result: seq=" + GetInt(root, "sequence").ToString() +
                    " status=" + status + " error=" + error + ".";
                if (root.TryGetProperty("result", out var resultPayload) &&
                    resultPayload.ValueKind == JsonValueKind.Object &&
                    resultPayload.TryGetProperty("child_results", out var childResults) &&
                    childResults.ValueKind == JsonValueKind.Array)
                {
                    var childSummaries = childResults.EnumerateArray()
                        .Where(child => child.ValueKind == JsonValueKind.Object)
                        .Select(child =>
                        {
                            var childId = GetString(child, "script_id");
                            var childStatus = TextOrFallback(GetString(child, "status"), "unknown");
                            var childError = TextOrFallback(GetString(child, "error_bucket"), "none");
                            return DescribeInstanceName(childId, instances) + "=" + childStatus + "/" + childError;
                        })
                        .Where(text => !string.IsNullOrWhiteSpace(text))
                        .ToList();
                    if (childSummaries.Count > 0)
                    {
                        resultSummary += " Child results: " + string.Join("; ", childSummaries) + ".";
                    }
                }
                if (string.Equals(error, "script_not_allowed_for_bridge", StringComparison.OrdinalIgnoreCase))
                {
                    resultSummary += " The in-game PB is asking for a script_id that is not in the worker assignment; click Build Multi-Script Bridge, then copy PB CustomData again.";
                }
            }
            catch (JsonException)
            {
                resultSummary = " Last worker result: invalid JSON.";
            }
            catch (IOException)
            {
                resultSummary = " Last worker result: temporarily unavailable.";
            }
            catch (UnauthorizedAccessException)
            {
                resultSummary = " Last worker result: temporarily unavailable.";
            }
        }
        RunningInstancesText.Text = "Currently running on this bridge: selected runtime=" + selected +
            "; child instances=" + (childInstances.Count == 0 ? "none" : string.Join("; ", childInstances)) +
            "." + resultSummary;
    }

    private static string DescribeInstanceForSummary(string instanceId, Dictionary<string, ScriptInstanceRecord> instances)
    {
        if (instances.TryGetValue(instanceId, out var instance))
        {
            return instance.DisplayName + " [" + instance.InstanceId + "] base=" + instance.BaseScriptId +
                " enabled=" + (instance.Enabled ? "true" : "false");
        }
        return instanceId;
    }

    private static string DescribeInstanceName(string instanceId, Dictionary<string, ScriptInstanceRecord> instances)
    {
        return instances.TryGetValue(instanceId, out var instance)
            ? instance.DisplayName + " [" + instance.InstanceId + "]"
            : instanceId;
    }

    private static JsonDocument ReadBridgeDiagnosticJson(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        return JsonDocument.Parse(stream);
    }

    private void SaveBridgeRecord(BridgeRegistryRecord bridge)
    {
        var payload = LoadBridgeRegistryPayload();
        payload.Bridges[bridge.BridgeId] = bridge;
        SaveBridgeRegistryPayload(payload);
        SyncBridgeScriptAssignment(bridge);
    }

    private void SyncBridgeScriptAssignment(BridgeRegistryRecord bridge)
    {
        var selectedScriptId = BridgeScriptIdForShim(bridge);
        var allowed = bridge.AllowedScriptInstanceIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (!allowed.Contains(selectedScriptId, StringComparer.OrdinalIgnoreCase))
        {
            allowed.Add(selectedScriptId);
        }
        var payload = LoadBridgeScriptsPayload();
        payload.Bridges[bridge.BridgeId] = new BridgeScriptAssignment(
            selectedScriptId,
            allowed,
            BuildChildWorkerScriptsForBridge(selectedScriptId, allowed),
            DateTime.UtcNow.ToString("o"));
        var path = BridgeScriptsPath();
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
    }

    private List<ChildWorkerScriptAssignment> BuildChildWorkerScriptsForBridge(string selectedScriptId, List<string> allowed)
    {
        var instances = LoadScriptInstancesPayload().Instances;
        var selectedBaseScriptId = instances.TryGetValue(selectedScriptId, out var selectedInstance)
            ? selectedInstance.BaseScriptId
            : selectedScriptId;
        if (!(selectedBaseScriptId == BridgeOrchestratorScriptId) &&
            !string.Equals(selectedScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
        {
            return new List<ChildWorkerScriptAssignment>();
        }
        var childInstanceIds = allowed
            .Where(childInstanceId => !string.Equals(childInstanceId, selectedScriptId, StringComparison.OrdinalIgnoreCase))
            .Where(childInstanceId => !string.Equals(childInstanceId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            .Where(childInstanceId =>
            {
                if (!instances.TryGetValue(childInstanceId, out var childInstance))
                {
                    return string.Equals(selectedScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase);
                }
                return !string.Equals(childInstance.BaseScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase);
            })
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        return childInstanceIds
            .Select((childInstanceId, index) => new ChildWorkerScriptAssignment(
                childInstanceId,
                true,
                1,
                10 + index,
                RoleForScript(childInstanceId),
                IsReactiveScript(childInstanceId),
                ExpiresAfterSequencesForScript(childInstanceId),
                FairnessWeightForScript(childInstanceId),
                OperatorStatusForScript(childInstanceId)))
            .ToList();
    }

    private BridgeRegistryPayload LoadBridgeRegistryPayload()
    {
        var path = BridgesRegistryPath();
        if (!File.Exists(path))
        {
            return new BridgeRegistryPayload
            {
                Schema = "novali.client_side_pb.bridges.v1",
                Bridges = new Dictionary<string, BridgeRegistryRecord>(StringComparer.OrdinalIgnoreCase)
            };
        }
        try
        {
            var payload = JsonSerializer.Deserialize<BridgeRegistryPayload>(File.ReadAllText(path), JsonOptions());
            if (payload == null)
            {
                throw new JsonException();
            }
            payload.Schema = "novali.client_side_pb.bridges.v1";
            payload.Bridges ??= new Dictionary<string, BridgeRegistryRecord>(StringComparer.OrdinalIgnoreCase);
            return payload;
        }
        catch (JsonException)
        {
            return new BridgeRegistryPayload
            {
                Schema = "novali.client_side_pb.bridges.v1",
                Bridges = new Dictionary<string, BridgeRegistryRecord>(StringComparer.OrdinalIgnoreCase)
            };
        }
    }

    private void SaveBridgeRegistryPayload(BridgeRegistryPayload payload)
    {
        var path = BridgesRegistryPath();
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        payload.Schema = "novali.client_side_pb.bridges.v1";
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
    }

    private ScriptInstancesPayload LoadScriptInstancesPayload()
    {
        var path = ScriptInstancesPath();
        if (!File.Exists(path))
        {
            return new ScriptInstancesPayload
            {
                Schema = "novali.client_side_pb.script_instances.v1",
                Instances = new Dictionary<string, ScriptInstanceRecord>(StringComparer.OrdinalIgnoreCase)
            };
        }
        try
        {
            var payload = JsonSerializer.Deserialize<ScriptInstancesPayload>(File.ReadAllText(path), JsonOptions());
            if (payload == null)
            {
                throw new JsonException();
            }
            payload.Schema = "novali.client_side_pb.script_instances.v1";
            payload.Instances ??= new Dictionary<string, ScriptInstanceRecord>(StringComparer.OrdinalIgnoreCase);
            return payload;
        }
        catch (JsonException)
        {
            return new ScriptInstancesPayload
            {
                Schema = "novali.client_side_pb.script_instances.v1",
                Instances = new Dictionary<string, ScriptInstanceRecord>(StringComparer.OrdinalIgnoreCase)
            };
        }
    }

    private void SaveScriptInstancesPayload(ScriptInstancesPayload payload)
    {
        var path = ScriptInstancesPath();
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        payload.Schema = "novali.client_side_pb.script_instances.v1";
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
    }

    private BridgeRegistryRecord NormalizeBridgeRecord(BridgeRegistryRecord bridge)
    {
        var now = DateTime.UtcNow.ToString("o");
        bridge.BridgeId = NormalizeScriptId(TextOrFallback(bridge.BridgeId, "pb-bridge-001"));
        bridge.DisplayName = TextOrFallback(bridge.DisplayName, bridge.BridgeId);
        bridge.Status = TextOrFallback(bridge.Status, "created");
        bridge.Shim ??= new BridgeShimSettings();
        bridge.Shim.MailboxMode = TextOrFallback(bridge.Shim.MailboxMode, "both");
        bridge.Shim.TextPanelName = TextOrFallback(bridge.Shim.TextPanelName, "NOVALI PB Bridge");
        bridge.Shim.SnapshotMode = TextOrFallback(bridge.Shim.SnapshotMode, "minimal");
        bridge.Shim.SetupScriptId = TextOrFallback(bridge.Shim.SetupScriptId, "sample_status_adapter");
        bridge.Shim.VerificationNonce = TextOrFallback(bridge.Shim.VerificationNonce, NewNonce());
        if (bridge.Shim.MaxCommandsPerMinute <= 0 || bridge.Shim.MaxCommandsPerMinute == 30) bridge.Shim.MaxCommandsPerMinute = 60;
        if (bridge.Shim.MaxApplyCommandsPerTick <= 0 || bridge.Shim.MaxApplyCommandsPerTick == 1 || bridge.Shim.MaxApplyCommandsPerTick == 4) bridge.Shim.MaxApplyCommandsPerTick = 8;
        if (bridge.Shim.RuntimeMsLimit <= 0 || Math.Abs(bridge.Shim.RuntimeMsLimit - 0.3) < 0.0001) bridge.Shim.RuntimeMsLimit = 0.25;
        if (bridge.Shim.RuntimeMsSoftRatio <= 0) bridge.Shim.RuntimeMsSoftRatio = 0.75;
        if (bridge.Shim.CooldownSeconds <= 0 || bridge.Shim.CooldownSeconds == 10) bridge.Shim.CooldownSeconds = 3;
        bridge.Verification ??= new BridgeVerificationRecord();
        bridge.AllowedScriptInstanceIds ??= new List<string>();
        bridge.CreatedAt = TextOrFallback(bridge.CreatedAt, now);
        bridge.UpdatedAt = TextOrFallback(bridge.UpdatedAt, now);
        return bridge;
    }

    private ScriptInstanceRecord NormalizeScriptInstanceRecord(ScriptInstanceRecord instance)
    {
        var now = DateTime.UtcNow.ToString("o");
        instance.InstanceId = NormalizeScriptId(instance.InstanceId);
        instance.BaseScriptId = TextOrFallback(instance.BaseScriptId, "sample_status_adapter");
        instance.DisplayName = TextOrFallback(instance.DisplayName, instance.InstanceId);
        instance.ConfigId = TextOrFallback(instance.ConfigId, instance.InstanceId);
        instance.CreatedAt = TextOrFallback(instance.CreatedAt, now);
        instance.UpdatedAt = TextOrFallback(instance.UpdatedAt, now);
        return instance;
    }

    private string NextBridgeId()
    {
        var existing = new HashSet<string>(_bridges.Select(bridge => bridge.BridgeId), StringComparer.OrdinalIgnoreCase);
        for (var index = 1; index < 1000; index++)
        {
            var candidate = "pb-bridge-" + index.ToString("000");
            if (!existing.Contains(candidate))
            {
                return candidate;
            }
        }
        return "pb-bridge-" + DateTime.UtcNow.ToString("yyyyMMddHHmmss");
    }

    private static string NewNonce() => Guid.NewGuid().ToString("N")[..16];

    private static string SelectedComboText(ComboBox combo, string fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item && item.Content != null)
        {
            return item.Content.ToString() ?? fallback;
        }
        return string.IsNullOrWhiteSpace(combo.Text) ? fallback : combo.Text.Trim();
    }

    private static int GetLimitInt(string? text, int fallback)
    {
        return int.TryParse(text, out var value) && value > 0 ? value : fallback;
    }

    private static double GetLimitDouble(string? text, double fallback)
    {
        return double.TryParse(text, out var value) && value > 0 ? value : fallback;
    }

    private static string EscapeCSharpString(string value)
    {
        return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    private string CurrentSelectedScriptId()
    {
        var selectedScriptId = BridgeSelectedScriptBox?.SelectedValue as string;
        if (!string.IsNullOrWhiteSpace(selectedScriptId))
        {
            return selectedScriptId.Trim();
        }
        return _workerScripts.FirstOrDefault(script => script.Enabled)?.ScriptId ?? "sample_status_adapter";
    }

    private static string TextOrFallback(string? text, string fallback)
    {
        return string.IsNullOrWhiteSpace(text) ? fallback : text.Trim();
    }

    private void SetCurrentWorkerBridgeId(string bridgeId)
    {
        if (string.Equals(CurrentWorkerBridgeId(), bridgeId, StringComparison.OrdinalIgnoreCase))
        {
            ApplyBridgeScriptSelection();
            UpdateLatestWorkerSummary();
            RefreshBridgePbConfigPromptText();
            return;
        }
        WorkerBridgeIdBox.Text = bridgeId;
    }

    private void SelectBridgeFile(string bridgeId)
    {
        var match = _bridgeFiles.FirstOrDefault(record =>
            string.Equals(BridgeIdFromFileRecord(record), bridgeId, StringComparison.OrdinalIgnoreCase) &&
            record.Name.StartsWith("bridge_results/", StringComparison.OrdinalIgnoreCase));
        match ??= _bridgeFiles.FirstOrDefault(record =>
            string.Equals(BridgeIdFromFileRecord(record), bridgeId, StringComparison.OrdinalIgnoreCase));
        if (match == null)
        {
            return;
        }
        BridgeGrid.SelectedItem = match;
        BridgeGrid.ScrollIntoView(match);
    }

    private static string BridgeIdFromFileRecord(FileRecord record)
    {
        return Path.GetFileNameWithoutExtension(record.FullPath);
    }

    private string CurrentWorkerBridgeId() => WorkerBridgeIdBox.Text.Trim();

    private string BridgeScriptsPath() => Path.Combine(_root, "data", "bridge_scripts.json");

    private string BridgesRegistryPath() => Path.Combine(_root, "data", "bridges.json");

    private string ScriptInstancesPath() => Path.Combine(_root, "data", "script_instances.json");

    private BridgeScriptsPayload LoadBridgeScriptsPayload()
    {
        var path = BridgeScriptsPath();
        if (!File.Exists(path))
        {
            return new BridgeScriptsPayload(
                "novali.client_side_pb.bridge_scripts.v1",
                new Dictionary<string, BridgeScriptAssignment>(StringComparer.OrdinalIgnoreCase));
        }
        try
        {
            var payload = JsonSerializer.Deserialize<BridgeScriptsPayload>(File.ReadAllText(path), JsonOptions());
            return payload ?? new BridgeScriptsPayload(
                "novali.client_side_pb.bridge_scripts.v1",
                new Dictionary<string, BridgeScriptAssignment>(StringComparer.OrdinalIgnoreCase));
        }
        catch (JsonException)
        {
            return new BridgeScriptsPayload(
                "novali.client_side_pb.bridge_scripts.v1",
                new Dictionary<string, BridgeScriptAssignment>(StringComparer.OrdinalIgnoreCase));
        }
    }

    private void ApplyBridgeScriptSelection()
    {
        ApplyBridgeScriptSelection(LoadBridgeScriptsPayload());
    }

    private void ApplyBridgeScriptSelection(BridgeScriptsPayload payload)
    {
        if (WorkerBridgeIdBox == null || BridgeSelectedScriptBox == null)
        {
            return;
        }
        var bridgeId = CurrentWorkerBridgeId();
        payload.Bridges.TryGetValue(bridgeId, out var bridgeConfig);
        var allowedBaseScriptIds = bridgeConfig == null
            ? new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            : AllowedBaseScriptIdsForBridgeConfig(bridgeConfig);
        foreach (var script in _workerScripts)
        {
            script.AllowedForBridge = allowedBaseScriptIds.Contains(script.ScriptId);
        }
        BridgeSelectedScriptBox.SelectedValue = bridgeConfig == null
            ? _workerScripts.FirstOrDefault(script => script.Enabled)?.ScriptId ?? ""
            : (AllowedBaseScriptIdsForBridgeConfig(new BridgeScriptAssignment(
                bridgeConfig.SelectedScriptId,
                new List<string> { bridgeConfig.SelectedScriptId },
                new List<ChildWorkerScriptAssignment>(),
                "")).FirstOrDefault() ?? _workerScripts.FirstOrDefault(script => script.Enabled)?.ScriptId ?? "");
        RefreshBridgePbConfigPromptText();
    }

    private HashSet<string> AllowedBaseScriptIdsForBridgeConfig(BridgeScriptAssignment bridgeConfig)
    {
        var instances = LoadScriptInstancesPayload().Instances;
        var ids = bridgeConfig.AllowedWorkerScripts
            .Concat(new[] { bridgeConfig.SelectedScriptId })
            .Concat(bridgeConfig.ChildWorkerScripts.Select(child => child.ScriptId))
            .Where(scriptId => !string.IsNullOrWhiteSpace(scriptId))
            .Select(scriptId => instances.TryGetValue(scriptId, out var instance) ? instance.BaseScriptId : scriptId)
            .Where(scriptId => !string.Equals(scriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase));
        return new HashSet<string>(ids, StringComparer.OrdinalIgnoreCase);
    }

    private void BridgeSelectedScriptBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        RefreshBridgePbConfigPromptText();
    }

    private void LoadLimits_Click(object sender, RoutedEventArgs e) => LoadLimits();

    private void SaveLimits_Click(object sender, RoutedEventArgs e)
    {
        var parseResult = TryReadLimitProfileFromUi(out var profile);
        if (parseResult != "none")
        {
            LimitsOutput.Text = "Invalid limiter config: " + parseResult;
            StatusText.Text = "Limiter config invalid";
            return;
        }

        var payload = new BridgeLimitsPayload(
            "novali.client_side_pb.bridge_limits.v1",
            profile,
            new Dictionary<string, BridgeLimitProfile>());
        var path = LimitsPath();
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
        LimitsOutput.Text = File.ReadAllText(path);
        StatusText.Text = "Limiter profile saved";
        RefreshLogs();
    }

    private void LoadLimits()
    {
        var path = LimitsPath();
        BridgeLimitProfile profile;
        if (!File.Exists(path))
        {
            profile = BridgeLimitProfile.Default;
            var payload = new BridgeLimitsPayload(
                "novali.client_side_pb.bridge_limits.v1",
                profile,
                new Dictionary<string, BridgeLimitProfile>());
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions()));
        }
        using (var doc = JsonDocument.Parse(File.ReadAllText(path)))
        {
            profile = ReadLimitProfile(doc.RootElement.TryGetProperty("default", out var defaults) ? defaults : doc.RootElement);
        }
        RuntimeMsLimitBox.Text = profile.RuntimeMsLimit.ToString("0.######");
        RuntimeMsSoftRatioBox.Text = profile.RuntimeMsSoftRatio.ToString("0.######");
        CooldownSecondsBox.Text = profile.CooldownSeconds.ToString();
        LimitMaxCommandsBox.Text = profile.MaxCommandsPerMinute.ToString();
        LimitFailClosedCheckBox.IsChecked = profile.FailClosed;
        LimitsOutput.Text = File.ReadAllText(path);
        RefreshBridgePbConfigPromptText();
    }

    private string TryReadLimitProfileFromUi(out BridgeLimitProfile profile)
    {
        profile = BridgeLimitProfile.Default;
        if (!double.TryParse(RuntimeMsLimitBox.Text.Trim(), out var runtimeMsLimit))
        {
            return "runtime_ms_limit_invalid";
        }
        if (!double.TryParse(RuntimeMsSoftRatioBox.Text.Trim(), out var softRatio))
        {
            return "runtime_ms_soft_ratio_invalid";
        }
        if (!int.TryParse(CooldownSecondsBox.Text.Trim(), out var cooldownSeconds))
        {
            return "cooldown_seconds_invalid";
        }
        if (!int.TryParse(LimitMaxCommandsBox.Text.Trim(), out var maxCommandsPerMinute))
        {
            return "max_commands_per_minute_invalid";
        }

        profile = new BridgeLimitProfile(
            runtimeMsLimit,
            softRatio,
            cooldownSeconds,
            maxCommandsPerMinute,
            LimitFailClosedCheckBox.IsChecked == true);
        return ValidateLimitProfile(profile);
    }

    private static string ValidateLimitProfile(BridgeLimitProfile profile)
    {
        if (profile.RuntimeMsLimit < 0)
        {
            return "runtime_ms_limit_negative";
        }
        if (profile.RuntimeMsSoftRatio <= 0 || profile.RuntimeMsSoftRatio > 1)
        {
            return "runtime_ms_soft_ratio_out_of_range";
        }
        if (profile.CooldownSeconds < 0)
        {
            return "cooldown_seconds_negative";
        }
        if (profile.MaxCommandsPerMinute < 0)
        {
            return "max_commands_per_minute_negative";
        }
        return "none";
    }

    private BridgeLimitProfile ReadLimitProfile(JsonElement element)
    {
        return new BridgeLimitProfile(
            GetDouble(element, "runtime_ms_limit", BridgeLimitProfile.Default.RuntimeMsLimit),
            GetDouble(element, "runtime_ms_soft_ratio", BridgeLimitProfile.Default.RuntimeMsSoftRatio),
            GetInt(element, "cooldown_seconds", BridgeLimitProfile.Default.CooldownSeconds),
            GetInt(element, "max_commands_per_minute", BridgeLimitProfile.Default.MaxCommandsPerMinute),
            element.TryGetProperty("fail_closed", out var failClosed) && failClosed.ValueKind is JsonValueKind.True or JsonValueKind.False
                ? failClosed.GetBoolean()
                : BridgeLimitProfile.Default.FailClosed);
    }

    private string LimitsPath() => Path.Combine(_root, "data", "bridge_limits.json");

    private async void DockerStart_Click(object sender, RoutedEventArgs e)
    {
        DockerOutput.Text = await RunProcess("docker", "compose up --build -d");
    }

    private async void DockerStop_Click(object sender, RoutedEventArgs e)
    {
        DockerOutput.Text = await RunProcess("docker", "compose down");
    }

    private async void DockerStatus_Click(object sender, RoutedEventArgs e)
    {
        DockerOutput.Text = await RunProcess("docker", "compose ps");
    }

    private void RefreshLogs_Click(object sender, RoutedEventArgs e) => RefreshLogs();

    private void RefreshLogs()
    {
        var lines = new List<string>();
        foreach (var file in new[] { "plugin_status.json", "worker_status.json", "virtual_pb_compatibility.json", "discovery_report.json", "profile_pack.json", "bridge_limits.json", "bridge_scripts.json", "workshop_catalog.json" })
        {
            var path = Path.Combine(_root, "data", file);
            if (File.Exists(path))
            {
                lines.Add("== " + file + " ==");
                lines.Add(File.ReadAllText(path));
            }
        }
        LogOutput.Text = string.Join(Environment.NewLine, lines);
        UpdateLatestWorkerSummary();
    }

    private void UpdateLatestWorkerSummary()
    {
        if (LatestWorkerSummaryText == null || string.IsNullOrWhiteSpace(_root))
        {
            return;
        }
        var bridgeId = CurrentWorkerBridgeId();
        var path = Path.Combine(_root, "data", "bridge_results", bridgeId + ".json");
        if (string.IsNullOrWhiteSpace(bridgeId) || !File.Exists(path))
        {
            LatestWorkerSummaryText.Text = "Latest worker summary: no bridge result loaded.";
            return;
        }
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            var status = GetString(root, "status");
            var error = GetString(root, "error_bucket");
            var text = "Latest worker summary: status=" + status + "; error=" + error;
            if (root.TryGetProperty("result", out var result))
            {
                var summary = GetString(result, "summary");
                if (!string.IsNullOrWhiteSpace(summary))
                {
                    text += "; " + summary;
                }
                if (result.TryGetProperty("inventory_sorting", out var sorting))
                {
                    text += "; proposed=" + GetInt(sorting, "proposed_transfers", 0);
                    text += "; budget=" + GetInt(sorting, "applied_command_budget", 0);
                    if (sorting.TryGetProperty("skipped_reasons", out var skipped) && skipped.ValueKind == JsonValueKind.Object)
                    {
                        text += "; skipped=" + string.Join(",", skipped.EnumerateObject().Select(item => item.Name + ":" + item.Value));
                    }
                }
            }
            LatestWorkerSummaryText.Text = text;
        }
        catch (JsonException)
        {
            LatestWorkerSummaryText.Text = "Latest worker summary: result JSON invalid.";
        }
        catch (IOException)
        {
            LatestWorkerSummaryText.Text = "Latest worker summary: result file busy.";
        }
    }

    private Task<string> RunProcess(string fileName, string arguments)
    {
        return Task.Run(() =>
        {
            var start = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = _root,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var process = Process.Start(start);
            if (process == null)
            {
                return "Could not start " + fileName;
            }
            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            return output + (string.IsNullOrWhiteSpace(error) ? "" : Environment.NewLine + error);
        });
    }

    private static string GetString(JsonElement item, string name)
    {
        return item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    }

    private static bool GetBool(JsonElement item, string name)
    {
        return item.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False && value.GetBoolean();
    }

    private static int GetInt(JsonElement item, string name)
    {
        return item.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : 0;
    }

    private static int GetInt(JsonElement item, string name, int fallback)
    {
        return item.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : fallback;
    }

    private static double GetDouble(JsonElement item, string name, double fallback)
    {
        return item.TryGetProperty(name, out var value) && value.TryGetDouble(out var result) ? result : fallback;
    }

    private static JsonSerializerOptions JsonOptions()
    {
        return new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
        };
    }
}

public sealed record WorkshopRecord(
    string WorkshopId,
    string WorkshopTitle,
    string SourcePath,
    string SourceHash,
    string SteamLibrary,
    string TimeUpdated,
    string DetectedTitle,
    string DetectedKind,
    string Compatibility)
{
    public string HumanName => string.IsNullOrWhiteSpace(WorkshopTitle) ? DetectedTitle : WorkshopTitle;
    public string ShortHash => SourceHash.Length >= 12 ? SourceHash[..12] : SourceHash;
}

public sealed record FileRecord(string Name, string Updated, long Size, string FullPath);

public sealed class BridgeUiRecord
{
    public string BridgeId { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public string Status { get; set; } = "";
    public BridgeShimSettings Shim { get; set; } = new();
    public BridgeVerificationRecord Verification { get; set; } = new();
    public string SelectedScriptInstanceId { get; set; } = "";
    public List<string> AllowedScriptInstanceIds { get; set; } = new();
    public string CreatedAt { get; set; } = "";
    public string UpdatedAt { get; set; } = "";
    public string AllowedScriptInstanceIdsText => string.Join(", ", AllowedScriptInstanceIds);
    public string VerificationSummary => Verification.Verified
        ? "verified seq=" + Verification.LastSequence.ToString()
        : TextOrEmpty(Verification.LastError);

    public static BridgeUiRecord FromRecord(BridgeRegistryRecord record)
    {
        return new BridgeUiRecord
        {
            BridgeId = record.BridgeId,
            DisplayName = record.DisplayName,
            Status = record.Status,
            Shim = record.Shim,
            Verification = record.Verification,
            SelectedScriptInstanceId = record.SelectedScriptInstanceId,
            AllowedScriptInstanceIds = record.AllowedScriptInstanceIds,
            CreatedAt = record.CreatedAt,
            UpdatedAt = record.UpdatedAt
        };
    }

    private static string TextOrEmpty(string? value) => string.IsNullOrWhiteSpace(value) ? "" : value;
}

public sealed class ScriptInstanceUiRecord
{
    public string InstanceId { get; set; } = "";
    public string BaseScriptId { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public string BridgeId { get; set; } = "";
    public bool Enabled { get; set; }
    public string ConfigId { get; set; } = "";
    public string CreatedAt { get; set; } = "";
    public string UpdatedAt { get; set; } = "";

    public static ScriptInstanceUiRecord FromRecord(ScriptInstanceRecord record)
    {
        return new ScriptInstanceUiRecord
        {
            InstanceId = record.InstanceId,
            BaseScriptId = record.BaseScriptId,
            DisplayName = record.DisplayName,
            BridgeId = record.BridgeId,
            Enabled = record.Enabled,
            ConfigId = record.ConfigId,
            CreatedAt = record.CreatedAt,
            UpdatedAt = record.UpdatedAt
        };
    }
}

public sealed class WorkerScriptRecord : INotifyPropertyChanged
{
    private bool _enabled;
    private bool _allowedForBridge;

    public WorkerScriptRecord(
        string scriptId,
        string displayName,
        string source,
        string module,
        string runtime,
        string sourcePath,
        string inputSchema,
        string outputSchema,
        bool enabled,
        bool allowedForBridge,
        int timeoutMs)
    {
        ScriptId = scriptId;
        DisplayName = displayName;
        Source = source;
        Module = module;
        Runtime = string.IsNullOrWhiteSpace(runtime) ? "python" : runtime;
        SourcePath = sourcePath;
        InputSchema = inputSchema;
        OutputSchema = outputSchema;
        _enabled = enabled;
        _allowedForBridge = allowedForBridge;
        TimeoutMs = timeoutMs;
    }

    public string ScriptId { get; }
    public string DisplayName { get; }
    public string Source { get; }
    public string Module { get; }
    public string Runtime { get; }
    public string SourcePath { get; }
    public string InputSchema { get; }
    public string OutputSchema { get; }
    public int TimeoutMs { get; }

    public bool Enabled
    {
        get => _enabled;
        set
        {
            if (_enabled == value)
            {
                return;
            }
            _enabled = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Enabled)));
        }
    }

    public bool AllowedForBridge
    {
        get => _allowedForBridge;
        set
        {
            if (_allowedForBridge == value)
            {
                return;
            }
            _allowedForBridge = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(AllowedForBridge)));
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
}

public sealed record WorkerManifestPayload(
    string Schema,
    List<WorkerScriptManifestRecord> Scripts);

public sealed record WorkerScriptManifestRecord(
    string ScriptId,
    string Source,
    string DisplayName,
    string Module,
    string Runtime,
    string SourcePath,
    string InputSchema,
    string OutputSchema,
    int TimeoutMs,
    bool Enabled);

public sealed record BridgeScriptsPayload(
    string Schema,
    Dictionary<string, BridgeScriptAssignment> Bridges);

public sealed record BridgeScriptAssignment(
    string SelectedScriptId,
    List<string> AllowedWorkerScripts,
    List<ChildWorkerScriptAssignment> ChildWorkerScripts,
    string UpdatedAt);

public sealed record ChildWorkerScriptAssignment(
    string ScriptId,
    bool Enabled,
    int Budget,
    int Priority,
    string Role = "",
    bool Reactive = false,
    int ExpiresAfterSequences = 0,
    int FairnessWeight = 1,
    string OperatorStatus = "ok");

public sealed class BridgeRegistryPayload
{
    public string Schema { get; set; } = "novali.client_side_pb.bridges.v1";
    public Dictionary<string, BridgeRegistryRecord> Bridges { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public sealed class BridgeRegistryRecord
{
    public string BridgeId { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public string Status { get; set; } = "created";
    public BridgeShimSettings Shim { get; set; } = new();
    public BridgeVerificationRecord Verification { get; set; } = new();
    public string SelectedScriptInstanceId { get; set; } = "";
    public List<string> AllowedScriptInstanceIds { get; set; } = new();
    public string CreatedAt { get; set; } = "";
    public string UpdatedAt { get; set; } = "";
}

public sealed class BridgeShimSettings
{
    public string MailboxMode { get; set; } = "both";
    public string TextPanelName { get; set; } = "NOVALI PB Bridge";
    public string SnapshotMode { get; set; } = "minimal";
    public string SetupScriptId { get; set; } = "sample_status_adapter";
    public string VerificationNonce { get; set; } = "";
    public int MaxCommandsPerMinute { get; set; } = 60;
    public int MaxApplyCommandsPerTick { get; set; } = 8;
    public bool ApplyWorkerCommands { get; set; } = true;
    public bool AllowConnectedGridCommands { get; set; }
    public double RuntimeMsLimit { get; set; } = 0.25;
    public double RuntimeMsSoftRatio { get; set; } = 0.75;
    public int CooldownSeconds { get; set; } = 3;
    public bool FailClosed { get; set; } = true;
}

public sealed class BridgeVerificationRecord
{
    public bool Verified { get; set; }
    public string VerificationNonce { get; set; } = "";
    public string ShimVersion { get; set; } = "";
    public int LastSequence { get; set; }
    public string LastResultStatus { get; set; } = "";
    public string LastError { get; set; } = "";
    public string CheckedAt { get; set; } = "";
}

public sealed class ScriptInstancesPayload
{
    public string Schema { get; set; } = "novali.client_side_pb.script_instances.v1";
    public Dictionary<string, ScriptInstanceRecord> Instances { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public sealed class ScriptInstanceRecord
{
    public string InstanceId { get; set; } = "";
    public string BaseScriptId { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public string BridgeId { get; set; } = "";
    public bool Enabled { get; set; } = true;
    public string ConfigId { get; set; } = "";
    public string CreatedAt { get; set; } = "";
    public string UpdatedAt { get; set; } = "";
}

public sealed class WorkerConfigEntry : INotifyPropertyChanged
{
    private string _valueText;

    public WorkerConfigEntry(string key, string valueText, string valueType, string description)
    {
        Key = key;
        _valueText = valueText;
        ValueType = valueType;
        Description = description;
    }

    public string Key { get; }
    public string ValueType { get; }
    public string Description { get; }

    public string ValueText
    {
        get => _valueText;
        set
        {
            if (_valueText == value)
            {
                return;
            }
            _valueText = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ValueText)));
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
}

public sealed record WorkerConfigPayload(
    string Schema,
    string ScriptId,
    string DisplayName,
    List<WorkerConfigManifestEntry> Entries);

public sealed record WorkerConfigManifestEntry(
    string Key,
    object Value,
    string ValueType,
    string Description);

public sealed record BridgeLimitsPayload(
    string Schema,
    BridgeLimitProfile Default,
    Dictionary<string, BridgeLimitProfile> PerBridge);

public sealed record BridgeLimitProfile(
    double RuntimeMsLimit,
    double RuntimeMsSoftRatio,
    int CooldownSeconds,
    int MaxCommandsPerMinute,
    bool FailClosed)
{
    public static BridgeLimitProfile Default { get; } = new(0.03, 0.75, 10, 30, true);
}
