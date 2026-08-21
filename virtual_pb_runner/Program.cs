using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

const string CapabilityVersion = "dynamic-harness-v12";

var options = ParseArgs(args);
var mode = options.GetValueOrDefault("mode", "run").ToLowerInvariant();
var outputPath = options.GetValueOrDefault("output", "");
if (mode == "capabilities")
{
    WriteJson(outputPath, Capabilities());
    return 0;
}
if (!options.TryGetValue("script", out var scriptPath) || string.IsNullOrWhiteSpace(outputPath))
{
    Console.Error.WriteLine("Usage: --script <Script.cs> --request <request.json> --output <output.json> [--mode run|analyze|capabilities]");
    return 2;
}

var source = File.ReadAllText(scriptPath);
var compatibility = Analyze(source);
if (mode == "analyze")
{
    var analysisStatus = compatibility["status"]?.GetValue<string>();
    if (analysisStatus == "supported" || analysisStatus == "blocked_command_mapping")
    {
        compatibility = Compile(scriptPath, source, compatibility);
    }
    WriteJson(outputPath, compatibility);
    return 0;
}
if (!options.TryGetValue("request", out var requestPath))
{
    Console.Error.WriteLine("Usage: --script <Script.cs> --request <request.json> --output <output.json> [--mode run|analyze|capabilities]");
    return 2;
}
if (compatibility["status"]?.GetValue<string>() != "supported")
{
    WriteJson(outputPath, Rejected(compatibility));
    return 0;
}

compatibility = Compile(scriptPath, source, compatibility);
if (compatibility["status"]?.GetValue<string>() != "supported")
{
    WriteJson(outputPath, Rejected(compatibility));
    return 0;
}

var cacheDir = CacheDirFor(scriptPath, source);
var runResult = RunGenerated(cacheDir, requestPath, outputPath);
if (runResult != 0)
{
    var failed = new JsonObject
    {
        ["adapter_status"] = "failed",
        ["summary"] = "Virtual PB generated harness failed.",
        ["commands"] = new JsonArray { new JsonObject { ["kind"] = "echo", ["text"] = "virtual PB generated harness failed" } },
        ["compatibility"] = compatibility,
        ["error_bucket"] = "virtual_pb_generated_runner_failed",
    };
    WriteJson(outputPath, failed);
    return 0;
}
return 0;

static JsonObject Analyze(string source)
{
    var unsupportedApis = new JsonArray();
    foreach (var item in UnsafePatterns())
    {
        if (source.Contains(item, StringComparison.Ordinal))
        {
            unsupportedApis.Add(item);
        }
    }

    var requiredInterfaces = new JsonArray();
    var implemented = ImplementedInterfaces().ToHashSet(StringComparer.Ordinal);
    var unsupportedInterfaces = new JsonArray();
    foreach (var name in Regex.Matches(source, @"\bIMy[A-Za-z0-9_]+\b").Select(item => item.Value).Distinct().OrderBy(item => item))
    {
        requiredInterfaces.Add(name);
        if (!implemented.Contains(name))
        {
            unsupportedInterfaces.Add(name);
            unsupportedApis.Add($"unsupported_interface:{name}");
        }
    }

    var unsupportedMembers = new JsonArray();
    foreach (var member in UnsupportedMemberPatterns())
    {
        if (member.Pattern.IsMatch(source))
        {
            unsupportedMembers.Add($"unsupported_member:{member.Name}");
            unsupportedApis.Add($"unsupported_member:{member.Name}");
        }
    }
    var blockedMembers = new JsonArray();
    var blockedMappings = new JsonArray();
    foreach (var property in BlockedCommandMappings(source))
    {
        var blocked = property.StartsWith("IMy", StringComparison.Ordinal)
            ? $"unsupported_member:{property}"
            : $"unsupported_member:IMyTerminalBlock.SetValue:{property}";
        blockedMembers.Add(blocked);
        blockedMappings.Add(property);
        unsupportedApis.Add(blocked);
    }

    var hasOnlyBlockedMappings = blockedMembers.Count > 0
        && unsupportedInterfaces.Count == 0
        && unsupportedMembers.Count == 0
        && unsupportedApis.Count == blockedMembers.Count;
    var status = unsupportedApis.Count == 0 ? "supported" : (hasOnlyBlockedMappings ? "blocked_command_mapping" : "unsupported");
    return new JsonObject
    {
        ["schema"] = "novali.client_side_pb.virtual_pb_compatibility_report.v1",
        ["status"] = status,
        ["compiled"] = false,
        ["unsupported_apis"] = unsupportedApis,
        ["unsupported_interfaces"] = unsupportedInterfaces,
        ["unsupported_members"] = unsupportedMembers,
        ["blocked_members"] = blockedMembers,
        ["blocked_command_mappings"] = blockedMappings,
        ["missing_types"] = new JsonArray(),
        ["missing_members"] = new JsonArray(),
        ["compile_errors"] = new JsonArray(),
        ["required_interfaces"] = requiredInterfaces,
        ["implemented_interfaces"] = JsonArrayFrom(ImplementedInterfaces()),
        ["supported_block_types"] = JsonArrayFrom(ImplementedInterfaces().Where(item => item.StartsWith("IMy", StringComparison.Ordinal))),
        ["available_command_kinds"] = JsonArrayFrom(AvailableCommandKinds()),
        ["snapshot_requirements"] = JsonArrayFrom(SnapshotFields()),
        ["capability_categories"] = CapabilityCategories(),
        ["uses_grid_terminal_system"] = source.Contains("GridTerminalSystem", StringComparison.Ordinal),
        ["uses_runtime"] = source.Contains("Runtime.", StringComparison.Ordinal),
        ["uses_custom_data"] = source.Contains("CustomData", StringComparison.Ordinal),
        ["capability_version"] = CapabilityVersion,
    };
}

static JsonObject Compile(string scriptPath, string source, JsonObject compatibility)
{
    var cacheDir = CacheDirFor(scriptPath, source);
    EnsureGeneratedProject(cacheDir, source);
    var dll = Path.Combine(cacheDir, "bin", "Debug", "net10.0", "GeneratedVirtualPb.dll");
    if (!File.Exists(dll))
    {
        var build = Dotnet(cacheDir, "build", "--nologo");
        if (build.ExitCode != 0)
        {
            compatibility["status"] = "unsupported";
            compatibility["compiled"] = false;
            var members = compatibility["unsupported_members"]?.AsArray() ?? new JsonArray();
            members.Add("compile_error");
            compatibility["unsupported_members"] = members;
            var apis = compatibility["unsupported_apis"]?.AsArray() ?? new JsonArray();
            apis.Add("compile_error");
            compatibility["unsupported_apis"] = apis;
            AddCompileGaps(compatibility, build.StdOut + "\n" + build.StdErr);
            compatibility["compile_stdout"] = TrimTail(build.StdOut);
            compatibility["compile_stderr"] = TrimTail(build.StdErr);
            return compatibility;
        }
    }
    compatibility["compiled"] = true;
    return compatibility;
}

static int RunGenerated(string cacheDir, string requestPath, string outputPath)
{
    var run = Dotnet(cacheDir, "run", "--no-build", "--", "--request", Path.GetFullPath(requestPath), "--output", Path.GetFullPath(outputPath));
    if (run.ExitCode != 0)
    {
        Console.Error.WriteLine(run.StdErr);
    }
    return run.ExitCode;
}

static (int ExitCode, string StdOut, string StdErr) Dotnet(string workingDirectory, params string[] arguments)
{
    var start = new ProcessStartInfo("dotnet")
    {
        WorkingDirectory = workingDirectory,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        UseShellExecute = false,
    };
    foreach (var argument in arguments)
    {
        start.ArgumentList.Add(argument);
    }
    using var process = Process.Start(start) ?? throw new InvalidOperationException("dotnet failed to start");
    var stdout = process.StandardOutput.ReadToEndAsync();
    var stderr = process.StandardError.ReadToEndAsync();
    if (!process.WaitForExit(120000))
    {
        process.Kill(entireProcessTree: true);
        return (124, stdout.GetAwaiter().GetResult(), "timeout\n" + stderr.GetAwaiter().GetResult());
    }
    return (process.ExitCode, stdout.GetAwaiter().GetResult(), stderr.GetAwaiter().GetResult());
}

static JsonObject Rejected(JsonObject compatibility)
{
    return new JsonObject
    {
        ["adapter_status"] = "rejected",
        ["summary"] = "Virtual PB script rejected by compatibility analysis.",
        ["commands"] = new JsonArray { new JsonObject { ["kind"] = "echo", ["text"] = "virtual PB rejected: unsupported API"} },
        ["compatibility"] = compatibility.DeepClone(),
        ["error_bucket"] = "virtual_pb_unsupported_api",
    };
}

static JsonObject Capabilities()
{
    return new JsonObject
    {
        ["schema"] = "novali.client_side_pb.virtual_pb_capabilities.v1",
        ["capability_version"] = CapabilityVersion,
        ["implemented_interfaces"] = JsonArrayFrom(ImplementedInterfaces()),
        ["available_command_kinds"] = JsonArrayFrom(AvailableCommandKinds()),
        ["snapshot_fields"] = JsonArrayFrom(SnapshotFields()),
        ["read_supported_members"] = JsonArrayFrom(ReadSupportedMembers()),
        ["generic_terminal_mutations"] = "blocked_unless_mapped",
        ["terminal_property_registry"] = JsonArrayFrom(TerminalPropertyRegistry()),
        ["client_overlay_properties"] = JsonArrayFrom(ClientOverlayProperties()),
        ["mapped_command_properties"] = JsonArrayFrom(MappedCommandProperties()),
        ["blocked_command_properties"] = JsonArrayFrom(BlockedCommandProperties()),
        ["partial_traversal_features"] = JsonArrayFrom(PartialTraversalFeatures()),
        ["capability_categories"] = CapabilityCategories(),
    };
}

static string CacheDirFor(string scriptPath, string source)
{
    var hashInput = CapabilityVersion + "\n" + Path.GetFullPath(scriptPath) + "\n" + source;
    var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(hashInput))).ToLowerInvariant()[..16];
    return Path.Combine(Directory.GetCurrentDirectory(), "data", "virtual_pb_cache", hash);
}

static void EnsureGeneratedProject(string cacheDir, string source)
{
    Directory.CreateDirectory(cacheDir);
    File.WriteAllText(
        Path.Combine(cacheDir, "GeneratedVirtualPb.csproj"),
        """
        <Project Sdk="Microsoft.NET.Sdk">
          <PropertyGroup>
            <OutputType>Exe</OutputType>
            <TargetFramework>net10.0</TargetFramework>
            <ImplicitUsings>enable</ImplicitUsings>
            <Nullable>disable</Nullable>
          </PropertyGroup>
        </Project>
        """,
        GeneratedSources.Utf8NoBom);
    File.WriteAllText(Path.Combine(cacheDir, "HarnessSupport.cs"), GeneratedSources.HarnessSupportSource, GeneratedSources.Utf8NoBom);
    File.WriteAllText(Path.Combine(cacheDir, "GeneratedProgram.cs"), GeneratedSources.GeneratedProgramSource, GeneratedSources.Utf8NoBom);
    File.WriteAllText(Path.Combine(cacheDir, "UserProgram.cs"), WrapUserSource(source), GeneratedSources.Utf8NoBom);
}

static string WrapUserSource(string source)
{
    var normalized = source.TrimStart('\uFEFF');
    return $$"""
    using System;
    using System.Collections.Generic;
    using System.Linq;
    using System.Text;
    using VRage.Game.GUI.TextPanel;
    using VRage.Game.ModAPI.Ingame.Utilities;
    using VRage.Game.ObjectBuilders.Definitions;
    using VRageMath;

    public sealed class Program : MyGridProgram
    {
    {{normalized}}
    }
    """;
}

static Dictionary<string, string> ParseArgs(string[] args)
{
    var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    for (var i = 0; i < args.Length; i++)
    {
        if (!args[i].StartsWith("--", StringComparison.Ordinal))
        {
            continue;
        }
        var key = args[i][2..];
        var value = i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal) ? args[++i] : "true";
        result[key] = value;
    }
    return result;
}

static void WriteJson(string path, JsonNode payload)
{
    var json = payload.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    if (string.IsNullOrWhiteSpace(path))
    {
        Console.WriteLine(json);
        return;
    }
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)) ?? ".");
    File.WriteAllText(path, json, GeneratedSources.Utf8NoBom);
}

static JsonArray JsonArrayFrom(IEnumerable<string> items)
{
    var array = new JsonArray();
    foreach (var item in items.Distinct().OrderBy(item => item, StringComparer.Ordinal))
    {
        array.Add(item);
    }
    return array;
}

