import json
from pathlib import Path

import sos as sos_package

import worker.sos as worker_sos
from worker.sos import (
    SOS_SHIPS_SCHEMA,
    expand_sos_bridge_configs,
    load_sos_registry,
    sos_context_for_request,
    validate_sos_registry,
)
from worker.worker import BridgeScriptConfig


def write_sos_ships(root: Path, ships: list[dict]) -> None:
    data = root / "data"
    data.mkdir()
    (data / "sos_ships.json").write_text(
        json.dumps({"schema": SOS_SHIPS_SCHEMA, "ships": ships}),
        encoding="utf-8",
    )


def test_load_sos_registry_accepts_ship_modes_and_services(tmp_path: Path):
    write_sos_ships(
        tmp_path,
        [
            {
                "ship_id": "mcrn-tachi",
                "bridge_id": "pb-bridge-001",
                "display_name": "Tachi",
                "expected_grid_entity_id": 4242,
                "mode": "Combat",
                "pb_limit_profile": "default",
                "services": [
                    {"script_id": "pb-bridge-001-sos_status", "service_id": "status"},
                    {"script_id": "pb-bridge-001-workshop_1216126863_adapter", "service_id": "inventory"},
                ],
                "status_surfaces": [{"block_entity_id": 9001, "surface_index": 0}],
            }
        ],
    )

    registry = load_sos_registry(tmp_path)

    assert registry.schema == SOS_SHIPS_SCHEMA
    assert registry.ships[0].ship_id == "mcrn-tachi"
    assert registry.ships[0].mode == "Combat"
    assert registry.ships[0].services[0]["script_id"] == "pb-bridge-001-sos_status"
    assert registry.ships[0].status_surfaces[0]["block_entity_id"] == 9001


def test_validate_sos_registry_rejects_duplicate_bridge_and_grid_claims(tmp_path: Path):
    write_sos_ships(
        tmp_path,
        [
            {"ship_id": "ship-a", "bridge_id": "pb-bridge-001", "expected_grid_entity_id": 10, "services": []},
            {"ship_id": "ship-b", "bridge_id": "pb-bridge-001", "expected_grid_entity_id": 11, "services": []},
            {"ship_id": "ship-c", "bridge_id": "pb-bridge-003", "expected_grid_entity_id": 10, "services": []},
        ],
    )

    errors = validate_sos_registry(load_sos_registry(tmp_path))

    assert "duplicate_bridge_id:pb-bridge-001" in errors
    assert "duplicate_expected_grid_entity_id:10" in errors


def test_expand_sos_bridge_configs_applies_mode_policy_and_services(tmp_path: Path):
    write_sos_ships(
        tmp_path,
        [
            {
                "ship_id": "ship-a",
                "bridge_id": "pb-bridge-001",
                "display_name": "Ship A",
                "mode": "Docked",
                "services": [
                    {"script_id": "pb-bridge-001-sos_status", "service_id": "status"},
                    {"script_id": "pb-bridge-001-sos_dashboard", "service_id": "dashboard"},
                    {"script_id": "pb-bridge-001-sos_integrity", "service_id": "integrity"},
                    {"script_id": "pb-bridge-001-sos_logistics", "service_id": "logistics"},
                    {"script_id": "pb-bridge-001-sos_airlock", "service_id": "airlock"},
                    {"script_id": "pb-bridge-001-sos_mobility", "service_id": "mobility"},
                    {"script_id": "pb-bridge-001-sos_power", "service_id": "power"},
                    {"script_id": "pb-bridge-001-sos_comms", "service_id": "comms"},
                    {"script_id": "pb-bridge-001-sos_crew", "service_id": "crew"},
                    {"script_id": "pb-bridge-001-sos_docking", "service_id": "docking"},
                    {"script_id": "pb-bridge-001-sos_life_support", "service_id": "life_support"},
                    {"script_id": "pb-bridge-001-sos_production", "service_id": "production"},
                    {"script_id": "pb-bridge-001-workshop_1216126863_adapter", "service_id": "inventory"},
                    {"script_id": "pb-bridge-001-virtual_whip_auto_door", "service_id": "doors"},
                ],
            }
        ],
    )
    existing = {
        "unrelated": BridgeScriptConfig("sample_status_adapter", ("sample_status_adapter",), ()),
    }

    expanded = expand_sos_bridge_configs(tmp_path, existing)

    assert expanded["unrelated"].selected_script_id == "sample_status_adapter"
    config = expanded["pb-bridge-001"]
    assert config.selected_script_id == "pb-bridge-001-orchestrator"
    assert config.allowed_worker_scripts == (
        "pb-bridge-001-orchestrator",
        "pb-bridge-001-sos_status",
        "pb-bridge-001-sos_dashboard",
        "pb-bridge-001-sos_integrity",
        "pb-bridge-001-sos_logistics",
        "pb-bridge-001-sos_airlock",
        "pb-bridge-001-sos_mobility",
        "pb-bridge-001-sos_power",
        "pb-bridge-001-sos_comms",
        "pb-bridge-001-sos_crew",
        "pb-bridge-001-sos_docking",
        "pb-bridge-001-sos_life_support",
        "pb-bridge-001-sos_production",
        "pb-bridge-001-workshop_1216126863_adapter",
        "pb-bridge-001-virtual_whip_auto_door",
    )
    assert [child["script_id"] for child in config.child_worker_scripts] == [
        "pb-bridge-001-sos_status",
        "pb-bridge-001-sos_dashboard",
        "pb-bridge-001-sos_integrity",
        "pb-bridge-001-sos_logistics",
        "pb-bridge-001-sos_airlock",
        "pb-bridge-001-sos_mobility",
        "pb-bridge-001-sos_power",
        "pb-bridge-001-sos_comms",
        "pb-bridge-001-sos_crew",
        "pb-bridge-001-sos_docking",
        "pb-bridge-001-sos_life_support",
        "pb-bridge-001-sos_production",
        "pb-bridge-001-workshop_1216126863_adapter",
        "pb-bridge-001-virtual_whip_auto_door",
    ]
    assert config.child_worker_scripts[0]["role"] == "status"
    assert config.child_worker_scripts[0]["priority"] == 5
    assert config.child_worker_scripts[1]["service_id"] == "dashboard"
    assert config.child_worker_scripts[1]["priority"] == 4
    assert config.child_worker_scripts[2]["service_id"] == "integrity"
    assert config.child_worker_scripts[2]["budget"] == 1
    assert config.child_worker_scripts[3]["service_id"] == "logistics"
    assert config.child_worker_scripts[3]["budget"] == 1
    assert config.child_worker_scripts[4]["service_id"] == "airlock"
    assert config.child_worker_scripts[4]["budget"] == 1
    assert config.child_worker_scripts[5]["service_id"] == "mobility"
    assert config.child_worker_scripts[5]["budget"] == 1
    assert config.child_worker_scripts[6]["service_id"] == "power"
    assert config.child_worker_scripts[6]["budget"] == 1
    assert config.child_worker_scripts[7]["service_id"] == "comms"
    assert config.child_worker_scripts[7]["budget"] == 1
    assert config.child_worker_scripts[7]["priority"] == 16
    assert config.child_worker_scripts[8]["service_id"] == "crew"
    assert config.child_worker_scripts[8]["budget"] == 1
    assert config.child_worker_scripts[8]["priority"] == 14
    assert config.child_worker_scripts[9]["service_id"] == "docking"
    assert config.child_worker_scripts[9]["budget"] == 1
    assert config.child_worker_scripts[9]["priority"] == 11
    assert config.child_worker_scripts[10]["service_id"] == "life_support"
    assert config.child_worker_scripts[10]["budget"] == 1
    assert config.child_worker_scripts[10]["priority"] == 14
    assert config.child_worker_scripts[11]["service_id"] == "production"
    assert config.child_worker_scripts[11]["budget"] == 1
    assert config.child_worker_scripts[11]["priority"] == 17
    assert config.child_worker_scripts[12]["budget"] == 0
    assert config.child_worker_scripts[13]["expires_after_sequences"] == 1
    assert config.child_worker_scripts[1]["budget"] == 1


