param(
    [string]$PackageRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

Push-Location $PackageRoot
try {
    & docker compose down
}
finally {
    Pop-Location
}

