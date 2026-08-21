param(
    [string]$PackageRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [switch]$SkipDockerStart
)

$ErrorActionPreference = "Stop"

function Ensure-Directory([string]$Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

$pluginSource = Join-Path $PackageRoot "plugin\NOVALI.ClientSidePBBridge.dll"
$pluginTargetRoot = "$env:APPDATA\Pulsar\Legacy\Local"
$pluginTarget = Join-Path $pluginTargetRoot "NOVALI.ClientSidePBBridge.dll"
$managerLauncher = Join-Path $PackageRoot "scripts\open-manager.ps1"
$protocolRoot = "HKCU:\Software\Classes\novali-client-side-pb-manager"
$commandKey = Join-Path $protocolRoot "shell\open\command"
$command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$managerLauncher`" -PackageRoot `"$PackageRoot`""

if (-not (Test-Path -LiteralPath $pluginSource)) {
    throw "Packaged plugin DLL not found: $pluginSource"
}
if (-not (Test-Path -LiteralPath $managerLauncher)) {
    throw "Manager launcher not found: $managerLauncher"
}

Ensure-Directory (Join-Path $PackageRoot "data")
Ensure-Directory (Join-Path $PackageRoot "data\bridge_requests")
Ensure-Directory (Join-Path $PackageRoot "data\bridge_requests\processed")
Ensure-Directory (Join-Path $PackageRoot "data\bridge_results")
Ensure-Directory (Join-Path $PackageRoot "data\command_queues")
Ensure-Directory (Join-Path $PackageRoot "data\worker_configs")
Ensure-Directory $pluginTargetRoot

Copy-Item -LiteralPath $pluginSource -Destination $pluginTarget -Force

New-Item -Path $protocolRoot -Force | Out-Null
Set-Item -Path $protocolRoot -Value "URL:NOVALI Client-Side PB Manager"
Set-ItemProperty -Path $protocolRoot -Name "URL Protocol" -Value ""
New-Item -Path $commandKey -Force | Out-Null
Set-Item -Path $commandKey -Value $command

if (-not $SkipDockerStart) {
    Push-Location $PackageRoot
    try {
        & docker compose up --build -d
        if ($LASTEXITCODE -ne 0) {
            throw "Docker worker start failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Installed NOVALI Client-Side PB Bridge beta package."
Write-Host "Plugin: $pluginTarget"
Write-Host "Manager: run scripts\open-manager.ps1"
