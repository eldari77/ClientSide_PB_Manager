// NOVALI Client-Side PB Bridge Shim
//
// Paste this into a Space Engineers programmable block that you own or have
// permission to edit. The shim keeps server-side work intentionally tiny:
// config parsing, compact snapshots, mailbox IO, sequence checks, and compact
// command application.

const string Schema = "novali.client_side_pb_bridge.v1";
const string ShimVersion = "baseline-template-v1";
const string Begin = "NOVALI_CLIENT_SIDE_PB_JSON_BEGIN";
const string End = "NOVALI_CLIENT_SIDE_PB_JSON_END";

string bridgeId = "pb-bridge-001";
string mailboxMode = "both";
string textPanelName = "NOVALI PB Bridge";
string scriptId = "sample_status_adapter";
string verificationNonce = "";
bool sosAutomationEnabled = false;
string sosAutomationApprovalActionId = "";
string sosAutomationApprovalNonce = "";
int sosAutomationApprovalExpiresSequence = 0;
string snapshotMode = "minimal";
int maxCommandsPerMinute = 30;
int maxApplyCommandsPerTick = 8;
bool dynamicApplyCommands = true;
int dynamicMinApplyCommandsPerTick = 1;
int dynamicMaxApplyCommandsPerTick = 8;
double dynamicRuntimeLowRatio = 0.45;
double dynamicRuntimeHighRatio = 0.75;
int dynamicApplyBudget = 1;
bool includeTerminalMetadata = false;
bool failClosed = true;
bool applyWorkerCommands = true;
bool allowConnectedGridCommands = false;
double runtimeMsLimit = 0.25;
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
string lastApplyActionText = "";
string lastApplyActionTime = "";
string lastApplyActionAtUtc = "";
string consumedSosAutomationActionId = "";
string consumedSosAutomationApprovalNonce = "";
int consumedSosAutomationSequence = -1;
string lastSosAutomationActionId = "";
string lastSosAutomationApprovalNonce = "";
string lastSosAutomationOutcome = "none";
string lastSosAutomationRejectionReason = "";
int lastSosAutomationSequence = -1;
int lastReceivedSequence = -1;
string lastReceivedStatus = "none";
string lastResultCompletedAt = "";
int lastQueueTotal = 0;
int lastQueueDrained = 0;
int lastQueueRemaining = 0;
List<string> lastChildStatusLines = new List<string>();
Dictionary<string, string> instanceLabels = new Dictionary<string, string>();
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
        EchoOperatorStatus("reset seq " + sequence.ToString(), -1);
        return;
    }

    var mailboxText = ReadMailboxText();
    if (!string.IsNullOrWhiteSpace(mailboxText))
    {
        var messageKind = ExtractString(mailboxText, "message_kind");
        if (messageKind == "request")
        {
            EchoOperatorStatus("waiting for worker", ExtractInt(mailboxText, "sequence"));
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
        EchoOperatorStatus("limiter " + limiterState, -1);
        return;
    }

    if (!RateLimitAllowsRequest())
    {
        EchoOperatorStatus("rate limited", -1);
        return;
    }

    sequence++;
    var request = BuildRequest();
    WriteMailboxText(request);
    lastRequestUtc = DateTime.UtcNow;
    SaveState();
    EchoOperatorStatus("request staged", sequence);
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
verification_nonce=
sos_automation_enabled=false
sos_automation_approval_action_id=
sos_automation_approval_nonce=
sos_automation_approval_expires_sequence=0
snapshot_mode=minimal
max_commands_per_minute=30
max_apply_commands_per_tick=8
dynamic_apply_commands=true
dynamic_min_apply_commands_per_tick=1
dynamic_max_apply_commands_per_tick=8
dynamic_runtime_low_ratio=0.45
dynamic_runtime_high_ratio=0.75
include_terminal_metadata=false
apply_worker_commands=true
allow_connected_grid_commands=false
runtime_ms_limit=0.25
runtime_ms_soft_ratio=0.75
cooldown_seconds=10
fail_closed=true

" + Me.CustomData;
    }
    UpgradeLegacyConfigDefaults();
    EnsureConfigLine("dynamic_apply_commands", "dynamic_apply_commands=true");
    EnsureConfigLine("dynamic_min_apply_commands_per_tick", "dynamic_min_apply_commands_per_tick=1");
    EnsureConfigLine("dynamic_max_apply_commands_per_tick", "dynamic_max_apply_commands_per_tick=8");
    EnsureConfigLine("dynamic_runtime_low_ratio", "dynamic_runtime_low_ratio=0.45");
    EnsureConfigLine("dynamic_runtime_high_ratio", "dynamic_runtime_high_ratio=0.75");
    EnsureConfigLine("include_terminal_metadata", "include_terminal_metadata=false");
    EnsureConfigLine("verification_nonce", "verification_nonce=");
    EnsureConfigLine("sos_automation_enabled", "sos_automation_enabled=false");
    EnsureConfigLine("sos_automation_approval_action_id", "sos_automation_approval_action_id=");
    EnsureConfigLine("sos_automation_approval_nonce", "sos_automation_approval_nonce=");
    EnsureConfigLine("sos_automation_approval_expires_sequence", "sos_automation_approval_expires_sequence=0");
}

