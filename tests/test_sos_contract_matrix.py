from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import sos
from sos import services

from worker.scripts.sos_dashboard import run as run_dashboard_adapter
from worker.worker import (
    BridgeScriptConfig,
    WorkerScript,
    child_service_telemetry,
    enriched_child_runtime_telemetry,
    execute_request,
    load_bridge_script_configs,
)


ADDON_SRC = Path(
    r"C:\Users\eLDARi\Documents\VScode\.venv\SOS-Starship-Operating-System\SOS-Starship-Operating-System\src\sos"
)
ALLOWED_SOS_COMMAND_KINDS = {"echo", "write_text_surface"}
DASHBOARD_COMPOSED_SERVICES = {
    "alerts",
    "airlock",
    "comms",
    "crew",
    "defense",
    "diagnostics",
    "display",
    "docking",
    "endurance",
    "environment",
    "guidance",
    "integrity",
    "life_support",
    "logistics",
    "maintenance",
    "mining",
    "mission_profile",
    "mobility",
    "navigation",
    "power",
    "production",
    "readiness",
    "runbook",
    "transit",
    "watch_log",
}


def _read_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _manifest_sos_scripts() -> list[dict[str, Any]]:
    payload = _read_json("worker/manifest.json")
    return [script for script in payload["scripts"] if str(script["script_id"]).startswith("sos_")]


def _default_sos_ship() -> dict[str, Any]:
    payload = _read_json("data/sos_ships.json")
    return payload["ships"][0]


def _mounted_sos_services() -> list[dict[str, Any]]:
    return [service for service in _default_sos_ship()["services"] if "-sos_" in service["script_id"]]


def _default_instance_ids() -> set[str]:
    payload = _read_json("data/script_instances.json")
    return set(payload["instances"])


def _service_id_from_script_id(script_id: str) -> str:
    return script_id.removeprefix("sos_")


