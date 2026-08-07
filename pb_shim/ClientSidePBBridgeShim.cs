// NOVALI Client-Side PB Bridge Shim
//
// Paste this into a Space Engineers programmable block that you own or have
// permission to edit. The shim keeps server-side work intentionally tiny:
// config parsing, compact snapshots, mailbox IO, sequence checks, and compact
// command application.

const string Schema = "novali.client_side_pb_bridge.v1";
const string ShimVersion = "2026-05-20-iim-action-parity-v13-customdata";
const string Begin = "NOVALI_CLIENT_SIDE_PB_JSON_BEGIN";
const string End = "NOVALI_CLIENT_SIDE_PB_JSON_END";

string bridgeId = "pb-bridge-001";
string mailboxMode = "both";
string textPanelName = "NOVALI PB Bridge";
string scriptId = "sample_status_adapter";
string snapshotMode = "minimal";
int maxCommandsPerMinute = 30;
int maxApplyCommandsPerTick = 1;
bool dynamicApplyCommands = true;
int dynamicMinApplyCommandsPerTick = 1;
int dynamicMaxApplyCommandsPerTick = 4;
double dynamicRuntimeLowRatio = 0.45;
double dynamicRuntimeHighRatio = 0.75;
int dynamicApplyBudget = 1;
bool failClosed = true;
bool applyWorkerCommands = true;
bool allowConnectedGridCommands = false;
double runtimeMsLimit = 0.3;
double runtimeMsSoftRatio = 0.75;
int cooldownSeconds = 10;
DateTime limiterCooldownUntilUtc = DateTime.MinValue;
double maxRuntimeMs = 0.0;
string limiterState = "ok";
string lastCommandSkipReason = "";
bool lastResultWasStale = false;
int lastApplySequence = -1;
string lastApplyResultStatus = "none";
string lastApplyStatus = "none";
int lastApplyCommandCount = 0;
int lastApplyApplied = 0;
int lastApplySkipped = 0;
int lastApplyEchoed = 0;
string lastApplyLastSkip = "";
int sequence = 0;
DateTime lastRequestUtc = DateTime.MinValue;

public Program()
{
    Runtime.UpdateFrequency = UpdateFrequency.Update100;
    EnsureConfig();
    LoadConfig();
    LoadState();
}

public void Save()
{
    SaveState();
}

public void Main(string argument, UpdateType updateSource)
{
    Runtime.UpdateFrequency = UpdateFrequency.Update100;
    LoadConfig();
    CaptureRuntimeTelemetry();
    var command = (argument ?? "").Trim().ToLower();
    if (command == "reset")
    {
        sequence = SeedSequence();
        limiterCooldownUntilUtc = DateTime.MinValue;
        limiterState = "ok";
        SaveState();
        ClearMailboxText();
        Echo("NOVALI shim=" + ShimVersion + " reset_seq=" + sequence.ToString());
        return;
    }

    var mailboxText = ReadMailboxText();
    if (!string.IsNullOrWhiteSpace(mailboxText))
    {
        var messageKind = ExtractString(mailboxText, "message_kind");
        if (messageKind == "request")
        {
            Echo("NOVALI shim=" + ShimVersion + " request_pending=" + ExtractInt(mailboxText, "sequence").ToString());
            return;
        }
        if (messageKind == "result")
        {
            lastResultWasStale = false;
            ApplyResultIfCurrent(mailboxText);
            ClearMailboxText();
        }
        else
        {
            ClearMailboxText();
        }
    }

    if (!RuntimeLimiterAllowsRequest())
    {
        Echo("NOVALI bridge limiter: " + limiterState + " last_ms=" + Runtime.LastRunTimeMs.ToString("0.000000"));
        return;
    }

    if (!RateLimitAllowsRequest())
    {
        Echo("NOVALI bridge rate limited.");
        return;
    }

    sequence++;
    var request = BuildRequest();
    WriteMailboxText(request);
    lastRequestUtc = DateTime.UtcNow;
    SaveState();
    Echo("NOVALI shim=" + ShimVersion + " staged_seq=" + sequence.ToString());
}

void EnsureConfig()
{
    if (!Me.CustomData.Contains("[NOVALI.ClientSidePB]"))
    {
        Me.CustomData =
@"[NOVALI.ClientSidePB]
bridge_id=pb-bridge-001
mailbox_mode=both
text_panel_name=NOVALI PB Bridge
script_id=sample_status_adapter
snapshot_mode=minimal
max_commands_per_minute=30
max_apply_commands_per_tick=1
dynamic_apply_commands=true
dynamic_min_apply_commands_per_tick=1
dynamic_max_apply_commands_per_tick=4
dynamic_runtime_low_ratio=0.45
dynamic_runtime_high_ratio=0.75
apply_worker_commands=true
allow_connected_grid_commands=false
runtime_ms_limit=0.3
runtime_ms_soft_ratio=0.75
cooldown_seconds=10
fail_closed=true

" + Me.CustomData;
    }
    else if (Me.CustomData.Contains("runtime_ms_limit=0.03"))
    {
        Me.CustomData = Me.CustomData.Replace("runtime_ms_limit=0.03", "runtime_ms_limit=0.3");
    }
    EnsureConfigLine("dynamic_apply_commands", "dynamic_apply_commands=true");
    EnsureConfigLine("dynamic_min_apply_commands_per_tick", "dynamic_min_apply_commands_per_tick=1");
    EnsureConfigLine("dynamic_max_apply_commands_per_tick", "dynamic_max_apply_commands_per_tick=4");
    EnsureConfigLine("dynamic_runtime_low_ratio", "dynamic_runtime_low_ratio=0.45");
    EnsureConfigLine("dynamic_runtime_high_ratio", "dynamic_runtime_high_ratio=0.75");
}

