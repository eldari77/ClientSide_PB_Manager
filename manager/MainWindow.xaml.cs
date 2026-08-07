using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;

namespace NOVALI.ClientSidePBManager;

public partial class MainWindow : Window
{
    private const string BridgeOrchestratorScriptId = "bridge_orchestrator";
    private const string ChildWorkerScriptsJsonField = "child_worker_scripts";
    private readonly string _root;
    private readonly ObservableCollection<WorkshopRecord> _workshopRecords = new();
    private readonly ObservableCollection<FileRecord> _bridgeFiles = new();
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
        WorkerGrid.ItemsSource = _workerScripts;
        BridgeSelectedScriptBox.ItemsSource = _workerScripts;
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
        LoadBridgeFiles();
        LoadWorkerScripts();
        LoadLimits();
        RefreshLogs();
        StatusText.Text = "Ready";
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
                GetString(item, "compatibility")));
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
        StatusText.Text = "Adapter scaffold prepared";
    }

    private void RefreshFiles_Click(object sender, RoutedEventArgs e) => LoadBridgeFiles();

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

    private void LoadWorkerConfig_Click(object sender, RoutedEventArgs e)
    {
        if (WorkerGrid.SelectedItem is WorkerScriptRecord script)
        {
            LoadWorkerConfig(script);
        }
    }

    private void LoadWorkerConfig(WorkerScriptRecord script)
    {
        _workerConfigEntries.Clear();
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
        StatusText.Text = "Saved config for " + script.ScriptId;
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
        EnsureWorkerConfigEntry("maxApplyCommands", "1", "int", "Maximum commands the PB shim may apply from one result.");
        EnsureWorkerConfigEntry("maxPlannedTransfers", "8", "int", "Maximum transfer or rename commands the worker plans per tick.");
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
        MaxApplyCommandsBox.Text = GetConfigText("maxApplyCommands", "1");
        MaxPlannedTransfersBox.Text = GetConfigText("maxPlannedTransfers", "8");
    }

    private void SyncInventorySortingEntriesFromUi()
    {
        EnsureInventorySortingConfigEntries();
        SetConfigText("inventorySortingEnabled", InventorySortingEnabledBox.IsChecked == true ? "true" : "false");
        SetConfigText("inventorySortingDryRun", InventorySortingDryRunBox.IsChecked == true ? "true" : "false");
        SetConfigText("allowConnectedGrids", AllowConnectedGridsBox.IsChecked == true ? "true" : "false");
        SetConfigText("maxApplyCommands", string.IsNullOrWhiteSpace(MaxApplyCommandsBox.Text) ? "1" : MaxApplyCommandsBox.Text.Trim());
        SetConfigText("maxPlannedTransfers", string.IsNullOrWhiteSpace(MaxPlannedTransfersBox.Text) ? "8" : MaxPlannedTransfersBox.Text.Trim());
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

    private static List<ChildWorkerScriptAssignment> BuildDefaultChildWorkerScripts(string selectedScriptId, List<string> allowed)
    {
        _ = ChildWorkerScriptsJsonField;
        if (!string.Equals(selectedScriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
        {
            return new List<ChildWorkerScriptAssignment>();
        }
        return allowed
            .Where(scriptId => !string.Equals(scriptId, BridgeOrchestratorScriptId, StringComparison.OrdinalIgnoreCase))
            .Select((scriptId, index) => new ChildWorkerScriptAssignment(scriptId, true, 1, 10 + index))
            .ToList();
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
        BridgePbConfigBox.Text = BuildPbCustomData(bridgeId);
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
            "max_commands_per_minute=" + TextOrFallback(LimitMaxCommandsBox?.Text, "30"),
            "max_apply_commands_per_tick=" + TextOrFallback(MaxApplyCommandsBox?.Text, "1"),
            "apply_worker_commands=true",
            "allow_connected_grid_commands=" + ((AllowConnectedGridsBox?.IsChecked == true) ? "true" : "false"),
            "runtime_ms_limit=" + TextOrFallback(RuntimeMsLimitBox?.Text, "0.3"),
            "runtime_ms_soft_ratio=" + TextOrFallback(RuntimeMsSoftRatioBox?.Text, "0.75"),
            "cooldown_seconds=" + TextOrFallback(CooldownSecondsBox?.Text, "10"),
            "fail_closed=" + ((LimitFailClosedCheckBox?.IsChecked == true) ? "true" : "false")
        });
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
        foreach (var script in _workerScripts)
        {
            script.AllowedForBridge = bridgeConfig?.AllowedWorkerScripts.Contains(script.ScriptId, StringComparer.OrdinalIgnoreCase) == true;
        }
        BridgeSelectedScriptBox.SelectedValue = bridgeConfig?.SelectedScriptId ?? _workerScripts.FirstOrDefault(script => script.Enabled)?.ScriptId ?? "";
        RefreshBridgePbConfigPromptText();
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
        foreach (var file in new[] { "plugin_status.json", "worker_status.json", "virtual_pb_compatibility.json", "bridge_limits.json", "bridge_scripts.json", "workshop_catalog.json" })
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
    int Priority);

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
