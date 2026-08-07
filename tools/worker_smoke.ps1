param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"
$requests = Join-Path $ProjectRoot "data\bridge_requests"
New-Item -ItemType Directory -Force -Path $requests | Out-Null
@{
    schema = "novali.client_side_pb_bridge.v1"
    message_kind = "request"
    bridge_id = "smoke-bridge"
    sequence = 1
    script_id = "sample_status_adapter"
    request_kind = "adapter_tick"
    runtime_telemetry = @{
        last_runtime_ms = 0.01
        max_runtime_ms = 0.02
        current_instruction_count = 10
        max_instruction_count = 50000
        limiter_state = "ok"
    }
    state = @{
        block_count = 2
        inventory_count = 1
    }
} | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $requests "smoke-bridge.json") -Encoding UTF8

Push-Location $ProjectRoot
try {
    python -m worker.worker --root . --once
    Get-Content -Path data\bridge_results\smoke-bridge.json
}
finally {
    Pop-Location
}
