param(
    [string]$PluginPath = "$env:APPDATA\Pulsar\Legacy\Local\NOVALI.ClientSidePBBridge.dll",
    [string]$SpaceEngineersBin64 = "C:\Program Files (x86)\Steam\steamapps\common\SpaceEngineers\Bin64"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PluginPath)) { throw "Plugin DLL not found: $PluginPath" }

$cecil = Join-Path $SpaceEngineersBin64 "Plugins\Libraries\Mono.Cecil.dll"
if (-not (Test-Path -LiteralPath $cecil)) { throw "Mono.Cecil not found: $cecil" }

Add-Type -Path $cecil
$assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($PluginPath)
$pluginTypes = @()

foreach ($type in $assembly.MainModule.Types) {
    foreach ($interface in $type.Interfaces) {
        if ($interface.InterfaceType.FullName -eq "VRage.Plugins.IPlugin") {
            $pluginTypes += $type.FullName
        }
    }
}

$result = [ordered]@{
    plugin_path = $PluginPath
    file_exists = $true
    file_length = (Get-Item -LiteralPath $PluginPath).Length
    assembly_name = $assembly.Name.Name
    assembly_version = $assembly.Name.Version.ToString()
    plugin_types = $pluginTypes
    implements_vrage_iplugin = $pluginTypes.Count -gt 0
}

$result | ConvertTo-Json -Depth 4

if (-not $result.implements_vrage_iplugin) { throw "No public type implements VRage.Plugins.IPlugin" }

