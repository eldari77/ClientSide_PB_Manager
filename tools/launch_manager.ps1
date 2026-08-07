param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$ProtocolUrl = "",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$project = Join-Path $ProjectRoot "manager\NOVALI.ClientSidePBManager.csproj"
$builtExe = Join-Path $ProjectRoot "manager\bin\Debug\net10.0-windows\NOVALI.ClientSidePBManager.exe"

if ($NoLaunch) {
    Write-Host "Manager project: $project"
    if (Test-Path -LiteralPath $builtExe) {
        Write-Host "Built manager: $builtExe"
    }
    return
}

if (Test-Path -LiteralPath $builtExe) {
    Start-Process -FilePath $builtExe -WorkingDirectory $ProjectRoot
    return
}

Start-Process -FilePath "dotnet" -ArgumentList @("run", "--project", $project) -WorkingDirectory $ProjectRoot -WindowStyle Hidden
