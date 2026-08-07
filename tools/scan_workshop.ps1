param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"
Push-Location $ProjectRoot
try {
    python -m workshop.scan_workshop --output data\workshop_catalog.json
}
finally {
    Pop-Location
}

