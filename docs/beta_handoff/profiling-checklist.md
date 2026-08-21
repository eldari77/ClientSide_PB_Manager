# 5-Minute Profile Checklist

Run this from the package folder after the PB shim and CustomData are loaded in a creative world.

```powershell
$durationSeconds = 300
$intervalSeconds = 10
$samples = @()
$end = (Get-Date).AddSeconds($durationSeconds)
while ((Get-Date) -lt $end) {
  $req = Get-Content data\bridge_requests\pb-bridge-001.json -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
  $res = Get-Content data\bridge_results\pb-bridge-001.json -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
  $worker = Get-Content data\worker_status.json -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
  $samples += [pscustomobject]@{
    time = (Get-Date).ToString("HH:mm:ss")
    req_seq = $req.sequence
    res_seq = $res.sequence
    limiter = $req.runtime_telemetry.limiter_state
    pb_ms = $req.runtime_telemetry.last_runtime_ms
    instructions = "$($req.runtime_telemetry.current_instruction_count)/$($req.runtime_telemetry.max_instruction_count)"
    budget = $req.runtime_telemetry.dynamic_apply_budget
    applied = $req.state.last_apply.applied
    skipped = $req.state.last_apply.skipped
    queue = "$($res.result.command_queue.drained)/$($res.result.command_queue.queued) rem=$($res.result.command_queue.remaining)"
    health = $worker.bridge_health.'pb-bridge-001'.status
  }
  $samples[-1] | Format-Table -AutoSize
  Start-Sleep -Seconds $intervalSeconds
}
$samples | Export-Csv data\profile-samples.csv -NoTypeInformation
```

Ready-for-live signals:

- `limiter` is `ok`.
- `pb_ms` is comfortably below the configured limit.
- `skipped` stays `0`.
- Queue `rem=0` most cycles.
- `health` stays `active`.
- Request and result sequences keep advancing.

