import json
import os
import sys
import time
import types
from pathlib import Path

from worker.worker import (
    BridgeScriptConfig,
    WorkerScript,
    apply_command_queue,
    command_priority,
    command_queue_drain_count,
    command_queue_key,
    cleanup_processed_requests,
    execute_request,
    learn_autocrafting_blueprints,
    load_effective_worker_config,
    load_bridge_health,
    latest_request_path,
    load_manifest,
    render_status_page,
    process_pending,
    update_bridge_health,
)


def test_execute_sample_adapter():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "sample_status_adapter",
            "state": {"block_count": 2, "inventory_count": 3},
        },
        scripts,
    )
    assert result["status"] == "ok"
    assert result["message_kind"] == "result"
    assert result["result"]["summary"] == "blocks=2;inventory=3"


def test_execute_rejects_bad_sequence():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 0,
            "script_id": "sample_status_adapter",
        },
        scripts,
    )
    assert result["status"] == "rejected"
    assert result["error_bucket"] == "sequence_invalid"


def test_worker_status_page_renders_container_ui_link_target(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "worker_status.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_status.v1",
                "updated_at": "2026-08-07T16:00:00+00:00",
                "processed": 3,
                "limiter_states": {"pb-bridge-001": "ok"},
            }
        ),
        encoding="utf-8",
    )
    (data / "virtual_pb_compatibility.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.virtual_pb_compatibility.v1",
                "scripts": {
                    "virtual_whip_auto_door": {
                        "status": "supported",
                        "emitted_command_kinds": ["set_door_open"],
                    },
                    "workshop_blocked_template": {
                        "status": "blocked_command_mapping",
                        "blocked_command_mappings": ["Dangerous.Property"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (data / "bridge_scripts.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridge_scripts.v1",
                "bridges": {
                    "pb-bridge-001": {
                        "selected_script_id": "pb-bridge-001-orchestrator",
                        "allowed_worker_scripts": ["pb-bridge-001-orchestrator", "pb-bridge-001-virtual_whip_auto_door"],
                        "child_worker_scripts": [
                            {"script_id": "pb-bridge-001-virtual_whip_auto_door", "enabled": True, "budget": 1, "priority": 10}
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    results = data / "bridge_results"
    results.mkdir()
    (results / "pb-bridge-001.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "result": {
                    "child_results": [
                        {
                            "script_id": "pb-bridge-001-virtual_whip_auto_door",
                            "status": "rejected",
                            "error_bucket": "virtual_pb_unsupported_api",
                            "summary": "Virtual PB script rejected by compatibility analysis.",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    html = render_status_page(tmp_path)

    assert "NOVALI Client-Side PB Gateway" in html
    assert "Processed requests" in html
    assert "pb-bridge-001" in html
    assert "virtual_whip_auto_door" in html
    assert "Open Configuration UI" in html
    assert "novali-client-side-pb-manager://open" in html
    assert "Launch Diagnostics" in html
    assert "/manager-launch.log" in html
    assert "Active Bridge Scripts" in html
    assert "pb-bridge-001-orchestrator" in html
    assert "pb-bridge-001-virtual_whip_auto_door" in html
    assert "rejected: virtual_pb_unsupported_api" in html
    assert "Virtual PB Compatibility Inventory" in html
    assert "Import compatibility reports are not active bridge failures unless the script is assigned above." in html


def test_docker_compose_publishes_worker_ui_port():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "8788:8788" in compose
    assert "NOVALI_CLIENT_SIDE_PB_UI_PORT" in compose


def test_worker_status_server_exposes_manager_launch_log_source():
    source = Path("worker/worker.py").read_text(encoding="utf-8")

    assert 'self.path == "/manager-launch.log"' in source
    assert 'manager_launch.log' in source
    assert "text/plain; charset=utf-8" in source


def test_update_bridge_health_marks_stale_bridge_as_concealed_suspected(tmp_path: Path):
    data = tmp_path / "data"
    processed = data / "bridge_requests" / "processed"
    results = data / "bridge_results"
    processed.mkdir(parents=True)
    results.mkdir(parents=True)
    (data / "bridges.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridges.v1",
                "bridges": {"bridge-a": {"bridge_id": "bridge-a", "display_name": "Bridge A"}},
            }
        ),
        encoding="utf-8",
    )
    request_path = processed / "bridge-a-1000.json"
    result_path = results / "bridge-a.json"
    request_path.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 4}), encoding="utf-8")
    result_path.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 4, "status": "ok"}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(request_path, (old, old))
    os.utime(result_path, (old, old))

    payload = update_bridge_health(tmp_path, stale_seconds=60)

    assert payload["bridges"]["bridge-a"]["status"] == "concealed_suspected"
    assert payload["bridges"]["bridge-a"]["queue_policy"] == "hold_until_fresh_heartbeat"


def test_update_bridge_health_marks_recovered_after_fresh_heartbeat(tmp_path: Path):
    data = tmp_path / "data"
    requests = data / "bridge_requests"
    results = data / "bridge_results"
    requests.mkdir(parents=True)
    results.mkdir(parents=True)
    (data / "bridges.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridges.v1",
                "bridges": {"bridge-a": {"bridge_id": "bridge-a", "display_name": "Bridge A"}},
            }
        ),
        encoding="utf-8",
    )
    (data / "bridge_health.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridge_health.v1",
                "bridges": {"bridge-a": {"status": "concealed_suspected"}},
            }
        ),
        encoding="utf-8",
    )
    (requests / "bridge-a.json").write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 5}), encoding="utf-8")
    (results / "bridge-a.json").write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 5, "status": "ok"}), encoding="utf-8")

    payload = update_bridge_health(tmp_path, stale_seconds=60)

    assert payload["bridges"]["bridge-a"]["status"] == "recovered"
    assert payload["bridges"]["bridge-a"]["queue_policy"] == "drain"


