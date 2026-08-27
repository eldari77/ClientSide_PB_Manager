from worker.scripts.sos_environment import run


def test_sos_environment_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.environment as environment_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(environment_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_environment_adapter_degrades_to_no_snapshot_with_echo():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
        }
    )

    assert result["sos_environment"]["snapshot_status"] == "no_snapshot"
    assert result["sos_environment"]["state"] == "unknown"
    assert result["commands"] == [{"kind": "echo", "text": "SOS Environment Ship A state=unknown snapshot=no_snapshot"}]


def test_sos_environment_adapter_emits_only_allowed_status_commands():
    result = run(
        {
            "bridge_id": "bridge-a",
            "sos_ship": {
                "ship_id": "ship-a",
                "display_name": "Ship A",
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            },
            "grid_snapshot": {
                "weather": {"state": "clear"},
                "hazards": [{"name": "meteor shower", "severity": "warning"}],
                "blocks": [
                    {
                        "name": "Air Vent",
                        "type": "AirVent",
                        "functional": True,
                        "enabled": True,
                        "oxygen_level": 0.9,
                        "pressure_ratio": 1.0,
                    }
                ],
            },
        }
    )

    assert {command["kind"] for command in result["commands"]} <= {"echo", "write_text_surface"}
    assert result["commands"][0]["kind"] == "write_text_surface"
