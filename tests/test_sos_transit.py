from worker.scripts.sos_transit import run


def test_sos_transit_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.transit as transit_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(transit_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_transit_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_transit"]["snapshot_status"] == "no_snapshot"
    assert result["sos_transit"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Transit Ship A state=unknown snapshot=no_snapshot"}]


def test_sos_transit_adapter_emits_only_allowed_status_commands():
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
                    {"name": "Jump Drive", "type": "JumpDrive", "functional": True, "enabled": True, "ready": True, "charge_ratio": 1.0},
                    {"name": "Hydrogen Tank", "type": "HydrogenTank", "functional": True, "enabled": True, "fill_ratio": 0.75},
                    {"name": "Gyro", "type": "Gyro", "functional": True, "enabled": True},
                    {"name": "Large Thruster", "type": "HydrogenThruster", "functional": True, "enabled": True},
                ]
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