def test_latest_request_path_prefers_active_request_over_archived_history(tmp_path: Path):
    requests = tmp_path / "data" / "bridge_requests"
    processed = requests / "processed"
    processed.mkdir(parents=True)
    active = requests / "bridge-a.json"
    archived = processed / "bridge-a-9999999999999.json"
    active.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 2}), encoding="utf-8")
    archived.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    newer = time.time() + 60
    os.utime(archived, (newer, newer))

    assert latest_request_path(tmp_path, "bridge-a") == active


def test_latest_request_path_uses_archive_suffix_without_mtime_order(tmp_path: Path):
    processed = tmp_path / "data" / "bridge_requests" / "processed"
    processed.mkdir(parents=True)
    older_name = processed / "bridge-a-1000.json"
    latest_name = processed / "bridge-a-2000.json"
    older_name.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    latest_name.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 2}), encoding="utf-8")
    newer_mtime = time.time() + 60
    os.utime(older_name, (newer_mtime, newer_mtime))

    assert latest_request_path(tmp_path, "bridge-a") == latest_name


def test_cleanup_processed_requests_removes_files_older_than_retention(tmp_path: Path):
    processed = tmp_path / "data" / "bridge_requests" / "processed"
    processed.mkdir(parents=True)
    expired = processed / "bridge-a-1000.json"
    fresh = processed / "bridge-a-2000.json"
    non_json = processed / "notes.txt"
    expired.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    fresh.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 2}), encoding="utf-8")
    non_json.write_text("keep", encoding="utf-8")
    os.utime(expired, (1000, 1000))
    os.utime(fresh, (1190, 1190))

    stats = cleanup_processed_requests(tmp_path, retention_seconds=120, now=1200)

    assert stats["retention_seconds"] == 120
    assert stats["scanned"] == 2
    assert stats["removed"] == 1
    assert stats["failed"] == 0
    assert not expired.exists()
    assert fresh.exists()
    assert non_json.exists()


def test_cleanup_processed_requests_limits_deletions_per_pass(tmp_path: Path):
    processed = tmp_path / "data" / "bridge_requests" / "processed"
    processed.mkdir(parents=True)
    for index in range(5):
        path = processed / f"bridge-a-{index}.json"
        path.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": index}), encoding="utf-8")
        os.utime(path, (1000, 1000))

    stats = cleanup_processed_requests(tmp_path, retention_seconds=120, now=1200, max_files_per_pass=2)

    assert stats["removed"] == 2
    assert stats["limit_reached"] == 1
    assert (len(list(processed.glob("*.json")))) == 3


def test_process_pending_reports_processed_request_cleanup(tmp_path: Path):
    data = tmp_path / "data"
    requests = data / "bridge_requests"
    processed = requests / "processed"
    results = data / "bridge_results"
    requests.mkdir(parents=True)
    processed.mkdir(parents=True)
    results.mkdir(parents=True)
    expired = processed / "bridge-a-1000.json"
    expired.write_text(json.dumps({"bridge_id": "bridge-a", "sequence": 1}), encoding="utf-8")
    os.utime(expired, (1000, 1000))

    process_pending(tmp_path, {})

    status = json.loads((data / "worker_status.json").read_text(encoding="utf-8"))
    cleanup = status["processed_request_cleanup"]
    assert cleanup["retention_seconds"] == 300
    assert cleanup["removed"] == 1
    assert not expired.exists()


def test_execute_request_holds_stale_snapshot_without_running_adapter():
    scripts = load_manifest(Path("."))
    stale = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 9,
            "script_id": "sample_status_adapter",
            "state": {"requested_at_utc": "2000-01-01T00:00:00Z", "block_count": 99, "inventory_count": 99},
        },
        scripts,
    )

    assert stale["status"] == "stale_held"
    assert stale["error_bucket"] == "stale_request_held"
    assert stale["result"]["commands"] == []
    assert stale["result"]["bridge_health"]["status"] == "concealed_suspected"


def test_execute_rejects_script_not_allowed_for_bridge():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "sample_status_adapter",
        },
        scripts,
        {"bridge-a": BridgeScriptConfig("workshop_1216126863_adapter", ("workshop_1216126863_adapter",))},
    )
    assert result["status"] == "rejected"
    assert result["error_bucket"] == "script_not_allowed_for_bridge"