static string TrimTail(string value) => value.Length <= 3000 ? value : value[^3000..];

static IEnumerable<string> UnsafePatterns() => new[]
{
    "System.IO",
    "File.",
    "Directory.",
    "System.Net",
    "HttpClient",
    "Process.",
    "System.Diagnostics",
    "Thread",
    "Task.",
    "Reflection",
    "Activator.",
    "Marshal.",
};

static IEnumerable<(Regex Pattern, string Name)> UnsupportedMemberPatterns() => new[]
{
    (new Regex(@"\.ApplyAction\s*\(", RegexOptions.Compiled), "IMyTerminalBlock.ApplyAction"),
};

static IEnumerable<string> BlockedCommandMappings(string source)
{
    var known = TerminalPropertyRegistry().ToHashSet(StringComparer.OrdinalIgnoreCase);
    var blocked = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
    foreach (Match match in Regex.Matches(source, @"\.SetValue(?:<[^>]+>)?\s*\(\s*""([^""]+)""", RegexOptions.Compiled))
    {
        var property = match.Groups[1].Value;
        if (property.StartsWith("ControlModule.", StringComparison.OrdinalIgnoreCase))
        {
            continue;
        }
        if (!known.Contains(property))
        {
            blocked.Add(property);
        }
    }
    foreach (var property in BlockedCommandProperties())
    {
        if (Regex.IsMatch(source, @"\." + Regex.Escape(property) + @"\s*=", RegexOptions.Compiled))
        {
            blocked.Add(property);
        }
    }
    foreach (var mapping in BlockedCommandMethodMappings())
    {
        if (mapping.Pattern.IsMatch(source))
        {
            blocked.Add(mapping.Name);
        }
    }
    return blocked;
}

static IEnumerable<string> ImplementedInterfaces() =>
    Regex.Matches(GeneratedSources.HarnessSupportSource, @"public\s+interface\s+(IMy[A-Za-z0-9_]+)\b")
        .Select(match => match.Groups[1].Value)
        .Distinct()
        .OrderBy(name => name);

static IEnumerable<string> AvailableCommandKinds() => ScanShimCommandKinds().DefaultIfEmpty("write_text_surface");

static IEnumerable<string> ScanShimCommandKinds()
{
    var shim = Path.Combine(Directory.GetCurrentDirectory(), "pb_shim", "ClientSidePBBridgeShim.cs");
    if (!File.Exists(shim))
    {
        return Array.Empty<string>();
    }
    var source = File.ReadAllText(shim);
    return Regex.Matches(source, "kind\\s*==\\s*\"([^\"]+)\"").Select(match => match.Groups[1].Value).Append("echo").Distinct();
}

static IEnumerable<string> SnapshotFields() => new[]
{
    "grid_snapshot.blocks[]",
    "grid_snapshot.blocks[].custom_data",
    "grid_snapshot.blocks[].custom_info",
    "grid_snapshot.blocks[].custom_name_with_faction",
    "grid_snapshot.blocks[].detailed_info",
    "grid_snapshot.blocks[].door_open_ratio",
    "grid_snapshot.blocks[].door_status",
    "grid_snapshot.blocks[].enabled",
    "grid_snapshot.blocks[].entity_id",
    "grid_snapshot.blocks[].inventories[]",
    "grid_snapshot.blocks[].inventories[].items[]",
    "grid_snapshot.blocks[].has_local_player_access",
    "grid_snapshot.blocks[].has_nobody_player_access",
    "grid_snapshot.blocks[].has_player_access",
    "grid_snapshot.blocks[].has_player_access_with_nobody_check",
    "grid_snapshot.blocks[].name",
    "grid_snapshot.blocks[].production_queue[]",
    "grid_snapshot.blocks[].same_construct",
    "grid_snapshot.blocks[].alignment",
    "grid_snapshot.blocks[].content_type",
    "grid_snapshot.blocks[].font",
    "grid_snapshot.blocks[].font_size",
    "grid_snapshot.blocks[].surface_count",
    "grid_snapshot.blocks[].surface_size",
    "grid_snapshot.blocks[].terminal_actions[]",
    "grid_snapshot.blocks[].terminal_actions[].id",
    "grid_snapshot.blocks[].terminal_actions[].name",
    "grid_snapshot.blocks[].terminal_properties[]",
    "grid_snapshot.blocks[].terminal_properties[].id",
    "grid_snapshot.blocks[].terminal_properties[].type",
    "grid_snapshot.blocks[].text",
    "grid_snapshot.blocks[].text_padding",
    "grid_snapshot.blocks[].texture_size",
    "grid_snapshot.blocks[].type",
    "inventory_snapshot.blocks[]",
    "inventory_snapshot.blocks[].inventories[].items[]",
};

static IEnumerable<string> ClientOverlayProperties() => new[]
{
    "IMyTerminalBlock.CustomData",
    "ControlModule.AddInput",
    "ControlModule.Inputs",
    "ControlModule.InputState",
    "ControlModule.RepeatDelay",
    "ControlModule.RunOnInput",
};

static IEnumerable<string> ReadSupportedMembers() => new[]
{
    "IMyTerminalBlock.CustomInfo",
    "IMyTerminalBlock.CustomNameWithFaction",
    "IMyTerminalBlock.DetailedInfo",
    "IMyTerminalBlock.GetActionWithName",
    "IMyTerminalBlock.GetActions",
    "IMyTerminalBlock.GetProperties",
    "IMyTerminalBlock.GetProperty",
    "IMyTerminalBlock.HasLocalPlayerAccess",
    "IMyTerminalBlock.HasNobodyPlayerAccessToBlock",
    "IMyTerminalBlock.HasPlayerAccess",
    "IMyTerminalBlock.HasPlayerAccessWithNobodyCheck",
    "IMyTerminalBlock.IsSameConstructAs",
};

static IEnumerable<string> MappedCommandProperties() => new[]
{
    "Color",
    "Enabled",
    "OnOff",
};

static IEnumerable<string> BlockedCommandProperties() => new[]
{
    "DampenersOverride",
    "IMyAssembler.AddQueueItem",
    "IMyAssembler.ClearQueue",
    "IMyAssembler.InsertQueueItem",
    "IMyAssembler.Mode.set",
    "IMyAssembler.MoveQueueItemRequest",
    "IMyAssembler.Repeating",
    "IMyAssembler.RemoveQueueItem",
    "IMyInventory.TransferItemTo",
    "RotorLock",
    "TargetVelocityRad",
    "ThrustOverride",
    "ThrustOverridePercentage",
};

static IEnumerable<string> PartialTraversalFeatures() => new[]
{
    "assembler_queue_mutations",
    "named_block_groups",
    "per_surface_metadata_arrays",
    "text_surface_sprites",
};

static IEnumerable<string> TerminalPropertyRegistry() => ClientOverlayProperties().Concat(MappedCommandProperties()).Concat(BlockedCommandProperties());

static JsonObject CapabilityCategories()
{
    return new JsonObject
    {
        ["read_supported"] = JsonArrayFrom(ImplementedInterfaces().Concat(SnapshotFields()).Concat(ReadSupportedMembers())),
        ["client_overlay"] = JsonArrayFrom(ClientOverlayProperties()),
        ["mapped_command"] = JsonArrayFrom(MappedCommandProperties().Concat(AvailableCommandKinds())),
        ["blocked_mapping"] = JsonArrayFrom(BlockedCommandProperties()),
        ["partial_traversal"] = JsonArrayFrom(PartialTraversalFeatures()),
        ["unsafe"] = JsonArrayFrom(UnsafePatterns()),
    };
}

static IEnumerable<(Regex Pattern, string Name)> BlockedCommandMethodMappings() => new[]
{
    (new Regex(@"\.TransferItemTo\s*\(", RegexOptions.Compiled), "IMyInventory.TransferItemTo"),
    (new Regex(@"\.AddQueueItem\s*\(", RegexOptions.Compiled), "IMyAssembler.AddQueueItem"),
    (new Regex(@"\.ClearQueue\s*\(", RegexOptions.Compiled), "IMyAssembler.ClearQueue"),
    (new Regex(@"\.InsertQueueItem\s*\(", RegexOptions.Compiled), "IMyAssembler.InsertQueueItem"),
    (new Regex(@"\.RemoveQueueItem\s*\(", RegexOptions.Compiled), "IMyAssembler.RemoveQueueItem"),
    (new Regex(@"\.MoveQueueItemRequest\s*\(", RegexOptions.Compiled), "IMyAssembler.MoveQueueItemRequest"),
};

static void AddCompileGaps(JsonObject compatibility, string output)
{
    var missingTypes = new SortedSet<string>(StringComparer.Ordinal);
    var missingMembers = new SortedSet<string>(StringComparer.Ordinal);
    var compileErrors = new List<string>();
    foreach (var line in output.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None))
    {
        if (!line.Contains("error CS", StringComparison.Ordinal))
        {
            continue;
        }
        var trimmed = Regex.Replace(line.Trim(), @"\x1B\[[0-9;]*m", "");
        compileErrors.Add(trimmed);
        var missingType = Regex.Match(trimmed, @"type or namespace name ['‘]([^'’]+)['’] could not be found");
        if (missingType.Success)
        {
            missingTypes.Add(missingType.Groups[1].Value);
        }
        var missingName = Regex.Match(trimmed, @"The name ['‘]([^'’]+)['’] does not exist in the current context");
        if (missingName.Success)
        {
            missingTypes.Add(missingName.Groups[1].Value);
        }
        var missingMember = Regex.Match(trimmed, @"['‘]([^'’]+)['’] does not contain a definition for ['‘]([^'’]+)['’]");
        if (missingMember.Success)
        {
            missingMembers.Add($"{missingMember.Groups[1].Value}.{missingMember.Groups[2].Value}");
        }
    }
    compatibility["missing_types"] = JsonArrayFrom(missingTypes);
    compatibility["missing_members"] = JsonArrayFrom(missingMembers);
    var errors = new JsonArray();
    foreach (var error in compileErrors.TakeLast(40))
    {
        errors.Add(error);
    }
    compatibility["compile_errors"] = errors;
}

static class GeneratedSources
{
public static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);

public const string GeneratedProgramSource = """
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

public static class EntryPoint
{
    public static void Main(string[] args)
    {
        var options = Args.Parse(args);
        var requestPath = options.GetValueOrDefault("request", "");
        var outputPath = options.GetValueOrDefault("output", "");
        var request = JsonNode.Parse(File.ReadAllText(requestPath))?.AsObject() ?? new JsonObject();
        var context = VirtualContext.FromRequest(request);
        var type = typeof(Program);
        VirtualContext.BeginConstruction(context);
        Program program;
        try
        {
            program = (Program)(Activator.CreateInstance(type, nonPublic: true)
                ?? throw new InvalidOperationException("Program constructor unavailable"));
        }
        finally
        {
            VirtualContext.EndConstruction();
        }
        program.Attach(context);

        try
        {
            const BindingFlags mainFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            var main = type.GetMethod("Main", mainFlags, null, new[] { typeof(string), typeof(UpdateType) }, null)
                ?? type.GetMethod("Main", mainFlags, null, new[] { typeof(string) }, null)
                ?? type.GetMethod("Main", mainFlags, null, Type.EmptyTypes, null);
            if (main == null)
            {
                context.Reject("unsupported_member:Program.Main");
            }
            else
            {
                var parameters = main.GetParameters().Length switch
                {
                    2 => new object?[] { "", UpdateType.Update1 },
                    1 => new object?[] { "" },
                    _ => Array.Empty<object?>(),
                };
                main.Invoke(program, parameters);
            }
        }
        catch (TargetInvocationException ex)
        {
            context.Fail(ex.InnerException?.GetType().Name ?? ex.GetType().Name, ex.InnerException?.Message ?? ex.Message);
        }
        catch (Exception ex)
        {
            context.Fail(ex.GetType().Name, ex.Message);
        }

        File.WriteAllText(outputPath, context.ToJson().ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
    }
}

public static class Args
{
    public static Dictionary<string, string> Parse(string[] args)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < args.Length; i++)
        {
            if (!args[i].StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }
            result[args[i][2..]] = i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal) ? args[++i] : "true";
        }
        return result;
    }
}
""";

