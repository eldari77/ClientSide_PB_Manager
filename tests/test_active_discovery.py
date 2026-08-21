import json
from pathlib import Path

from discovery.active_discovery import DISCOVERY_SCHEMA, generate_discovery_report, write_discovery_report


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_active_discovery_report_flags_bridge_workshop_and_repair_actions(tmp_path: Path):
    root = tmp_path
    write_json(root / "data" / "plugin_status.json", {"marked_mailboxes": 0, "status": "ready"})
    write_json(
        root / "data" / "bridge_health.json",
        {
            "bridges": {
                "codex-guided-smoke-123": {
                    "status": "active",
                    "last_result_sequence": 1,
                    "last_request_sequence": 1,
                },
                "pb-bridge-001": {
                    "status": "concealed_suspected",
                    "last_result_sequence": 10,
                    "last_request_sequence": 11,
                }
            }
        },
    )
    write_json(
        root / "data" / "bridge_scripts.json",
        {
            "bridges": {
                "pb-bridge-001": {
                    "selected_script_id": "bridge_orchestrator",
                    "allowed_worker_scripts": ["bridge_orchestrator", "workshop_1216126863_adapter"],
                }
            }
        },
    )
    write_json(
        root / "data" / "workshop_catalog.json",
        {
            "records": [
                {
                    "workshop_id": "1216126863",
                    "workshop_title": "Isy's Inventory Manager",
                    "detected_kind": "pb_script",
                    "compatibility": "profile_adapter_ready",
                },
                {
                    "workshop_id": "2831096030",
                    "workshop_title": "Vector Thrust OS",
                    "detected_kind": "pb_script",
                    "compatibility": "virtual_pb_blocked",
                },
            ]
        },
    )

    report = generate_discovery_report(root)

    assert report["schema"] == DISCOVERY_SCHEMA
    assert report["plugin"]["status"] == "ready"
    assert report["plugin"]["marked_mailboxes"] == 0
    assert [bridge["bridge_id"] for bridge in report["bridges"]] == ["pb-bridge-001"]
    assert report["bridges"][0]["operator_status"] == "stale_mailbox"
    assert "copy_pb_custom_data" in report["repair_actions"]
    assert "run_pb_heartbeat" in report["repair_actions"]
    statuses = {item["workshop_id"]: item["operator_status"] for item in report["workshop_scripts"]}
    assert statuses["1216126863"] == "ready_profile"
    assert statuses["2831096030"] == "blocked_needs_command_mapping"


def test_active_discovery_includes_api_probe_alignment_status(tmp_path: Path):
    root = tmp_path
    write_json(
        root / "data" / "se_api_surface.json",
        {
            "schema": "novali.client_side_pb.se_api_surface.v1",
            "api_hash": "api-a",
            "generated_at": "2026-08-20T00:00:00+00:00",
            "interfaces": {"IMyTextSurface": {"properties": {}, "methods": {}}},
            "enums": {},
        },
    )
    write_json(
        root / "data" / "harness_alignment.json",
        {
            "schema": "novali.client_side_pb.harness_alignment.v1",
            "api_hash": "api-a",
            "operator_status": "needs_mapping_review",
            "summary": {
                "supported": 10,
                "missing_read_stub": 2,
                "mutation_requires_command_mapping": 3,
                "blocked_for_safety": 1,
                "partial_traversal": 4,
            },
        },
    )
    write_json(root / "data" / "virtual_pb_capabilities.json", {"capability_version": "2026-test"})
    write_json(
        root / "data" / "harness_update_plan.json",
        {
            "schema": "novali.client_side_pb.harness_update_plan.v1",
            "operator_status": "read_only_stubs_ready",
            "next_recommended_action": "add_read_only_stubs",
            "summary": {
                "read_only_stub_queue": 2,
                "mapping_review_queue": 3,
                "blocked_for_safety_queue": 1,
            },
            "read_only_stub_queue": [
                {"member": "IMyDoor.OpenRatio", "reason": "read-only snapshot and harness getter"},
            ],
            "mapping_review_queue": [
                {"member": "IMyDoor.Open", "reason": "mutating endpoint needs reviewed bridge command"},
            ],
        },
    )

    report = generate_discovery_report(root)

    assert report["api_probe"]["status"] == "needs_mapping_review"
    assert report["api_probe"]["surface_status"] == "seen"
    assert report["api_probe"]["alignment_status"] == "seen"
    assert report["api_probe"]["stale"] is False
    assert report["api_probe"]["summary"]["missing_read_stub"] == 2
    assert report["harness_update_plan"]["status"] == "read_only_stubs_ready"
    assert report["harness_update_plan"]["top_read_only_stubs"] == ["IMyDoor.OpenRatio"]
    assert report["harness_update_plan"]["top_mapping_reviews"] == ["IMyDoor.Open"]
    assert "prioritize_read_only_stubs" in report["repair_actions"]
    assert "review_api_mappings" in report["repair_actions"]


