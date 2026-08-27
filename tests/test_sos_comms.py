from worker.scripts.sos_comms import run


def test_sos_comms_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.comms as comms_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(comms_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_comms_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_comms"]["snapshot_status"] == "no_snapshot"
    assert result["sos_comms"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Comms Ship A state=unknown snapshot=no_snapshot"}]


def test_sos_comms_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
            "grid_snapshot": {
                "blocks": [
                    {"name": "Main Antenna", "type": "RadioAntenna", "functional": True, "enabled": True},
                    {"name": "Main Sensor", "type": "Sensor", "functional": True, "enabled": True},
                ]
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
