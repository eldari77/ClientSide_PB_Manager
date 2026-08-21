import json
from pathlib import Path

from discovery.api_probe import (
    API_SURFACE_SCHEMA,
    HARNESS_ALIGNMENT_SCHEMA,
    HARNESS_UPDATE_PLAN_SCHEMA,
    align_api_surface_with_harness,
    build_harness_update_plan,
    probe_api_surface_from_source,
    write_api_probe_reports,
)


SOURCE_FIXTURE = """
namespace Sandbox.ModAPI.Ingame
{
    public interface IMyTextSurface
    {
        string Font { get; set; }
        float FontSize { get; set; }
        VRageMath.Vector2 SurfaceSize { get; }
        void WriteText(string value, bool append = false);
        MySpriteDrawFrame DrawFrame();
    }

    public interface IMyAssembler
    {
        int QueueCount { get; }
        void AddQueueItem(MyDefinitionId blueprint, VRage.MyFixedPoint amount);
    }

    public enum ContentType { NONE, TEXT_AND_IMAGE, SCRIPT }
}
"""


def test_probe_api_surface_from_csharp_source_lists_interfaces_members_and_enums():
    report = probe_api_surface_from_source(SOURCE_FIXTURE, source_name="fixture.cs", assembly_version="1.2.3")

    assert report["schema"] == API_SURFACE_SCHEMA
    assert report["source"] == "fixture.cs"
    assert report["assembly_version"] == "1.2.3"
    assert report["api_hash"]
    assert report["interfaces"]["IMyTextSurface"]["properties"]["Font"]["can_write"] is True
    assert report["interfaces"]["IMyTextSurface"]["properties"]["SurfaceSize"]["can_write"] is False
    assert report["interfaces"]["IMyTextSurface"]["methods"]["WriteText"]["return_type"] == "void"
    assert report["interfaces"]["IMyAssembler"]["methods"]["AddQueueItem"]["parameters"][0]["name"] == "blueprint"
    assert report["enums"]["ContentType"] == ["NONE", "TEXT_AND_IMAGE", "SCRIPT"]


def test_align_api_surface_classifies_supported_missing_mutating_and_partial_features():
    api_surface = probe_api_surface_from_source(SOURCE_FIXTURE, source_name="fixture.cs")
    harness = {
        "schema": "novali.client_side_pb.virtual_pb_capabilities.v1",
        "implemented_interfaces": ["IMyTextSurface", "IMyAssembler"],
        "snapshot_fields": ["grid_snapshot.blocks[].surface_size"],
        "mapped_command_properties": [],
        "blocked_command_properties": ["IMyAssembler.AddQueueItem"],
        "available_command_kinds": ["write_text_surface"],
        "partial_traversal_features": ["text_surface_sprites"],
    }

    alignment = align_api_surface_with_harness(api_surface, harness)

    assert alignment["schema"] == HARNESS_ALIGNMENT_SCHEMA
    assert alignment["summary"]["supported"] >= 2
    assert "IMyTextSurface.SurfaceSize" in alignment["supported"]
    assert "IMyTextSurface.Font" in alignment["mutation_requires_command_mapping"]
    assert "IMyAssembler.AddQueueItem" in alignment["blocked_for_safety"]
    assert "IMyTextSurface.DrawFrame" in alignment["partial_traversal"]
    assert alignment["operator_status"] == "needs_mapping_review"


def test_align_api_surface_honors_explicit_read_supported_members():
    source = """
namespace Sandbox.ModAPI.Ingame
{
    public interface IMyTerminalBlock
    {
        string CustomNameWithFaction { get; }
        bool HasLocalPlayerAccess();
        bool HasPlayerAccess(long playerId);
        void GetActions(System.Collections.Generic.List<ITerminalAction> result, System.Func<ITerminalAction, bool> collect = null);
    }
    public interface ITerminalAction { string Id { get; } }
}
"""
    api_surface = probe_api_surface_from_source(source, source_name="terminal_fixture.cs")
    harness = {
        "schema": "novali.client_side_pb.virtual_pb_capabilities.v1",
        "implemented_interfaces": ["IMyTerminalBlock", "ITerminalAction"],
        "snapshot_fields": ["grid_snapshot.blocks[].custom_name_with_faction"],
        "read_supported_members": [
            "IMyTerminalBlock.GetActions",
            "IMyTerminalBlock.HasLocalPlayerAccess",
            "IMyTerminalBlock.HasPlayerAccess",
        ],
        "mapped_command_properties": [],
        "blocked_command_properties": [],
        "available_command_kinds": [],
        "partial_traversal_features": [],
    }

    alignment = align_api_surface_with_harness(api_surface, harness)

    assert "IMyTerminalBlock.CustomNameWithFaction" in alignment["supported"]
    assert "IMyTerminalBlock.GetActions" in alignment["supported"]
    assert "IMyTerminalBlock.HasLocalPlayerAccess" in alignment["supported"]
    assert "IMyTerminalBlock.HasPlayerAccess" in alignment["supported"]
    assert "IMyTerminalBlock.GetActions" not in alignment["missing_read_stub"]
    assert "IMyTerminalBlock.HasPlayerAccess" not in alignment["missing_read_stub"]


