# NOVALI Client-Side PB Bridge Beta

This private beta package lets a Space Engineers player run supported Programmable Block workloads locally through a small in-game bridge PB, a Pulsar local plugin, and a Docker worker.

Start here:

1. Read `docs/setup-guide.md`.
2. Run `scripts/install-or-update.ps1` from PowerShell.
3. Open the manager with `scripts/open-manager.ps1`.
4. In Space Engineers, paste `pb/ClientSidePBBridgeShim.cs` into the bridge PB.
5. Use the manager's Bridges tab to copy PB CustomData into that same PB.
6. Recompile the PB, then run the profile check in `docs/profiling-checklist.md`.

This package is local-only. It does not edit Steam Workshop items, does not run arbitrary PB C# from Docker, and the in-game shim only applies reviewed command kinds.

