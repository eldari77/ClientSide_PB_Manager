param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$protocol = "novali-client-side-pb-manager"
$launcher = Join-Path $ProjectRoot "tools\launch_manager.ps1"
$project = Join-Path $ProjectRoot "manager\NOVALI.ClientSidePBManager.csproj"
$managerBuildRoot = Join-Path $ProjectRoot "data\manager_builds"
$managerBuildDir = Join-Path $managerBuildRoot (Get-Date -Format "yyyyMMddHHmmss")
$managerCurrentExe = Join-Path $ProjectRoot "data\manager_current_exe.txt"
$builtExe = Join-Path $managerBuildDir "NOVALI.ClientSidePBManager.exe"
$protocolRoot = "HKCU:\Software\Classes\$protocol"
$commandKey = Join-Path $protocolRoot "shell\open\command"
$command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" -ProjectRoot `"$ProjectRoot`" -ProtocolUrl `"%1`""

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Manager launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $project)) {
    throw "Manager project not found: $project"
}

New-Item -ItemType Directory -Path $managerBuildDir -Force | Out-Null
& dotnet build $project --nologo -p:OutDir="$managerBuildDir\"
if ($LASTEXITCODE -ne 0) {
    throw "Manager build failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "Manager build completed but executable was not found: $builtExe"
}
Set-Content -LiteralPath $managerCurrentExe -Value $builtExe -Encoding UTF8

New-Item -Path $protocolRoot -Force | Out-Null
Set-Item -Path $protocolRoot -Value "URL:NOVALI Client-Side PB Manager"
Set-ItemProperty -Path $protocolRoot -Name "URL Protocol" -Value ""
New-Item -Path $commandKey -Force | Out-Null
Set-Item -Path $commandKey -Value $command

Write-Host "Registered $protocol protocol for $launcher"
