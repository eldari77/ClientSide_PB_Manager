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
    assert result["sos_dashboard"]["redundancy"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["guidance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["diagnostics"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["watch_log"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mission_profile"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["endurance"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["runbook"]["snapshot_status"] == "missing_child_result"
    assert result["commands"] == [
        {
            "kind": "echo",
            "text": "SOS Dashboard Ship A mode=Docked guidance=unknown readiness=unknown capabilities=unknown redundancy=unknown diagnostics=unknown watch_log=unknown mission_profile=unknown endurance=unknown runbook=unknown integrity=unknown logistics=unknown maintenance=unknown airlock=unknown mobility=unknown navigation=unknown power=unknown comms=unknown crew=unknown docking=unknown life_support=unknown environment=unknown display=unknown mining=unknown production=unknown transit=unknown defense=unknown alerts=unknown queue=none blockers=none",
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