void UpgradeLegacyConfigDefaults()
{
    ReplaceLegacyConfigLine("max_commands_per_minute", "30", "60");
    ReplaceLegacyConfigLine("max_apply_commands_per_tick", "1", "8");
    ReplaceLegacyConfigLine("max_apply_commands_per_tick", "4", "8");
    ReplaceLegacyConfigLine("dynamic_max_apply_commands_per_tick", "4", "8");
    ReplaceLegacyConfigLine("runtime_ms_limit", "0.03", "0.25");
    ReplaceLegacyConfigLine("runtime_ms_limit", "0.3", "0.25");
    ReplaceLegacyConfigLine("runtime_ms_limit", "0.300000", "0.25");
    ReplaceLegacyConfigLine("cooldown_seconds", "10", "3");
}

void ReplaceLegacyConfigLine(string key, string oldValue, string newValue)
{
    var legacy = key + "=" + oldValue;
    var replacement = key + "=" + newValue;
    var lines = Me.CustomData.Split('\n');
    var changed = false;
    for (var i = 0; i < lines.Length; i++)
    {
        if (lines[i].Trim() == legacy)
        {
            lines[i] = replacement;
            changed = true;
        }
    }
    if (changed)
    {
        Me.CustomData = string.Join("\n", lines);
    }
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
    instanceLabels.Clear();
    sosAutomationEnabled = false;
    sosAutomationApprovalActionId = "";
    sosAutomationApprovalNonce = "";
    sosAutomationApprovalExpiresSequence = 0;
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
        if (key == "verification_nonce") verificationNonce = value;
        if (key == "sos_automation_enabled") bool.TryParse(value, out sosAutomationEnabled);
        if (key == "sos_automation_approval_action_id") sosAutomationApprovalActionId = value;
        if (key == "sos_automation_approval_nonce") sosAutomationApprovalNonce = value;
        if (key == "sos_automation_approval_expires_sequence") int.TryParse(value, out sosAutomationApprovalExpiresSequence);
        if (key == "snapshot_mode") snapshotMode = value;
        if (key == "max_commands_per_minute") int.TryParse(value, out maxCommandsPerMinute);
        if (key == "max_apply_commands_per_tick") int.TryParse(value, out maxApplyCommandsPerTick);
        if (key == "dynamic_apply_commands") bool.TryParse(value, out dynamicApplyCommands);
        if (key == "dynamic_min_apply_commands_per_tick") int.TryParse(value, out dynamicMinApplyCommandsPerTick);
        if (key == "dynamic_max_apply_commands_per_tick") int.TryParse(value, out dynamicMaxApplyCommandsPerTick);
        if (key == "dynamic_runtime_low_ratio") double.TryParse(value, out dynamicRuntimeLowRatio);
        if (key == "dynamic_runtime_high_ratio") double.TryParse(value, out dynamicRuntimeHighRatio);
        if (key == "include_terminal_metadata") bool.TryParse(value, out includeTerminalMetadata);
        if (key == "apply_worker_commands") bool.TryParse(value, out applyWorkerCommands);
        if (key == "allow_connected_grid_commands") bool.TryParse(value, out allowConnectedGridCommands);
        if (key == "runtime_ms_limit") double.TryParse(value, out runtimeMsLimit);
        if (key == "runtime_ms_soft_ratio") double.TryParse(value, out runtimeMsSoftRatio);
        if (key == "cooldown_seconds") int.TryParse(value, out cooldownSeconds);
        if (key == "fail_closed") bool.TryParse(value, out failClosed);
        if (key.StartsWith("instance_label."))
        {
            var instanceId = key.Substring("instance_label.".Length).Trim();
            if (!string.IsNullOrWhiteSpace(instanceId))
            {
                instanceLabels[instanceId] = value;
            }
        }
    }
}

