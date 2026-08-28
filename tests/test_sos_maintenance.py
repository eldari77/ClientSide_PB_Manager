from worker.scripts.sos_maintenance import run


def test_sos_maintenance_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.maintenance as maintenance_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(maintenance_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_maintenance_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_maintenance"]["snapshot_status"] == "no_snapshot"
    assert result["sos_maintenance"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Maintenance Ship A state=unknown snapshot=no_snapshot"}]


def test_sos_maintenance_adapter_emits_only_allowed_status_commands():
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
                    {"name": "Projector", "type": "Projector", "functional": True, "enabled": True, "is_projecting": True},
                    {"name": "Welder", "type": "ShipWelder", "functional": True, "enabled": True},
                    {"name": "Grinder", "type": "ShipGrinder", "functional": True, "enabled": True},
                    {"name": "Damaged Armor", "type": "ArmorBlock", "functional": False, "integrity_ratio": 0.4},
                ]
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
