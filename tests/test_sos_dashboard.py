from worker.scripts.sos_dashboard import run


def test_sos_dashboard_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.dashboard as dashboard_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(dashboard_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_dashboard_adapter_degrades_to_missing_child_result_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_dashboard"]["integrity"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["logistics"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["conveyor"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["maintenance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mobility"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["navigation"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["power"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["comms"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["crew"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["docking"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["life_support"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["environment"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["display"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mining"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["transit"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["defense"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["alerts"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["readiness"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["capabilities"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["telemetry_quality"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["automation"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["automation_plan"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["redundancy"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["topology"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["config_drift"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["guidance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["diagnostics"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["watch_log"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mission_profile"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["endurance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["runbook"]["snapshot_status"] == "missing_child_result"
    assert result["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Dashboard Ship A mode=Docked guidance=unknown readiness=unknown capabilities=unknown telemetry_quality=unknown automation=unknown automation_plan=unknown redundancy=unknown topology=unknown diagnostics=unknown config_drift=unknown watch_log=unknown mission_profile=unknown endurance=unknown runbook=unknown integrity=unknown logistics=unknown conveyor=unknown maintenance=unknown airlock=unknown mobility=unknown navigation=unknown power=unknown comms=unknown crew=unknown docking=unknown life_support=unknown environment=unknown display=unknown mining=unknown production=unknown transit=unknown defense=unknown alerts=unknown queue=none blockers=none",
        }
    ]


def test_sos_dashboard_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"


def test_sos_dashboard_adapter_reads_automation_plan_history_from_all_telemetry_shapes():
    automation_plan = {
        "state": "blocked",
        "snapshot_status": "ok",
        "proposed_count": 1,
        "approval_required_count": 1,
        "blocked_count": 1,
        "expired_count": 0,
        "warnings": ["operator_approval_required"],
        "blockers": ["identity_mismatch"],
    }
    child = {
        "service_id": "automation_plan",
        "script_id": "pb-bridge-001-sos_automation_plan",
        "status": "ok",
        "error_bucket": "none",
        "summary": "automation plan blocked",
        "result": {"sos_automation_plan": automation_plan},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"automation_plan": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_automation_plan": child}},
    )

    for runtime_telemetry in telemetry_shapes:
        result = run(
            {
                "bridge_id": "pb-bridge-001",
                "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
                "runtime_telemetry": runtime_telemetry,
            }
        )

        assert result["sos_dashboard"]["automation_plan"]["state"] == "blocked"
        assert result["sos_dashboard"]["automation_plan"]["proposed_count"] == 1
        assert result["sos_dashboard"]["automation_plan"]["blockers"] == ["identity_mismatch"]