void EchoOperatorStatus(string status, int pendingSequence)
{
    Echo(RenderOperatorStatus(status, pendingSequence));
}

string RenderOperatorStatus(string status, int pendingSequence)
{
    var text = "NOVALI " + bridgeId + "\n" +
        "State " + status + "\n" +
        "Shim " + ShimVersion + "\n";
    if (pendingSequence > 0)
    {
        text += "Pend seq " + pendingSequence.ToString() + "\n";
    }
    if (lastReceivedSequence > 0)
    {
        text += "Last seq " + lastReceivedSequence.ToString() + " @ " + ShortTimestamp(lastResultCompletedAt) + "\n";
    }
    else
    {
        text += "Last none\n";
    }
    text += "Apply " + CompactStatus(lastApplyStatus) + " " + lastApplyApplied.ToString() + "/" + lastApplyCommandCount.ToString() +
        " skip=" + lastApplySkipped.ToString() + "\n" +
        "Queue total=" + lastQueueTotal.ToString() + " rem=" + lastQueueRemaining.ToString() +
        " drain=" + lastQueueDrained.ToString() + "\n" +
        "SOS automation " + CompactStatus(lastSosAutomationOutcome) + " " +
        Truncate(lastSosAutomationActionId, 24) + " seq=" + lastSosAutomationSequence.ToString() +
        (string.IsNullOrWhiteSpace(lastSosAutomationRejectionReason) ? "" : " " + Truncate(lastSosAutomationRejectionReason, 32)) + "\n" +
        "Running:" + "\n";
    if (lastChildStatusLines.Count == 0)
    {
        text += "- " + InstanceLabel(scriptId) + ": awaiting first result\n";
        return text;
    }
    foreach (var line in lastChildStatusLines)
    {
        text += "- " + line + "\n";
    }
    return text;
}

string ShortTimestamp(string value)
{
    if (string.IsNullOrWhiteSpace(value))
    {
        return "unknown";
    }
    if (value.Length > 19)
    {
        return value.Substring(0, 19);
    }
    return value;
}

string InstanceLabel(string instanceId)
{
    if (instanceLabels.ContainsKey(instanceId))
    {
        return instanceLabels[instanceId];
    }
    return ShortInstanceId(instanceId);
}

string ShortInstanceId(string instanceId)
{
    if (instanceId.StartsWith(bridgeId + "-"))
    {
        return instanceId.Substring(bridgeId.Length + 1).Replace("_", " ");
    }
    return instanceId.Replace("_", " ");
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
        if (key == "last_apply_action_text")
        {
            lastApplyActionText = value;
        }
        if (key == "last_apply_action_time")
        {
            lastApplyActionTime = value;
        }
        if (key == "last_apply_action_at_utc")
        {
            lastApplyActionAtUtc = value;
        }
        if (key == "consumed_sos_automation_action_id")
        {
            consumedSosAutomationActionId = value;
        }
        if (key == "consumed_sos_automation_approval_nonce")
        {
            consumedSosAutomationApprovalNonce = value;
        }
        if (key == "consumed_sos_automation_sequence")
        {
            int.TryParse(value, out consumedSosAutomationSequence);
        }
        if (key == "last_sos_automation_action_id")
        {
            lastSosAutomationActionId = value;
        }
        if (key == "last_sos_automation_approval_nonce")
        {
            lastSosAutomationApprovalNonce = value;
        }
        if (key == "last_sos_automation_outcome")
        {
            lastSosAutomationOutcome = value;
        }
        if (key == "last_sos_automation_rejection_reason")
        {
            lastSosAutomationRejectionReason = value;
        }
        if (key == "last_sos_automation_sequence")
        {
            int.TryParse(value, out lastSosAutomationSequence);
        }
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
        "sequence=" + sequence.ToString() + "\n" +
        SaveField("last_apply_action_text", lastApplyActionText) +
        SaveField("last_apply_action_time", lastApplyActionTime) +
        SaveField("last_apply_action_at_utc", lastApplyActionAtUtc) +
        SaveField("consumed_sos_automation_action_id", consumedSosAutomationActionId) +
        SaveField("consumed_sos_automation_approval_nonce", consumedSosAutomationApprovalNonce) +
        SaveField("consumed_sos_automation_sequence", consumedSosAutomationSequence.ToString()) +
        SaveField("last_sos_automation_action_id", lastSosAutomationActionId) +
        SaveField("last_sos_automation_approval_nonce", lastSosAutomationApprovalNonce) +
        SaveField("last_sos_automation_outcome", lastSosAutomationOutcome) +
        SaveField("last_sos_automation_rejection_reason", lastSosAutomationRejectionReason) +
        SaveField("last_sos_automation_sequence", lastSosAutomationSequence.ToString());
}