def test_active_discovery_flags_stale_or_missing_api_probe(tmp_path: Path):
    root = tmp_path
    write_json(root / "data" / "se_api_surface.json", {"schema": "novali.client_side_pb.se_api_surface.v1", "api_hash": "api-a"})
    write_json(root / "data" / "harness_alignment.json", {"schema": "novali.client_side_pb.harness_alignment.v1", "api_hash": "api-b"})

    report = generate_discovery_report(root)

    assert report["api_probe"]["stale"] is True
    assert report["api_probe"]["status"] == "stale_probe"
    assert "run_api_probe" in report["repair_actions"]


def test_active_discovery_can_refresh_api_probe_report(tmp_path: Path):
    root = tmp_path
    source = root / "fixture.cs"
    source.write_text(
        """
public interface IMyTextSurface
{
    VRageMath.Vector2 SurfaceSize { get; }
    void WriteText(string value, bool append = false);
}
""",
        encoding="utf-8",
    )
    write_json(
        root / "data" / "virtual_pb_capabilities.json",
        {
            "schema": "novali.client_side_pb.virtual_pb_capabilities.v1",
            "implemented_interfaces": ["IMyTextSurface"],
            "snapshot_fields": ["grid_snapshot.blocks[].surface_size"],
            "available_command_kinds": ["write_text_surface"],
            "partial_traversal_features": [],
            "blocked_command_properties": [],
            "mapped_command_properties": [],
        },
    )

    report = generate_discovery_report(root, run_api_probe=True, api_source_path=source)

    assert (root / "data" / "se_api_surface.json").exists()
    assert (root / "data" / "harness_alignment.json").exists()
    assert (root / "data" / "harness_update_plan.json").exists()
    assert report["api_probe"]["status"] == "aligned"


def test_active_discovery_finds_standard_space_engineers_save_hints(tmp_path: Path):
    root = tmp_path / "project"
    save_root = tmp_path / "SpaceEngineers" / "Saves" / "7656119" / "DemoWorld"
    save_root.mkdir(parents=True)
    (save_root / "Sandbox_config.sbc").write_text("<MyObjectBuilder_SessionSettings />", encoding="utf-8")

    report = generate_discovery_report(root, standard_save_roots=[tmp_path / "SpaceEngineers" / "Saves"])

    assert report["space_engineers"]["active_save_status"] == "found"
    assert report["space_engineers"]["active_save_hints"][0]["config_path"].endswith("Sandbox_config.sbc")


def test_active_discovery_reads_plugin_state_field_as_status(tmp_path: Path):
    root = tmp_path
    write_json(root / "data" / "plugin_status.json", {"state": "ok", "marked_mailboxes": 1})

    report = generate_discovery_report(root)

    assert report["plugin"]["status"] == "ok"


def test_write_discovery_report_persists_schema(tmp_path: Path):
    output = tmp_path / "data" / "discovery_report.json"

    report = write_discovery_report(tmp_path, output)

    assert output.exists()
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema"] == DISCOVERY_SCHEMA
    assert saved == report