def test_bridge_script_config_parses_orchestrator_children(tmp_path: Path):
    from worker.worker import load_bridge_script_configs

    root = tmp_path
    data = root / "data"
    data.mkdir()
    (data / "bridge_scripts.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.bridge_scripts.v1",
                "bridges": {
                    "bridge-orch": {
                        "selected_script_id": "bridge_orchestrator",
                        "allowed_worker_scripts": ["bridge_orchestrator", "sample_status_adapter"],
                        "child_worker_scripts": [
                            {
                                "script_id": "sample_status_adapter",
                                "enabled": True,
                                "budget": 2,
                                "priority": 5,
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    configs = load_bridge_script_configs(root)

    assert configs["bridge-orch"].selected_script_id == "bridge_orchestrator"
    assert configs["bridge-orch"].child_worker_scripts[0]["script_id"] == "sample_status_adapter"
    assert configs["bridge-orch"].child_worker_scripts[0]["budget"] == 2


def test_load_manifest_exposes_script_instance_aliases(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "status-base-grid": {
                        "instance_id": "status-base-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Base Grid",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                        "config_id": "status-base-grid",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)

    assert scripts["status-base-grid"].script_id == "status-base-grid"
    assert scripts["status-base-grid"].base_script_id == "sample_status_adapter"
    assert scripts["status-base-grid"].module == scripts["sample_status_adapter"].module
    assert scripts["status-base-grid"].instance_bridge_id == "bridge-a"


def test_execute_instance_alias_preserves_instance_id_for_result_and_config(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "status-base-grid": {
                        "instance_id": "status-base-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Base Grid",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                        "config_id": "status-base-grid",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config_dir = data / "worker_configs"
    config_dir.mkdir()
    (config_dir / "status-base-grid.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "status-base-grid",
                "entries": [{"key": "instance_marker", "value": "base-grid"}],
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 2,
            "script_id": "status-base-grid",
            "state": {"block_count": 1, "inventory_count": 0},
        },
        scripts,
        {"bridge-a": BridgeScriptConfig("status-base-grid", ("status-base-grid",))},
        root,
    )

    assert result["status"] == "ok"
    assert result["script_id"] == "status-base-grid"
    assert result["result"]["summary"] == "blocks=1;inventory=0"


def test_worker_instance_inherits_base_worker_config_when_instance_config_missing(tmp_path: Path):
    config_dir = tmp_path / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "workshop_1216126863_adapter.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "workshop_1216126863_adapter",
                "entries": [
                    {"key": "maxApplyCommands", "value": 8},
                    {"key": "maxPlannedMachineCommands", "value": 12},
                ],
            }
        ),
        encoding="utf-8",
    )
    script = WorkerScript(
        "pb-bridge-001-workshop_1216126863_adapter",
        "script_instance",
        "Isy Base Grid",
        "worker.scripts.workshop_1216126863_adapter",
        "adapter_tick.v1",
        "compact_commands.v1",
        1000,
        True,
        base_script_id="workshop_1216126863_adapter",
        config_id="pb-bridge-001-workshop_1216126863_adapter",
    )

    config = load_effective_worker_config(tmp_path, script)

    assert config["maxApplyCommands"] == 8
    assert config["maxPlannedMachineCommands"] == 12


def test_execute_instance_alias_rejects_wrong_bridge_or_disabled(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "status-base-grid": {
                        "instance_id": "status-base-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Base Grid",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                    "status-disabled-grid": {
                        "instance_id": "status-disabled-grid",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Status - Disabled Grid",
                        "bridge_id": "bridge-a",
                        "enabled": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)
    wrong_bridge = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-b",
            "sequence": 1,
            "script_id": "status-base-grid",
        },
        scripts,
        {"bridge-b": BridgeScriptConfig("status-base-grid", ("status-base-grid",))},
        root,
    )
    disabled = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 1,
            "script_id": "status-disabled-grid",
        },
        scripts,
        {"bridge-a": BridgeScriptConfig("status-disabled-grid", ("status-disabled-grid",))},
        root,
    )

    assert wrong_bridge["status"] == "rejected"
    assert wrong_bridge["error_bucket"] == "script_instance_bridge_mismatch"
    assert disabled["status"] == "rejected"
    assert disabled["error_bucket"] == "script_disabled"


def test_bridge_orchestrator_merges_child_commands_with_source_metadata():
    scripts = load_manifest(Path("."))
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-orch",
            "sequence": 3,
            "script_id": "bridge_orchestrator",
            "state": {"block_count": 2, "inventory_count": 1},
        },
        scripts,
        {
            "bridge-orch": BridgeScriptConfig(
                "bridge_orchestrator",
                ("bridge_orchestrator", "sample_status_adapter"),
                (
                    {
                        "script_id": "sample_status_adapter",
                        "enabled": True,
                        "budget": 2,
                        "priority": 10,
                    },
                ),
            )
        },
    )

    assert result["status"] == "ok"
    assert result["result"]["orchestrator"]["status"] == "processed"
    assert result["result"]["child_results"][0]["script_id"] == "sample_status_adapter"
    assert result["result"]["commands"][0]["source_script_id"] == "sample_status_adapter"


def test_bridge_orchestrator_instance_runs_child_instances(tmp_path: Path):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "bridge-a-orchestrator": {
                        "instance_id": "bridge-a-orchestrator",
                        "base_script_id": "bridge_orchestrator",
                        "display_name": "Bridge A Orchestrator",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                    "bridge-a-status": {
                        "instance_id": "bridge-a-status",
                        "base_script_id": "sample_status_adapter",
                        "display_name": "Bridge A Status",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "state": {"block_count": 2, "inventory_count": 1},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-status"),
                (
                    {
                        "script_id": "bridge-a-status",
                        "enabled": True,
                        "budget": 2,
                        "priority": 10,
                    },
                ),
            )
        },
        root,
    )

    assert result["status"] == "ok"
    assert result["script_id"] == "bridge-a-orchestrator"
    assert result["result"]["orchestrator"]["status"] == "processed"
    assert result["result"]["child_results"][0]["script_id"] == "bridge-a-status"
    assert result["result"]["commands"][0]["source_script_id"] == "bridge-a-status"


def test_virtual_pb_request_receives_custom_data_from_worker_config(tmp_path: Path, monkeypatch):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "virtual_fixture",
                        "source": "workshop_import",
                        "display_name": "Virtual Fixture",
                        "runtime": "virtual_pb_csharp",
                        "source_path": "data/imports/fixture/Script.cs",
                        "timeout_ms": 5000,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_dir = root / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "virtual_fixture.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "virtual_fixture",
                "entries": [
                    {
                        "key": "virtualPbCustomData",
                        "value": "station_mode;\nitemID;blueprintID\nMyObjectBuilder_Component/SteelPlate;MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0SteelPlate",
                        "value_type": "multiline_text",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    script_path = root / "data" / "imports" / "fixture" / "Script.cs"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("public Program() {} public void Main(string argument) {}", encoding="utf-8")

    def fake_run_virtual_pb(script_path: Path, request: dict, root: Path | None = None) -> dict:
        assert request["virtual_pb"]["custom_data"].startswith("station_mode;")
        assert request["virtual_pb"]["custom_data_source"] == "worker_config.virtualPbCustomData"
        return {"summary": "ok", "commands": []}

    monkeypatch.setattr("worker.virtual_pb.run_virtual_pb", fake_run_virtual_pb)

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "virtual_fixture",
            "grid_snapshot": {"blocks": []},
        },
        scripts,
        {},
        root,
    )

    assert result["status"] == "ok"