void EnsureConfigLine(string key, string line)
{
    if (Me.CustomData.Contains(key + "="))
    {
        return;
    }
    var marker = "fail_closed=true";
    if (Me.CustomData.Contains(marker))
    {
        Me.CustomData = Me.CustomData.Replace(marker, marker + "\n" + line);
        return;
    }
    Me.CustomData = Me.CustomData.TrimEnd() + "\n" + line + "\n";
}

void LoadConfig()
{
    var lines = Me.CustomData.Split('\n');
    bool inSection = false;
    foreach (var raw in lines)
    {
        var line = raw.Trim();
        if (line == "[NOVALI.ClientSidePB]")
        {
            inSection = true;
            continue;
        }
        if (line.StartsWith("[") && line.EndsWith("]"))
        {
            inSection = false;
            continue;
        }
        if (!inSection || line.Length == 0 || line.StartsWith("#"))
        {
            continue;
        }
        var split = line.IndexOf('=');
        if (split <= 0)
        {
            continue;
        }
        var key = line.Substring(0, split).Trim();
        var value = line.Substring(split + 1).Trim();
        if (key == "bridge_id") bridgeId = value;
        if (key == "mailbox_mode") mailboxMode = value;
        if (key == "text_panel_name") textPanelName = value;
        if (key == "script_id") scriptId = value;
        if (key == "snapshot_mode") snapshotMode = value;
        if (key == "max_commands_per_minute") int.TryParse(value, out maxCommandsPerMinute);
        if (key == "max_apply_commands_per_tick") int.TryParse(value, out maxApplyCommandsPerTick);
        if (key == "dynamic_apply_commands") bool.TryParse(value, out dynamicApplyCommands);
        if (key == "dynamic_min_apply_commands_per_tick") int.TryParse(value, out dynamicMinApplyCommandsPerTick);
        if (key == "dynamic_max_apply_commands_per_tick") int.TryParse(value, out dynamicMaxApplyCommandsPerTick);
        if (key == "dynamic_runtime_low_ratio") double.TryParse(value, out dynamicRuntimeLowRatio);
        if (key == "dynamic_runtime_high_ratio") double.TryParse(value, out dynamicRuntimeHighRatio);
        if (key == "apply_worker_commands") bool.TryParse(value, out applyWorkerCommands);
        if (key == "allow_connected_grid_commands") bool.TryParse(value, out allowConnectedGridCommands);
        if (key == "runtime_ms_limit") double.TryParse(value, out runtimeMsLimit);
        if (key == "runtime_ms_soft_ratio") double.TryParse(value, out runtimeMsSoftRatio);
        if (key == "cooldown_seconds") int.TryParse(value, out cooldownSeconds);
        if (key == "fail_closed") bool.TryParse(value, out failClosed);
    }
}

void CaptureRuntimeTelemetry()
{
    var last = Runtime.LastRunTimeMs;
    if (last > maxRuntimeMs)
    {
        maxRuntimeMs = last;
    }
}

void LoadState()
{
    var lines = (Storage ?? "").Split('\n');
    foreach (var raw in lines)
    {
        var line = raw.Trim();
        var split = line.IndexOf('=');
        if (split <= 0)
        {
            continue;
        }
        var key = line.Substring(0, split).Trim();
        var value = line.Substring(split + 1).Trim();
        if (key == "sequence")
        {
            int storedSequence;
            if (int.TryParse(value, out storedSequence) && storedSequence > sequence)
            {
                sequence = storedSequence;
            }
        }
    }
}

void SaveState()
{
    Storage = "schema=" + Schema + "\n" +
        "shim_version=" + ShimVersion + "\n" +
        "sequence=" + sequence.ToString() + "\n";
}

bool RuntimeLimiterAllowsRequest()
{
    if (runtimeMsLimit == 0)
    {
        limiterState = "disabled";
        return true;
    }
    if (runtimeMsLimit < 0 || runtimeMsSoftRatio <= 0 || runtimeMsSoftRatio > 1 || cooldownSeconds < 0)
    {
        limiterState = "config_invalid";
        return !failClosed;
    }
    if (DateTime.UtcNow < limiterCooldownUntilUtc)
    {
        limiterState = "cooldown";
        return false;
    }

    var last = Runtime.LastRunTimeMs;
    if (last >= runtimeMsLimit)
    {
        limiterState = "cooldown";
        limiterCooldownUntilUtc = DateTime.UtcNow.AddSeconds(cooldownSeconds);
        return false;
    }
    if (last >= runtimeMsLimit * runtimeMsSoftRatio)
    {
        limiterState = "soft_limited";
        return false;
    }

    limiterState = "ok";
    return true;
}

bool RateLimitAllowsRequest()
{
    if (maxCommandsPerMinute <= 0)
    {
        return false;
    }
    var minSeconds = 60.0 / Math.Max(1, maxCommandsPerMinute);
    return (DateTime.UtcNow - lastRequestUtc).TotalSeconds >= minSeconds;
}