def test_sos_context_for_request_validates_expected_grid_identity(tmp_path: Path):
    write_sos_ships(
        tmp_path,
        [
            {
                "ship_id": "ship-a",
                "bridge_id": "pb-bridge-001",
                "expected_grid_entity_id": 777,
                "mode": "Cruise",
                "services": [],
            }
        ],
    )

    context = sos_context_for_request(
        tmp_path,
        {
            "bridge_id": "pb-bridge-001",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 777, "blocks": []},
        },
    )

    assert context["ship"]["ship_id"] == "ship-a"
    assert context["identity_status"] == "ok"
    assert context["ship"]["mode"] == "Cruise"
    assert context["ship"]["services"] == []
    assert context["ship"]["status_surfaces"] == []

    mismatch = sos_context_for_request(
        tmp_path,
        {
            "bridge_id": "pb-bridge-001",
            "grid_snapshot": {"schema": "novali.client_side_pb.grid_snapshot.v1", "grid_entity_id": 778, "blocks": []},
        },
    )

    assert mismatch["identity_status"] == "grid_mismatch"
    assert mismatch["blockers"] == ["expected_grid_entity_id_mismatch"]


def test_worker_sos_adapter_delegates_expansion_to_editable_sos_package(monkeypatch, tmp_path: Path):
    calls: list[tuple[Path, dict, object]] = []

    def fake_expand(root, bridge_configs, bridge_config_factory=None):
        calls.append((root, bridge_configs, bridge_config_factory))
        assert bridge_config_factory is BridgeScriptConfig
        return {
            "bridge-a": bridge_config_factory(
                "bridge-a-orchestrator",
                ("bridge-a-orchestrator", "bridge-a-sos_status"),
                ({"script_id": "bridge-a-sos_status"},),
            )
        }

    monkeypatch.setattr(sos_package, "expand_sos_bridge_configs", fake_expand)

    expanded = worker_sos.expand_sos_bridge_configs(
        tmp_path,
        {},
        bridge_config_factory=BridgeScriptConfig,
    )

    assert calls == [(tmp_path, {}, BridgeScriptConfig)]
    assert expanded["bridge-a"].selected_script_id == "bridge-a-orchestrator"
    assert expanded["bridge-a"].allowed_worker_scripts == ("bridge-a-orchestrator", "bridge-a-sos_status")


def test_worker_sos_adapter_delegates_context_attachment_to_editable_sos_package(monkeypatch, tmp_path: Path):
    request = {"bridge_id": "bridge-a"}

    def fake_attach(root, request_payload):
        assert root == tmp_path
        assert request_payload is request
        request_payload["sos_ship"] = {"ship_id": "from-package", "blockers": []}
        return {"ship": {"ship_id": "from-package"}, "blockers": []}

    monkeypatch.setattr(sos_package, "attach_sos_request_context", fake_attach)

    context = worker_sos.attach_sos_request_context(tmp_path, request)

    assert context["ship"]["ship_id"] == "from-package"
    assert request["sos_ship"]["ship_id"] == "from-package"