def test_bridge_orchestrator_reports_total_and_per_child_queue_counts(tmp_path: Path):
    def install_adapter(module_name: str, block_id: int) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": "planned one command",
                "commands": [
                    {
                        "kind": "set_block_enabled",
                        "block_entity_id": block_id,
                        "enabled": True,
                    }
                ],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.queue_child_a", 101)
    install_adapter("tests.queue_child_b", 202)

    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A Orchestrator",
            "",
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-child-a": WorkerScript("bridge-a-child-a", "manual", "Child A", "tests.queue_child_a", "", "", 1000, True),
        "bridge-a-child-b": WorkerScript("bridge-a-child-b", "manual", "Child B", "tests.queue_child_b", "", "", 1000, True),
    }
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 7,
            "script_id": "bridge-a-orchestrator",
            "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
            "state": {},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-child-a", "bridge-a-child-b"),
                (
                    {"script_id": "bridge-a-child-a", "enabled": True, "budget": 1, "priority": 10},
                    {"script_id": "bridge-a-child-b", "enabled": True, "budget": 1, "priority": 20},
                ),
            )
        },
        tmp_path,
    )

    assert result["status"] == "ok"
    assert result["result"]["command_queue"]["queued"] == 2
    assert result["result"]["command_queue"]["remaining"] == 1
    assert result["result"]["command_queue"]["by_source"]["bridge-a-child-a"] == {"queued": 1, "drained": 1, "remaining": 0}
    assert result["result"]["command_queue"]["by_source"]["bridge-a-child-b"] == {"queued": 1, "drained": 0, "remaining": 1}
    assert result["result"]["child_results"][0]["command_queue"] == {"queued": 1, "drained": 1, "remaining": 0}
    assert result["result"]["child_results"][1]["command_queue"] == {"queued": 1, "drained": 0, "remaining": 1}


def test_bridge_orchestrator_reports_scheduler_queue_pressure_and_operator_status(tmp_path: Path):
    def install_adapter(module_name: str, kind: str, block_id: int) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": "planned one command",
                "commands": [
                    {
                        "kind": kind,
                        "block_entity_id": block_id,
                        "open": True,
                    }
                ],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.scheduler_child_a", "set_door_open", 101)
    install_adapter("tests.scheduler_child_b", "set_door_open", 202)
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A Orchestrator",
            "",
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-door": WorkerScript("bridge-a-door", "manual", "Door", "tests.scheduler_child_a", "", "", 1000, True),
        "bridge-a-lcd": WorkerScript("bridge-a-lcd", "manual", "LCD", "tests.scheduler_child_b", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 7,
            "script_id": "bridge-a-orchestrator",
            "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 1},
            "state": {},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-door", "bridge-a-lcd"),
                (
                    {
                        "script_id": "bridge-a-door",
                        "enabled": True,
                        "budget": 1,
                        "priority": 5,
                        "role": "reactive",
                        "reactive": True,
                        "expires_after_sequences": 1,
                        "fairness_weight": 3,
                        "operator_status": "ready_virtual_pb",
                    },
                    {
                        "script_id": "bridge-a-lcd",
                        "enabled": True,
                        "budget": 1,
                        "priority": 30,
                        "role": "display",
                        "fairness_weight": 1,
                        "operator_status": "ready_virtual_pb",
                    },
                ),
            )
        },
        tmp_path,
    )

    output = result["result"]
    assert output["scheduler"]["policy"] == "priority_fairness_v1"
    assert output["scheduler"]["fairness"][0]["fairness_weight"] == 3
    assert output["queue_pressure"]["remaining"] == 1
    assert output["child_results"][0]["operator_status"] == "ready_virtual_pb"
    assert output["commands"][0]["expires_after_sequences"] == 1
    assert output["commands"][0]["source_role"] == "reactive"


def test_bridge_orchestrator_reports_same_target_conflicts_and_keeps_highest_priority_command(tmp_path: Path):
    def install_adapter(module_name: str, open_value: bool) -> None:
        module = types.ModuleType(module_name)

        def run(request):
            return {
                "summary": "planned conflicting door command",
                "commands": [
                    {
                        "kind": "set_door_open",
                        "block_entity_id": 777,
                        "open": open_value,
                    }
                ],
            }

        module.run = run
        sys.modules[module_name] = module

    install_adapter("tests.conflict_child_fast", False)
    install_adapter("tests.conflict_child_slow", True)
    scripts = {
        "bridge-a-orchestrator": WorkerScript(
            "bridge-a-orchestrator",
            "script_instance",
            "Bridge A Orchestrator",
            "",
            "",
            "",
            1000,
            True,
            base_script_id="bridge_orchestrator",
        ),
        "bridge-a-fast": WorkerScript("bridge-a-fast", "manual", "Fast", "tests.conflict_child_fast", "", "", 1000, True),
        "bridge-a-slow": WorkerScript("bridge-a-slow", "manual", "Slow", "tests.conflict_child_slow", "", "", 1000, True),
    }

    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 8,
            "script_id": "bridge-a-orchestrator",
            "state": {},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-fast", "bridge-a-slow"),
                (
                    {"script_id": "bridge-a-fast", "enabled": True, "budget": 1, "priority": 5},
                    {"script_id": "bridge-a-slow", "enabled": True, "budget": 1, "priority": 50},
                ),
            )
        },
        tmp_path,
    )

    output = result["result"]
    assert len(output["commands"]) == 1
    assert output["commands"][0]["source_script_id"] == "bridge-a-fast"
    assert output["commands"][0]["open"] is False
    assert output["conflicts"][0]["target"] == "set_door_open:777"
    assert output["conflicts"][0]["kept_source_script_id"] == "bridge-a-fast"
    assert output["conflicts"][0]["suppressed_source_script_ids"] == ["bridge-a-slow"]