string SaveField(string key, string value)
{
    return key + "=" + (value ?? "").Replace("\r", "\\r").Replace("\n", "\\n") + "\n";
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
        Quote("include_terminal_metadata") + ":" + (includeTerminalMetadata ? "true" : "false") + "," +
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
            Quote("verification_nonce") + ":" + Quote(verificationNonce) + "," +
            Quote("requested_at_utc") + ":" + Quote(DateTime.UtcNow.ToString("o")) + "," +
            Quote("snapshot_mode") + ":" + Quote(snapshotMode) + "," +
            Quote("block_count") + ":" + blockCount.ToString() + "," +
            Quote("inventory_count") + ":" + inventoryCount.ToString() + "," +
            Quote("sos_automation") + ":{" +
                Quote("last_action_id") + ":" + Quote(lastSosAutomationActionId) + "," +
                Quote("last_outcome") + ":" + Quote(lastSosAutomationOutcome) + "," +
                Quote("last_rejection_reason") + ":" + Quote(lastSosAutomationRejectionReason) + "," +
                Quote("last_sequence") + ":" + lastSosAutomationSequence.ToString() +
            "}," +
            Quote("last_apply") + ":{" +
                Quote("sequence") + ":" + lastApplySequence.ToString() + "," +
                Quote("result_status") + ":" + Quote(lastApplyResultStatus) + "," +
                Quote("status") + ":" + Quote(lastApplyStatus) + "," +
                Quote("command_count") + ":" + lastApplyCommandCount.ToString() + "," +
                Quote("applied") + ":" + lastApplyApplied.ToString() + "," +
                Quote("skipped") + ":" + lastApplySkipped.ToString() + "," +
                Quote("echo") + ":" + lastApplyEchoed.ToString() + "," +
                Quote("last_skip") + ":" + Quote(lastApplyLastSkip) + "," +
                Quote("last_action_text") + ":" + Quote(lastApplyActionText) + "," +
                Quote("last_action_time") + ":" + Quote(lastApplyActionTime) + "," +
                Quote("last_action_at_utc") + ":" + Quote(lastApplyActionAtUtc) +
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
        EchoOperatorStatus("stale result ignored", -1);
        return true;
    }
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
    CacheResultStatus(text, resultSequence, status);
    EchoOperatorStatus(status == "ok" ? "active" : status, -1);
    return true;
}

void CacheResultStatus(string resultText, int resultSequence, string status)
{
    lastReceivedSequence = resultSequence;
    lastReceivedStatus = status;
    lastResultCompletedAt = ExtractString(resultText, "completed_at");
    var commandQueue = ExtractLastObjectForKey(resultText, "command_queue");
    if (!string.IsNullOrWhiteSpace(commandQueue))
    {
        lastQueueTotal = Math.Max(0, ExtractInt(commandQueue, "queued"));
        lastQueueDrained = Math.Max(0, ExtractInt(commandQueue, "drained"));
        lastQueueRemaining = Math.Max(0, ExtractInt(commandQueue, "remaining"));
    }
    else
    {
        lastQueueTotal = Math.Max(0, ExtractInt(resultText, "queued_commands"));
        lastQueueDrained = Math.Max(0, ExtractInt(resultText, "drained_commands"));
        lastQueueRemaining = Math.Max(0, ExtractInt(resultText, "remaining_commands"));
    }
    lastChildStatusLines = BuildChildStatusLines(resultText);
}

