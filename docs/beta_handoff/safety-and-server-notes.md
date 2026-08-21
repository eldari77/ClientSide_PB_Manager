# Safety And Server Notes

This bridge is designed as a local-only helper for reducing server-side PB work.

## Boundaries

- The manager and Docker worker run on the player's computer.
- The Pulsar plugin mirrors bridge mailbox files between the game client and local disk.
- The PB shim remains the only in-game execution surface.
- There is no arbitrary PB C# execution in Docker.
- The PB shim applies only reviewed, allowlisted command kinds.
- Commands are same-construct guarded unless explicitly configured otherwise.
- Steam Workshop cache files are not modified.

## Stale Link Behavior

If the in-game bridge stops producing fresh requests, bridge health moves to stale or concealed suspected. Worker-side scripts should pause rather than continue issuing commands from old snapshots.

This is intentional. A stale bridge means the local worker no longer has current game truth.

## Live Server Guidance

Run the 5-minute profile in a creative copy before using a live server. For a live server trial, keep the first session short and watch:

- PB runtime and limiter state.
- Instruction pressure.
- Queue remaining.
- Skipped commands.
- Bridge health.
- LCD timestamp freshness.

If any of those drift, stop the worker with `scripts\stop-worker.ps1` or Docker Desktop before troubleshooting.

## Supported Beta Path

The first beta path is the guided bridge flow with recognized safe profiles such as Isy's Inventory Manager. Other scripts may appear in discovery but should not be enabled on a live server until their adapter or virtual PB compatibility status is clear.