def test_write_api_probe_reports_persists_surface_and_alignment(tmp_path: Path):
    source = tmp_path / "fixture.cs"
    surface_output = tmp_path / "data" / "se_api_surface.json"
    alignment_output = tmp_path / "data" / "harness_alignment.json"
    source.write_text(SOURCE_FIXTURE, encoding="utf-8")
    harness = {
        "implemented_interfaces": ["IMyTextSurface"],
        "snapshot_fields": ["grid_snapshot.blocks[].surface_size"],
        "available_command_kinds": ["write_text_surface"],
        "partial_traversal_features": ["text_surface_sprites"],
        "blocked_command_properties": [],
        "mapped_command_properties": [],
    }

    write_api_probe_reports(
        root=tmp_path,
        source_path=source,
        surface_output=surface_output,
        alignment_output=alignment_output,
        harness_capabilities=harness,
    )

    assert json.loads(surface_output.read_text(encoding="utf-8"))["schema"] == API_SURFACE_SCHEMA
    assert json.loads(alignment_output.read_text(encoding="utf-8"))["schema"] == HARNESS_ALIGNMENT_SCHEMA


def test_harness_update_plan_prioritizes_read_only_stubs_before_mutation_mappings():
    source = """
namespace Sandbox.ModAPI.Ingame
{
    public interface IMyDoor
    {
        float OpenRatio { get; }
        bool Open { get; set; }
        void OpenDoor();
    }

    public interface IMyThrust
    {
        float CurrentThrust { get; }
        float ThrustOverride { get; set; }
    }

    public interface IMySensorBlock
    {
        bool IsActive { get; }
    }

    public interface IMyCameraBlock
    {
        bool CanScan(double distance);
    }

    public interface IMyTerminalBlock
    {
        string CustomData { get; set; }
        bool HasPlayerAccess(long playerId);
    }
}
"""
    api_surface = probe_api_surface_from_source(source, source_name="fixture.cs")
    harness = {
        "implemented_interfaces": ["IMyDoor", "IMyThrust", "IMySensorBlock", "IMyCameraBlock", "IMyTerminalBlock"],
        "snapshot_fields": [],
        "available_command_kinds": ["set_door_open"],
        "client_overlay_properties": ["IMyTerminalBlock.CustomData"],
        "mapped_command_properties": [],
        "blocked_command_properties": ["ThrustOverride"],
        "partial_traversal_features": [],
    }
    alignment = align_api_surface_with_harness(api_surface, harness)

    plan = build_harness_update_plan(api_surface, alignment, max_items=10)

    assert plan["schema"] == HARNESS_UPDATE_PLAN_SCHEMA
    assert plan["operator_status"] == "read_only_stubs_ready"
    assert plan["next_recommended_action"] == "add_read_only_stubs"
    read_only_members = [item["member"] for item in plan["read_only_stub_queue"]]
    assert read_only_members.index("IMyTerminalBlock.HasPlayerAccess") < read_only_members.index("IMyThrust.CurrentThrust")
    assert read_only_members.index("IMyDoor.OpenRatio") < read_only_members.index("IMyThrust.CurrentThrust")
    door_item = next(item for item in plan["read_only_stub_queue"] if item["member"] == "IMyDoor.OpenRatio")
    assert door_item["snapshot_field"] == "grid_snapshot.blocks[].door_open_ratio"
    assert "IMyCameraBlock.CanScan" in read_only_members
    assert "IMyTerminalBlock.HasPlayerAccess" in read_only_members
    assert "IMyTerminalBlock.CustomData" not in [item["member"] for item in plan["mapping_review_queue"]]
    assert plan["mapping_review_queue"][0]["member"] == "IMyDoor.Open"
    assert plan["mapping_review_queue"][0]["review_required"] is True
    assert plan["blocked_for_safety_queue"][0]["member"] == "IMyThrust.ThrustOverride"


def test_write_api_probe_reports_persists_harness_update_plan(tmp_path: Path):
    source = tmp_path / "fixture.cs"
    surface_output = tmp_path / "data" / "se_api_surface.json"
    alignment_output = tmp_path / "data" / "harness_alignment.json"
    plan_output = tmp_path / "data" / "harness_update_plan.json"
    source.write_text(SOURCE_FIXTURE, encoding="utf-8")

    write_api_probe_reports(
        root=tmp_path,
        source_path=source,
        surface_output=surface_output,
        alignment_output=alignment_output,
        plan_output=plan_output,
        harness_capabilities={
            "implemented_interfaces": ["IMyTextSurface"],
            "snapshot_fields": [],
            "available_command_kinds": [],
            "partial_traversal_features": [],
            "blocked_command_properties": [],
            "mapped_command_properties": [],
        },
    )

    assert json.loads(plan_output.read_text(encoding="utf-8"))["schema"] == HARNESS_UPDATE_PLAN_SCHEMA