List<string> BuildChildStatusLines(string resultText)
{
    var lines = new List<string>();
    var children = ExtractObjectsFromArray(resultText, "child_results");
    foreach (var child in children)
    {
        var childId = ExtractString(child, "script_id");
        if (string.IsNullOrWhiteSpace(childId))
        {
            continue;
        }
        var childStatus = ExtractString(child, "status");
        var error = ExtractString(child, "error_bucket");
        var summary = ExtractString(child, "summary");
        var queue = ExtractLastObjectForKey(child, "command_queue");
        var queued = Math.Max(0, ExtractInt(queue, "queued"));
        var remaining = Math.Max(0, ExtractInt(queue, "remaining"));
        var line = InstanceLabel(childId) + ": " + (string.IsNullOrWhiteSpace(childStatus) ? "unknown" : childStatus);
        if (!string.IsNullOrWhiteSpace(error) && error != "none")
        {
            line += " " + error;
        }
        line += " q=" + queued.ToString() + " rem=" + remaining.ToString();
        if (!string.IsNullOrWhiteSpace(summary))
        {
            line += " - " + Truncate(summary, 32);
        }
        lines.Add(line);
    }
    return lines;
}

string CompactStatus(string value)
{
    if (value == "no_commands")
    {
        return "no_cmd";
    }
    if (value == "apply_disabled")
    {
        return "disabled";
    }
    return value;
}