public const string HarnessSupportSource = """
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text;
using VRage.Game.GUI.TextPanel;
using VRageMath;

[Flags]
public enum UpdateType { None = 0, Terminal = 1, Trigger = 2, Update1 = 4, Update10 = 8, Update100 = 16 }

[Flags]
public enum UpdateFrequency { None = 0, Update1 = 1, Update10 = 2, Update100 = 4, Once = 8 }

public class MyGridProgram
{
    public IMyGridTerminalSystem GridTerminalSystem { get; private set; }
    public IMyProgrammableBlock Me { get; private set; }
    public MyRuntimeInfo Runtime { get; private set; }
    public string Storage { get; set; } = "";
    internal VirtualContext Context { get; private set; }
    public MyGridProgram()
    {
        Attach(VirtualContext.ConstructionContextOrNew());
    }
    public void Attach(VirtualContext context)
    {
        Context = context;
        GridTerminalSystem = context.GridTerminalSystem;
        Me = context.Me;
        Runtime = context.Runtime;
    }
    public void Echo(string text) => Context.Echo(text);
}

public class MyRuntimeInfo
{
    public UpdateFrequency UpdateFrequency { get; set; } = UpdateFrequency.None;
    public double LastRunTimeMs { get; set; }
    public int CurrentInstructionCount { get; set; }
    public int MaxInstructionCount { get; set; } = 50000;
    public TimeSpan TimeSinceLastRun { get; set; } = TimeSpan.FromSeconds(1.0 / 60.0);
}

public sealed class VirtualContext
{
    [ThreadStatic]
    static VirtualContext? ConstructionContext;
    public List<VirtualBlock> Blocks { get; } = new();
    public VirtualGridTerminalSystem GridTerminalSystem { get; }
    public VirtualBlock MeBlock { get; }
    public IMyProgrammableBlock Me => MeBlock;
    public MyRuntimeInfo Runtime { get; } = new();
    public JsonArray Commands { get; } = new();
    public JsonArray Echoes { get; } = new();
    public JsonArray ClientOverlayWrites { get; } = new();
    public string Status { get; private set; } = "ok";
    public string ErrorBucket { get; private set; } = "none";
    public string Summary { get; private set; } = "Virtual PB tick processed.";

    public VirtualContext()
    {
        GridTerminalSystem = new VirtualGridTerminalSystem(this);
        MeBlock = new VirtualBlock(this, new JsonObject { ["entity_id"] = 1, ["name"] = "Virtual PB", ["same_construct"] = true }, 0);
    }

    public static void BeginConstruction(VirtualContext context) => ConstructionContext = context;
    public static void EndConstruction() => ConstructionContext = null;
    public static VirtualContext ConstructionContextOrNew() => ConstructionContext ?? new VirtualContext();

    public static VirtualContext FromRequest(JsonObject request)
    {
        var context = new VirtualContext();
        var customData = request["virtual_pb"]?["custom_data"]?.ToString() ?? "";
        if (!string.IsNullOrEmpty(customData))
        {
            context.MeBlock.SetInitialCustomData(customData);
        }
        context.Blocks.Clear();
        var blocks = request["grid_snapshot"]?["blocks"]?.AsArray() ?? new JsonArray();
        var index = 0;
        foreach (var node in blocks)
        {
            if (node is JsonObject block)
            {
                context.Blocks.Add(new VirtualBlock(context, block, index++));
            }
        }
        if (context.Blocks.Count == 0)
        {
            context.Blocks.Add(context.MeBlock);
        }
        return context;
    }

    public void AddCommand(JsonObject command) => Commands.Add(command);
    public void Echo(string text) => Echoes.Add(text);
    public void RecordClientOverlayWrite(string member, long entityId, object? value)
    {
        ClientOverlayWrites.Add(new JsonObject
        {
            ["member"] = member,
            ["block_entity_id"] = entityId,
            ["value_type"] = value?.GetType().Name ?? "null",
        });
    }
    public void Reject(string bucket)
    {
        if (Status == "rejected")
        {
            return;
        }
        Status = "rejected";
        ErrorBucket = bucket;
        Summary = "Virtual PB script rejected during execution.";
    }
    public void Fail(string type, string message)
    {
        Status = "failed";
        ErrorBucket = "virtual_pb_execution_exception";
        Summary = "Virtual PB execution failed: " + type;
        Echoes.Add(type + ": " + message);
    }

    public JsonObject ToJson()
    {
        var status = Status == "ok" ? "supported" : (ErrorBucket.StartsWith("unsupported_member:", StringComparison.Ordinal) ? "blocked_command_mapping" : "unsupported");
        var blockedMembers = new JsonArray();
        var blockedMappings = new JsonArray();
        if (status == "blocked_command_mapping")
        {
            blockedMembers.Add(ErrorBucket);
            blockedMappings.Add(ErrorBucket.Replace("unsupported_member:", "", StringComparison.Ordinal));
        }
        var result = new JsonObject
        {
            ["summary"] = Summary,
            ["commands"] = Commands,
            ["compatibility"] = new JsonObject
            {
                ["status"] = status,
                ["compiled"] = true,
                ["available_command_kinds"] = new JsonArray("write_text_surface", "set_door_open", "set_light_color", "set_block_enabled"),
                ["emitted_command_kinds"] = EmittedKinds(),
                ["blocked_members"] = blockedMembers,
                ["blocked_command_mappings"] = blockedMappings,
                ["client_overlay_writes"] = ClientOverlayWrites.DeepClone(),
                ["capability_categories"] = new JsonObject
                {
                    ["client_overlay"] = new JsonArray("IMyTerminalBlock.CustomData", "ControlModule.AddInput", "ControlModule.InputState", "ControlModule.Inputs", "ControlModule.RepeatDelay", "ControlModule.RunOnInput"),
                    ["mapped_command"] = new JsonArray("set_block_enabled", "set_door_open", "set_light_color", "write_text_surface"),
                    ["blocked_mapping"] = blockedMappings.DeepClone(),
                },
            },
        };
        if (Status != "ok")
        {
            result["adapter_status"] = Status;
            result["error_bucket"] = ErrorBucket;
        }
        return result;
    }

    JsonArray EmittedKinds()
    {
        var kinds = Commands.OfType<JsonObject>()
            .Select(command => command["kind"]?.GetValue<string>() ?? "")
            .Where(kind => kind.Length > 0)
            .Distinct()
            .OrderBy(kind => kind);
        var array = new JsonArray();
        foreach (var kind in kinds) array.Add(kind);
        return array;
    }
}

public interface IMyCubeGrid
{
    string CustomName { get; }
    float GridSize { get; }
    bool IsStatic { get; }
    MatrixD WorldMatrix { get; }
    IMySlimBlock GetCubeBlock(Vector3I position);
    bool IsSameConstructAs(IMyCubeGrid other);
}
public interface IMyTerminalAction { string Id { get; } }
public interface ITerminalAction { string Id { get; } string Name { get; } }
public interface ITerminalProperty { string Id { get; } string TypeName { get; } }

public interface IMyTerminalBlock
{
    long EntityId { get; }
    string Name { get; }
    string CustomName { get; set; }
    string CustomNameWithFaction { get; }
    string CustomData { get; set; }
    string DisplayNameText { get; }
    string DefinitionDisplayNameText { get; }
    string DetailedInfo { get; }
    string CustomInfo { get; }
    bool IsWorking { get; }
    bool IsFunctional { get; }
    bool HasInventory { get; }
    bool ShowInInventory { get; set; }
    int InventoryCount { get; }
    long OwnerId { get; }
    IMyCubeGrid CubeGrid { get; }
    MyDefinitionId BlockDefinition { get; }
    MyComponentContainer Components { get; }
    Vector3I Position { get; }
    MyBlockOrientation Orientation { get; }
    MatrixD WorldMatrix { get; }
    Vector3D GetPosition();
    IMyInventory GetInventory(int index = 0);
    T GetValue<T>(string id);
    void SetValue<T>(string id, T value);
    ITerminalProperty GetProperty(string id);
    void GetProperties(List<ITerminalProperty> result, Func<ITerminalProperty, bool> collect = null);
    ITerminalAction GetActionWithName(string name);
    void GetActions(List<ITerminalAction> result, Func<ITerminalAction, bool> collect = null);
    bool HasLocalPlayerAccess();
    bool HasNobodyPlayerAccessToBlock();
    bool HasPlayerAccess(long playerId);
    bool HasPlayerAccessWithNobodyCheck(long playerId);
    bool IsSameConstructAs(IMyTerminalBlock other);
    string GetOwnerFactionTag();
}

public interface IMyFunctionalBlock : IMyTerminalBlock { bool Enabled { get; set; } }
public interface IMyProgrammableBlock : IMyFunctionalBlock, IMyTextSurfaceProvider {}
public interface IMyTextSurface
{
    string Font { get; set; }
    float FontSize { get; set; }
    float TextPadding { get; set; }
    TextAlignment Alignment { get; set; }
    ContentType ContentType { get; set; }
    Color ScriptBackgroundColor { get; set; }
    Color ScriptForegroundColor { get; set; }
    string Script { get; set; }
    Vector2 SurfaceSize { get; }
    Vector2 TextureSize { get; }
    void WriteText(string text, bool append = false);
    void WriteText(StringBuilder text, bool append = false);
    string GetText();
    MySpriteDrawFrame DrawFrame();
    Vector2 MeasureStringInPixels(StringBuilder text, string font, float scale);
}
public interface IMyTextPanel : IMyFunctionalBlock, IMyTextSurface { bool Closed { get; } void WritePublicTitle(string value, bool append = false); }
public interface IMyTextSurfaceProvider : IMyTerminalBlock { int SurfaceCount { get; } IMyTextSurface GetSurface(int index); }
public interface IMyInventory
{
    double CurrentVolume { get; }
    double MaxVolume { get; }
    double CurrentMass { get; }
    int ItemCount { get; }
    bool IsFull { get; }
    void GetItems(List<MyInventoryItem> items);
    MyInventoryItem? GetItemAt(int index);
    MyInventoryItem? FindItem(MyItemType itemType);
    MyInventoryItem? FindItem(MyDefinitionId itemType);
    VRage.MyFixedPoint GetItemAmount(MyItemType itemType);
    bool CanItemsBeAdded(VRage.MyFixedPoint amount, MyItemType itemType);
    bool CanItemsBeAdded(VRage.MyFixedPoint amount, MyDefinitionId itemType);
    bool CanTransferItemTo(IMyInventory destinationInventory, MyItemType itemType);
    bool CanTransferItemTo(IMyInventory destinationInventory, MyDefinitionId itemType);
    bool TransferItemTo(IMyInventory destinationInventory, int sourceItemIndex, int? targetItemIndex = null, bool? stackIfPossible = null, VRage.MyFixedPoint? amount = null);
    bool IsConnectedTo(IMyInventory other);
}
public interface IMyGridTerminalSystem
{
    void GetBlocks(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null);
    void GetBlocksOfType<T>(List<T> blocks, Func<T, bool> collect = null) where T : class;
    void GetBlocksOfType<T>(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null) where T : class, IMyTerminalBlock;
    IMyTerminalBlock GetBlockWithName(string name);
    IMyTerminalBlock GetBlockWithId(long id);
    void SearchBlocksOfName(string name, List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null);
    void GetBlockGroups(List<IMyBlockGroup> blockGroups, Func<IMyBlockGroup, bool> collect = null);
    IMyBlockGroup GetBlockGroupWithName(string name);
    bool CanAccess(IMyTerminalBlock block);
    bool CanAccess(IMyTerminalBlock first, IMyTerminalBlock second);
}
public interface IMyBlockGroup { string Name { get; } void GetBlocks(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null); }

public interface IMyDoor : IMyFunctionalBlock { float OpenRatio { get; } DoorStatus Status { get; } void OpenDoor(); void CloseDoor(); }
public interface IMyAirtightHangarDoor : IMyDoor {}
public interface IMyLightingBlock : IMyFunctionalBlock { Color Color { get; set; } float Radius { get; set; } float Intensity { get; set; } float BlinkIntervalSeconds { get; set; } float BlinkLength { get; set; } }
public interface IMyInteriorLight : IMyLightingBlock {}
public interface IMyReflectorLight : IMyLightingBlock {}
public interface IMySoundBlock : IMyFunctionalBlock { float LoopPeriod { get; set; } string SelectedSound { get; set; } void Play(); void Stop(); }
public interface IMyCargoContainer : IMyFunctionalBlock {}
public interface IMyAssembler : IMyProductionBlock
{
    bool CooperativeMode { get; set; }
    MyAssemblerMode Mode { get; set; }
    int QueueCount { get; }
    bool IsQueueEmpty { get; }
    bool Repeating { get; set; }
    bool CanUseBlueprint(MyDefinitionId blueprint);
    void GetQueue(List<MyProductionItem> queue);
    void ClearQueue();
    void AddQueueItem(MyDefinitionId blueprint, VRage.MyFixedPoint amount);
    void InsertQueueItem(int idx, MyDefinitionId blueprint, VRage.MyFixedPoint amount);
    void RemoveQueueItem(int idx, VRage.MyFixedPoint? amount = null);
    void MoveQueueItemRequest(uint queueItemId, int targetIdx);
}
public interface IMyRefinery : IMyProductionBlock {}
public interface IMyProductionBlock : IMyFunctionalBlock { bool IsProducing { get; } bool UseConveyorSystem { get; set; } }
public interface IMyGasTank : IMyFunctionalBlock { double FilledRatio { get; } double Capacity { get; } bool Stockpile { get; set; } bool AutoRefillBottles { get; set; } }
public interface IMyGasGenerator : IMyFunctionalBlock { bool UseConveyorSystem { get; set; } bool AutoRefill { get; set; } }
public interface IMyReactor : IMyPowerProducer { bool UseConveyorSystem { get; set; } }
public interface IMyPowerProducer : IMyFunctionalBlock { float CurrentOutput { get; } float MaxOutput { get; } }
public interface IMyBatteryBlock : IMyPowerProducer { float CurrentStoredPower { get; } float MaxStoredPower { get; } float CurrentInput { get; } ChargeMode ChargeMode { get; set; } }
public interface IMyShipController : IMyFunctionalBlock { bool DampenersOverride { get; set; } bool IsUnderControl { get; } bool IsMainCockpit { get; set; } bool CanControlShip { get; } bool ControlThrusters { get; set; } Vector3D MoveIndicator { get; } bool TryGetPlanetElevation(MyPlanetElevation detail, out double elevation); MyShipMass CalculateShipMass(); MyShipVelocities GetShipVelocities(); Vector3D GetNaturalGravity(); Vector3D GetArtificialGravity(); Vector3D GetTotalGravity(); double GetShipSpeed(); }
public interface IMyCockpit : IMyShipController {}
public interface IMyRemoteControl : IMyShipController {}
public interface IMyShipConnector : IMyFunctionalBlock { MyShipConnectorStatus Status { get; } IMyShipConnector OtherConnector { get; } }
public interface IMyLaserAntenna : IMyFunctionalBlock { MyLaserAntennaStatus Status { get; } }
public interface IMyAirVent : IMyFunctionalBlock { bool CanPressurize { get; } float GetOxygenLevel(); }
public interface IMyCollector : IMyFunctionalBlock {}
public interface IMyConveyorSorter : IMyFunctionalBlock { bool UseConveyorSystem { get; set; } }
public interface IMyBeacon : IMyFunctionalBlock { float Radius { get; set; } }
public interface IMyBroadcastController : IMyFunctionalBlock {}
public interface IMyButtonPanel : IMyFunctionalBlock {}
public interface IMyCameraBlock : IMyFunctionalBlock {}
public interface IMyControlPanel : IMyFunctionalBlock {}
public interface IMyCryoChamber : IMyCockpit {}
public interface IMyDecoy : IMyFunctionalBlock {}
public interface IMyFarmPlotLogic : IMyFunctionalBlock { string GetDetailedInfoWithoutRequiredInput(); }
public interface IMyGravityGenerator : IMyFunctionalBlock {}
public interface IMyGravityGeneratorSphere : IMyGravityGenerator {}
public interface IMyGyro : IMyFunctionalBlock {}
public interface IMyJumpDrive : IMyFunctionalBlock { float CurrentStoredPower { get; } float MaxStoredPower { get; } }
public interface IMyLandingGear : IMyFunctionalBlock { LandingGearMode LockMode { get; } bool IsLocked { get; } }
public interface IMyLargeGatlingTurret : IMyFunctionalBlock {}
public interface IMyLargeInteriorTurret : IMyFunctionalBlock {}
public interface IMyLargeMissileTurret : IMyFunctionalBlock {}
public interface IMyMedicalRoom : IMyFunctionalBlock {}
public interface IMyMotorStator : IMyFunctionalBlock { float TargetVelocityRPM { get; set; } float TargetVelocityRad { get; set; } bool RotorLock { get; set; } IMyTerminalBlock Top { get; } IMyCubeGrid TopGrid { get; } }
public interface IMyOreDetector : IMyFunctionalBlock {}
public interface IMyOxygenFarm : IMyFunctionalBlock { float GetOutput(); }
public interface IMyParachute : IMyFunctionalBlock {}
public interface IMyPistonBase : IMyFunctionalBlock {}
public interface IMyProjector : IMyFunctionalBlock { int TotalBlocks { get; } int RemainingBlocks { get; } }
public interface IMyRadioAntenna : IMyFunctionalBlock { float Radius { get; set; } }
public interface IMySafeZoneBlock : IMyFunctionalBlock {}
public interface IMySensorBlock : IMyFunctionalBlock {}
public interface IMyShipDrill : IMyFunctionalBlock {}
public interface IMyShipGrinder : IMyFunctionalBlock {}
public interface IMyShipMergeBlock : IMyFunctionalBlock {}
public interface IMyShipWelder : IMyFunctionalBlock {}
public interface IMySlimBlock { float MaxIntegrity { get; } float BuildIntegrity { get; } float CurrentDamage { get; } IMyTerminalBlock FatBlock { get; } }
public interface IMySmallGatlingGun : IMyFunctionalBlock {}
public interface IMySmallMissileLauncher : IMyFunctionalBlock {}
public interface IMySmallMissileLauncherReload : IMySmallMissileLauncher {}
public interface IMySolarPanel : IMyPowerProducer {}
public interface IMyThrust : IMyFunctionalBlock { float CurrentThrust { get; } float MaxThrust { get; } float MaxEffectiveThrust { get; } float ThrustOverride { get; set; } float ThrustOverridePercentage { get; set; } }
public interface IMyTimerBlock : IMyFunctionalBlock {}
public interface IMyTransponder : IMyFunctionalBlock {}
public interface IMyVirtualMass : IMyFunctionalBlock {}
public interface IMyWarhead : IMyFunctionalBlock {}

public enum DoorStatus { Closed, Opening, Open, Closing }
public enum MyShipConnectorStatus { Unconnected, Connectable, Connected }
public enum MyLaserAntennaStatus { Idle, RotatingToTarget, SearchingTargetForAntenna, Connecting, Connected, OutOfRange }
public enum MyPlanetElevation { Sealevel, Surface }
public enum ChargeMode { Auto, Recharge, Discharge }
public enum LandingGearMode { Unlocked, ReadyToLock, Locked }
public enum MyAssemblerMode { Assembly, Disassembly }
public struct MyShipMass { public float BaseMass; public float TotalMass; public float PhysicalMass; }
public struct MyShipVelocities { public Vector3D LinearVelocity; public Vector3D AngularVelocity; }
public struct MyBlockOrientation
{
    public Base6Directions.Direction Forward { get; set; }
    public Base6Directions.Direction Up { get; set; }
    public MyBlockOrientation(Base6Directions.Direction forward, Base6Directions.Direction up) { Forward = forward; Up = up; }
}
public sealed class ListReader<T>
{
    readonly List<T> _items;
    public ListReader(IEnumerable<T> items) { _items = items.ToList(); }
    public int Count => _items.Count;
    public T this[int index] => _items[index];
    public int IndexOf(T item) => _items.IndexOf(item);
}

public static class ListExtensions
{
    public static void AddList<T>(this List<T> target, IEnumerable<T> source)
    {
        target.AddRange(source);
    }
}

public static class NumericExtensions
{
    public static int ToIntSafe(this double value) => value > int.MaxValue ? int.MaxValue : value < int.MinValue ? int.MinValue : (int)value;
    public static int ToIntSafe(this float value) => value > int.MaxValue ? int.MaxValue : value < int.MinValue ? int.MinValue : (int)value;
    public static int ToIntSafe(this VRage.MyFixedPoint value) => ((double)value).ToIntSafe();
}

public static class StringParsingExtensions
{
    public static bool ToBoolean(this string value, bool defaultValue) => bool.TryParse(value, out var parsed) ? parsed : defaultValue;
    public static double ToDouble(this string value, double defaultValue) => double.TryParse(value, out var parsed) ? parsed : defaultValue;
    public static float ToSingle(this string value, float defaultValue) => float.TryParse(value, out var parsed) ? parsed : defaultValue;
    public static int ToInt32(this string value, int defaultValue) => int.TryParse(value, out var parsed) ? parsed : defaultValue;
    public static string ToString(this string value, string defaultValue) => string.IsNullOrEmpty(value) ? defaultValue : value;
}
public sealed class MyComponentContainer
{
    public bool TryGet<T>(out T value) where T : class
    {
        if (typeof(T) == typeof(MyResourceSinkComponent))
        {
            value = (T)(object)new MyResourceSinkComponent();
            return true;
        }
        if (typeof(T) == typeof(MyResourceSourceComponent))
        {
            value = (T)(object)new MyResourceSourceComponent();
            return true;
        }
        value = null;
        return false;
    }
}
public sealed class MyResourceSinkComponent
{
    public ListReader<MyDefinitionId> AcceptedResources { get; } = new ListReader<MyDefinitionId>(Array.Empty<MyDefinitionId>());
    public double CurrentInputByType(MyDefinitionId id) => 0;
    public double MaxRequiredInputByType(MyDefinitionId id) => 0;
}
public sealed class MyResourceSourceComponent
{
    public double CurrentOutputByType(MyDefinitionId id) => 0;
    public double MaxOutputByType(MyDefinitionId id) => 0;
}

public struct MyDefinitionId
{
    public string TypeIdString { get; set; }
    public string SubtypeId { get; set; }
    public string TypeId => TypeIdString;
    public string SubtypeName => SubtypeId;
    public MyDefinitionId(string typeId, string subtypeId) { TypeIdString = typeId; SubtypeId = subtypeId; }
    public MyDefinitionId(Type typeId, string subtypeId) { TypeIdString = typeId.Name; SubtypeId = subtypeId; }
    public static MyDefinitionId Parse(string value)
    {
        var parts = value.Split('/', 2);
        return new MyDefinitionId { TypeIdString = parts[0], SubtypeId = parts.Length > 1 ? parts[1] : "" };
    }
    public static bool TryParse(string value, out MyDefinitionId id)
    {
        id = default;
        if (string.IsNullOrWhiteSpace(value)) return false;
        id = Parse(value);
        return !string.IsNullOrWhiteSpace(id.TypeIdString);
    }
    public override string ToString() => string.IsNullOrWhiteSpace(SubtypeId) ? TypeIdString : TypeIdString + "/" + SubtypeId;
    public static implicit operator MyDefinitionId(MyItemType item) => new MyDefinitionId(item.TypeId, item.SubtypeId);
    public static bool operator ==(MyDefinitionId left, MyDefinitionId right) => string.Equals(left.TypeIdString, right.TypeIdString, StringComparison.OrdinalIgnoreCase) && string.Equals(left.SubtypeId, right.SubtypeId, StringComparison.OrdinalIgnoreCase);
    public static bool operator !=(MyDefinitionId left, MyDefinitionId right) => !(left == right);
    public override bool Equals(object obj) => obj is MyDefinitionId other && this == other;
    public override int GetHashCode() => HashCode.Combine(TypeIdString?.ToLowerInvariant(), SubtypeId?.ToLowerInvariant());
}
public struct MyItemType
{
    public string TypeId { get; set; }
    public string SubtypeId { get; set; }
    public string SubtypeName => SubtypeId;
    public static MyItemType MakeOre(string subtypeId) => new MyItemType { TypeId = "MyObjectBuilder_Ore", SubtypeId = subtypeId };
    public static MyItemType MakeIngot(string subtypeId) => new MyItemType { TypeId = "MyObjectBuilder_Ingot", SubtypeId = subtypeId };
    public static MyItemType MakeComponent(string subtypeId) => new MyItemType { TypeId = "MyObjectBuilder_Component", SubtypeId = subtypeId };
    public static MyItemType MakeTool(string subtypeId) => new MyItemType { TypeId = "MyObjectBuilder_PhysicalGunObject", SubtypeId = subtypeId };
    public static MyItemType MakeAmmo(string subtypeId) => new MyItemType { TypeId = "MyObjectBuilder_AmmoMagazine", SubtypeId = subtypeId };
    public static MyItemType MakePhysicalObject(string subtypeId) => new MyItemType { TypeId = "MyObjectBuilder_PhysicalObject", SubtypeId = subtypeId };
    public static implicit operator MyItemType(MyDefinitionId id) => new MyItemType { TypeId = id.TypeIdString, SubtypeId = id.SubtypeId };
    public override string ToString() => string.IsNullOrWhiteSpace(SubtypeId) ? TypeId : TypeId + "/" + SubtypeId;
    public static bool operator ==(MyItemType left, MyItemType right) => string.Equals(left.TypeId, right.TypeId, StringComparison.OrdinalIgnoreCase) && string.Equals(left.SubtypeId, right.SubtypeId, StringComparison.OrdinalIgnoreCase);
    public static bool operator !=(MyItemType left, MyItemType right) => !(left == right);
    public override bool Equals(object obj) => obj is MyItemType other && this == other;
    public override int GetHashCode() => HashCode.Combine(TypeId?.ToLowerInvariant(), SubtypeId?.ToLowerInvariant());
}
public struct MyInventoryItem { public MyItemType Type { get; set; } public VRage.MyFixedPoint Amount { get; set; } public uint ItemId { get; set; } }
public struct MyProductionItem { public MyDefinitionId BlueprintId { get; set; } public VRage.MyFixedPoint Amount { get; set; } public uint ItemId { get; set; } }
public struct RectangleF
{
    public float X;
    public float Y;
    public float Width;
    public float Height;
    public Vector2 Position { get => new Vector2(X, Y); set { X = value.X; Y = value.Y; } }
    public Vector2 Size { get => new Vector2(Width, Height); set { Width = value.X; Height = value.Y; } }
    public RectangleF(Vector2 position, Vector2 size) { X = position.X; Y = position.Y; Width = size.X; Height = size.Y; }
}
public enum SpriteType { TEXTURE, TEXT }
public struct MySprite
{
    public SpriteType Type;
    public string Data;
    public string FontId;
    public TextAlignment Alignment;
    public Vector2 Position;
    public Vector2 Size;
    public Color? Color;
    public float RotationOrScale;
    public MySprite(SpriteType type = SpriteType.TEXTURE, string data = "", Vector2? position = null, Vector2? size = null, Color? color = null, string fontId = "Debug", TextAlignment alignment = TextAlignment.LEFT, float rotationOrScale = 0f)
    {
        Type = type;
        Data = data;
        FontId = fontId;
        Alignment = alignment;
        Color = color;
        Position = position ?? Vector2.Zero;
        Size = size ?? Vector2.Zero;
        RotationOrScale = rotationOrScale;
    }
    public static MySprite CreateSprite(string data, Vector2 position, Vector2 size) => new MySprite(SpriteType.TEXTURE, data, position: position, size: size);
    public static MySprite CreateText(string text, string fontId, Color color, float scale = 1f, TextAlignment alignment = TextAlignment.LEFT) => new MySprite(SpriteType.TEXT, text, fontId: fontId, color: color, alignment: alignment, rotationOrScale: scale);
}
public sealed class MySpriteDrawFrame : IDisposable
{
    public void Add(MySprite sprite) {}
    public void Dispose() {}
}
public static class Base6Directions
{
    public enum Direction { Forward, Backward, Left, Right, Up, Down }
    public static Direction GetFlippedDirection(Direction direction) => direction switch
    {
        Direction.Forward => Direction.Backward,
        Direction.Backward => Direction.Forward,
        Direction.Left => Direction.Right,
        Direction.Right => Direction.Left,
        Direction.Up => Direction.Down,
        Direction.Down => Direction.Up,
        _ => Direction.Forward,
    };
    public static Vector3I GetVector(Direction direction) => direction switch
    {
        Direction.Backward => new Vector3I(0, 0, 1),
        Direction.Left => new Vector3I(-1, 0, 0),
        Direction.Right => new Vector3I(1, 0, 0),
        Direction.Up => new Vector3I(0, 1, 0),
        Direction.Down => new Vector3I(0, -1, 0),
        _ => new Vector3I(0, 0, -1),
    };
    public static Direction GetDirection(Vector3I vector)
    {
        var ax = Math.Abs(vector.X);
        var ay = Math.Abs(vector.Y);
        var az = Math.Abs(vector.Z);
        if (ay >= ax && ay >= az) return vector.Y >= 0 ? Direction.Up : Direction.Down;
        if (ax >= ay && ax >= az) return vector.X >= 0 ? Direction.Right : Direction.Left;
        return vector.Z >= 0 ? Direction.Backward : Direction.Forward;
    }
}

public sealed class VirtualGrid : IMyCubeGrid
{
    readonly VirtualBlock? _block;
    public VirtualGrid(VirtualBlock? block = null) { _block = block; }
    public string CustomName => _block?.ReadString("grid_name", "Virtual Grid") ?? "Virtual Grid";
    public float GridSize => _block?.ReadFloat("grid_size", 1f) ?? 1f;
    public bool IsStatic => _block?.ReadBool("grid_is_static") ?? false;
    public MatrixD WorldMatrix => MatrixD.Identity;
    public IMySlimBlock GetCubeBlock(Vector3I position) => new VirtualSlimBlock(_block);
    public bool IsSameConstructAs(IMyCubeGrid other) => true;
}

public sealed class VirtualTerminalProperty : ITerminalProperty
{
    public string Id { get; init; } = "";
    public string TypeName { get; init; } = "Boolean";
}

public sealed class VirtualTerminalAction : ITerminalAction
{
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
}

public sealed class VirtualGridTerminalSystem : IMyGridTerminalSystem
{
    readonly VirtualContext _context;
    public VirtualGridTerminalSystem(VirtualContext context) { _context = context; }
    public void GetBlocks(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null)
    {
        foreach (var block in _context.Blocks)
        {
            if (collect == null || collect(block)) blocks.Add(block);
        }
    }

    public void GetBlocksOfType<T>(List<T> blocks, Func<T, bool> collect = null) where T : class
    {
        foreach (var block in _context.Blocks)
        {
            if (!block.Supports(typeof(T))) continue;
            if (block is T typed && (collect == null || collect(typed))) blocks.Add(typed);
        }
    }
    public void GetBlocksOfType<T>(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null) where T : class, IMyTerminalBlock
    {
        foreach (var block in _context.Blocks)
        {
            if (!block.Supports(typeof(T))) continue;
            if (collect == null || collect(block)) blocks.Add(block);
        }
    }
    public IMyTerminalBlock GetBlockWithName(string name) => _context.Blocks.FirstOrDefault(block => string.Equals(block.CustomName, name, StringComparison.OrdinalIgnoreCase));
    public IMyTerminalBlock GetBlockWithId(long id) => _context.Blocks.FirstOrDefault(block => block.EntityId == id);
    public void SearchBlocksOfName(string name, List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null)
    {
        foreach (var block in _context.Blocks)
        {
            if (!block.CustomName.Contains(name, StringComparison.OrdinalIgnoreCase)) continue;
            if (collect == null || collect(block)) blocks.Add(block);
        }
    }

    public void GetBlockGroups(List<IMyBlockGroup> blockGroups, Func<IMyBlockGroup, bool> collect = null)
    {
        var group = new VirtualBlockGroup("All Blocks", _context.Blocks);
        if (collect == null || collect(group)) blockGroups.Add(group);
    }

    public IMyBlockGroup GetBlockGroupWithName(string name) => new VirtualBlockGroup(name, _context.Blocks);
    public bool CanAccess(IMyTerminalBlock block) => true;
    public bool CanAccess(IMyTerminalBlock first, IMyTerminalBlock second) => true;
}

public sealed class VirtualBlockGroup : IMyBlockGroup
{
    readonly List<VirtualBlock> _blocks;
    public string Name { get; }
    public VirtualBlockGroup(string name, List<VirtualBlock> blocks) { Name = name; _blocks = blocks; }
    public void GetBlocks(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null)
    {
        foreach (var block in _blocks)
        {
            if (collect == null || collect(block)) blocks.Add(block);
        }
    }
}

public sealed class VirtualInventory : IMyInventory
{
    readonly List<MyInventoryItem> _items = new();
    readonly VirtualContext _context;
    public double CurrentVolume { get; }
    public double MaxVolume { get; }
    public double CurrentMass { get; }
    public int ItemCount => _items.Count;
    public bool IsFull => MaxVolume > 0 && CurrentVolume >= MaxVolume;
    public VirtualInventory(VirtualContext context, JsonObject inventory)
    {
        _context = context;
        CurrentVolume = ReadDouble(inventory, "current_volume");
        MaxVolume = ReadDouble(inventory, "max_volume");
        CurrentMass = ReadDouble(inventory, "current_mass");
        foreach (var itemNode in inventory["items"]?.AsArray() ?? new JsonArray())
        {
            if (itemNode is not JsonObject item) continue;
            _items.Add(new MyInventoryItem
            {
                Type = new MyItemType { TypeId = ReadString(item, "type_id"), SubtypeId = ReadString(item, "subtype_id") },
                Amount = ReadDouble(item, "amount"),
                ItemId = (uint)ReadDouble(item, "item_id"),
            });
        }
    }
    public void GetItems(List<MyInventoryItem> items) => items.AddRange(_items);
    public MyInventoryItem? GetItemAt(int index) => index >= 0 && index < _items.Count ? _items[index] : null;
    public MyInventoryItem? FindItem(MyItemType itemType)
    {
        foreach (var item in _items)
        {
            if (item.Type == itemType) return item;
        }
        return null;
    }
    public MyInventoryItem? FindItem(MyDefinitionId itemType) => FindItem((MyItemType)itemType);
    public VRage.MyFixedPoint GetItemAmount(MyItemType itemType)
    {
        double amount = 0;
        foreach (var item in _items)
        {
            if (item.Type == itemType) amount += (double)item.Amount;
        }
        return amount;
    }
    public VRage.MyFixedPoint GetItemAmount(MyDefinitionId itemType) => GetItemAmount((MyItemType)itemType);
    public bool CanItemsBeAdded(VRage.MyFixedPoint amount, MyItemType itemType) => !IsFull;
    public bool CanItemsBeAdded(VRage.MyFixedPoint amount, MyDefinitionId itemType) => CanItemsBeAdded(amount, (MyItemType)itemType);
    public bool CanTransferItemTo(IMyInventory destinationInventory, MyItemType itemType) => true;
    public bool CanTransferItemTo(IMyInventory destinationInventory, MyDefinitionId itemType) => CanTransferItemTo(destinationInventory, (MyItemType)itemType);
    public bool TransferItemTo(IMyInventory destinationInventory, int sourceItemIndex, int? targetItemIndex = null, bool? stackIfPossible = null, VRage.MyFixedPoint? amount = null)
    {
        _context.Reject("unsupported_member:IMyInventory.TransferItemTo");
        return false;
    }
    public bool IsConnectedTo(IMyInventory other) => true;
    static string ReadString(JsonObject obj, string key) => obj.TryGetPropertyValue(key, out var value) && value != null ? value.ToString() : "";
    static double ReadDouble(JsonObject obj, string key) => obj.TryGetPropertyValue(key, out var value) && value != null && double.TryParse(value.ToString(), out var parsed) ? parsed : 0;
}

public sealed class VirtualSlimBlock : IMySlimBlock
{
    readonly VirtualBlock? _block;
    public VirtualSlimBlock(VirtualBlock? block) { _block = block; }
    public float MaxIntegrity => _block?.ReadFloat("max_integrity", 1f) ?? 1f;
    public float BuildIntegrity => _block?.ReadFloat("build_integrity", MaxIntegrity) ?? 1f;
    public float CurrentDamage => _block?.ReadFloat("current_damage") ?? 0f;
    public IMyTerminalBlock FatBlock => _block;
}

public sealed class VirtualBlock :
    IMyProgrammableBlock, IMyTextPanel, IMyTextSurfaceProvider, IMyAirtightHangarDoor, IMyInteriorLight, IMyReflectorLight,
    IMySoundBlock, IMyCargoContainer, IMyAssembler, IMyRefinery, IMyGasTank, IMyGasGenerator, IMyReactor, IMyBatteryBlock,
    IMyCockpit, IMyRemoteControl, IMyShipConnector, IMyLaserAntenna, IMyAirVent, IMyCollector, IMyConveyorSorter, IMyBeacon,
    IMyBroadcastController, IMyButtonPanel, IMyCameraBlock, IMyControlPanel, IMyCryoChamber, IMyDecoy, IMyFarmPlotLogic,
    IMyGravityGeneratorSphere, IMyGyro, IMyJumpDrive, IMyLandingGear, IMyLargeGatlingTurret, IMyLargeInteriorTurret,
    IMyLargeMissileTurret, IMyMedicalRoom, IMyMotorStator, IMyOreDetector, IMyOxygenFarm, IMyParachute, IMyPistonBase,
    IMyProjector, IMyRadioAntenna, IMySafeZoneBlock, IMySensorBlock, IMyShipDrill, IMyShipGrinder, IMyShipMergeBlock,
    IMyShipWelder, IMySmallGatlingGun, IMySmallMissileLauncherReload, IMySolarPanel, IMyThrust, IMyTimerBlock,
    IMyTransponder, IMyVirtualMass, IMyWarhead
{
    readonly VirtualContext _context;
    readonly JsonObject _source;
    readonly List<VirtualInventory> _inventories = new();
    readonly List<MyProductionItem> _productionQueue = new();
    readonly Dictionary<string, object> _terminalOverlay = new(StringComparer.OrdinalIgnoreCase);
    string _text;
    string _customData;
    Vector2 _surfaceSize;
    Vector2 _textureSize;
    string _font = "Debug";
    float _fontSize = 0.6f;
    float _textPadding = 2f;
    TextAlignment _alignment = TextAlignment.LEFT;
    ContentType _contentType = ContentType.TEXT_AND_IMAGE;
    bool _hasTextSurfaceMetadata;
    bool _textSurfaceStyleDirty;
    bool _enabled;
    Color _color;
    public long EntityId { get; }
    public string Name => CustomName;
    public string CustomName { get; set; }
    public string CustomNameWithFaction => ReadString("custom_name_with_faction", CustomName);
    public string CustomData { get => _customData; set { _customData = value ?? ""; _context.RecordClientOverlayWrite("IMyTerminalBlock.CustomData", EntityId, value); } }
    public void SetInitialCustomData(string value) => _customData = value ?? "";
    public string DisplayNameText => CustomName;
    public string DefinitionDisplayNameText => ReadString("definition_display_name", BlockDefinition.SubtypeId);
    public string DetailedInfo => ReadString("detailed_info");
    public string CustomInfo => ReadString("custom_info");
    public bool IsWorking => Enabled;
    public bool IsFunctional => true;
    public bool HasInventory => _inventories.Count > 0;
    public bool ShowInInventory { get; set; }
    public int InventoryCount => Math.Max(_inventories.Count, ReadInt("inventory_count"));
    public long OwnerId => ReadLong("owner_id");
    public IMyCubeGrid CubeGrid => new VirtualGrid(this);
    public MyDefinitionId BlockDefinition { get; }
    public MyComponentContainer Components { get; } = new MyComponentContainer();
    public Vector3I Position => new Vector3I(ReadInt("grid_x"), ReadInt("grid_y"), ReadInt("grid_z"));
    public MyBlockOrientation Orientation { get; } = new MyBlockOrientation(Base6Directions.Direction.Forward, Base6Directions.Direction.Up);
    public MatrixD WorldMatrix => MatrixD.Identity;
    public int SurfaceCount => Math.Max(1, ReadInt("surface_count"));
    public string Font { get => _font; set { _font = value ?? "Debug"; _textSurfaceStyleDirty = true; } }
    public float FontSize { get => _fontSize; set { _fontSize = value; _textSurfaceStyleDirty = true; } }
    public float TextPadding { get => _textPadding; set { _textPadding = value; _textSurfaceStyleDirty = true; } }
    public TextAlignment Alignment { get => _alignment; set { _alignment = value; _textSurfaceStyleDirty = true; } }
    public ContentType ContentType { get => _contentType; set { _contentType = value; _textSurfaceStyleDirty = true; } }
    public Color ScriptBackgroundColor { get; set; } = new Color(0, 0, 0);
    public Color ScriptForegroundColor { get; set; } = new Color(255, 255, 255);
    public string Script { get; set; } = "";
    public bool Closed => ReadBool("closed");
    public Vector2 SurfaceSize => _surfaceSize;
    public Vector2 TextureSize => _textureSize;
    public float OpenRatio => (float)ReadDouble("door_open_ratio");
    public DoorStatus Status => Enum.TryParse<DoorStatus>(ReadString("door_status"), true, out var status) ? status : (OpenRatio > 0.9f ? DoorStatus.Open : DoorStatus.Closed);
    public bool CooperativeMode { get; set; }
    MyAssemblerMode _assemblerMode;
    public MyAssemblerMode Mode { get => _assemblerMode; set { _assemblerMode = value; _context.Reject("unsupported_member:IMyAssembler.Mode.set"); } }
    public int QueueCount => Math.Max(_productionQueue.Count, ReadInt("production_queue_count"));
    public bool IsQueueEmpty => QueueCount == 0;
    bool _repeating;
    public bool Repeating { get => _repeating; set { _repeating = value; _context.Reject("unsupported_member:IMyAssembler.Repeating"); } }
    public bool IsProducing => ReadBool("is_producing", Enabled);
    public double FilledRatio => ReadDouble("gas_filled_ratio");
    public double Capacity => ReadDouble("capacity");
    public bool Stockpile { get; set; }
    public bool AutoRefillBottles { get; set; }
    public bool AutoRefill { get; set; }
    public bool UseConveyorSystem { get; set; }
    public float CurrentOutput => (float)ReadDouble("current_output");
    public float MaxOutput => (float)ReadDouble("max_output");
    public float CurrentStoredPower => (float)ReadDouble("current_stored_power");
    public float MaxStoredPower => (float)ReadDouble("max_stored_power");
    public float CurrentInput => (float)ReadDouble("current_input");
    ChargeMode _chargeMode;
    public ChargeMode ChargeMode { get => _chargeMode; set { _chargeMode = value; _context.Reject("unsupported_member:IMyBatteryBlock.ChargeMode.set"); } }
    public float MaxStoredPowerJump => (float)ReadDouble("max_stored_power");
    bool _dampenersOverride;
    public bool DampenersOverride { get => _dampenersOverride; set { _dampenersOverride = value; _context.Reject("unsupported_member:IMyShipController.DampenersOverride.set"); } }
    public bool IsUnderControl => ReadBool("is_under_control");
    public bool IsMainCockpit { get; set; }
    public bool CanControlShip => ReadBool("can_control_ship", true);
    public bool ControlThrusters { get; set; } = true;
    public Vector3D MoveIndicator => new Vector3D(ReadDouble("move_x"), ReadDouble("move_y"), ReadDouble("move_z"));
    public MyShipConnectorStatus StatusConnector => MyShipConnectorStatus.Unconnected;
    MyShipConnectorStatus IMyShipConnector.Status => MyShipConnectorStatus.Unconnected;
    IMyShipConnector IMyShipConnector.OtherConnector => null;
    MyLaserAntennaStatus IMyLaserAntenna.Status => MyLaserAntennaStatus.Idle;
    public bool CanPressurize => ReadBool("can_pressurize", true);
    public LandingGearMode LockMode => Enum.TryParse<LandingGearMode>(ReadString("lock_mode"), true, out var lockMode) ? lockMode : LandingGearMode.Unlocked;
    public bool IsLocked => LockMode == LandingGearMode.Locked || ReadBool("is_locked");
    public int TotalBlocks => ReadInt("total_blocks");
    public int RemainingBlocks => ReadInt("remaining_blocks");
    public float CurrentThrust => (float)ReadDouble("current_thrust");
    public float MaxThrust => (float)ReadDouble("max_thrust");
    public float MaxEffectiveThrust => (float)ReadDouble("max_effective_thrust", MaxThrust);
    public float ThrustOverride { get => (float)ReadDouble("thrust_override"); set => _context.Reject("unsupported_member:IMyThrust.ThrustOverride.set"); }
    public float ThrustOverridePercentage { get => (float)ReadDouble("thrust_override_percentage"); set => _context.Reject("unsupported_member:IMyThrust.ThrustOverridePercentage.set"); }
    public float TargetVelocityRPM { get => (float)ReadDouble("target_velocity_rpm"); set => _context.Reject("unsupported_member:IMyMotorStator.TargetVelocityRPM.set"); }
    public float TargetVelocityRad { get => (float)ReadDouble("target_velocity_rad"); set => _context.Reject("unsupported_member:IMyMotorStator.TargetVelocityRad.set"); }
    public bool RotorLock { get => ReadBool("rotor_lock"); set => _context.Reject("unsupported_member:IMyMotorStator.RotorLock.set"); }
    public IMyTerminalBlock Top => this;
    public IMyCubeGrid TopGrid => CubeGrid;
    public float LoopPeriod { get; set; }
    public string SelectedSound { get; set; } = "";
    public float Radius { get; set; }
    public float Intensity { get; set; }
    public float BlinkIntervalSeconds { get; set; }
    public float BlinkLength { get; set; }

    public VirtualBlock(VirtualContext context, JsonObject source, int index)
    {
        _context = context;
        _source = source;
        EntityId = ReadLong("entity_id", index + 1);
        CustomName = ReadString("name", "Block " + EntityId);
        _customData = ReadString("custom_data");
        _text = ReadString("text");
        _enabled = ReadBool("enabled", true);
        _hasTextSurfaceMetadata = HasSnapshotField("font") || HasSnapshotField("font_size") || HasSnapshotField("text_padding") ||
            HasSnapshotField("alignment") || HasSnapshotField("content_type") || HasSnapshotField("surface_size") || HasSnapshotField("texture_size");
        _font = ReadString("font", "Debug");
        _fontSize = ReadFloat("font_size", 0.6f);
        _textPadding = ReadFloat("text_padding", 2f);
        if (Enum.TryParse<TextAlignment>(ReadString("alignment"), true, out var alignment)) _alignment = alignment;
        if (Enum.TryParse<ContentType>(ReadString("content_type"), true, out var contentType)) _contentType = contentType;
        _surfaceSize = ReadVector2("surface_size", 512, 512);
        _textureSize = ReadVector2("texture_size", 512, 512);
        ShowInInventory = ReadBool("show_in_inventory", true);
        BlockDefinition = new MyDefinitionId { TypeIdString = ReadString("type"), SubtypeId = ReadString("subtype") };
        _color = ReadColor();
        _chargeMode = Enum.TryParse<ChargeMode>(ReadString("charge_mode"), true, out var chargeMode) ? chargeMode : ChargeMode.Auto;
        _assemblerMode = ReadString("assembler_mode").Contains("dis", StringComparison.OrdinalIgnoreCase) ? MyAssemblerMode.Disassembly : MyAssemblerMode.Assembly;
        Radius = ReadFloat("radius");
        Intensity = ReadFloat("intensity");
        foreach (var inventoryNode in source["inventories"]?.AsArray() ?? new JsonArray())
        {
            if (inventoryNode is JsonObject inventory) _inventories.Add(new VirtualInventory(context, inventory));
        }
        foreach (var queueNode in source["production_queue"]?.AsArray() ?? new JsonArray())
        {
            if (queueNode is not JsonObject item) continue;
            _productionQueue.Add(new MyProductionItem
            {
                BlueprintId = MyDefinitionId.Parse(ReadString(item, "blueprint_id")),
                Amount = ReadDouble(item, "amount"),
                ItemId = (uint)ReadDouble(item, "item_id"),
            });
        }
    }

    public bool Enabled
    {
        get => _enabled;
        set
        {
            if (_enabled == value) return;
            _enabled = value;
            _context.AddCommand(new JsonObject { ["kind"] = "set_block_enabled", ["block_entity_id"] = EntityId, ["enabled"] = value });
        }
    }

    public Color Color
    {
        get => _color;
        set
        {
            _color = value;
            _context.AddCommand(new JsonObject
            {
                ["kind"] = "set_light_color",
                ["block_entity_id"] = EntityId,
                ["color"] = new JsonObject { ["r"] = value.R, ["g"] = value.G, ["b"] = value.B, ["a"] = value.A },
            });
        }
    }

    public bool Supports(Type type)
    {
        var name = type.Name;
        if (name == nameof(IMyTerminalBlock) || name == nameof(IMyFunctionalBlock)) return true;
        if (name == nameof(IMyTextSurface) || name == nameof(IMyTextPanel) || name == nameof(IMyTextSurfaceProvider)) return IsFlag("is_lcd") || SurfaceCount > 0 || Contains("text");
        if (name == nameof(IMyDoor) || name == nameof(IMyAirtightHangarDoor)) return IsFlag("is_door") || IsFlag("is_hangar_door") || Contains("door");
        if (name == nameof(IMyLightingBlock) || name == nameof(IMyInteriorLight) || name == nameof(IMyReflectorLight)) return IsFlag("is_light") || Contains("light");
        if (name == nameof(IMySoundBlock)) return IsFlag("is_sound") || Contains("sound");
        if (name == nameof(IMyCargoContainer)) return IsFlag("is_cargo") || Contains("cargo") || Contains("container");
        if (name == nameof(IMyAssembler)) return IsFlag("is_assembler") || Contains("assembler");
        if (name == nameof(IMyRefinery)) return IsFlag("is_refinery") || Contains("refinery");
        if (name == nameof(IMyGasGenerator)) return IsFlag("is_gas_generator") || Contains("generator");
        if (name == nameof(IMyGasTank)) return IsFlag("is_gas_tank") || Contains("tank");
        if (name == nameof(IMyReactor)) return IsFlag("is_reactor") || Contains("reactor");
        if (name == nameof(IMyShipConnector)) return IsFlag("is_connector") || Contains("connector");
        return Contains(name.Replace("IMy", ""));
    }

    public IMyInventory GetInventory(int index = 0) => index >= 0 && index < _inventories.Count ? _inventories[index] : new VirtualInventory(_context, new JsonObject());
    public Vector3D GetPosition() => new Vector3D(ReadDouble("x"), ReadDouble("y"), ReadDouble("z"));
    public T GetValue<T>(string id)
    {
        object value = id switch
        {
            "OnOff" => Enabled,
            "FontSize" => FontSize,
            "Radius" => Radius,
            "Intensity" => Intensity,
            "ControlModule.Inputs" => ControlModuleInputs(),
            _ => default(T),
        };
        return value is T typed ? typed : default;
    }
    public void SetValue<T>(string id, T value)
    {
        if (id.StartsWith("ControlModule.", StringComparison.OrdinalIgnoreCase))
        {
            _terminalOverlay[id] = value!;
            return;
        }
        _context.Reject("unsupported_member:IMyTerminalBlock.SetValue:" + id);
    }
    public void GetQueue(List<MyProductionItem> queue) => queue.AddRange(_productionQueue);
    public bool CanUseBlueprint(MyDefinitionId blueprint) => true;
    public void ClearQueue() => _context.Reject("unsupported_member:IMyAssembler.ClearQueue");
    public void AddQueueItem(MyDefinitionId blueprint, VRage.MyFixedPoint amount) => _context.Reject("unsupported_member:IMyAssembler.AddQueueItem");
    public void InsertQueueItem(int idx, MyDefinitionId blueprint, VRage.MyFixedPoint amount) => _context.Reject("unsupported_member:IMyAssembler.InsertQueueItem");
    public void RemoveQueueItem(int idx, VRage.MyFixedPoint? amount = null) => _context.Reject("unsupported_member:IMyAssembler.RemoveQueueItem");
    public void MoveQueueItemRequest(uint queueItemId, int targetIdx) => _context.Reject("unsupported_member:IMyAssembler.MoveQueueItemRequest");
    public void GetProperties(List<ITerminalProperty> result, Func<ITerminalProperty, bool> collect = null)
    {
        foreach (var property in TerminalProperties())
        {
            if (collect == null || collect(property)) result.Add(property);
        }
    }
    public ITerminalProperty GetProperty(string id) =>
        TerminalProperties().FirstOrDefault(property => string.Equals(property.Id, id, StringComparison.OrdinalIgnoreCase))
        ?? new VirtualTerminalProperty { Id = id, TypeName = "Boolean" };
    public ITerminalAction GetActionWithName(string name) =>
        TerminalActions().FirstOrDefault(action =>
            string.Equals(action.Id, name, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(action.Name, name, StringComparison.OrdinalIgnoreCase));
    public void GetActions(List<ITerminalAction> result, Func<ITerminalAction, bool> collect = null)
    {
        foreach (var action in TerminalActions())
        {
            if (collect == null || collect(action)) result.Add(action);
        }
    }
    public bool HasLocalPlayerAccess() => ReadBool("has_local_player_access", true);
    public bool HasNobodyPlayerAccessToBlock() => ReadBool("has_nobody_player_access", true);
    public bool HasPlayerAccess(long playerId) => ReadBool("has_player_access", HasLocalPlayerAccess());
    public bool HasPlayerAccessWithNobodyCheck(long playerId) => ReadBool("has_player_access_with_nobody_check", HasPlayerAccess(playerId) || HasNobodyPlayerAccessToBlock());
    public bool IsSameConstructAs(IMyTerminalBlock other) => ReadBool("same_construct", true);
    public string GetOwnerFactionTag() => ReadString("owner_faction_tag");
    public IMyTextSurface GetSurface(int index) => new VirtualTextSurface(this, Math.Max(0, index));
    public void WriteText(string text, bool append = false) => WriteTextSurface(0, text, append);
    internal void WriteTextSurface(int surfaceIndex, string text, bool append = false)
    {
        _text = append ? _text + text : text;
        var command = new JsonObject
        {
            ["kind"] = "write_text_surface",
            ["block_entity_id"] = EntityId,
            ["surface_index"] = surfaceIndex,
            ["append"] = append,
            ["text"] = text,
        };
        if (_hasTextSurfaceMetadata || _textSurfaceStyleDirty)
        {
            command["font"] = Font;
            command["font_size"] = Math.Round(FontSize, 3);
            command["text_padding"] = Math.Round(TextPadding, 3);
            command["alignment"] = Alignment.ToString();
            command["content_type"] = ContentType.ToString();
        }
        _context.AddCommand(command);
    }
    public void WriteText(StringBuilder text, bool append = false) => WriteText(text.ToString(), append);
    public void WritePublicTitle(string value, bool append = false) {}
    public MySpriteDrawFrame DrawFrame() => new MySpriteDrawFrame();
    public Vector2 MeasureStringInPixels(StringBuilder text, string font, float scale) => new Vector2((text?.Length ?? 0) * 10f * scale, 20f * scale);
    public string GetText() => _text;
    public void OpenDoor() => _context.AddCommand(new JsonObject { ["kind"] = "set_door_open", ["block_entity_id"] = EntityId, ["open"] = true });
    public void CloseDoor() => _context.AddCommand(new JsonObject { ["kind"] = "set_door_open", ["block_entity_id"] = EntityId, ["open"] = false });
    public void Play() {}
    public void Stop() {}
    public bool TryGetPlanetElevation(MyPlanetElevation detail, out double elevation) { elevation = double.NaN; return false; }
    public MyShipMass CalculateShipMass() => new MyShipMass();
    public MyShipVelocities GetShipVelocities() => new MyShipVelocities();
    public Vector3D GetNaturalGravity() => new Vector3D();
    public Vector3D GetArtificialGravity() => new Vector3D();
    public Vector3D GetTotalGravity() => new Vector3D();
    public double GetShipSpeed() => GetShipVelocities().LinearVelocity.Length();
    public float GetOxygenLevel() => (float)ReadDouble("oxygen_level");
    public float GetOutput() => (float)ReadDouble("oxygen_farm_output");
    public string GetDetailedInfoWithoutRequiredInput() => DetailedInfo;

    Dictionary<string, object> ControlModuleInputs()
    {
        var inputs = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in _terminalOverlay)
        {
            if (item.Key.StartsWith("ControlModule.", StringComparison.OrdinalIgnoreCase))
            {
                inputs[item.Key] = item.Value;
            }
        }
        return inputs;
    }

    bool IsFlag(string key) => ReadBool(key, false);
    bool Contains(string token)
    {
        var needle = token.ToLowerInvariant();
        return CustomName.ToLowerInvariant().Contains(needle)
            || ReadString("type").ToLowerInvariant().Contains(needle)
            || ReadString("subtype").ToLowerInvariant().Contains(needle);
    }
    IEnumerable<ITerminalAction> TerminalActions()
    {
        var actions = _source["terminal_actions"] as JsonArray;
        if (actions == null || actions.Count == 0)
        {
            yield return new VirtualTerminalAction { Id = "OnOff_On", Name = "On/Off" };
            yield return new VirtualTerminalAction { Id = "OnOff_Off", Name = "On/Off" };
            yield break;
        }
        foreach (var node in actions)
        {
            if (node is not JsonObject action) continue;
            var id = ReadString(action, "id");
            if (string.IsNullOrWhiteSpace(id)) continue;
            yield return new VirtualTerminalAction
            {
                Id = id,
                Name = ReadString(action, "name", id),
            };
        }
    }
    IEnumerable<ITerminalProperty> TerminalProperties()
    {
        var properties = _source["terminal_properties"] as JsonArray;
        if (properties == null || properties.Count == 0)
        {
            yield return new VirtualTerminalProperty { Id = "OnOff", TypeName = "Boolean" };
            yield return new VirtualTerminalProperty { Id = "ShowInInventory", TypeName = "Boolean" };
            yield break;
        }
        foreach (var node in properties)
        {
            if (node is not JsonObject property) continue;
            var id = ReadString(property, "id");
            if (string.IsNullOrWhiteSpace(id)) continue;
            yield return new VirtualTerminalProperty
            {
                Id = id,
                TypeName = ReadString(property, "type", ReadString(property, "type_name", "Boolean")),
            };
        }
    }
    public string ReadString(string key, string fallback = "") => _source.TryGetPropertyValue(key, out var value) && value != null ? value.ToString() : fallback;
    bool HasSnapshotField(string key) => _source.TryGetPropertyValue(key, out var value) && value != null;
    public bool ReadBool(string key, bool fallback = false) => _source.TryGetPropertyValue(key, out var value) && value != null && bool.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    int ReadInt(string key) => _source.TryGetPropertyValue(key, out var value) && value != null && int.TryParse(value.ToString(), out var parsed) ? parsed : 0;
    long ReadLong(string key, long fallback = 0) => _source.TryGetPropertyValue(key, out var value) && value != null && long.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    double ReadDouble(string key, double fallback = 0) => _source.TryGetPropertyValue(key, out var value) && value != null && double.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    public float ReadFloat(string key, float fallback = 0f) => _source.TryGetPropertyValue(key, out var value) && value != null && float.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    Vector2 ReadVector2(string key, float fallbackX, float fallbackY)
    {
        var obj = _source[key] as JsonObject;
        if (obj == null) return new Vector2(fallbackX, fallbackY);
        return new Vector2(ReadFloat(obj, "x", fallbackX), ReadFloat(obj, "y", fallbackY));
    }
    static float ReadFloat(JsonObject source, string key, float fallback) => source.TryGetPropertyValue(key, out var value) && value != null && float.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    Color ReadColor()
    {
        var color = _source["color"] as JsonObject;
        return color == null ? new Color(255, 255, 255) : new Color(ReadInt(color, "r", 255), ReadInt(color, "g", 255), ReadInt(color, "b", 255), ReadInt(color, "a", 255));
    }
    static int ReadInt(JsonObject source, string key, int fallback) => source.TryGetPropertyValue(key, out var value) && value != null && int.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    static string ReadString(JsonObject source, string key, string fallback = "") => source.TryGetPropertyValue(key, out var value) && value != null ? value.ToString() : fallback;
    static double ReadDouble(JsonObject source, string key) => source.TryGetPropertyValue(key, out var value) && value != null && double.TryParse(value.ToString(), out var parsed) ? parsed : 0;
}

public sealed class VirtualTextSurface : IMyTextSurface
{
    readonly VirtualBlock _block;
    readonly int _index;
    public VirtualTextSurface(VirtualBlock block, int index) { _block = block; _index = index; }
    public string Font { get => _block.Font; set => _block.Font = value; }
    public float FontSize { get => _block.FontSize; set => _block.FontSize = value; }
    public float TextPadding { get => _block.TextPadding; set => _block.TextPadding = value; }
    public TextAlignment Alignment { get => _block.Alignment; set => _block.Alignment = value; }
    public ContentType ContentType { get => _block.ContentType; set => _block.ContentType = value; }
    public Color ScriptBackgroundColor { get => _block.ScriptBackgroundColor; set => _block.ScriptBackgroundColor = value; }
    public Color ScriptForegroundColor { get => _block.ScriptForegroundColor; set => _block.ScriptForegroundColor = value; }
    public string Script { get => _block.Script; set => _block.Script = value; }
    public Vector2 SurfaceSize => _block.SurfaceSize;
    public Vector2 TextureSize => _block.TextureSize;
    public void WriteText(string text, bool append = false) => _block.WriteTextSurface(_index, text, append);
    public void WriteText(StringBuilder text, bool append = false) => WriteText(text.ToString(), append);
    public string GetText() => _block.GetText();
    public MySpriteDrawFrame DrawFrame() => _block.DrawFrame();
    public Vector2 MeasureStringInPixels(StringBuilder text, string font, float scale) => _block.MeasureStringInPixels(text, font, scale);
}

namespace VRage
{
    public struct MyFixedPoint
    {
        readonly double _value;
        public MyFixedPoint(double value) { _value = value; }
        public override string ToString() => _value.ToString();
        public static implicit operator MyFixedPoint(double value) => new MyFixedPoint(value);
        public static implicit operator MyFixedPoint(int value) => new MyFixedPoint(value);
        public static explicit operator double(MyFixedPoint value) => value._value;
        public static explicit operator int(MyFixedPoint value) => (int)value._value;
        public static MyFixedPoint operator +(MyFixedPoint left, MyFixedPoint right) => new MyFixedPoint(left._value + right._value);
        public static MyFixedPoint operator -(MyFixedPoint left, MyFixedPoint right) => new MyFixedPoint(left._value - right._value);
        public static bool operator >(MyFixedPoint left, MyFixedPoint right) => left._value > right._value;
        public static bool operator <(MyFixedPoint left, MyFixedPoint right) => left._value < right._value;
        public static bool operator >=(MyFixedPoint left, MyFixedPoint right) => left._value >= right._value;
        public static bool operator <=(MyFixedPoint left, MyFixedPoint right) => left._value <= right._value;
        public static bool operator ==(MyFixedPoint left, MyFixedPoint right) => Math.Abs(left._value - right._value) < 0.0000001;
        public static bool operator !=(MyFixedPoint left, MyFixedPoint right) => !(left == right);
        public override bool Equals(object obj) => obj is MyFixedPoint other && this == other;
        public override int GetHashCode() => _value.GetHashCode();
    }
}

namespace VRageMath
{
    public struct Color
    {
        public int R; public int G; public int B; public int A;
        public static Color Black => new Color(0, 0, 0, 255);
        public static Color Red => new Color(255, 0, 0, 255);
        public static Color White => new Color(255, 255, 255, 255);
        public static Color Transparent => new Color(0, 0, 0, 0);
        public Color(int r, int g, int b, int a = 255) { R = r; G = g; B = b; A = a; }
        public static bool operator ==(Color left, Color right) => left.R == right.R && left.G == right.G && left.B == right.B && left.A == right.A;
        public static bool operator !=(Color left, Color right) => !(left == right);
        public override bool Equals(object obj) => obj is Color other && this == other;
        public override int GetHashCode() => HashCode.Combine(R, G, B, A);
    }
    public struct Vector2
    {
        public float X; public float Y;
        public Vector2(float x, float y) { X = x; Y = y; }
        public static Vector2 Zero => new Vector2(0, 0);
        public static Vector2 One => new Vector2(1, 1);
        public static Vector2 UnitX => new Vector2(1, 0);
        public static Vector2 UnitY => new Vector2(0, 1);
        public float Length() => (float)Math.Sqrt(X * X + Y * Y);
        public float LengthSquared() => X * X + Y * Y;
        public void Normalize()
        {
            var length = Length();
            if (length <= 0) return;
            X = (float)(X / length);
            Y = (float)(Y / length);
        }
        public static float Dot(Vector2 a, Vector2 b) => a.X * b.X + a.Y * b.Y;
        public static Vector2 Normalize(Vector2 value)
        {
            value.Normalize();
            return value;
        }
        public static bool IsZero(ref Vector2 value, float epsilon = 0.00001f) => Math.Abs(value.X) <= epsilon && Math.Abs(value.Y) <= epsilon;
        public static Vector2 SignNonZero(Vector2 value) => new Vector2(value.X < 0 ? -1 : 1, value.Y < 0 ? -1 : 1);
        public static Vector2 operator +(Vector2 a, Vector2 b) => new Vector2(a.X + b.X, a.Y + b.Y);
        public static Vector2 operator +(Vector2 a, float b) => new Vector2(a.X + b, a.Y + b);
        public static Vector2 operator -(Vector2 a, Vector2 b) => new Vector2(a.X - b.X, a.Y - b.Y);
        public static Vector2 operator -(Vector2 a, float b) => new Vector2(a.X - b, a.Y - b);
        public static Vector2 operator -(Vector2 a) => new Vector2(-a.X, -a.Y);
        public static Vector2 operator *(Vector2 a, float b) => new Vector2(a.X * b, a.Y * b);
        public static Vector2 operator *(float b, Vector2 a) => a * b;
        public static Vector2 operator *(Vector2 a, Vector2 b) => new Vector2(a.X * b.X, a.Y * b.Y);
        public static Vector2 operator /(Vector2 a, float b) => b == 0 ? a : new Vector2(a.X / b, a.Y / b);
    }
    public struct Vector3D
    {
        public double X; public double Y; public double Z;
        public double this[int index]
        {
            get => GetDim(index);
            set
            {
                if (index == 0) X = value;
                else if (index == 1) Y = value;
                else if (index == 2) Z = value;
            }
        }
        public Vector3D(double x, double y, double z) { X = x; Y = y; Z = z; }
        public static Vector3D Zero => new Vector3D();
        public static Vector3D Up => new Vector3D(0, 1, 0);
        public static Vector3D Down => new Vector3D(0, -1, 0);
        public static Vector3D Right => new Vector3D(1, 0, 0);
        public static Vector3D Left => new Vector3D(-1, 0, 0);
        public static Vector3D Forward => new Vector3D(0, 0, -1);
        public static Vector3D Backward => new Vector3D(0, 0, 1);
        public double GetDim(int index) => index == 0 ? X : index == 1 ? Y : index == 2 ? Z : 0;
        public double Length() => Math.Sqrt(X * X + Y * Y + Z * Z);
        public double LengthSquared() => X * X + Y * Y + Z * Z;
        public double Normalize()
        {
            var length = Length();
            if (length <= 0) return 0;
            X /= length;
            Y /= length;
            Z /= length;
            return length;
        }
        public double Max() => Math.Max(X, Math.Max(Y, Z));
        public double Min() => Math.Min(X, Math.Min(Y, Z));
        public Vector3D Round() => new Vector3D(Math.Round(X), Math.Round(Y), Math.Round(Z));
        public static double Distance(Vector3D a, Vector3D b) => (new Vector3D(a.X - b.X, a.Y - b.Y, a.Z - b.Z)).Length();
        public static double Dot(Vector3D a, Vector3D b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
        public double Dot(Vector3D other) => Dot(this, other);
        public static Vector3D Cross(Vector3D a, Vector3D b) => new Vector3D(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);
        public static Vector3D Normalize(Vector3D value)
        {
            value.Normalize();
            return value;
        }
        public static bool IsZero(Vector3D value) => value.LengthSquared() <= 0.0000000001;
        public static bool IsUnit(ref Vector3D value) => Math.Abs(value.LengthSquared() - 1) <= 0.0001;
        public static Vector3D Rotate(Vector3D value, MatrixD matrix) => value;
        public static Vector3D TransformNormal(Vector3D value, MatrixD matrix) => value;
        public override string ToString() => $"{X}:{Y}:{Z}";
        public string ToString(string format) => $"{X.ToString(format)}:{Y.ToString(format)}:{Z.ToString(format)}";
        public static Vector3D Round(Vector3D value, int decimals = 0) => new Vector3D(Math.Round(value.X, decimals), Math.Round(value.Y, decimals), Math.Round(value.Z, decimals));
        public static explicit operator Vector3D(Vector3I value) => new Vector3D(value.X, value.Y, value.Z);
        public static Vector3D operator +(Vector3D a, Vector3D b) => new Vector3D(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
        public static Vector3D operator +(Vector3D a, Vector3I b) => new Vector3D(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
        public static Vector3D operator +(Vector3I b, Vector3D a) => a + b;
        public static Vector3D operator -(Vector3D a, Vector3D b) => new Vector3D(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
        public static Vector3D operator -(Vector3D a) => new Vector3D(-a.X, -a.Y, -a.Z);
        public static Vector3D operator *(Vector3D a, double b) => new Vector3D(a.X * b, a.Y * b, a.Z * b);
        public static Vector3D operator *(double b, Vector3D a) => a * b;
        public static Vector3D operator /(Vector3D a, double b) => b == 0 ? a : new Vector3D(a.X / b, a.Y / b, a.Z / b);
        public static bool operator ==(Vector3D left, Vector3D right) => Math.Abs(left.X - right.X) <= 0.000001 && Math.Abs(left.Y - right.Y) <= 0.000001 && Math.Abs(left.Z - right.Z) <= 0.000001;
        public static bool operator !=(Vector3D left, Vector3D right) => !(left == right);
        public override bool Equals(object obj) => obj is Vector3D other && this == other;
        public override int GetHashCode() => HashCode.Combine(X, Y, Z);
    }
    public struct Vector3I
    {
        public int X; public int Y; public int Z;
        public Vector3I(int x, int y, int z) { X = x; Y = y; Z = z; }
        public static Vector3I Zero => new Vector3I();
        public int GetDim(int index) => index == 0 ? X : index == 1 ? Y : index == 2 ? Z : 0;
        public static Vector3I operator +(Vector3I a, Vector3I b) => new Vector3I(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
        public static Vector3I operator *(Vector3I a, float b) => new Vector3I((int)(a.X * b), (int)(a.Y * b), (int)(a.Z * b));
        public static Vector3I operator *(float b, Vector3I a) => a * b;
    }
    public struct MatrixD
    {
        public static MatrixD Identity => new MatrixD();
        public Vector3D Forward => Vector3D.Forward;
        public Vector3D Backward => Vector3D.Backward;
        public Vector3D Up => Vector3D.Up;
        public Vector3D Down => Vector3D.Down;
        public Vector3D Right => Vector3D.Right;
        public Vector3D Left => Vector3D.Left;
        public static MatrixD Transpose(MatrixD matrix) => matrix;
        public static bool operator ==(MatrixD left, MatrixD right) => true;
        public static bool operator !=(MatrixD left, MatrixD right) => false;
        public override bool Equals(object obj) => obj is MatrixD;
        public override int GetHashCode() => 0;
    }
    public static class MathHelper
    {
        public const float Pi = (float)Math.PI;
        public const float PiOver2 = (float)(Math.PI / 2);
        public const float PiOver4 = (float)(Math.PI / 4);
        public const float TwoPi = (float)(Math.PI * 2);
        public const float EPSILON = 0.00001f;
        public static float Clamp(float value, float min, float max) => Math.Min(Math.Max(value, min), max);
        public static double Clamp(double value, double min, double max) => Math.Min(Math.Max(value, min), max);
        public static int Clamp(int value, int min, int max) => Math.Min(Math.Max(value, min), max);
        public static float ToRadians(float degrees) => degrees * Pi / 180f;
        public static double ToRadians(double degrees) => degrees * Math.PI / 180.0;
        public static float ToDegrees(float radians) => radians * 180f / Pi;
        public static double ToDegrees(double radians) => radians * 180.0 / Math.PI;
    }
    public static class MyMath
    {
        public static float FastSin(float value) => (float)Math.Sin(value);
        public static float FastCos(float value) => (float)Math.Cos(value);
        public static double FastSin(double value) => Math.Sin(value);
        public static double FastCos(double value) => Math.Cos(value);
    }
}

namespace VRage.Game.GUI.TextPanel
{
    public enum TextAlignment { LEFT, CENTER, RIGHT }
    public enum ContentType { NONE, TEXT_AND_IMAGE, SCRIPT }
}

namespace VRage.Game.ModAPI.Ingame.Utilities
{
    public struct MyIniKey
    {
        public string Section { get; set; }
        public string Name { get; set; }
        public MyIniKey(string section, string name) { Section = section; Name = name; }
    }
    public sealed class MyIni
    {
        readonly Dictionary<string, string> _values = new(StringComparer.OrdinalIgnoreCase);
        public string EndContent { get; set; } = "";
        public bool TryParse(string text) => true;
        public string Get(string section, string key) => _values.TryGetValue(section + "." + key, out var value) ? value : "";
        public string Get(MyIniKey key) => Get(key.Section, key.Name);
        public void Set(string section, string key, object value) => _values[section + "." + key] = value?.ToString() ?? "";
        public void Set(MyIniKey key, object value) => Set(key.Section, key.Name, value);
        public void SetComment(string section, string key, string comment) {}
        public void SetSectionComment(string section, string comment) {}
        public void GetKeys(List<MyIniKey> keys)
        {
            foreach (var key in _values.Keys)
            {
                var parts = key.Split('.', 2);
                keys.Add(new MyIniKey(parts[0], parts.Length > 1 ? parts[1] : ""));
            }
        }
        public void GetKeys(string section, List<MyIniKey> keys)
        {
            foreach (var key in _values.Keys.Where(item => item.StartsWith(section + ".", StringComparison.OrdinalIgnoreCase)))
            {
                keys.Add(new MyIniKey(section, key[(section.Length + 1)..]));
            }
        }
        public void Clear() => _values.Clear();
        public override string ToString() => string.Join("\n", _values.Select(item => item.Key + "=" + item.Value));
    }
}

namespace VRage.Game.ObjectBuilders.Definitions
{
    public sealed class MyObjectBuilder_GasProperties {}
}
""";
}
