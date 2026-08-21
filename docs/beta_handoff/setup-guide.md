# Setup Guide

Audience: private beta testers who are comfortable launching Space Engineers but should not need to build the project by hand.

## Prerequisites

- Space Engineers installed through Steam.
- Pulsar installed and enabled for Space Engineers.
- Docker Desktop installed and running.
- Windows PowerShell.
- If the packaged manager does not open, install the .NET Desktop Runtime that matches the package note from the sender.

## Install Or Update

1. Unzip the package to a normal user folder such as `Documents\NOVALI-ClientSidePB-Bridge-beta`.
2. Right-click PowerShell and choose normal user mode. Administrator is not required.
3. Run:

```powershell
cd "$HOME\Documents\NOVALI-ClientSidePB-Bridge-beta"
.\scripts\install-or-update.ps1
```

The installer creates local data folders, copies `NOVALI.ClientSidePBBridge.dll` into `%APPDATA%\Pulsar\Legacy\Local`, registers the manager URL protocol for this package, and starts the Docker worker with `docker compose up --build -d`.

## Configure The Bridge PB

1. Start Space Engineers with Pulsar enabled.
2. Load a creative test world before joining a live server.
3. Place or choose one Programmable Block on the target grid.
4. Open `pb\ClientSidePBBridgeShim.cs`.
5. Copy the whole file into the PB code editor.
6. Compile the PB.
7. Open the manager with:

```powershell
.\scripts\open-manager.ps1
```

8. In the manager, use the Bridges tab.
9. Click `Copy PB Shim Script` if you need to refresh the PB code.
10. Click `Copy PB CustomData`.
11. Paste that text into the bridge PB Custom Data field.
12. Recompile the PB.

For scripts such as Isy's Inventory Manager that read `Me.CustomData`, select the worker script in the manager, open the `Custom Data` tab next to `Config`, paste the script's Custom Data there, and save.

## Start And Verify

1. In the manager, start Docker from the Docker tab if it is not running.
2. Click `Open Worker UI`, or open `http://localhost:8788`.
3. Check that bridge health is `active`.
4. Check that worker results are `ok`.
5. Run the 5-minute profile in `docs/profiling-checklist.md`.

## Before A Live Server

Use a creative copy of the ship or station first. Stay out of the live server until:

- Bridge health is `active`.
- PB limiter is `ok`.
- Result status is `ok`.
- Skipped command count is `0`.
- Queue remaining is usually `0`.
- PB runtime is comfortably below the configured runtime limit.

## Troubleshooting

If the plugin DLL is locked, close Space Engineers and Pulsar, then run `scripts\install-or-update.ps1` again.

If Docker fails to start, open Docker Desktop first, wait for it to finish booting, then run `scripts\start-worker.ps1`.

If the manager says the shim or CustomData does not match, copy PB CustomData again from the manager, paste it into the in-game PB Custom Data field, and recompile.

If bridge health becomes stale, scripts should pause until a fresh in-game heartbeat returns. Do not force commands onto a live server while the bridge is stale.
