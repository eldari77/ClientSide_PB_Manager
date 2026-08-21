from workshop.profile_pack import (
    PROFILE_PACK_SCHEMA,
    builtin_profile_pack,
    operator_status_for_compatibility,
    profile_for_workshop,
)


def test_builtin_profile_pack_declares_safe_initial_scripts():
    pack = builtin_profile_pack()

    assert pack["schema"] == PROFILE_PACK_SCHEMA
    profiles = pack["profiles"]
    assert profiles["1216126863"]["script_id"] == "workshop_1216126863_adapter"
    assert profiles["1216126863"]["operator_status"] == "ready_profile"
    assert profiles["416932930"]["script_id"] == "virtual_whip_auto_door"
    assert profiles["416932930"]["operator_status"] == "ready_virtual_pb"
    assert profiles["822950976"]["script_id"] == "virtual_workshop_822950976"
    assert profiles["822950976"]["operator_status"] == "ready_virtual_pb"
    assert profiles["2831096030"]["operator_status"] == "blocked_needs_command_mapping"


def test_profile_lookup_supports_known_titles_and_blocked_vector_thrust():
    assert profile_for_workshop("1216126863", "Isy's Inventory Manager")["safe_default_enabled"] is True
    assert profile_for_workshop("416932930", "Whip's Auto Door and Airlock Script")["role"] == "reactive"
    assert profile_for_workshop("822950976", "Automatic LCDs 2")["role"] == "display"
    assert profile_for_workshop("2831096030", "Vector Thrust OS")["safe_default_enabled"] is False
    assert profile_for_workshop("000", "unknown") is None


def test_operator_status_translates_adapter_and_virtual_pb_states():
    assert operator_status_for_compatibility("profile_adapter_ready") == "ready_profile"
    assert operator_status_for_compatibility("virtual_pb_ready") == "ready_virtual_pb"
    assert operator_status_for_compatibility("virtual_pb_blocked") == "blocked_needs_command_mapping"
    assert operator_status_for_compatibility("adapter_scaffold_created") == "manual_adapter_required"
    assert (
        operator_status_for_compatibility(
            "manual_adapter_required",
            compatibility={"missing_snapshot_fields": ["blocks[].inventory"]},
        )
        == "missing_snapshot_fields"
    )