string Truncate(string text, int maxLength)
{
    if (string.IsNullOrWhiteSpace(text) || text.Length <= maxLength)
    {
        return text;
    }
    if (maxLength <= 3)
    {
        return text.Substring(0, maxLength);
    }
    return text.Substring(0, maxLength - 3) + "...";
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
            if (ApplySetBlockEnabledCommand(command, resultSequence))
            {
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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
                RecordActionText(DescribeCommandAction(kind, command));
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

void RecordActionText(string text)
{
    if (!string.IsNullOrWhiteSpace(text))
    {
        lastApplyActionText = Truncate(text, 180);
        lastApplyActionTime = DateTime.Now.ToString("HH:mm:ss");
        lastApplyActionAtUtc = DateTime.UtcNow.ToString("o");
    }
}

string DescribeCommandAction(string kind, string command)
{
    var blockId = ExtractLong(command, "block_entity_id");
    var block = ResolveTerminalBlock(blockId);
    var name = BlockName(block, blockId);
    if (kind == "rename_block")
    {
        return "Renamed " + name + " to '" + ExtractString(command, "new_name") + "'";
    }
    if (kind == "write_block_custom_data")
    {
        return "Updated custom data on " + name;
    }
    if (kind == "set_block_enabled")
    {
        return "Set " + name + " enabled=" + ExtractBool(command, "enabled").ToString();
    }
    if (kind == "set_use_conveyor")
    {
        return "Set conveyor on " + name + " to " + ExtractBool(command, "enabled").ToString();
    }
    if (kind == "set_door_open")
    {
        return "Set door " + name + " open=" + ExtractBool(command, "open").ToString();
    }
    if (kind == "set_light_color")
    {
        return "Set light color on " + name;
    }
    if (kind == "set_assembler_mode")
    {
        return "Set assembler " + name + " mode=" + ExtractString(command, "mode");
    }
    if (kind == "set_assembler_cooperative_mode")
    {
        return "Set assembler " + name + " cooperative=" + ExtractBool(command, "enabled").ToString();
    }
    if (kind == "set_gas_auto_refill")
    {
        return "Set gas auto refill on " + name + " to " + ExtractBool(command, "enabled").ToString();
    }
    if (kind == "move_assembler_queue_item")
    {
        return "Moved assembler queue item on " + name;
    }
    if (kind == "remove_assembler_queue_item")
    {
        return "Removed assembler queue item on " + name;
    }
    if (kind == "enqueue_assembler_blueprint")
    {
        return "Queued blueprint on " + name;
    }
    if (kind == "clear_assembler_queue")
    {
        return "Cleared assembler queue on " + name;
    }
    return "";
}

string DescribeTransferAction(string command, IMyTerminalBlock sourceBlock, IMyTerminalBlock destinationBlock, double moveAmount, string subtypeId)
{
    return "Moved: " + FormatActionAmount(moveAmount) + " " + subtypeId +
        " from: '" + BlockName(sourceBlock, ExtractLong(command, "source_entity_id")) +
        "' to: '" + BlockName(destinationBlock, ExtractLong(command, "destination_entity_id")) + "'";
}

string BlockName(IMyTerminalBlock block, long fallbackId)
{
    if (block != null && !string.IsNullOrWhiteSpace(block.CustomName))
    {
        return block.CustomName;
    }
    return fallbackId == 0 ? "unknown" : fallbackId.ToString();
}

string FormatActionAmount(double value)
{
    if (value >= 1000000) return (value / 1000000.0).ToString("0.##") + "M";
    if (value >= 1000) return (value / 1000.0).ToString("0.##") + "K";
    return value.ToString("0.##");
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
        RecordActionText(DescribeTransferAction(command, sourceBlock, destinationBlock, moveAmount, subtypeId));
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
        PrepareTextSurface(panel, command);
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
    PrepareTextSurface(surface, command);
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

void PrepareTextSurface(IMyTextSurface surface, string command)
{
    var font = ExtractString(command, "font");
    surface.Font = string.IsNullOrWhiteSpace(font) ? "Debug" : font;
    var fontSize = ExtractDouble(command, "font_size");
    surface.FontSize = (float)ClampDouble(fontSize <= 0 ? 0.6 : fontSize, 0.35, 2.0);
    var textPadding = ExtractDouble(command, "text_padding");
    surface.TextPadding = (float)ClampDouble(textPadding < 0 ? 2.0 : textPadding, 0.0, 20.0);
    var alignment = ExtractString(command, "alignment").ToLower();
    if (alignment == "center")
    {
        surface.Alignment = TextAlignment.CENTER;
    }
    else if (alignment == "right")
    {
        surface.Alignment = TextAlignment.RIGHT;
    }
    else
    {
        surface.Alignment = TextAlignment.LEFT;
    }
    var contentType = ExtractString(command, "content_type").ToLower();
    surface.ContentType = contentType == "script" ? ContentType.SCRIPT : ContentType.TEXT_AND_IMAGE;
}

bool ApplySetBlockEnabledCommand(string command, int resultSequence)
{
    var isSosAutomationRecovery = HasJsonField(command, "sos_action_family");
    if (isSosAutomationRecovery && !ValidateSosAutomationRecoveryCommand(command, resultSequence))
    {
        return false;
    }
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
    if (isSosAutomationRecovery)
    {
        ConsumeSosAutomationReceipt(command, resultSequence);
    }
    return true;
}

bool ValidateSosAutomationRecoveryCommand(string command, int resultSequence)
{
    var actionId = ExtractString(command, "sos_action_id");
    var actionFamily = ExtractString(command, "sos_action_family");
    var approvalNonce = ExtractString(command, "sos_approval_nonce");
    if (!sosAutomationEnabled)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_automation_disabled");
    }
    if (actionFamily != "programmable_block_recovery")
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_action_family_unsupported");
    }
    if (!ExtractBool(command, "enabled"))
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_recovery_requires_enabled");
    }
    if (string.IsNullOrWhiteSpace(actionId))
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_action_id_missing");
    }
    if (string.IsNullOrWhiteSpace(approvalNonce))
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_nonce_missing");
    }
    if (actionId != sosAutomationApprovalActionId)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_action_mismatch");
    }
    if (approvalNonce != sosAutomationApprovalNonce)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_nonce_mismatch");
    }
    var expiresAfterSequence = ExtractInt(command, "sos_expires_after_sequence");
    if (sosAutomationApprovalExpiresSequence <= 0)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_expiry_missing");
    }
    if (expiresAfterSequence != sosAutomationApprovalExpiresSequence)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_expiry_mismatch");
    }
    if (expiresAfterSequence < resultSequence)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_expired");
    }
    if (IsSosAutomationReceiptConsumed(actionId, approvalNonce))
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_approval_receipt_consumed");
    }
    var targetGridEntityId = ExtractLong(command, "sos_target_grid_entity_id");
    if (targetGridEntityId == 0)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_target_grid_invalid");
    }
    var target = ResolveTerminalBlock(ExtractLong(command, "block_entity_id")) as IMyProgrammableBlock;
    if (target == null)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_target_not_programmable_block");
    }
    if (target.CubeGrid == null || Me.CubeGrid == null ||
        target.CubeGrid.EntityId != Me.CubeGrid.EntityId ||
        target.CubeGrid.EntityId != targetGridEntityId)
    {
        return RejectSosAutomationRecovery(actionId, approvalNonce, resultSequence, "sos_target_grid_mismatch");
    }
    return true;
}