int SeedSequence()
{
    var epoch = new DateTime(2020, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    var seconds = (DateTime.UtcNow - epoch).TotalSeconds;
    if (seconds < 1)
    {
        return 1;
    }
    if (seconds > 2000000000)
    {
        return 2000000000;
    }
    return (int)seconds;
}

string BuildRequest()
{
    var blockCount = 0;
    var inventoryCount = 0;
    if (snapshotMode == "grid_summary")
    {
        var blocks = new List<IMyTerminalBlock>();
        GridTerminalSystem.GetBlocksOfType<IMyTerminalBlock>(blocks, b => b.CubeGrid == Me.CubeGrid);
        blockCount = blocks.Count;
        foreach (var block in blocks)
        {
            if (block.HasInventory)
            {
                inventoryCount++;
            }
        }
    }

    var json = "{" +
        Quote("schema") + ":" + Quote(Schema) + "," +
        Quote("message_kind") + ":" + Quote("request") + "," +
        Quote("bridge_id") + ":" + Quote(bridgeId) + "," +
        Quote("sequence") + ":" + sequence.ToString() + "," +
        Quote("script_id") + ":" + Quote(scriptId) + "," +
        Quote("request_kind") + ":" + Quote("adapter_tick") + "," +
        Quote("runtime_telemetry") + ":{" +
            Quote("last_runtime_ms") + ":" + Runtime.LastRunTimeMs.ToString("0.000000") + "," +
            Quote("max_runtime_ms") + ":" + maxRuntimeMs.ToString("0.000000") + "," +
            Quote("runtime_ms_limit") + ":" + runtimeMsLimit.ToString("0.000000") + "," +
            Quote("runtime_ms_soft_ratio") + ":" + runtimeMsSoftRatio.ToString("0.000000") + "," +
            Quote("dynamic_apply_commands") + ":" + (dynamicApplyCommands ? "true" : "false") + "," +
            Quote("dynamic_apply_budget") + ":" + dynamicApplyBudget.ToString() + "," +
            Quote("dynamic_apply_min") + ":" + dynamicMinApplyCommandsPerTick.ToString() + "," +
            Quote("dynamic_apply_max") + ":" + dynamicMaxApplyCommandsPerTick.ToString() + "," +
            Quote("current_instruction_count") + ":" + Runtime.CurrentInstructionCount.ToString() + "," +
            Quote("max_instruction_count") + ":" + Runtime.MaxInstructionCount.ToString() + "," +
            Quote("limiter_state") + ":" + Quote(limiterState) +
        "}," +
        Quote("state") + ":{" +
            Quote("shim_version") + ":" + Quote(ShimVersion) + "," +
            Quote("snapshot_mode") + ":" + Quote(snapshotMode) + "," +
            Quote("block_count") + ":" + blockCount.ToString() + "," +
            Quote("inventory_count") + ":" + inventoryCount.ToString() + "," +
            Quote("last_apply") + ":{" +
                Quote("sequence") + ":" + lastApplySequence.ToString() + "," +
                Quote("result_status") + ":" + Quote(lastApplyResultStatus) + "," +
                Quote("status") + ":" + Quote(lastApplyStatus) + "," +
                Quote("command_count") + ":" + lastApplyCommandCount.ToString() + "," +
                Quote("applied") + ":" + lastApplyApplied.ToString() + "," +
                Quote("skipped") + ":" + lastApplySkipped.ToString() + "," +
                Quote("echo") + ":" + lastApplyEchoed.ToString() + "," +
                Quote("last_skip") + ":" + Quote(lastApplyLastSkip) +
            "}" +
        "}" +
    "}";
    return Begin + "\n" + json + "\n" + End;
}

void WriteMailboxText(string text)
{
    if (mailboxMode == "customdata" || mailboxMode == "both")
    {
        Me.CustomData = ReplaceMarkedBlock(Me.CustomData, text);
    }
    if (mailboxMode == "text_panel" || mailboxMode == "both")
    {
        var panel = GridTerminalSystem.GetBlockWithName(textPanelName) as IMyTextPanel;
        if (panel != null)
        {
            panel.WriteText(text, false);
        }
        else if (failClosed)
        {
            Echo("NOVALI bridge text panel missing: " + textPanelName);
        }
    }
}

void ClearMailboxText()
{
    if (mailboxMode == "customdata" || mailboxMode == "both")
    {
        Me.CustomData = RemoveMarkedBlock(Me.CustomData);
    }
    if (mailboxMode == "text_panel" || mailboxMode == "both")
    {
        var panel = GridTerminalSystem.GetBlockWithName(textPanelName) as IMyTextPanel;
        if (panel != null)
        {
            panel.WriteText("", false);
        }
    }
}

string ReadMailboxText()
{
    if (mailboxMode == "customdata" || mailboxMode == "both")
    {
        if (Me.CustomData.Contains(Begin) && Me.CustomData.Contains(End))
        {
            return Me.CustomData;
        }
    }
    if (mailboxMode == "text_panel" || mailboxMode == "both")
    {
        var panel = GridTerminalSystem.GetBlockWithName(textPanelName) as IMyTextPanel;
        if (panel != null)
        {
            var text = panel.GetText();
            if (text.Contains(Begin) && text.Contains(End))
            {
                return text;
            }
        }
    }
    return "";
}

bool ApplyResultIfCurrent(string text)
{
    var messageKind = ExtractString(text, "message_kind");
    if (messageKind != "result")
    {
        return false;
    }
    var bridge = ExtractString(text, "bridge_id");
    var script = ExtractString(text, "script_id");
    var status = ExtractString(text, "status");
    var resultSequence = ExtractInt(text, "sequence");
    if (bridge != bridgeId || script != scriptId || resultSequence != sequence)
    {
        lastResultWasStale = true;
        RecordApplyTelemetry(resultSequence, status, "stale_result", 0, 0, 0, 0, "identity_or_sequence_mismatch");
        Echo("NOVALI bridge ignored non-current result.");
        return true;
    }
    Echo("NOVALI bridge result: " + status);
    var commandText = ExtractString(text, "text");
    if (!string.IsNullOrWhiteSpace(commandText) && text.IndexOf("\"commands\"") < 0)
    {
        Echo(commandText);
    }
    if (applyWorkerCommands)
    {
        var report = ApplyWorkerCommands(text, resultSequence, status);
        if (!string.IsNullOrWhiteSpace(report))
        {
            Echo(report);
        }
    }
    else
    {
        RecordApplyTelemetry(resultSequence, status, "apply_disabled", 0, 0, 0, 0, "");
    }
    return true;
}

void RecordApplyTelemetry(int resultSequence, string resultStatus, string status, int commandCount, int applied, int skipped, int echoed, string lastSkip)
{
    lastApplySequence = resultSequence;
    lastApplyResultStatus = resultStatus;
    lastApplyStatus = status;
    lastApplyCommandCount = commandCount;
    lastApplyApplied = applied;
    lastApplySkipped = skipped;
    lastApplyEchoed = echoed;
    lastApplyLastSkip = lastSkip;
}

string ApplyWorkerCommands(string resultText, int resultSequence, string resultStatus)
{
    lastCommandSkipReason = "";
    var resultBudget = ExtractInt(resultText, "max_apply_commands");
    var budget = ApplyCommandBudget(resultBudget);

    var commands = ExtractCommandObjects(resultText);
    var applied = 0;
    var skipped = 0;
    var echoed = 0;
    foreach (var command in commands)
    {
        var kind = ExtractString(command, "kind");
        if (kind == "echo")
        {
            var text = ExtractString(command, "text");
            if (!string.IsNullOrWhiteSpace(text))
            {
                Echo(text);
                echoed++;
            }
            continue;
        }
        if (applied >= budget)
        {
            lastCommandSkipReason = "budget";
            skipped++;
            continue;
        }
        if (kind == "transfer_item")
        {
            if (ApplyTransferItemCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "rename_block")
        {
            if (ApplyRenameBlockCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "write_text_surface")
        {
            if (ApplyWriteTextSurfaceCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "write_block_custom_data")
        {
            if (ApplyWriteBlockCustomDataCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_block_enabled")
        {
            if (ApplySetBlockEnabledCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_use_conveyor")
        {
            if (ApplySetUseConveyorCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_door_open")
        {
            if (ApplySetDoorOpenCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_light_color")
        {
            if (ApplySetLightColorCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_assembler_mode")
        {
            if (ApplySetAssemblerModeCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_assembler_cooperative_mode")
        {
            if (ApplySetAssemblerCooperativeModeCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "set_gas_auto_refill")
        {
            if (ApplySetGasAutoRefillCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "move_assembler_queue_item")
        {
            if (ApplyMoveAssemblerQueueItemCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "remove_assembler_queue_item")
        {
            if (ApplyRemoveAssemblerQueueItemCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "enqueue_assembler_blueprint")
        {
            if (ApplyEnqueueAssemblerBlueprintCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (kind == "clear_assembler_queue")
        {
            if (ApplyClearAssemblerQueueCommand(command))
            {
                applied++;
            }
            else
            {
                skipped++;
            }
            continue;
        }
        if (!string.IsNullOrWhiteSpace(kind))
        {
            lastCommandSkipReason = "unknown_kind:" + kind;
            skipped++;
        }
    }
    if (commands.Count == 0)
    {
        RecordApplyTelemetry(resultSequence, resultStatus, "no_commands", 0, 0, 0, 0, "");
        return "";
    }
    RecordApplyTelemetry(resultSequence, resultStatus, "processed", commands.Count, applied, skipped, echoed, lastCommandSkipReason);
    var report = "NOVALI bridge commands: applied=" + applied.ToString() + " skipped=" + skipped.ToString() + " echo=" + echoed.ToString();
    if (skipped > 0 && !string.IsNullOrWhiteSpace(lastCommandSkipReason))
    {
        report += " last_skip=" + lastCommandSkipReason;
    }
    return report;
}

int ApplyCommandBudget(int resultBudget)
{
    var hardMax = dynamicApplyCommands ? dynamicMaxApplyCommandsPerTick : maxApplyCommandsPerTick;
    if (resultBudget >= 0)
    {
        hardMax = Math.Min(hardMax, resultBudget);
    }
    if (hardMax <= 0)
    {
        dynamicApplyBudget = 0;
        return 0;
    }
    if (!dynamicApplyCommands)
    {
        return hardMax;
    }

    var minBudget = Math.Max(0, Math.Min(dynamicMinApplyCommandsPerTick, hardMax));
    if (dynamicApplyBudget <= 0)
    {
        dynamicApplyBudget = minBudget;
    }
    if (runtimeMsLimit <= 0)
    {
        dynamicApplyBudget = hardMax;
        return hardMax;
    }

    var lowRatio = dynamicRuntimeLowRatio;
    var highRatio = dynamicRuntimeHighRatio;
    if (lowRatio < 0 || highRatio <= 0 || highRatio < lowRatio)
    {
        lowRatio = 0.45;
        highRatio = 0.75;
    }
    var last = Runtime.LastRunTimeMs;
    var low = runtimeMsLimit * lowRatio;
    var high = runtimeMsLimit * highRatio;
    if (limiterState == "cooldown" || limiterState == "soft_limited" || last >= high)
    {
        dynamicApplyBudget = Math.Max(minBudget, dynamicApplyBudget - 1);
    }
    else if (last <= low)
    {
        dynamicApplyBudget = Math.Min(hardMax, dynamicApplyBudget + 1);
    }
    else
    {
        dynamicApplyBudget = Math.Min(dynamicApplyBudget, hardMax);
    }
    dynamicApplyBudget = Math.Max(minBudget, Math.Min(dynamicApplyBudget, hardMax));
    return dynamicApplyBudget;
}

bool ApplyTransferItemCommand(string command)
{
    var sourceId = ExtractLong(command, "source_entity_id");
    var destinationId = ExtractLong(command, "destination_entity_id");
    var sourceInventoryIndex = ExtractInt(command, "source_inventory_index");
    var destinationInventoryIndex = ExtractInt(command, "destination_inventory_index");
    var typeId = ExtractString(command, "item_type_id");
    var subtypeId = ExtractString(command, "item_subtype_id");
    var amount = ExtractDouble(command, "amount");
    if (sourceId == 0 || destinationId == 0 || sourceInventoryIndex < 0 || destinationInventoryIndex < 0 || amount <= 0)
    {
        lastCommandSkipReason = "transfer_invalid_fields";
        return false;
    }
    var sourceBlock = ResolveTerminalBlock(sourceId);
    var destinationBlock = ResolveTerminalBlock(destinationId);
    if (sourceBlock == null || destinationBlock == null || !sourceBlock.HasInventory || !destinationBlock.HasInventory)
    {
        lastCommandSkipReason = "transfer_block_missing";
        return false;
    }
    if (!allowConnectedGridCommands && (!sourceBlock.IsSameConstructAs(Me) || !destinationBlock.IsSameConstructAs(Me)))
    {
        lastCommandSkipReason = "transfer_connected_grid_blocked";
        return false;
    }
    var sourceInventory = sourceBlock.GetInventory(sourceInventoryIndex);
    var destinationInventory = destinationBlock.GetInventory(destinationInventoryIndex);
    if (sourceInventory == null || destinationInventory == null)
    {
        lastCommandSkipReason = "transfer_inventory_missing";
        return false;
    }
    var items = new List<MyInventoryItem>();
    sourceInventory.GetItems(items);
    for (var index = 0; index < items.Count; index++)
    {
        var item = items[index];
        if (!ItemTypeIdMatches(item.Type.TypeId, typeId) || item.Type.SubtypeId != subtypeId)
        {
            continue;
        }
        var available = (double)item.Amount;
        var moveAmount = Math.Min(amount, available);
        if (moveAmount <= 0)
        {
            lastCommandSkipReason = "transfer_amount_empty";
            return false;
        }
        if (!sourceInventory.CanTransferItemTo(destinationInventory, item.Type))
        {
            lastCommandSkipReason = "transfer_not_allowed";
            return false;
        }
        if (!destinationInventory.CanItemsBeAdded((VRage.MyFixedPoint)moveAmount, item.Type))
        {
            lastCommandSkipReason = "transfer_destination_full";
            return false;
        }
        VRage.MyFixedPoint? transferAmount = amount >= available ? (VRage.MyFixedPoint?)null : (VRage.MyFixedPoint)moveAmount;
        var moved = false;
        moved = sourceInventory.TransferItemTo(destinationInventory, item, transferAmount);
        if (!moved)
        {
            moved = sourceInventory.TransferItemTo(destinationInventory, index, null, true, transferAmount);
        }
        if (!moved)
        {
            lastCommandSkipReason = "transfer_failed";
            return false;
        }
        return true;
    }
    lastCommandSkipReason = "transfer_item_missing";
    return false;
}

bool ItemTypeIdMatches(string actual, string expected)
{
    if (actual == expected)
    {
        return true;
    }
    if (actual == null || expected == null)
    {
        return false;
    }
    return actual.EndsWith("_" + expected) || expected.EndsWith("_" + actual);
}

bool ApplyRenameBlockCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var newName = ExtractString(command, "new_name");
    var reason = ExtractString(command, "reason");
    if (blockId == 0 || string.IsNullOrWhiteSpace(newName) || newName.Length > 120 || reason != "auto_container_assignment")
    {
        lastCommandSkipReason = "rename_invalid_fields";
        return false;
    }
    var block = ResolveTerminalBlock(blockId);
    if (block == null)
    {
        lastCommandSkipReason = "rename_block_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !block.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "rename_connected_grid_blocked";
        return false;
    }
    if (!LooksLikeContainerAssignmentName(newName))
    {
        lastCommandSkipReason = "rename_name_rejected";
        return false;
    }
    block.CustomName = newName;
    return true;
}

bool ApplyWriteTextSurfaceCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var surfaceIndex = ExtractInt(command, "surface_index");
    var text = ExtractString(command, "text");
    var title = ExtractString(command, "title");
    var append = ExtractBool(command, "append");
    if (blockId == 0 || surfaceIndex < 0)
    {
        lastCommandSkipReason = "text_surface_invalid_fields";
        return false;
    }
    var block = ResolveTerminalBlock(blockId);
    if (block == null)
    {
        lastCommandSkipReason = "text_surface_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !block.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "text_surface_connected_grid_blocked";
        return false;
    }
    var provider = block as IMyTextSurfaceProvider;
    if (provider == null || surfaceIndex >= provider.SurfaceCount)
    {
        var panel = block as IMyTextPanel;
        if (panel == null || surfaceIndex != 0)
        {
            lastCommandSkipReason = "text_surface_missing";
            return false;
        }
        PrepareIsyTextSurface(panel);
        if (!string.IsNullOrWhiteSpace(title))
        {
            panel.WritePublicTitle(title);
        }
        panel.WriteText(text, append);
        return true;
    }
    var surface = provider.GetSurface(surfaceIndex);
    if (surface == null)
    {
        lastCommandSkipReason = "text_surface_missing";
        return false;
    }
    PrepareIsyTextSurface(surface);
    surface.WriteText(text, append);
    return true;
}

bool ApplyWriteBlockCustomDataCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var text = ExtractString(command, "text");
    var append = ExtractBool(command, "append");
    var reason = ExtractString(command, "reason");
    if (blockId == 0 || text.Length > 8000 || reason != "autocrafting_discovered_items")
    {
        lastCommandSkipReason = "custom_data_invalid_fields";
        return false;
    }
    var block = ResolveTerminalBlock(blockId);
    if (block == null)
    {
        lastCommandSkipReason = "custom_data_block_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !block.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "custom_data_connected_grid_blocked";
        return false;
    }
    if (append)
    {
        block.CustomData = block.CustomData + text;
    }
    else
    {
        block.CustomData = text;
    }
    return true;
}

void PrepareIsyTextSurface(IMyTextSurface surface)
{
    surface.Font = "Debug";
    surface.FontSize = 0.6f;
    surface.TextPadding = 2f;
    surface.Alignment = TextAlignment.LEFT;
    surface.ContentType = ContentType.TEXT_AND_IMAGE;
}

bool ApplySetBlockEnabledCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var enabled = ExtractBool(command, "enabled");
    if (blockId == 0)
    {
        lastCommandSkipReason = "block_enable_invalid_fields";
        return false;
    }
    var block = ResolveTerminalBlock(blockId);
    var functional = block as IMyFunctionalBlock;
    if (block == null || functional == null)
    {
        lastCommandSkipReason = "block_not_functional";
        return false;
    }
    if (!allowConnectedGridCommands && !block.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "block_enable_connected_grid_blocked";
        return false;
    }
    functional.Enabled = enabled;
    return true;
}

bool ApplySetUseConveyorCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var enabled = ExtractBool(command, "enabled");
    if (blockId == 0)
    {
        lastCommandSkipReason = "conveyor_invalid_fields";
        return false;
    }
    var block = ResolveTerminalBlock(blockId);
    if (block == null)
    {
        lastCommandSkipReason = "conveyor_property_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !block.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "conveyor_connected_grid_blocked";
        return false;
    }
    if (TrySetBoolTerminalProperty(block, "UseConveyorSystem", enabled))
    {
        return true;
    }
    if (TrySetBoolTerminalProperty(block, "UseConveyor", enabled))
    {
        return true;
    }
    lastCommandSkipReason = "conveyor_property_missing";
    return false;
}

bool TrySetBoolTerminalProperty(IMyTerminalBlock block, string propertyName, bool value)
{
    try
    {
        var property = block.GetProperty(propertyName);
        if (property == null)
        {
            return false;
        }
        block.SetValueBool(propertyName, value);
        return true;
    }
    catch
    {
        return false;
    }
}

bool ApplySetDoorOpenCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var open = ExtractBool(command, "open");
    var door = ResolveTerminalBlock(blockId) as IMyDoor;
    if (blockId == 0 || door == null)
    {
        lastCommandSkipReason = "door_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !door.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "door_connected_grid_blocked";
        return false;
    }
    try
    {
        if (open)
        {
            door.OpenDoor();
        }
        else
        {
            door.CloseDoor();
        }
        return true;
    }
    catch
    {
        lastCommandSkipReason = "door_open_failed";
        return false;
    }
}

bool ApplySetLightColorCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var light = ResolveTerminalBlock(blockId) as IMyLightingBlock;
    if (blockId == 0 || light == null)
    {
        lastCommandSkipReason = "light_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !light.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "light_connected_grid_blocked";
        return false;
    }
    try
    {
        light.Color = ExtractColor(command);
        return true;
    }
    catch
    {
        lastCommandSkipReason = "light_color_failed";
        return false;
    }
}

bool ApplySetAssemblerModeCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var mode = ExtractString(command, "mode").ToLower();
    var assembler = ResolveTerminalBlock(blockId) as IMyAssembler;
    if (blockId == 0 || assembler == null)
    {
        lastCommandSkipReason = "assembler_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !assembler.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "assembler_connected_grid_blocked";
        return false;
    }
    assembler.Mode = mode.Contains("dis") ? MyAssemblerMode.Disassembly : MyAssemblerMode.Assembly;
    return true;
}

bool ApplySetAssemblerCooperativeModeCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var enabled = ExtractBool(command, "enabled");
    var assembler = ResolveTerminalBlock(blockId) as IMyAssembler;
    if (blockId == 0 || assembler == null)
    {
        lastCommandSkipReason = "assembler_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !assembler.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "assembler_cooperative_connected_grid_blocked";
        return false;
    }
    try
    {
        assembler.CooperativeMode = enabled;
        return true;
    }
    catch
    {
        lastCommandSkipReason = "assembler_cooperative_failed";
        return false;
    }
}

bool ApplySetGasAutoRefillCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var enabled = ExtractBool(command, "enabled");
    if (blockId == 0)
    {
        lastCommandSkipReason = "gas_auto_refill_invalid_fields";
        return false;
    }
    var block = ResolveTerminalBlock(blockId);
    if (block == null)
    {
        lastCommandSkipReason = "gas_auto_refill_property_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !block.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "gas_auto_refill_connected_grid_blocked";
        return false;
    }
    if (TrySetBoolTerminalProperty(block, "AutoRefill", enabled))
    {
        return true;
    }
    if (TrySetBoolTerminalProperty(block, "AutoRefillBottles", enabled))
    {
        return true;
    }
    lastCommandSkipReason = "gas_auto_refill_property_missing";
    return false;
}

bool ApplyMoveAssemblerQueueItemCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var queueItemId = ExtractLong(command, "queue_item_id");
    var targetIndex = ExtractInt(command, "target_index");
    var assembler = ResolveTerminalBlock(blockId) as IMyAssembler;
    if (blockId == 0 || queueItemId < 0 || targetIndex < 0)
    {
        lastCommandSkipReason = "assembler_queue_move_invalid_fields";
        return false;
    }
    if (assembler == null)
    {
        lastCommandSkipReason = "assembler_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !assembler.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "assembler_queue_connected_grid_blocked";
        return false;
    }
    try
    {
        assembler.MoveQueueItemRequest((uint)queueItemId, targetIndex);
        return true;
    }
    catch
    {
        lastCommandSkipReason = "queue_move_failed";
        return false;
    }
}

bool ApplyRemoveAssemblerQueueItemCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var queueIndex = ExtractInt(command, "queue_index");
    var amount = ExtractDouble(command, "amount");
    var assembler = ResolveTerminalBlock(blockId) as IMyAssembler;
    if (blockId == 0 || queueIndex < 0 || amount <= 0)
    {
        lastCommandSkipReason = "assembler_queue_remove_invalid_fields";
        return false;
    }
    if (assembler == null)
    {
        lastCommandSkipReason = "assembler_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !assembler.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "assembler_queue_connected_grid_blocked";
        return false;
    }
    try
    {
        assembler.RemoveQueueItem(queueIndex, (VRage.MyFixedPoint)amount);
        return true;
    }
    catch
    {
        lastCommandSkipReason = "queue_remove_failed";
        return false;
    }
}

bool ApplyEnqueueAssemblerBlueprintCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var blueprintId = ExtractString(command, "blueprint_id");
    var amount = ExtractDouble(command, "amount");
    var assembler = ResolveTerminalBlock(blockId) as IMyAssembler;
    if (blockId == 0 || assembler == null)
    {
        lastCommandSkipReason = "assembler_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !assembler.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "assembler_connected_grid_blocked";
        return false;
    }
    if (string.IsNullOrWhiteSpace(blueprintId) || amount <= 0)
    {
        lastCommandSkipReason = "blueprint_invalid";
        return false;
    }
    MyDefinitionId blueprint;
    try
    {
        blueprint = MyDefinitionId.Parse(blueprintId);
    }
    catch
    {
        lastCommandSkipReason = "blueprint_invalid";
        return false;
    }
    try
    {
        assembler.AddQueueItem(blueprint, (VRage.MyFixedPoint)amount);
        return true;
    }
    catch
    {
        lastCommandSkipReason = "queue_failed";
        return false;
    }
}

bool ApplyClearAssemblerQueueCommand(string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var assembler = ResolveTerminalBlock(blockId) as IMyAssembler;
    if (blockId == 0 || assembler == null)
    {
        lastCommandSkipReason = "assembler_missing";
        return false;
    }
    if (!allowConnectedGridCommands && !assembler.IsSameConstructAs(Me))
    {
        lastCommandSkipReason = "assembler_connected_grid_blocked";
        return false;
    }
    try
    {
        assembler.ClearQueue();
        return true;
    }
    catch
    {
        lastCommandSkipReason = "queue_failed";
        return false;
    }
}

bool LooksLikeContainerAssignmentName(string name)
{
    return name.Contains("Ores") ||
        name.Contains("Ingots") ||
        name.Contains("Components") ||
        name.Contains("Tools") ||
        name.Contains("Ammo") ||
        name.Contains("Bottles") ||
        name.Contains("Food") ||
        name.Contains("Consumables") ||
        name.Contains("Special");
}

IMyTerminalBlock ResolveTerminalBlock(long entityId)
{
    var blocks = new List<IMyTerminalBlock>();
    GridTerminalSystem.GetBlocksOfType<IMyTerminalBlock>(blocks, block => block.EntityId == entityId);
    if (blocks.Count == 0)
    {
        return null;
    }
    return blocks[0];
}

List<string> ExtractCommandObjects(string text)
{
    var commands = new List<string>();
    var search = 0;
    while (search < text.Length)
    {
        var kindAt = text.IndexOf("\"kind\"", search);
        if (kindAt < 0)
        {
            break;
        }
        var start = text.LastIndexOf("{", kindAt);
        if (start < 0)
        {
            break;
        }
        var depth = 0;
        var inString = false;
        var escaped = false;
        for (var i = start; i < text.Length; i++)
        {
            var c = text[i];
            if (inString)
            {
                if (escaped)
                {
                    escaped = false;
                }
                else if (c == '\\')
                {
                    escaped = true;
                }
                else if (c == '"')
                {
                    inString = false;
                }
                continue;
            }
            if (c == '"')
            {
                inString = true;
                continue;
            }
            if (c == '{')
            {
                depth++;
                continue;
            }
            if (c == '}')
            {
                depth--;
                if (depth == 0)
                {
                    commands.Add(text.Substring(start, i - start + 1));
                    search = i + 1;
                    break;
                }
            }
        }
        if (search <= kindAt)
        {
            search = kindAt + 6;
        }
    }
    return commands;
}

string ReplaceMarkedBlock(string original, string replacement)
{
    var start = original.IndexOf(Begin);
    var end = original.IndexOf(End);
    if (start >= 0 && end > start)
    {
        end += End.Length;
        return original.Substring(0, start) + replacement + original.Substring(end);
    }
    return original.TrimEnd() + "\n\n" + replacement + "\n";
}

string RemoveMarkedBlock(string original)
{
    var start = original.IndexOf(Begin);
    var end = original.IndexOf(End);
    if (start >= 0 && end > start)
    {
        end += End.Length;
        return (original.Substring(0, start) + original.Substring(end)).TrimEnd() + "\n";
    }
    return original;
}

string Quote(string value)
{
    return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
}

string ExtractString(string text, string key)
{
    var needle = "\"" + key + "\"";
    var start = text.IndexOf(needle);
    if (start < 0) return "";
    start += needle.Length;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (start >= text.Length || text[start] != ':') return "";
    start++;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (start >= text.Length || text[start] != '"') return "";
    start++;
    var value = "";
    var escaped = false;
    for (var i = start; i < text.Length; i++)
    {
        var c = text[i];
        if (escaped)
        {
            if (c == 'n') value += "\n";
            else if (c == 'r') value += "\r";
            else if (c == 't') value += "\t";
            else if (c == 'b') value += "\b";
            else if (c == 'f') value += "\f";
            else if (c == '"' || c == '\\' || c == '/') value += c.ToString();
            else if (c == 'u' && i + 4 < text.Length)
            {
                try
                {
                    value += ((char)Convert.ToInt32(text.Substring(i + 1, 4), 16)).ToString();
                    i += 4;
                }
                catch
                {
                    value += "u";
                }
            }
            else
            {
                value += c.ToString();
            }
            escaped = false;
            continue;
        }
        if (c == '\\')
        {
            escaped = true;
            continue;
        }
        if (c == '"')
        {
            return value;
        }
        value += c.ToString();
    }
    return "";
}

int ExtractInt(string text, string key)
{
    var needle = "\"" + key + "\"";
    var start = text.IndexOf(needle);
    if (start < 0) return -1;
    start += needle.Length;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (start >= text.Length || text[start] != ':') return -1;
    start++;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    var endAt = start;
    while (endAt < text.Length && char.IsDigit(text[endAt]))
    {
        endAt++;
    }
    int value;
    return int.TryParse(text.Substring(start, endAt - start), out value) ? value : -1;
}

long ExtractLong(string text, string key)
{
    var needle = "\"" + key + "\"";
    var start = text.IndexOf(needle);
    if (start < 0) return 0;
    start += needle.Length;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (start >= text.Length || text[start] != ':') return 0;
    start++;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    var endAt = start;
    while (endAt < text.Length && (char.IsDigit(text[endAt]) || text[endAt] == '-'))
    {
        endAt++;
    }
    long value;
    return long.TryParse(text.Substring(start, endAt - start), out value) ? value : 0;
}

double ExtractDouble(string text, string key)
{
    var needle = "\"" + key + "\"";
    var start = text.IndexOf(needle);
    if (start < 0) return 0;
    start += needle.Length;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (start >= text.Length || text[start] != ':') return 0;
    start++;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    var endAt = start;
    while (endAt < text.Length && (char.IsDigit(text[endAt]) || text[endAt] == '.' || text[endAt] == '-'))
    {
        endAt++;
    }
    double value;
    return double.TryParse(text.Substring(start, endAt - start), out value) ? value : 0;
}

bool ExtractBool(string text, string key)
{
    var needle = "\"" + key + "\"";
    var start = text.IndexOf(needle);
    if (start < 0) return false;
    start += needle.Length;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (start >= text.Length || text[start] != ':') return false;
    start++;
    while (start < text.Length && char.IsWhiteSpace(text[start])) start++;
    if (text.Substring(start).StartsWith("true")) return true;
    if (text.Substring(start).StartsWith("false")) return false;
    if (start < text.Length && text[start] == '"')
    {
        start++;
        var endAt = text.IndexOf("\"", start);
        if (endAt < 0) return false;
        bool value;
        return bool.TryParse(text.Substring(start, endAt - start), out value) && value;
    }
    return false;
}

Color ExtractColor(string text)
{
    var color = ExtractObject(text, "color");
    var r = ClampByte(ExtractInt(color, "r"));
    var g = ClampByte(ExtractInt(color, "g"));
    var b = ClampByte(ExtractInt(color, "b"));
    var a = ExtractInt(color, "a");
    return new Color(r, g, b, a < 0 ? 255 : ClampByte(a));
}

string ExtractObject(string text, string key)
{
    var needle = "\"" + key + "\"";
    var start = text.IndexOf(needle);
    if (start < 0) return "";
    start = text.IndexOf("{", start + needle.Length);
    if (start < 0) return "";
    var depth = 0;
    for (var i = start; i < text.Length; i++)
    {
        if (text[i] == '{') depth++;
        if (text[i] == '}')
        {
            depth--;
            if (depth == 0)
            {
                return text.Substring(start, i - start + 1);
            }
        }
    }
    return "";
}

int ClampByte(int value)
{
    if (value < 0) return 0;
    if (value > 255) return 255;
    return value;
}
