param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$ProtocolUrl = "",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$project = Join-Path $ProjectRoot "manager\NOVALI.ClientSidePBManager.csproj"
$fallbackBuiltExe = Join-Path $ProjectRoot "manager\bin\Debug\net10.0-windows\NOVALI.ClientSidePBManager.exe"
$managerCurrentExe = Join-Path $ProjectRoot "data\manager_current_exe.txt"
$builtExe = $fallbackBuiltExe
if (Test-Path -LiteralPath $managerCurrentExe) {
    $candidate = (Get-Content -LiteralPath $managerCurrentExe -Raw).Trim()
    if ($candidate) {
        $builtExe = $candidate
    }
}
$logPath = Join-Path $ProjectRoot "data\manager_launch.log"

function Write-LaunchLog {
    param([string]$Message)
    $directory = Split-Path -Parent $logPath
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    Add-Content -LiteralPath $logPath -Value ("{0:o} {1}" -f (Get-Date), $Message)
}

function Ensure-WindowTools {
    if ("NovaliWindowTools" -as [type]) {
        return
    }
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class NovaliWindowTools {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
}

function BringManagerToFront {
    param([System.Diagnostics.Process]$Process)
    try {
        $Process.Refresh()
        if ($Process.MainWindowHandle -eq 0) {
            $Process.WaitForInputIdle(5000) | Out-Null
            $Process.Refresh()
        }
        if ($Process.MainWindowHandle -ne 0) {
            Ensure-WindowTools
            [NovaliWindowTools]::ShowWindow($Process.MainWindowHandle, 9) | Out-Null
            [NovaliWindowTools]::SetForegroundWindow($Process.MainWindowHandle) | Out-Null
        }
    }
    catch {
        Write-LaunchLog "foreground warning: $($_.Exception.Message)"
    }
}

if ($NoLaunch) {
    Write-Host "Manager project: $project"
    if (Test-Path -LiteralPath $builtExe) {
        Write-Host "Built manager: $builtExe"
    }
    return
}

try {
    Write-LaunchLog "launch requested ProjectRoot=$ProjectRoot ProtocolUrl=$ProtocolUrl"
    if (-not (Test-Path -LiteralPath $builtExe)) {
        throw "Manager executable was not found: $builtExe. Run tools\register_manager_protocol.ps1 to build and register it."
    }

    $process = Start-Process -FilePath $builtExe -WorkingDirectory $ProjectRoot -PassThru
    Write-LaunchLog "started manager pid=$($process.Id) path=$builtExe"
    BringManagerToFront $process
}
catch {
    Write-LaunchLog "launch failed: $($_.Exception.Message)"
    throw
}