bool RejectSosAutomationRecovery(string actionId, string approvalNonce, int resultSequence, string reason)
{
    lastCommandSkipReason = reason;
    RecordSosAutomationReceipt(actionId, approvalNonce, resultSequence, "rejected", reason, false);
    return false;
}

bool IsSosAutomationReceiptConsumed(string actionId, string approvalNonce)
{
    return !string.IsNullOrWhiteSpace(actionId) &&
        actionId == consumedSosAutomationActionId &&
        approvalNonce == consumedSosAutomationApprovalNonce;
}

void ConsumeSosAutomationReceipt(string command, int resultSequence)
{
    var actionId = ExtractString(command, "sos_action_id");
    var approvalNonce = ExtractString(command, "sos_approval_nonce");
    RecordSosAutomationReceipt(actionId, approvalNonce, resultSequence, "applied", "", true);
}

void RecordSosAutomationReceipt(string actionId, string approvalNonce, int resultSequence, string outcome, string reason, bool consumeReceipt)
{
    lastSosAutomationActionId = actionId;
    lastSosAutomationApprovalNonce = approvalNonce;
    lastSosAutomationOutcome = outcome;
    lastSosAutomationRejectionReason = reason;
    lastSosAutomationSequence = resultSequence;
    if (consumeReceipt)
    {
        consumedSosAutomationActionId = actionId;
        consumedSosAutomationApprovalNonce = approvalNonce;
        consumedSosAutomationSequence = resultSequence;
    }
    SaveState();
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

List<string> ExtractObjectsFromArray(string text, string key)
{
    var objects = new List<string>();
    var keyAt = text.IndexOf("\"" + key + "\"");
    if (keyAt < 0)
    {
        return objects;
    }
    var arrayStart = text.IndexOf("[", keyAt);
    if (arrayStart < 0)
    {
        return objects;
    }
    var arrayEnd = FindMatching(text, arrayStart, '[', ']');
    if (arrayEnd <= arrayStart)
    {
        return objects;
    }
    var search = arrayStart + 1;
    while (search < arrayEnd)
    {
        var objectStart = text.IndexOf("{", search);
        if (objectStart < 0 || objectStart > arrayEnd)
        {
            break;
        }
        var objectEnd = FindMatching(text, objectStart, '{', '}');
        if (objectEnd <= objectStart || objectEnd > arrayEnd)
        {
            break;
        }
        objects.Add(text.Substring(objectStart, objectEnd - objectStart + 1));
        search = objectEnd + 1;
    }
    return objects;
}

string ExtractLastObjectForKey(string text, string key)
{
    var keyAt = text.LastIndexOf("\"" + key + "\"");
    if (keyAt < 0)
    {
        return "";
    }
    var objectStart = text.IndexOf("{", keyAt);
    if (objectStart < 0)
    {
        return "";
    }
    var objectEnd = FindMatching(text, objectStart, '{', '}');
    if (objectEnd <= objectStart)
    {
        return "";
    }
    return text.Substring(objectStart, objectEnd - objectStart + 1);
}

int FindMatching(string text, int start, char open, char close)
{
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
        if (c == open)
        {
            depth++;
            continue;
        }
        if (c == close)
        {
            depth--;
            if (depth == 0)
            {
                return i;
            }
        }
    }
    return -1;
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
    if (start >= 0)
    {
        return original.Substring(0, start).TrimEnd() + "\n\n" + replacement + "\n";
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
    return RemoveOrphanedMarkedBlock(original);
}

string RemoveOrphanedMarkedBlock(string original)
{
    int start = original.IndexOf(Begin);
    if (start >= 0)
    {
        lastResultWasStale = true;
        return original.Substring(0, start).TrimEnd() + "\n";
    }
    return original;
}

string Quote(string value)
{
    return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
}

bool HasJsonField(string text, string key)
{
    return text.IndexOf("\"" + key + "\"") >= 0;
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

double ClampDouble(double value, double min, double max)
{
    if (value < min) return min;
    if (value > max) return max;
    return value;
}
