param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Url = "http://localhost:8788",
    [int]$TimeoutSeconds = 30,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

Push-Location $ProjectRoot
try {
    docker compose up --build -d client-side-pb-worker

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                if (-not $NoOpen) {
                    Start-Process $Url
                    Write-Host "Opened $Url"
                }
                else {
                    Write-Host "Worker UI ready at $Url"
                }
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    if (-not $NoOpen) {
        Start-Process $Url
    }
    Write-Host "Started worker, but $Url did not return HTTP 200 within $TimeoutSeconds seconds."
}
finally {
    Pop-Location
}
