from worker.scripts.sos_life_support import run


def test_sos_life_support_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.life_support as life_support_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(life_support_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_life_support_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_life_support"]["snapshot_status"] == "no_snapshot"
    assert result["sos_life_support"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Life Support Ship A state=unknown snapshot=no_snapshot"}]


def test_sos_life_support_adapter_emits_only_allowed_status_commands():
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
                    {"name": "Med Bay", "type": "MedicalRoom", "functional": True},
                    {"name": "Survival Kit", "type": "SurvivalKit", "functional": True},
                    {"name": "Oxygen Tank", "type": "OxygenTank", "functional": True, "fill_ratio": 0.8},
                    {"name": "Hydrogen Tank", "type": "HydrogenTank", "functional": True, "fill_ratio": 0.8},
                    {"name": "O2/H2 Generator", "type": "O2H2Generator", "functional": True},
                ]
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
