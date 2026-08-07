param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$PluginName = "NOVALI.ClientSidePBBridge",
    [string]$LocalPluginRoot = "$env:APPDATA\Pulsar\Legacy\Local"
)

$ErrorActionPreference = "Stop"

$buildScript = Join-Path $ProjectRoot "tools\build_local_plugin.ps1"
$source = Join-Path $ProjectRoot "artifacts\plugin_handoff\$PluginName.dll"
$targetRoot = [System.IO.Path]::GetFullPath($LocalPluginRoot)
$target = Join-Path $targetRoot "$PluginName.dll"
$expectedRoot = [System.IO.Path]::GetFullPath("$env:APPDATA\Pulsar\Legacy\Local")

if ($targetRoot.TrimEnd('\') -ne $expectedRoot.TrimEnd('\')) {
    throw "Refusing to hand off outside the expected Pulsar Legacy Local plugin folder: $targetRoot"
}

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
& $buildScript -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "Plugin build failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $source)) { throw "Built plugin DLL not found: $source" }

Get-ChildItem -LiteralPath $targetRoot -File -Filter "NOVALI.ClientSidePBBridge*.dll" | ForEach-Object {
    try {
        Remove-Item -LiteralPath $_.FullName -Force
    }
    catch {
        throw "Could not replace $($_.FullName). Close Space Engineers/Pulsar and rerun tools\handoff_plugin.ps1."
    }
}

Copy-Item -LiteralPath $source -Destination $target
& (Join-Path $ProjectRoot "tools\validate_local_plugin.ps1") -PluginPath $target | Out-Host
Write-Host "Handed off $PluginName to $target"

