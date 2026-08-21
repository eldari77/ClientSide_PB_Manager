param(
    [string]$PackageRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

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

