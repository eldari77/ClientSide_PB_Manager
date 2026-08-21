param(
    [string]$PackageRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$exe = Join-Path $PackageRoot "manager\NOVALI.ClientSidePBManager.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Manager executable not found: $exe"
}

Start-Process -FilePath $exe -WorkingDirectory $PackageRoot -WindowStyle Normal

