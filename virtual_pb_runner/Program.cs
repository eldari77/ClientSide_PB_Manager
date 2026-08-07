using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

const string CapabilityVersion = "dynamic-harness-v6";

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
    if (compatibility["status"]?.GetValue<string>() == "supported")
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

    var status = unsupportedApis.Count == 0 ? "supported" : "unsupported";
    return new JsonObject
    {
        ["schema"] = "novali.client_side_pb.virtual_pb_compatibility_report.v1",
        ["status"] = status,
        ["compiled"] = false,
        ["unsupported_apis"] = unsupportedApis,
        ["unsupported_interfaces"] = unsupportedInterfaces,
        ["unsupported_members"] = unsupportedMembers,
        ["required_interfaces"] = requiredInterfaces,
        ["implemented_interfaces"] = JsonArrayFrom(ImplementedInterfaces()),
        ["supported_block_types"] = JsonArrayFrom(ImplementedInterfaces().Where(item => item.StartsWith("IMy", StringComparison.Ordinal))),
        ["available_command_kinds"] = JsonArrayFrom(AvailableCommandKinds()),
        ["snapshot_requirements"] = JsonArrayFrom(SnapshotFields()),
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
        ["generic_terminal_mutations"] = "blocked_unless_mapped",
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
    (new Regex(@"\.SetValue(?:<[^>]+>)?\s*\(", RegexOptions.Compiled), "IMyTerminalBlock.SetValue"),
};

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
    "grid_snapshot.blocks[].door_open_ratio",
    "grid_snapshot.blocks[].door_status",
    "grid_snapshot.blocks[].enabled",
    "grid_snapshot.blocks[].entity_id",
    "grid_snapshot.blocks[].inventories[]",
    "grid_snapshot.blocks[].inventories[].items[]",
    "grid_snapshot.blocks[].name",
    "grid_snapshot.blocks[].same_construct",
    "grid_snapshot.blocks[].surface_count",
    "grid_snapshot.blocks[].text",
    "grid_snapshot.blocks[].type",
    "inventory_snapshot.blocks[]",
    "inventory_snapshot.blocks[].inventories[].items[]",
};

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
        var program = (Program)(Activator.CreateInstance(type, nonPublic: true)
            ?? throw new InvalidOperationException("Program constructor unavailable"));
        program.Attach(context);

        try
        {
            var main = type.GetMethod("Main", new[] { typeof(string), typeof(UpdateType) })
                ?? type.GetMethod("Main", new[] { typeof(string) })
                ?? type.GetMethod("Main", Type.EmptyTypes);
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
    public IMyGridTerminalSystem GridTerminalSystem { get; private set; } = new VirtualGridTerminalSystem(new VirtualContext());
    public IMyProgrammableBlock Me { get; private set; } = new VirtualBlock(new VirtualContext(), new JsonObject(), 0);
    public MyRuntimeInfo Runtime { get; private set; } = new MyRuntimeInfo();
    internal VirtualContext Context { get; private set; } = new VirtualContext();
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
    public List<VirtualBlock> Blocks { get; } = new();
    public VirtualGridTerminalSystem GridTerminalSystem { get; }
    public VirtualBlock MeBlock { get; }
    public IMyProgrammableBlock Me => MeBlock;
    public MyRuntimeInfo Runtime { get; } = new();
    public JsonArray Commands { get; } = new();
    public JsonArray Echoes { get; } = new();
    public string Status { get; private set; } = "ok";
    public string ErrorBucket { get; private set; } = "none";
    public string Summary { get; private set; } = "Virtual PB tick processed.";

    public VirtualContext()
    {
        GridTerminalSystem = new VirtualGridTerminalSystem(this);
        MeBlock = new VirtualBlock(this, new JsonObject { ["entity_id"] = 1, ["name"] = "Virtual PB", ["same_construct"] = true }, 0);
    }

    public static VirtualContext FromRequest(JsonObject request)
    {
        var context = new VirtualContext();
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
    public void Reject(string bucket)
    {
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
        var result = new JsonObject
        {
            ["summary"] = Summary,
            ["commands"] = Commands,
            ["compatibility"] = new JsonObject
            {
                ["status"] = Status == "ok" ? "supported" : "unsupported",
                ["compiled"] = true,
                ["available_command_kinds"] = new JsonArray("write_text_surface", "set_door_open", "set_light_color", "set_block_enabled"),
                ["emitted_command_kinds"] = EmittedKinds(),
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

public interface IMyCubeGrid { string CustomName { get; } IMySlimBlock GetCubeBlock(Vector3I position); }
public interface IMyTerminalAction { string Id { get; } }
public interface ITerminalAction { string Id { get; } }
public interface ITerminalProperty { string Id { get; } string TypeName { get; } }

public interface IMyTerminalBlock
{
    long EntityId { get; }
    string CustomName { get; set; }
    string CustomData { get; set; }
    string DisplayNameText { get; }
    string DefinitionDisplayNameText { get; }
    string DetailedInfo { get; }
    string CustomInfo { get; }
    bool IsWorking { get; }
    bool IsFunctional { get; }
    bool HasInventory { get; }
    int InventoryCount { get; }
    IMyCubeGrid CubeGrid { get; }
    MyDefinitionId BlockDefinition { get; }
    MyComponentContainer Components { get; }
    Vector3I Position { get; }
    MatrixD WorldMatrix { get; }
    Vector3D GetPosition();
    IMyInventory GetInventory(int index = 0);
    T GetValue<T>(string id);
    ITerminalProperty GetProperty(string id);
    void GetProperties(List<ITerminalProperty> result, Func<ITerminalProperty, bool> collect = null);
    void GetActions(List<ITerminalAction> result, Func<ITerminalAction, bool> collect = null);
    bool IsSameConstructAs(IMyTerminalBlock other);
}

public interface IMyFunctionalBlock : IMyTerminalBlock { bool Enabled { get; set; } }
public interface IMyProgrammableBlock : IMyFunctionalBlock {}
public interface IMyTextSurface
{
    string Font { get; set; }
    float FontSize { get; set; }
    float TextPadding { get; set; }
    TextAlignment Alignment { get; set; }
    ContentType ContentType { get; set; }
    Vector2 SurfaceSize { get; }
    Vector2 TextureSize { get; }
    void WriteText(string text, bool append = false);
    string GetText();
}
public interface IMyTextPanel : IMyFunctionalBlock, IMyTextSurface {}
public interface IMyTextSurfaceProvider : IMyTerminalBlock { int SurfaceCount { get; } IMyTextSurface GetSurface(int index); }
public interface IMyInventory { double CurrentVolume { get; } double MaxVolume { get; } double CurrentMass { get; } void GetItems(List<MyInventoryItem> items); }
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
}
public interface IMyBlockGroup { string Name { get; } void GetBlocks(List<IMyTerminalBlock> blocks, Func<IMyTerminalBlock, bool> collect = null); }

public interface IMyDoor : IMyFunctionalBlock { float OpenRatio { get; } DoorStatus Status { get; } void OpenDoor(); void CloseDoor(); }
public interface IMyAirtightHangarDoor : IMyDoor {}
public interface IMyLightingBlock : IMyFunctionalBlock { Color Color { get; set; } float Radius { get; set; } float Intensity { get; set; } }
public interface IMyInteriorLight : IMyLightingBlock {}
public interface IMyReflectorLight : IMyLightingBlock {}
public interface IMySoundBlock : IMyFunctionalBlock { void Play(); void Stop(); }
public interface IMyCargoContainer : IMyFunctionalBlock {}
public interface IMyAssembler : IMyProductionBlock { bool CooperativeMode { get; set; } }
public interface IMyRefinery : IMyProductionBlock {}
public interface IMyProductionBlock : IMyFunctionalBlock { bool IsProducing { get; } }
public interface IMyGasTank : IMyFunctionalBlock { double FilledRatio { get; } double Capacity { get; } bool Stockpile { get; set; } }
public interface IMyGasGenerator : IMyFunctionalBlock { bool UseConveyorSystem { get; set; } }
public interface IMyReactor : IMyPowerProducer {}
public interface IMyPowerProducer : IMyFunctionalBlock { float CurrentOutput { get; } float MaxOutput { get; } }
public interface IMyBatteryBlock : IMyPowerProducer { float CurrentStoredPower { get; } float MaxStoredPower { get; } ChargeMode ChargeMode { get; set; } }
public interface IMyShipController : IMyFunctionalBlock { bool DampenersOverride { get; set; } bool IsUnderControl { get; } bool IsMainCockpit { get; set; } bool TryGetPlanetElevation(MyPlanetElevation detail, out double elevation); MyShipMass CalculateShipMass(); MyShipVelocities GetShipVelocities(); Vector3D GetNaturalGravity(); Vector3D GetArtificialGravity(); Vector3D GetTotalGravity(); double GetShipSpeed(); }
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
public interface IMyLandingGear : IMyFunctionalBlock { LandingGearMode LockMode { get; } }
public interface IMyLargeGatlingTurret : IMyFunctionalBlock {}
public interface IMyLargeInteriorTurret : IMyFunctionalBlock {}
public interface IMyLargeMissileTurret : IMyFunctionalBlock {}
public interface IMyMedicalRoom : IMyFunctionalBlock {}
public interface IMyMotorStator : IMyFunctionalBlock {}
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
public interface IMyThrust : IMyFunctionalBlock { float CurrentThrust { get; } float MaxThrust { get; } float ThrustOverride { get; set; } }
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
public struct MyShipMass { public double BaseMass; public double TotalMass; public double PhysicalMass; }
public struct MyShipVelocities { public Vector3D LinearVelocity; public Vector3D AngularVelocity; }
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
    public MyDefinitionId(string typeId, string subtypeId) { TypeIdString = typeId; SubtypeId = subtypeId; }
    public MyDefinitionId(Type typeId, string subtypeId) { TypeIdString = typeId.Name; SubtypeId = subtypeId; }
    public static MyDefinitionId Parse(string value)
    {
        var parts = value.Split('/', 2);
        return new MyDefinitionId { TypeIdString = parts[0], SubtypeId = parts.Length > 1 ? parts[1] : "" };
    }
    public override string ToString() => string.IsNullOrWhiteSpace(SubtypeId) ? TypeIdString : TypeIdString + "/" + SubtypeId;
}
public struct MyItemType
{
    public string TypeId { get; set; }
    public string SubtypeId { get; set; }
    public string SubtypeName => SubtypeId;
    public override string ToString() => string.IsNullOrWhiteSpace(SubtypeId) ? TypeId : TypeId + "/" + SubtypeId;
}
public struct MyInventoryItem { public MyItemType Type { get; set; } public double Amount { get; set; } }

public sealed class VirtualGrid : IMyCubeGrid
{
    readonly VirtualBlock? _block;
    public VirtualGrid(VirtualBlock? block = null) { _block = block; }
    public string CustomName { get; init; } = "Virtual Grid";
    public IMySlimBlock GetCubeBlock(Vector3I position) => new VirtualSlimBlock(_block);
}

public sealed class VirtualTerminalProperty : ITerminalProperty
{
    public string Id { get; init; } = "";
    public string TypeName { get; init; } = "Boolean";
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
    public double CurrentVolume { get; }
    public double MaxVolume { get; }
    public double CurrentMass { get; }
    public VirtualInventory(JsonObject inventory)
    {
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
            });
        }
    }
    public void GetItems(List<MyInventoryItem> items) => items.AddRange(_items);
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
    string _text;
    bool _enabled;
    Color _color;
    public long EntityId { get; }
    public string CustomName { get; set; }
    public string CustomData { get; set; }
    public string DisplayNameText => CustomName;
    public string DefinitionDisplayNameText => ReadString("definition_display_name", BlockDefinition.SubtypeId);
    public string DetailedInfo => ReadString("detailed_info");
    public string CustomInfo => ReadString("custom_info");
    public bool IsWorking => Enabled;
    public bool IsFunctional => true;
    public bool HasInventory => _inventories.Count > 0;
    public int InventoryCount => Math.Max(_inventories.Count, ReadInt("inventory_count"));
    public IMyCubeGrid CubeGrid => new VirtualGrid(this);
    public MyDefinitionId BlockDefinition { get; }
    public MyComponentContainer Components { get; } = new MyComponentContainer();
    public Vector3I Position => new Vector3I(ReadInt("grid_x"), ReadInt("grid_y"), ReadInt("grid_z"));
    public MatrixD WorldMatrix => MatrixD.Identity;
    public int SurfaceCount => Math.Max(1, ReadInt("surface_count"));
    public string Font { get; set; } = "Debug";
    public float FontSize { get; set; } = 0.6f;
    public float TextPadding { get; set; } = 2f;
    public TextAlignment Alignment { get; set; } = TextAlignment.LEFT;
    public ContentType ContentType { get; set; } = ContentType.TEXT_AND_IMAGE;
    public Vector2 SurfaceSize { get; } = new Vector2(512, 512);
    public Vector2 TextureSize { get; } = new Vector2(512, 512);
    public float OpenRatio => (float)ReadDouble("door_open_ratio");
    public DoorStatus Status => Enum.TryParse<DoorStatus>(ReadString("door_status"), true, out var status) ? status : (OpenRatio > 0.9f ? DoorStatus.Open : DoorStatus.Closed);
    public bool CooperativeMode { get; set; }
    public bool IsProducing => ReadBool("is_producing", Enabled);
    public double FilledRatio => ReadDouble("gas_filled_ratio");
    public double Capacity => ReadDouble("capacity");
    public bool Stockpile { get; set; }
    public bool UseConveyorSystem { get; set; }
    public float CurrentOutput => (float)ReadDouble("current_output");
    public float MaxOutput => (float)ReadDouble("max_output");
    public float CurrentStoredPower => (float)ReadDouble("current_stored_power");
    public float MaxStoredPower => (float)ReadDouble("max_stored_power");
    ChargeMode _chargeMode;
    public ChargeMode ChargeMode { get => _chargeMode; set { _chargeMode = value; _context.Reject("unsupported_member:IMyBatteryBlock.ChargeMode.set"); } }
    public float MaxStoredPowerJump => (float)ReadDouble("max_stored_power");
    public bool DampenersOverride { get; set; }
    public bool IsUnderControl => ReadBool("is_under_control");
    public bool IsMainCockpit { get; set; }
    public MyShipConnectorStatus StatusConnector => MyShipConnectorStatus.Unconnected;
    MyShipConnectorStatus IMyShipConnector.Status => MyShipConnectorStatus.Unconnected;
    IMyShipConnector IMyShipConnector.OtherConnector => null;
    MyLaserAntennaStatus IMyLaserAntenna.Status => MyLaserAntennaStatus.Idle;
    public bool CanPressurize => ReadBool("can_pressurize", true);
    public LandingGearMode LockMode => Enum.TryParse<LandingGearMode>(ReadString("lock_mode"), true, out var lockMode) ? lockMode : LandingGearMode.Unlocked;
    public int TotalBlocks => ReadInt("total_blocks");
    public int RemainingBlocks => ReadInt("remaining_blocks");
    public float CurrentThrust => (float)ReadDouble("current_thrust");
    public float MaxThrust => (float)ReadDouble("max_thrust");
    public float ThrustOverride { get => (float)ReadDouble("thrust_override"); set => _context.Reject("unsupported_member:IMyThrust.ThrustOverride.set"); }
    public float Radius { get; set; }
    public float Intensity { get; set; }

    public VirtualBlock(VirtualContext context, JsonObject source, int index)
    {
        _context = context;
        _source = source;
        EntityId = ReadLong("entity_id", index + 1);
        CustomName = ReadString("name", "Block " + EntityId);
        CustomData = ReadString("custom_data");
        _text = ReadString("text");
        _enabled = ReadBool("enabled", true);
        BlockDefinition = new MyDefinitionId { TypeIdString = ReadString("type"), SubtypeId = ReadString("subtype") };
        _color = ReadColor();
        _chargeMode = Enum.TryParse<ChargeMode>(ReadString("charge_mode"), true, out var chargeMode) ? chargeMode : ChargeMode.Auto;
        Radius = ReadFloat("radius");
        Intensity = ReadFloat("intensity");
        foreach (var inventoryNode in source["inventories"]?.AsArray() ?? new JsonArray())
        {
            if (inventoryNode is JsonObject inventory) _inventories.Add(new VirtualInventory(inventory));
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

    public IMyInventory GetInventory(int index = 0) => index >= 0 && index < _inventories.Count ? _inventories[index] : new VirtualInventory(new JsonObject());
    public Vector3D GetPosition() => new Vector3D(ReadDouble("x"), ReadDouble("y"), ReadDouble("z"));
    public T GetValue<T>(string id)
    {
        object value = id switch
        {
            "OnOff" => Enabled,
            "FontSize" => FontSize,
            "Radius" => Radius,
            "Intensity" => Intensity,
            _ => default(T),
        };
        return value is T typed ? typed : default;
    }
    public void GetProperties(List<ITerminalProperty> result, Func<ITerminalProperty, bool> collect = null) {}
    public ITerminalProperty GetProperty(string id) => new VirtualTerminalProperty { Id = id, TypeName = "Boolean" };
    public void GetActions(List<ITerminalAction> result, Func<ITerminalAction, bool> collect = null) {}
    public bool IsSameConstructAs(IMyTerminalBlock other) => ReadBool("same_construct", true);
    public IMyTextSurface GetSurface(int index) => this;
    public void WriteText(string text, bool append = false)
    {
        _text = append ? _text + text : text;
        _context.AddCommand(new JsonObject
        {
            ["kind"] = "write_text_surface",
            ["block_entity_id"] = EntityId,
            ["surface_index"] = 0,
            ["append"] = append,
            ["text"] = text,
        });
    }
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

    bool IsFlag(string key) => ReadBool(key, false);
    bool Contains(string token)
    {
        var needle = token.ToLowerInvariant();
        return CustomName.ToLowerInvariant().Contains(needle)
            || ReadString("type").ToLowerInvariant().Contains(needle)
            || ReadString("subtype").ToLowerInvariant().Contains(needle);
    }
    string ReadString(string key, string fallback = "") => _source.TryGetPropertyValue(key, out var value) && value != null ? value.ToString() : fallback;
    bool ReadBool(string key, bool fallback = false) => _source.TryGetPropertyValue(key, out var value) && value != null && bool.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    int ReadInt(string key) => _source.TryGetPropertyValue(key, out var value) && value != null && int.TryParse(value.ToString(), out var parsed) ? parsed : 0;
    long ReadLong(string key, long fallback = 0) => _source.TryGetPropertyValue(key, out var value) && value != null && long.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    double ReadDouble(string key) => _source.TryGetPropertyValue(key, out var value) && value != null && double.TryParse(value.ToString(), out var parsed) ? parsed : 0;
    public float ReadFloat(string key, float fallback = 0f) => _source.TryGetPropertyValue(key, out var value) && value != null && float.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
    Color ReadColor()
    {
        var color = _source["color"] as JsonObject;
        return color == null ? new Color(255, 255, 255) : new Color(ReadInt(color, "r", 255), ReadInt(color, "g", 255), ReadInt(color, "b", 255), ReadInt(color, "a", 255));
    }
    static int ReadInt(JsonObject source, string key, int fallback) => source.TryGetPropertyValue(key, out var value) && value != null && int.TryParse(value.ToString(), out var parsed) ? parsed : fallback;
}

namespace VRageMath
{
    public struct Color
    {
        public int R; public int G; public int B; public int A;
        public Color(int r, int g, int b, int a = 255) { R = r; G = g; B = b; A = a; }
    }
    public struct Vector2
    {
        public float X; public float Y;
        public Vector2(float x, float y) { X = x; Y = y; }
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
        public double GetDim(int index) => index == 0 ? X : index == 1 ? Y : index == 2 ? Z : 0;
        public double Length() => Math.Sqrt(X * X + Y * Y + Z * Z);
        public static double Distance(Vector3D a, Vector3D b) => (new Vector3D(a.X - b.X, a.Y - b.Y, a.Z - b.Z)).Length();
        public override string ToString() => $"{X}:{Y}:{Z}";
        public string ToString(string format) => $"{X.ToString(format)}:{Y.ToString(format)}:{Z.ToString(format)}";
        public static Vector3D operator -(Vector3D a, Vector3D b) => new Vector3D(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
    }
    public struct Vector3I
    {
        public int X; public int Y; public int Z;
        public Vector3I(int x, int y, int z) { X = x; Y = y; Z = z; }
        public int GetDim(int index) => index == 0 ? X : index == 1 ? Y : index == 2 ? Z : 0;
    }
    public struct MatrixD
    {
        public static MatrixD Identity => new MatrixD();
        public static bool operator ==(MatrixD left, MatrixD right) => true;
        public static bool operator !=(MatrixD left, MatrixD right) => false;
        public override bool Equals(object obj) => obj is MatrixD;
        public override int GetHashCode() => 0;
    }
}

namespace VRage.Game.GUI.TextPanel
{
    public enum TextAlignment { LEFT, CENTER, RIGHT }
    public enum ContentType { NONE, TEXT_AND_IMAGE, SCRIPT }
}

namespace VRage.Game.ModAPI.Ingame.Utilities
{
    public sealed class MyIni
    {
        public bool TryParse(string text) => true;
        public string Get(string section, string key) => "";
        public void Set(string section, string key, string value) {}
        public override string ToString() => "";
    }
}

namespace VRage.Game.ObjectBuilders.Definitions
{
    public sealed class MyObjectBuilder_GasProperties {}
}
""";
}