def _write_sos_registry(root: Path, bridge_id: str, services_payload: list[dict[str, Any]]) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "sos_ships.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.sos_ships.v1",
                "ships": [
                    {
                        "ship_id": f"ship-{bridge_id}",
                        "bridge_id": bridge_id,
                        "display_name": "Matrix Ship",
                        "expected_grid_entity_id": 0,
                        "mode": "Docked",
                        "services": services_payload,
                        "status_surfaces": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _request(bridge_id: str, script_id: str) -> dict[str, Any]:
    return {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": bridge_id,
        "sequence": 1,
        "script_id": script_id,
        "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 0, "blocks": []},
        "runtime_telemetry": {},
        "state": {},
    }


def test_manifest_sos_scripts_have_thin_adapter_default_instance_and_sos_ship_mount() -> None:
    mounted_by_script_id = {service["script_id"]: service for service in _mounted_sos_services()}
    instance_ids = _default_instance_ids()

    for script in _manifest_sos_scripts():
        script_id = script["script_id"]
        service_id = _service_id_from_script_id(script_id)
        mounted_id = f"pb-bridge-001-{script_id}"

        assert script["module"] == f"worker.scripts.{script_id}"
        assert Path("worker", "scripts", f"{script_id}.py").exists()
        assert mounted_id in instance_ids
        assert mounted_by_script_id[mounted_id]["service_id"] == service_id


def test_thin_adapters_delegate_to_editable_sos_service_run(monkeypatch) -> None:
    for script in _manifest_sos_scripts():
        script_id = script["script_id"]
        service_id = _service_id_from_script_id(script_id)
        adapter = importlib.import_module(f"worker.scripts.{script_id}")
        service_module = getattr(adapter, f"_{service_id}_service")
        sentinel = {"summary": f"{service_id} delegated", "commands": [{"kind": "echo", "text": service_id}]}

        def fake_run(request: dict[str, Any], expected_service: str = service_id) -> dict[str, Any]:
            assert request["service_under_test"] == expected_service
            return sentinel

        monkeypatch.setattr(service_module, "run", fake_run)

        assert adapter.run({"service_under_test": service_id}) is sentinel


def test_editable_sos_imports_resolve_to_nested_addon_source() -> None:
    assert Path(sos.__file__).resolve().is_relative_to(ADDON_SRC)
    for service_id in services.__all__:
        module = importlib.import_module(f"sos.services.{service_id}")
        assert Path(module.__file__).resolve().is_relative_to(ADDON_SRC / "services")


def test_orchestrator_expansion_includes_all_configured_sos_children() -> None:
    config = load_bridge_script_configs(Path("."))["pb-bridge-001"]
    mounted_script_ids = [service["script_id"] for service in _default_sos_ship()["services"]]

    assert config.selected_script_id == "pb-bridge-001-orchestrator"
    assert list(config.allowed_worker_scripts) == ["pb-bridge-001-orchestrator", *mounted_script_ids]
    assert [child["script_id"] for child in config.child_worker_scripts] == mounted_script_ids
    assert {child["service_id"] for child in config.child_worker_scripts} == {
        service["service_id"] for service in _default_sos_ship()["services"]
    }


def test_dashboard_no_history_summary_has_unknown_tokens_for_all_composed_services() -> None:
    result = run_dashboard_adapter(
        {
            "bridge_id": "pb-bridge-001",
            "sos_ship": {"ship_id": "ship-pb-bridge-001", "display_name": "Primary SOS Ship", "status_surfaces": []},
        }
    )

    for service_id in sorted(DASHBOARD_COMPOSED_SERVICES):
        assert f"{service_id}=unknown" in result["summary"]


def test_runtime_telemetry_history_reaches_list_service_and_script_indexes() -> None:
    child_configs = (
        {"script_id": "bridge-a-sos_status", "service_id": "status"},
        {"script_id": "bridge-a-sos_readiness", "service_id": "readiness"},
        {"script_id": "bridge-a-sos_power", "service_id": "power"},
    )
    previous_payload = {
        "queue_pressure": {
            "queued": 3,
            "drained": 1,
            "remaining": 2,
            "by_source": {"bridge-a-sos_power": {"queued": 2, "drained": 1, "remaining": 1}},
        },
        "child_results": [
            {
                "script_id": "bridge-a-sos_status",
                "status": "ok",
                "error_bucket": "none",
                "summary": "status ok",
                "result": {"sos_status": {"mode": "Combat", "identity_status": "ok"}},
            },
            {
                "script_id": "bridge-a-sos_readiness",
                "status": "ok",
                "error_bucket": "none",
                "summary": "readiness ready",
                "result": {"sos_readiness": {"state": "ready", "summary": "ready sources=1 blockers=0 warnings=0"}},
            },
            {
                "script_id": "bridge-a-sos_power",
                "status": "ok",
                "error_bucket": "none",
                "summary": "power warning",
                "result": {"sos_power": {"state": "warning", "snapshot_status": "ok"}},
            },
        ],
    }

    telemetry_list = child_service_telemetry(child_configs, previous_payload, previous_payload["queue_pressure"])
    by_service = {item["service_id"]: item for item in telemetry_list}
    by_script = {item["script_id"]: item for item in telemetry_list}

    assert by_service["status"]["result"]["sos_status"]["mode"] == "Combat"
    assert by_service["readiness"]["result"]["sos_readiness"]["state"] == "ready"
    assert by_script["bridge-a-sos_power"]["result"]["sos_power"]["state"] == "warning"
    assert by_script["bridge-a-sos_power"]["command_queue"] == {"queued": 2, "drained": 1, "remaining": 1}


def test_enriched_runtime_telemetry_exposes_child_history_in_all_supported_shapes(tmp_path: Path) -> None:
    result_dir = tmp_path / "data" / "bridge_results"
    result_dir.mkdir(parents=True)
    (result_dir / "bridge-a.json").write_text(
        json.dumps(
            {
                "result": {
                    "child_results": [
                        {
                            "script_id": "bridge-a-sos_status",
                            "status": "ok",
                            "error_bucket": "none",
                            "summary": "status ok",
                            "result": {"sos_status": {"mode": "Combat"}},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    telemetry = enriched_child_runtime_telemetry(
        tmp_path,
        {"bridge_id": "bridge-a", "runtime_telemetry": {"limiter_state": "ok"}},
        ({"script_id": "bridge-a-sos_status", "service_id": "status"},),
    )

    assert telemetry["child_services"][0]["result"]["sos_status"]["mode"] == "Combat"
    assert telemetry["child_services_by_service_id"]["status"]["result"]["sos_status"]["mode"] == "Combat"
    assert telemetry["child_services_by_script_id"]["bridge-a-sos_status"]["result"]["sos_status"]["mode"] == "Combat"


def test_service_specific_snapshot_aliases_do_not_leak_to_sibling_children(tmp_path: Path) -> None:
    captured: dict[str, set[str]] = {}
    service_ids = ("endurance", "watch_log", "runbook", "readiness", "diagnostics", "maintenance", "status")
    service_specific_aliases = {
        "endurance_snapshot",
        "watch_log_snapshot",
        "runbook_snapshot",
        "readiness_snapshot",
        "diagnostics_snapshot",
        "maintenance_snapshot",
    }
    services_payload = [{"script_id": f"bridge-a-sos_{service_id}", "service_id": service_id} for service_id in service_ids]
    _write_sos_registry(tmp_path, "bridge-a", services_payload)

    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A SOS",
            "",
            "adapter_tick.v1",
            "compact_commands.v1",
            1000,
            True,
            base_script_id="bridge_orchestrator",
            instance_bridge_id="bridge-a",
        )
    }
    for service_id in service_ids:
        module_name = f"tests.matrix_capture_{service_id}"
        module = types.ModuleType(module_name)

        def run(request: dict[str, Any], expected_service: str = service_id) -> dict[str, Any]:
            captured[expected_service] = set(request)
            return {"summary": expected_service, "commands": [{"kind": "echo", "text": expected_service}]}

        module.run = run
        sys.modules[module_name] = module
        scripts[f"bridge-a-sos_{service_id}"] = WorkerScript(
            f"bridge-a-sos_{service_id}",
            "manual",
            service_id,
            module_name,
            "adapter_tick.v1",
            "compact_commands.v1",
            1000,
            True,
        )

    request = _request("bridge-a", "bridge-a-orchestrator") | {
        "endurance_snapshot": {"cargo": {"used_volume": 10, "max_volume": 100}},
        "watch_log_snapshot": {"events": [{"message": "watch"}]},
        "runbook_snapshot": {"procedure": "Cruise Watch"},
        "readiness_snapshot": {"sources": [{"service_id": "power", "state": "ok"}]},
        "diagnostics_snapshot": {"checked_services": ["status"]},
        "maintenance_snapshot": {"projectors": [{"name": "Projector"}]},
    }
    result = execute_request(request, scripts, {}, tmp_path)

    assert result["status"] == "ok"
    assert "endurance_snapshot" in captured["endurance"]
    assert "watch_log_snapshot" in captured["watch_log"]
    assert "runbook_snapshot" in captured["runbook"]
    assert "readiness_snapshot" in captured["readiness"]
    assert "diagnostics_snapshot" in captured["diagnostics"]
    assert "maintenance_snapshot" in captured["maintenance"]
    assert captured["status"].isdisjoint(service_specific_aliases)
    assert "watch_log_snapshot" not in captured["endurance"]
    assert "runbook_snapshot" not in captured["watch_log"]
    assert "watch_log_snapshot" not in captured["runbook"]
    assert "maintenance_snapshot" not in captured["diagnostics"]


def test_configured_sos_orchestrator_no_history_tick_stays_within_command_allowlist_and_size_boundary(tmp_path: Path) -> None:
    _write_sos_registry(tmp_path, "pb-bridge-001", _default_sos_ship()["services"])
    scripts = {
        script_id: script
        for script_id, script in __import__("worker.worker", fromlist=["load_manifest"]).load_manifest(Path(".")).items()
        if script_id.startswith("pb-bridge-001-") or script_id.startswith("sos_") or script_id in {"bridge_orchestrator"}
    }
    result = execute_request(
        _request("pb-bridge-001", "pb-bridge-001-orchestrator"),
        scripts,
        {},
        tmp_path,
    )
    commands = result["result"]["commands"]

    assert result["status"] == "ok"
    assert result["result"]["orchestrator"]["child_count"] == len(_default_sos_ship()["services"])
    assert {command["kind"] for command in commands} <= ALLOWED_SOS_COMMAND_KINDS
    assert len(json.dumps(result, separators=(",", ":"))) < 64000
