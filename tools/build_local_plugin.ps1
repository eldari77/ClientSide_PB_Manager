param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$SpaceEngineersBin64 = "C:\Program Files (x86)\Steam\steamapps\common\SpaceEngineers\Bin64",
    [string]$PluginName = "NOVALI.ClientSidePBBridge"
)

$ErrorActionPreference = "Stop"

$compiler = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$source = Join-Path $ProjectRoot "client_plugins\$PluginName\LocalPlugin\ClientSidePBBridgePlugin.cs"
$outDir = Join-Path $ProjectRoot "artifacts\plugin_handoff"
$outDll = Join-Path $outDir "$PluginName.dll"

if (-not (Test-Path -LiteralPath $compiler)) { throw "C# compiler not found: $compiler" }
if (-not (Test-Path -LiteralPath $source)) { throw "Local plugin source not found: $source" }
if (-not (Test-Path -LiteralPath $SpaceEngineersBin64)) { throw "Space Engineers Bin64 folder not found: $SpaceEngineersBin64" }

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$references = @(
    "netstandard.dll",
    "VRage.dll",
    "VRage.Game.dll",
    "Sandbox.Common.dll",
    "Sandbox.Game.dll"
) | ForEach-Object { Join-Path $SpaceEngineersBin64 $_ }

foreach ($reference in $references) {
    if (-not (Test-Path -LiteralPath $reference)) { throw "Required Space Engineers assembly not found: $reference" }
}

& $compiler `
    /nologo `
    /target:library `
    /optimize+ `
    /out:$outDll `
    ($references | ForEach-Object { "/reference:$_" }) `
    $source

if ($LASTEXITCODE -ne 0) { throw "Local plugin build failed with exit code $LASTEXITCODE" }

Write-Host "Built $outDll"
return $outDll
