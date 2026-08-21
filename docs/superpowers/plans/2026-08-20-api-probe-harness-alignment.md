# API Probe Harness Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local API probe and harness alignment report so Space Engineers API drift becomes visible and safe harness updates can be planned from evidence.

**Architecture:** A Python discovery module reads current virtual PB capabilities and a static API surface report. The first probe source is deterministic and testable: it can parse C# interface/enum declarations from harness support or a source fixture, and it can later be pointed at generated reflection output from game assemblies. Discovery embeds the alignment summary while preserving the safety model that mutating APIs are diagnostics until mapped to reviewed bridge commands.

**Tech Stack:** Python discovery CLI, JSON reports under `data/`, existing `virtual_pb_runner --mode capabilities`, pytest, manager-readable discovery schema.

---

### Task 1: API Surface Probe

**Files:**
- Create: `discovery/api_probe.py`
- Test: `tests/test_api_probe.py`

- [ ] Write tests that parse a C# fixture containing `IMyTextSurface`, `IMyAssembler`, and an enum.
- [ ] Verify the tests fail before implementation.
- [ ] Implement `probe_api_surface_from_source`, `write_api_surface_report`, and a CLI that writes `data/se_api_surface.json`.
- [ ] Verify focused tests pass.

### Task 2: Harness Alignment

**Files:**
- Modify: `discovery/api_probe.py`
- Test: `tests/test_api_probe.py`

- [ ] Write tests that classify members as `supported`, `missing_read_stub`, `mutation_requires_command_mapping`, and `blocked_for_safety`.
- [ ] Verify the tests fail before implementation.
- [ ] Implement `align_api_surface_with_harness` and `write_harness_alignment_report`.
- [ ] Verify focused tests pass.

### Task 3: Active Discovery Integration

**Files:**
- Modify: `discovery/active_discovery.py`
- Test: `tests/test_active_discovery.py`

- [ ] Write tests expecting discovery to include `api_probe` status, counts, stale flag, and exact repair actions.
- [ ] Verify the tests fail before implementation.
- [ ] Load `data/se_api_surface.json`, `data/harness_alignment.json`, and `data/virtual_pb_capabilities.json` into discovery.
- [ ] Verify focused tests pass.

### Task 4: Validation and Live Check

**Files:**
- No source files unless tests expose a defect.

- [ ] Run `python -m pytest tests/test_api_probe.py tests/test_active_discovery.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Run `dotnet build virtual_pb_runner\NOVALI.VirtualPBRunner.csproj --nologo`.
- [ ] Run `dotnet build manager\NOVALI.ClientSidePBManager.csproj --nologo -p:OutDir="$env:TEMP\novali-manager-build\"`.
- [ ] Run `python -m discovery.api_probe --root . --output data\se_api_surface.json --alignment-output data\harness_alignment.json`.
- [ ] Run `python -m discovery.active_discovery --root . --output data\discovery_report.json`.
- [ ] Inspect live `data\bridge_requests\pb-bridge-001.json` after SE/Pulsar restarts and confirm whether LCD snapshot fields include `surface_size`, `texture_size`, and `font_size`.
