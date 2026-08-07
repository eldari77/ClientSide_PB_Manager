param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$protocol = "novali-client-side-pb-manager"
$launcher = Join-Path $ProjectRoot "tools\launch_manager.ps1"
$protocolRoot = "HKCU:\Software\Classes\$protocol"
$commandKey = Join-Path $protocolRoot "shell\open\command"
$command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -ProjectRoot `"$ProjectRoot`" -ProtocolUrl `"%1`""

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Manager launcher not found: $launcher"
}

New-Item -Path $protocolRoot -Force | Out-Null
Set-Item -Path $protocolRoot -Value "URL:NOVALI Client-Side PB Manager"
Set-ItemProperty -Path $protocolRoot -Name "URL Protocol" -Value ""
New-Item -Path $commandKey -Force | Out-Null
Set-Item -Path $commandKey -Value $command

Write-Host "Registered $protocol protocol for $launcher"
