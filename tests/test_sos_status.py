from worker.scripts.sos_status import run


def test_sos_status_adapter_delegates_to_editable_sos_package(monkeypatch):
    import sos.services.status as status_service

    def fake_run(request):
        assert request["bridge_id"] == "bridge-a"
        return {"summary": "from package", "commands": [{"kind": "echo", "text": "from package"}]}

    monkeypatch.setattr(status_service, "run", fake_run)

    result = run({"bridge_id": "bridge-a"})

    assert result["summary"] == "from package"
    assert result["commands"] == [{"kind": "echo", "text": "from package"}]


def test_sos_status_writes_configured_cockpit_surface():
    request = {
        "bridge_id": "pb-bridge-001",
        "sequence": 12,
        "runtime_telemetry": {"limiter_state": "ok", "last_runtime_ms": 0.04},
        "sos_ship": {
            "ship_id": "ship-a",
            "display_name": "Ship A",
            "mode": "Combat",
            "identity_status": "ok",
            "blockers": [],
            "warnings": [],
            "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
        },
    }

    result = run(request)

    assert result["summary"] == "SOS Ship A mode=Combat identity=ok"
    command = result["commands"][0]
    assert command["kind"] == "write_text_surface"
    assert command["block_entity_id"] == 9001
    assert command["surface_index"] == 0
    assert "SOS - Ship A" in command["text"]
    assert "Mode: Combat" in command["text"]
    assert "Limiter: ok" in command["text"]


def test_sos_status_emits_echo_when_no_surface_configured():
    result = run(
        {
            "bridge_id": "pb-bridge-002",
            "sequence": 1,
            "sos_ship": {
                "ship_id": "ship-b",
                "display_name": "Ship B",
                "mode": "Cruise",
                "identity_status": "grid_mismatch",
                "blockers": ["expected_grid_entity_id_mismatch"],
                "warnings": [],
                "status_surfaces": [],
            },
        }
    )

    assert result["commands"][0]["kind"] == "echo"
    assert "SOS Ship B mode=Cruise identity=grid_mismatch" in result["commands"][0]["text"]