def test_bridge_orchestrator_persists_child_virtual_pb_compatibility(tmp_path: Path, monkeypatch):
    root = tmp_path
    worker_dir = root / "worker"
    worker_dir.mkdir()
    (worker_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "bridge_orchestrator",
                        "source": "local_worker",
                        "display_name": "Bridge Orchestrator",
                        "module": "worker.scripts.bridge_orchestrator",
                        "runtime": "python",
                        "timeout_ms": 3000,
                        "enabled": True,
                    },
                    {
                        "script_id": "virtual_fixture",
                        "source": "workshop_import",
                        "display_name": "Virtual Fixture",
                        "module": "",
                        "runtime": "virtual_pb_csharp",
                        "source_path": "data/imports/fixture/Script.cs",
                        "timeout_ms": 5000,
                        "enabled": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    script_path = root / "data" / "imports" / "fixture" / "Script.cs"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("public Program() {} public void Main(string argument) {}", encoding="utf-8")
    (root / "data" / "script_instances.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.script_instances.v1",
                "instances": {
                    "bridge-a-orchestrator": {
                        "instance_id": "bridge-a-orchestrator",
                        "base_script_id": "bridge_orchestrator",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                    "bridge-a-virtual-fixture": {
                        "instance_id": "bridge-a-virtual-fixture",
                        "base_script_id": "virtual_fixture",
                        "bridge_id": "bridge-a",
                        "enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_virtual_pb(script_path: Path, request: dict, root: Path | None = None) -> dict:
        assert root == tmp_path
        return {
            "adapter_status": "rejected",
            "summary": "Virtual PB script rejected by compatibility analysis.",
            "commands": [{"kind": "echo", "text": "blocked"}],
            "error_bucket": "virtual_pb_unsupported_api",
            "compatibility": {
                "status": "unsupported",
                "compiled": False,
                "missing_members": ["IMyLightingBlock.BlinkIntervalSeconds"],
                "blocked_command_mappings": [],
                "available_command_kinds": ["set_door_open"],
            },
        }

    monkeypatch.setattr("worker.virtual_pb.run_virtual_pb", fake_run_virtual_pb)

    scripts = load_manifest(root)
    result = execute_request(
        {
            "schema": "novali.client_side_pb_bridge.v1",
            "message_kind": "request",
            "bridge_id": "bridge-a",
            "sequence": 3,
            "script_id": "bridge-a-orchestrator",
            "grid_snapshot": {"blocks": []},
        },
        scripts,
        {
            "bridge-a": BridgeScriptConfig(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-virtual-fixture"),
                ({"script_id": "bridge-a-virtual-fixture", "enabled": True, "budget": 1, "priority": 10},),
            )
        },
        root,
    )

    report = json.loads((root / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert result["result"]["child_results"][0]["status"] == "rejected"
    assert report["scripts"]["bridge-a-virtual-fixture"]["status"] == "unsupported"
    assert report["scripts"]["bridge-a-virtual-fixture"]["missing_members"] == ["IMyLightingBlock.BlinkIntervalSeconds"]


def test_process_pending_writes_result(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    (requests / "bridge-a.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-a",
                "sequence": 7,
                "script_id": "sample_status_adapter",
                "runtime_telemetry": {
                    "last_runtime_ms": 0.01,
                    "max_runtime_ms": 0.02,
                    "current_instruction_count": 10,
                    "max_instruction_count": 50000,
                    "limiter_state": "ok",
                },
                "state": {},
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result = json.loads((root / "data" / "bridge_results" / "bridge-a.json").read_text(encoding="utf-8"))
    assert result["sequence"] == 7
    assert result["message_kind"] == "result"
    assert result["status"] == "ok"
    assert result["runtime_telemetry"]["last_runtime_ms"] == 0.01
    assert result["limiter_state"] == "ok"


def test_process_pending_accepts_utf8_bom_request(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    payload = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-bom",
        "sequence": 1,
        "script_id": "sample_status_adapter",
        "state": {},
    }
    (requests / "bridge-bom.json").write_text(json.dumps(payload), encoding="utf-8-sig")
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result = json.loads((root / "data" / "bridge_results" / "bridge-bom.json").read_text(encoding="utf-8"))
    assert result["status"] == "ok"


def test_process_pending_writes_compact_result_for_pb_parser(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    (requests / "bridge-compact.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-compact",
                "sequence": 1,
                "script_id": "sample_status_adapter",
                "state": {},
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result_text = (root / "data" / "bridge_results" / "bridge-compact.json").read_text(encoding="utf-8")
    assert '"message_kind":"result"' in result_text


def test_command_queue_drain_uses_dynamic_pb_apply_budget():
    request = {
        "worker_config": {"commandQueueDrainPerResult": 1, "dynamicCommandQueueDrain": True},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 3},
    }
    adapter_output = {"max_apply_commands": 5}

    assert command_queue_drain_count(request, adapter_output) == 3


def test_command_queue_drain_clamps_dynamic_budget_to_result_budget():
    request = {
        "worker_config": {"commandQueueDrainPerResult": 1, "dynamicCommandQueueDrain": True},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 4},
    }
    adapter_output = {"max_apply_commands": 2}

    assert command_queue_drain_count(request, adapter_output) == 2


def test_command_queue_drain_can_keep_static_budget():
    request = {
        "worker_config": {"commandQueueDrainPerResult": 2, "dynamicCommandQueueDrain": False},
        "runtime_telemetry": {"dynamic_apply_commands": True, "dynamic_apply_budget": 4},
    }
    adapter_output = {"max_apply_commands": 5}

    assert command_queue_drain_count(request, adapter_output) == 2


def test_process_pending_injects_worker_config(tmp_path: Path):
    root = tmp_path
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(Path("worker/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    config_dir = root / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "sample_status_adapter.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "sample_status_adapter",
                "display_name": "Sample Status Adapter",
                "entries": [{"key": "example", "value": "enabled", "value_type": "string", "description": ""}],
            }
        ),
        encoding="utf-8",
    )
    (requests / "bridge-config.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-config",
                "sequence": 1,
                "script_id": "sample_status_adapter",
                "state": {},
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    assert (root / "data" / "bridge_results" / "bridge-config.json").exists()


def test_process_pending_writes_compact_isy_foundation_commands(tmp_path: Path, monkeypatch):
    root = tmp_path
    module_root = tmp_path / "modules"
    module_root.mkdir()
    (module_root / "isy_fixture_adapter.py").write_text(
        "from worker.isy_foundation import plan_isy_foundation\n\n"
        "def run(request):\n"
        "    return plan_isy_foundation(request)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(module_root))
    (root / "worker").mkdir()
    (root / "worker" / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_manifest.v1",
                "scripts": [
                    {
                        "script_id": "workshop_1216126863_adapter",
                        "source": "workshop_import",
                        "display_name": "Isy's Inventory Manager",
                        "module": "isy_fixture_adapter",
                        "input_schema": "adapter_tick.v1",
                        "output_schema": "compact_commands.v1",
                        "timeout_ms": 1000,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_dir = root / "data" / "worker_configs"
    config_dir.mkdir(parents=True)
    (config_dir / "workshop_1216126863_adapter.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.worker_config.v1",
                "script_id": "workshop_1216126863_adapter",
                "entries": [
                    {"key": "maxApplyCommands", "value": 4},
                    {"key": "maxPlannedMachineCommands", "value": 4},
                    {"key": "mainLCDKeyword", "value": "Main LCD"},
                    {"key": "enableAutocrafting", "value": True},
                    {"key": "enableOreBalancing", "value": False},
                    {"key": "enableIceBalancing", "value": False},
                    {"key": "enableUraniumBalancing", "value": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    requests = root / "data" / "bridge_requests"
    requests.mkdir(parents=True)
    (requests / "bridge-isy.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb_bridge.v1",
                "message_kind": "request",
                "bridge_id": "bridge-isy",
                "sequence": 3,
                "script_id": "workshop_1216126863_adapter",
                "request_kind": "adapter_tick",
                "state": {},
                "inventory_snapshot": {"source": "plugin", "blocks": []},
                "grid_snapshot": {
                    "source": "plugin",
                    "blocks": [
                        {"entity_id": 100, "name": "Main LCD", "same_construct": True, "is_lcd": True, "surface_count": 1},
                        {"entity_id": 200, "name": "Assembler", "same_construct": True, "is_assembler": True},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    scripts = load_manifest(root)
    assert process_pending(root, scripts) == 1
    result_text = (root / "data" / "bridge_results" / "bridge-isy.json").read_text(encoding="utf-8")
    assert any(kind in result_text for kind in ['"write_text_surface"', '"set_assembler_mode"', '"set_assembler_cooperative_mode"'])
    assert '"command_queue"' in result_text
    assert "\n" not in result_text


def test_worker_persists_modded_autocrafting_blueprints_from_manual_queue(tmp_path: Path):
    request = {
        "bridge_id": "bridge-mod",
        "script_id": "workshop_1216126863_adapter",
        "grid_snapshot": {
            "blocks": [
                {
                    "name": "Assembler",
                    "same_construct": True,
                    "is_assembler": True,
                    "production_queue": [
                        {
                            "item_id": 7,
                            "blueprint_id": "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent",
                            "amount": 1,
                        }
                    ],
                }
            ]
        },
    }
    learned = learn_autocrafting_blueprints(tmp_path, request)
    assert learned["items"]["quantumcore"]["component_subtype"] == "QuantumCore"
    assert learned["items"]["quantumcore"]["blueprint_id"] == "MyObjectBuilder_BlueprintDefinition/QuantumCoreComponent"
    persisted = json.loads(
        (tmp_path / "data" / "autocrafting_blueprints" / "bridge-mod-workshop_1216126863_adapter.json").read_text(encoding="utf-8")
    )
    assert persisted["items"]["quantumcore"]["aliases"] == ["QuantumCore", "QuantumCoreComponent"]


def test_worker_command_queue_drains_commands_in_steady_stream(tmp_path: Path):
    root = tmp_path
    request = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-queue",
        "sequence": 10,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 5,
        "commands": [
            {"kind": "set_use_conveyor", "block_entity_id": 1, "enabled": True, "command_id": "old:1"},
            {"kind": "set_use_conveyor", "block_entity_id": 2, "enabled": False, "command_id": "old:2"},
            {"kind": "set_gas_auto_refill", "block_entity_id": 3, "enabled": True, "command_id": "old:3"},
        ],
    }

    first = apply_command_queue(root, request, output)
    assert len(first["commands"]) == 1
    assert first["commands"][0]["block_entity_id"] == 1
    assert first["remaining_commands"] == 2
    assert first["command_queue"]["queued"] == 3

    request["sequence"] = 11
    request["state"] = {"last_apply": {"sequence": 10, "status": "processed", "applied": 1, "skipped": 0}}
    second = apply_command_queue(
        root,
        request,
        {
            **output,
            "commands": [
                {"kind": "set_use_conveyor", "block_entity_id": 2, "enabled": False, "command_id": "old:2"},
                {"kind": "set_gas_auto_refill", "block_entity_id": 3, "enabled": True, "command_id": "old:3"},
            ],
        },
    )
    assert len(second["commands"]) == 1
    assert second["commands"][0]["block_entity_id"] == 2
    assert second["remaining_commands"] == 1


def test_worker_command_queue_keeps_echo_passthrough(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 1,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {"kind": "echo", "text": "hello"},
            {"kind": "set_block_enabled", "block_entity_id": 7, "enabled": True},
        ],
    }

    result = apply_command_queue(tmp_path, request, output)
    assert [command["kind"] for command in result["commands"]] == ["echo", "set_block_enabled"]


def test_worker_command_queue_prunes_transfers_into_managed_machines(tmp_path: Path):
    queue_dir = tmp_path / "data" / "command_queues"
    queue_dir.mkdir(parents=True)
    stale_key = (
        '{"destination_entity_id":99,"destination_inventory_index":1,'
        '"item_subtype_id":"MealPack_KelpCrisp","item_type_id":"MyObjectBuilder_ConsumableItem",'
        '"kind":"transfer_item","source_entity_id":1,"source_inventory_index":0}'
    )
    (queue_dir / "bridge-queue.json").write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.command_queue.v1",
                "bridge_id": "bridge-queue",
                "script_id": "script-a",
                "entries": [
                    {
                        "key": stale_key,
                        "command": {
                            "kind": "transfer_item",
                            "source_entity_id": 1,
                            "source_inventory_index": 0,
                            "destination_entity_id": 99,
                            "destination_inventory_index": 1,
                            "item_type_id": "MyObjectBuilder_ConsumableItem",
                            "item_subtype_id": "MealPack_KelpCrisp",
                            "amount": 33,
                        },
                        "first_seen_sequence": 1,
                        "last_seen_sequence": 1,
                    }
                ],
                "in_flight": [{"key": stale_key, "command": {}}],
                "delivered": {},
            }
        ),
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-queue",
        "script_id": "script-a",
        "sequence": 2,
        "inventory_snapshot": {
            "blocks": [
                {
                    "entity_id": 99,
                    "type": "MyAssembler",
                    "subtype": "",
                    "inventories": [{"index": 0, "items": []}, {"index": 1, "items": []}],
                }
            ]
        },
    }

    result = apply_command_queue(tmp_path, request, {"apply_mode": "immediate", "max_apply_commands": 5, "commands": []})

    assert result["commands"] == []
    assert result["command_queue"]["queued"] == 0


def test_worker_command_queue_coalesces_transfer_amount_updates():
    first = {
        "kind": "transfer_item",
        "source_entity_id": 1,
        "source_inventory_index": 0,
        "destination_entity_id": 2,
        "destination_inventory_index": 0,
        "item_type_id": "MyObjectBuilder_Ore",
        "item_subtype_id": "Ice",
        "amount": 10,
    }
    second = {**first, "amount": 20}

    assert command_queue_key(first) == command_queue_key(second)
    assert command_queue_key(first) == command_queue_key({**second, "reason": "gas_generator_topup"})


def test_worker_command_queue_coalesces_autocrafting_enqueue_amount_updates():
    first = {
        "kind": "enqueue_assembler_blueprint",
        "block_entity_id": 1,
        "blueprint_id": "MyObjectBuilder_BlueprintDefinition/Display",
        "reason": "autocrafting_goal",
        "amount": 100,
    }
    second = {**first, "amount": 80}

    assert command_queue_key(first) == command_queue_key(second)


def test_worker_command_queue_prioritizes_reactive_orchestrator_source(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 10,
        "script_id": "bridge_orchestrator",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {
                "kind": "write_text_surface",
                "block_entity_id": 9,
                "surface_index": 0,
                "append": False,
                "text": "maintenance",
                "source_script_id": "workshop_1216126863_adapter",
                "source_priority": 50,
            },
            {
                "kind": "set_door_open",
                "block_entity_id": 100,
                "open": False,
                "source_script_id": "virtual_whip_auto_door",
                "source_priority": 5,
            },
        ],
    }

    result = apply_command_queue(tmp_path, request, output)

    assert result["commands"][0]["kind"] == "set_door_open"
    assert result["commands"][0]["source_script_id"] == "virtual_whip_auto_door"


def test_worker_command_queue_expires_stale_reactive_commands(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 1,
        "script_id": "bridge_orchestrator",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 0},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {
                "kind": "set_door_open",
                "block_entity_id": 100,
                "open": False,
                "source_script_id": "virtual_whip_auto_door",
                "expires_after_sequences": 1,
            }
        ],
    }
    first = apply_command_queue(tmp_path, request, output)
    assert first["queued_commands"] == 1

    request["sequence"] = 3
    second = apply_command_queue(tmp_path, request, {"apply_mode": "immediate", "max_apply_commands": 1, "commands": []})

    assert second["queued_commands"] == 0


def test_worker_command_queue_prioritizes_setup_then_allows_lcd_refresh(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 20,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1, "lcdCommandQueueCooldownSequences": 6},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {"kind": "transfer_item", "source_entity_id": 1, "source_inventory_index": 0, "destination_entity_id": 2, "destination_inventory_index": 0, "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Ice", "amount": 10},
            {"kind": "set_use_conveyor", "block_entity_id": 7, "enabled": False},
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "fresh"},
        ],
    }

    first = apply_command_queue(tmp_path, request, output)
    assert first["commands"][0]["kind"] == "set_use_conveyor"

    request["sequence"] = 21
    request["state"] = {"last_apply": {"sequence": 20, "status": "processed", "applied": 1, "skipped": 0}}
    second_output = dict(output)
    second_output["commands"] = [output["commands"][0], output["commands"][2]]
    second = apply_command_queue(tmp_path, request, second_output)
    assert second["commands"][0]["kind"] == "write_text_surface"


def test_worker_command_queue_default_lcd_cooldown_allows_next_sequence_refresh(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 50,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {"commandQueueDrainPerResult": 1},
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "first"},
        ],
    }

    first = apply_command_queue(tmp_path, request, output)
    assert first["commands"][0]["kind"] == "write_text_surface"

    request["sequence"] = 51
    request["state"] = {"last_apply": {"sequence": 50, "status": "processed", "applied": 1, "skipped": 0}}
    second = apply_command_queue(tmp_path, request, {**output, "commands": [{**output["commands"][0], "text": "second"}]})

    assert second["commands"][0]["kind"] == "write_text_surface"
    assert second["commands"][0]["text"] == "second"


def test_worker_command_queue_reserves_lcd_refresh_in_busy_mixed_batch(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 60,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {
            "commandQueueDrainPerResult": 5,
            "dynamicCommandQueueDrain": False,
            "lcdCommandQueueCooldownSequences": 1,
        },
    }
    transfers = [
        {
            "kind": "transfer_item",
            "source_entity_id": index,
            "source_inventory_index": 0,
            "destination_entity_id": 100 + index,
            "destination_inventory_index": 0,
            "item_type_id": "MyObjectBuilder_Ingot",
            "item_subtype_id": "Magnesium",
            "reason": "refinery_output_cleanup",
            "amount": 1,
        }
        for index in range(7)
    ]
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 8,
        "commands": [
            *transfers,
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "19:47:46: Moved item"},
        ],
    }

    result = apply_command_queue(tmp_path, request, output)
    kinds = [command["kind"] for command in result["commands"]]

    assert kinds.count("write_text_surface") == 1
    assert kinds.count("transfer_item") == 4


def test_worker_command_queue_ages_lcd_refreshes_to_prevent_starvation(tmp_path: Path):
    request = {
        "bridge_id": "bridge-queue",
        "sequence": 30,
        "script_id": "sample_status_adapter",
        "state": {},
        "worker_config": {
            "commandQueueDrainPerResult": 1,
            "lcdCommandQueueCooldownSequences": 0,
            "lcdCommandQueueMaxWaitSequences": 3,
        },
    }
    output = {
        "apply_mode": "immediate",
        "max_apply_commands": 1,
        "commands": [
            {
                "kind": "transfer_item",
                "source_entity_id": 1,
                "source_inventory_index": 0,
                "destination_entity_id": 2,
                "destination_inventory_index": 0,
                "item_type_id": "MyObjectBuilder_Ore",
                "item_subtype_id": "Iron",
                "reason": "refinery_ore_rebalance",
                "amount": 10,
            },
            {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "append": False, "text": "refresh"},
        ],
    }

    first = apply_command_queue(tmp_path, request, output)
    assert first["commands"][0]["kind"] == "transfer_item"

    emitted = []
    for offset in range(1, 5):
        request["sequence"] = 30 + offset
        request["state"] = {"last_apply": {"sequence": 29 + offset, "status": "processed", "applied": 1, "skipped": 0}}
        result = apply_command_queue(tmp_path, request, output)
        emitted.append(result["commands"][0]["kind"])

    assert "write_text_surface" in emitted


def test_worker_command_queue_prioritizes_critical_transfers_before_bulk_ice():
    uranium = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Uranium"}
    magnesium = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Magnesium"}
    gas_ice = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Ice", "reason": "gas_generator_topup"}
    refinery_ore = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Silver", "reason": "refinery_ore_input"}
    ice = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Ice"}

    assert command_priority(uranium) == command_priority(gas_ice)
    assert command_priority(gas_ice) == command_priority(refinery_ore)
    assert command_priority(refinery_ore) < command_priority(magnesium) < command_priority(ice)


def test_worker_command_queue_prioritizes_autocrafting_goal_before_reactive_transfers():
    assembler_mode = {"kind": "set_assembler_mode", "block_entity_id": 7, "mode": "assembly"}
    refinery_output = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Cobalt", "reason": "refinery_output_cleanup"}
    material = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Nickel", "reason": "autocrafting_material"}
    autocrafting_lcd = {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0, "title": "Craft item manually once to show up here"}
    output_cleanup = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Component", "item_subtype_id": "Display", "reason": "assembler_output_cleanup"}
    enqueue = {"kind": "enqueue_assembler_blueprint", "blueprint_id": "MyObjectBuilder_BlueprintDefinition/MetalGrid", "reason": "autocrafting_goal"}
    inventory_sorting = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Cobalt", "reason": "inventory_sorting"}
    lcd = {"kind": "write_text_surface", "block_entity_id": 9, "surface_index": 0}
    refinery_ore = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Nickel", "reason": "refinery_ore_input"}
    refinery_unload = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Iron", "reason": "refinery_input_unload"}
    refinery_rebalance = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Iron", "reason": "refinery_ore_rebalance"}
    shortage_ore = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ore", "item_subtype_id": "Nickel", "reason": "autocrafting_ore_refining"}
    queue_consolidation = {"kind": "move_assembler_queue_item", "block_entity_id": 7, "queue_item_id": 12, "target_index": 1, "reason": "assembler_queue_consolidation"}
    input_cleanup = {"kind": "transfer_item", "item_type_id": "MyObjectBuilder_Ingot", "item_subtype_id": "Nickel", "reason": "assembler_input_cleanup"}

    assert command_priority(assembler_mode) < command_priority(refinery_rebalance) < command_priority(enqueue)
    assert command_priority(enqueue) < command_priority(material) < command_priority(input_cleanup) < command_priority(queue_consolidation)
    assert command_priority(queue_consolidation) < command_priority(shortage_ore) < command_priority(refinery_output)
    assert command_priority(refinery_output) < command_priority(output_cleanup) < command_priority(refinery_unload)
    assert command_priority(refinery_unload) < command_priority(inventory_sorting) < command_priority(refinery_ore)
    assert command_priority(refinery_ore) < command_priority(lcd)
    assert command_priority(lcd) == command_priority(autocrafting_lcd)
