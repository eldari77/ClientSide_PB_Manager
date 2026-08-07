using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

var options = ParseArgs(args);
if (!options.TryGetValue("script", out var scriptPath) ||
    !options.TryGetValue("request", out var requestPath) ||
    !options.TryGetValue("output", out var outputPath))
{
    Console.Error.WriteLine("Usage: --script <Script.cs> --request <request.json> --output <output.json>");
    return 2;
}

var source = File.ReadAllText(scriptPath);
var request = JsonNode.Parse(File.ReadAllText(requestPath))?.AsObject() ?? new JsonObject();
var compatibility = Analyze(source);
var commands = new JsonArray();

if (compatibility["status"]?.GetValue<string>() == "supported")
{
    var blocks = request["grid_snapshot"]?["blocks"]?.AsArray() ?? new JsonArray();
    foreach (var blockNode in blocks)
    {
        if (blockNode is not JsonObject block)
        {
            continue;
        }
        var blockId = GetLong(block, "entity_id");
        if (blockId == 0 || !GetBool(block, "same_construct", true))
        {
            continue;
        }
        if (GetBool(block, "is_door", false) && SourceCanCloseDoors(source) && GetDouble(block, "door_open_ratio") > 0.9)
        {
            commands.Add(new JsonObject
            {
                ["kind"] = "set_door_open",
                ["block_entity_id"] = blockId,
                ["open"] = false,
            });
        }
        if (GetBool(block, "is_light", false))
        {
            if (Regex.IsMatch(source, @"\bEnabled\s*=\s*true\b"))
            {
                commands.Add(new JsonObject
                {
                    ["kind"] = "set_block_enabled",
                    ["block_entity_id"] = blockId,
                    ["enabled"] = true,
                });
            }
            var color = ExtractAssignedColor(source);
            if (color is not null)
            {
                commands.Add(new JsonObject
                {
                    ["kind"] = "set_light_color",
                    ["block_entity_id"] = blockId,
                    ["color"] = color,
                });
            }
        }
    }
}

var result = new JsonObject
{
    ["summary"] = compatibility["status"]?.GetValue<string>() == "supported"
        ? "Virtual PB tick processed."
        : "Virtual PB script rejected by compatibility analysis.",
    ["commands"] = commands,
    ["compatibility"] = compatibility,
};
if (compatibility["status"]?.GetValue<string>() != "supported")
{
    result["adapter_status"] = "rejected";
    result["error_bucket"] = "virtual_pb_unsupported_api";
}
File.WriteAllText(outputPath, result.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
return 0;

static Dictionary<string, string> ParseArgs(string[] args)
{
    var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    for (var i = 0; i < args.Length - 1; i++)
    {
        if (args[i].StartsWith("--", StringComparison.Ordinal))
        {
            result[args[i][2..]] = args[i + 1];
            i++;
        }
    }
    return result;
}

static JsonObject Analyze(string source)
{
    var unsupported = new JsonArray();
    foreach (var item in new[] { "System.IO", "File.", "Directory.", "System.Net", "HttpClient", "Process.", "System.Diagnostics", "Thread", "Task.", "Reflection", "Activator.", "Marshal." })
    {
        if (source.Contains(item, StringComparison.Ordinal))
        {
            unsupported.Add(item);
        }
    }
    var supportedInterfaces = new HashSet<string>(StringComparer.Ordinal)
    {
        "IMyAirtightHangarDoor",
        "IMyDoor",
        "IMyGridTerminalSystem",
        "IMyLightingBlock",
        "IMyProgrammableBlock",
        "IMySoundBlock",
        "IMyTerminalBlock",
        "IMyTextSurface",
    };
    var unsupportedInterfaces = new JsonArray();
    foreach (var match in Regex.Matches(source, @"\bIMy[A-Za-z0-9_]+\b").Select(item => item.Value).Distinct().OrderBy(item => item))
    {
        if (!supportedInterfaces.Contains(match))
        {
            unsupportedInterfaces.Add(match);
            unsupported.Add($"unsupported_interface:{match}");
        }
    }
    var supportedTypes = new JsonArray();
    foreach (var item in supportedInterfaces.OrderBy(item => item))
    {
        if (source.Contains(item, StringComparison.Ordinal))
        {
            supportedTypes.Add(item);
        }
    }
    return new JsonObject
    {
        ["status"] = unsupported.Count == 0 ? "supported" : "unsupported",
        ["unsupported_apis"] = unsupported,
        ["unsupported_interfaces"] = unsupportedInterfaces,
        ["supported_block_types"] = supportedTypes,
        ["uses_grid_terminal_system"] = source.Contains("GridTerminalSystem", StringComparison.Ordinal),
        ["uses_runtime"] = source.Contains("Runtime.", StringComparison.Ordinal),
        ["uses_custom_data"] = source.Contains("CustomData", StringComparison.Ordinal),
    };
}

static bool SourceCanCloseDoors(string source)
{
    return source.Contains(".CloseDoor()", StringComparison.Ordinal) || source.Contains("CloseDoor(", StringComparison.Ordinal);
}

static JsonObject? ExtractAssignedColor(string source)
{
    var match = Regex.Match(source, @"Color\s*=\s*new\s+Color\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)");
    if (!match.Success)
    {
        return null;
    }
    return new JsonObject
    {
        ["r"] = int.Parse(match.Groups[1].Value),
        ["g"] = int.Parse(match.Groups[2].Value),
        ["b"] = int.Parse(match.Groups[3].Value),
        ["a"] = match.Groups[4].Success ? int.Parse(match.Groups[4].Value) : 255,
    };
}

static bool GetBool(JsonObject block, string key, bool defaultValue)
{
    return block.TryGetPropertyValue(key, out var value) && value is not null && value.GetValueKind() == JsonValueKind.True
        ? true
        : block.TryGetPropertyValue(key, out value) && value is not null && value.GetValueKind() == JsonValueKind.False
            ? false
            : defaultValue;
}

static long GetLong(JsonObject block, string key)
{
    return block.TryGetPropertyValue(key, out var value) && value is not null && long.TryParse(value.ToString(), out var parsed) ? parsed : 0;
}

static double GetDouble(JsonObject block, string key)
{
    return block.TryGetPropertyValue(key, out var value) && value is not null && double.TryParse(value.ToString(), out var parsed) ? parsed : 0;
}
