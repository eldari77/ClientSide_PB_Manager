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
    assert result["sos_dashboard"]["authority"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["operating_directive"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mode_ledger"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mode_transition_plan"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["mode_transition_apply"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["automation_plan"]["snapshot_status"] == "missing_child_result"
    assert result["sos_dashboard"]["automation_recovery"]["snapshot_status"] == "missing_child_result"
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
            "text": "SOS Dashboard Ship A mode=Docked guidance=unknown readiness=unknown capabilities=unknown telemetry_quality=unknown automation=unknown authority=unknown operating_directive=unknown mode_ledger=unknown mode_transition_plan=unknown mode_transition_review=unknown mode_transition_apply=unknown automation_plan=unknown automation_recovery=unknown redundancy=unknown topology=unknown diagnostics=unknown config_drift=unknown watch_log=unknown mission_profile=unknown endurance=unknown runbook=unknown integrity=unknown logistics=unknown conveyor=unknown maintenance=unknown airlock=unknown mobility=unknown navigation=unknown power=unknown comms=unknown crew=unknown docking=unknown life_support=unknown environment=unknown display=unknown mining=unknown production=unknown transit=unknown defense=unknown alerts=unknown queue=none blockers=none",
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


def test_sos_dashboard_adapter_reads_authority_history_from_all_telemetry_shapes():
    authority = {
        "state": "blocked",
        "policy_status": "blocked",
        "snapshot_status": "ok",
        "eligible_actions": [],
        "prohibited_actions": [],
        "blocked_actions": ["programmable_block_recovery"],
        "unknown_actions": [],
        "warnings": ["same_grid_identity_missing_or_mismatch"],
        "source_services": ["automation_plan", "grid_snapshot"],
    }
    child = {
        "service_id": "authority",
        "script_id": "pb-bridge-001-sos_authority",
        "status": "ok",
        "error_bucket": "none",
        "summary": "authority blocked",
        "result": {"sos_authority": authority},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"authority": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_authority": child}},
    )

    for runtime_telemetry in telemetry_shapes:
        result = run(
            {
                "bridge_id": "pb-bridge-001",
                "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
                "runtime_telemetry": runtime_telemetry,
            }
        )

        dashboard_authority = result["sos_dashboard"]["authority"]
        assert dashboard_authority["state"] == "blocked"
        assert dashboard_authority["policy_status"] == "blocked"
        assert dashboard_authority["blocked_actions"] == ["programmable_block_recovery"]
        assert dashboard_authority["warnings"] == ["same_grid_identity_missing_or_mismatch"]
        assert dashboard_authority["source_services"] == ["automation_plan", "grid_snapshot"]


def test_sos_dashboard_adapter_reads_operating_directive_history_from_all_telemetry_shapes():
    directive = {
        "state": "approval_required",
        "transition_status": "approval_required",
        "approval_status": "required",
        "current_mode": "Docked",
        "requested_mode": "Cruise",
        "snapshot_status": "ok",
        "warnings": ["operator_transition_approval_required"],
        "blocked_prerequisites": [],
        "unknown_prerequisites": [],
        "source_services": ["operator_mode_request", "sos_identity"],
    }
    child = {
        "service_id": "operating_directive",
        "script_id": "pb-bridge-001-sos_operating_directive",
        "status": "ok",
        "error_bucket": "none",
        "summary": "directive approval required",
        "result": {"sos_operating_directive": directive},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"operating_directive": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_operating_directive": child}},
    )

    for runtime_telemetry in telemetry_shapes:
        result = run(
            {
                "bridge_id": "pb-bridge-001",
                "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
                "runtime_telemetry": runtime_telemetry,
            }
        )

        dashboard_directive = result["sos_dashboard"]["operating_directive"]
        assert dashboard_directive["state"] == "approval_required"
        assert dashboard_directive["requested_mode"] == "Cruise"
        assert dashboard_directive["approval_status"] == "required"
        assert dashboard_directive["source_services"] == ["operator_mode_request", "sos_identity"]


def test_sos_dashboard_adapter_reads_mode_ledger_history_from_all_telemetry_shapes():
    ledger = {
        "state": "confirmed",
        "snapshot_status": "ok",
        "active_mode": "Cruise",
        "requested_mode": "Cruise",
        "transition_id": "transition-1",
        "transition_sequence": 12,
        "receipt_status": "applied",
        "receipt_reason": "",
        "authority_state": "allowed",
        "directive_state": "approval_required",
        "warnings": [],
        "blockers": [],
        "source_services": ["mode_transition_receipt", "authority"],
    }
    child = {
        "service_id": "mode_ledger",
        "script_id": "pb-bridge-001-sos_mode_ledger",
        "status": "ok",
        "error_bucket": "none",
        "summary": "mode ledger confirmed",
        "result": {"sos_mode_ledger": ledger},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"mode_ledger": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_mode_ledger": child}},
    )

    for runtime_telemetry in telemetry_shapes:
        result = run({"bridge_id": "pb-bridge-001", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []}, "runtime_telemetry": runtime_telemetry})
        dashboard_ledger = result["sos_dashboard"]["mode_ledger"]
        assert dashboard_ledger["state"] == "confirmed"
        assert dashboard_ledger["transition_id"] == "transition-1"
        assert dashboard_ledger["receipt_status"] == "applied"
        assert dashboard_ledger["authority_state"] == "allowed"


def test_sos_dashboard_adapter_reads_mode_transition_plan_history_from_all_telemetry_shapes():
    plan = {
        "state": "proposed", "snapshot_status": "ok", "plans": [{"action_id": "sos-mtp-1", "to_mode": "Cruise"}],
        "blockers": [], "warnings": ["operator_approval_required"], "source_services": ["mode_ledger", "operating_directive"],
    }
    child = {
        "service_id": "mode_transition_plan", "script_id": "pb-bridge-001-sos_mode_transition_plan", "status": "ok",
        "error_bucket": "none", "summary": "mode transition plan", "result": {"sos_mode_transition_plan": plan},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"mode_transition_plan": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_mode_transition_plan": child}},
    )
    for runtime_telemetry in telemetry_shapes:
        result = run({"bridge_id": "pb-bridge-001", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []}, "runtime_telemetry": runtime_telemetry})
        dashboard_plan = result["sos_dashboard"]["mode_transition_plan"]
        assert dashboard_plan["state"] == "proposed"
        assert dashboard_plan["plan_count"] == 1
        assert dashboard_plan["warnings"] == ["operator_approval_required"]


def test_sos_dashboard_adapter_reads_mode_transition_review_history_from_all_telemetry_shapes():
    for state in ("ready", "blocked", "unknown"):
        review = {
            "state": state, "snapshot_status": "ok",
            "approval_packet": {"action_id": "review-1", "approval_nonce": "nonce-1", "target_grid_entity_id": 10, "from_mode": "Docked", "to_mode": "Cruise", "expires_after_sequence": 20},
            "blockers": [] if state == "ready" else ["review_blocked"], "warnings": ["operator_review_required"], "source_services": ["mode_transition_plan", "mode_ledger", "authority"],
        }
        child = {
            "service_id": "mode_transition_review", "script_id": "pb-bridge-001-sos_mode_transition_review", "status": "ok",
            "error_bucket": "none", "summary": "mode transition review", "result": {"sos_mode_transition_review": review},
        }
        telemetry_shapes = (
            {"child_services": [child]},
            {"child_services_by_service_id": {"mode_transition_review": child}},
            {"child_services_by_script_id": {"pb-bridge-001-sos_mode_transition_review": child}},
        )
        for runtime_telemetry in telemetry_shapes:
            result = run({"bridge_id": "pb-bridge-001", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []}, "runtime_telemetry": runtime_telemetry})
            dashboard_review = result["sos_dashboard"]["mode_transition_review"]
            assert dashboard_review["state"] == state
            assert dashboard_review["approval_packet"]["action_id"] == "review-1"
            assert dashboard_review["approval_packet"]["to_mode"] == "Cruise"


def test_sos_dashboard_adapter_reads_mode_transition_apply_history_from_all_telemetry_shapes():
    applied = {
        "state": "applied", "snapshot_status": "ok", "action_id": "mode-apply-1",
        "from_mode": "Docked", "to_mode": "Cruise", "approval_status": "approved",
        "receipt_status": "applied", "receipt_reason": "", "reconciliation_state": "applied",
        "warnings": [], "blockers": [], "source_services": ["mode_transition_plan", "mode_ledger"],
    }
    child = {
        "service_id": "mode_transition_apply", "script_id": "pb-bridge-001-sos_mode_transition_apply", "status": "ok",
        "error_bucket": "none", "summary": "mode transition applied", "result": {"sos_mode_transition_apply": applied},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"mode_transition_apply": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_mode_transition_apply": child}},
    )
    for runtime_telemetry in telemetry_shapes:
        result = run({"bridge_id": "pb-bridge-001", "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []}, "runtime_telemetry": runtime_telemetry})
        dashboard_apply = result["sos_dashboard"]["mode_transition_apply"]
        assert dashboard_apply["state"] == "applied"
        assert dashboard_apply["action_id"] == "mode-apply-1"
        assert dashboard_apply["receipt_status"] == "applied"


def test_sos_dashboard_adapter_reads_automation_recovery_history_from_all_telemetry_shapes():
    automation_recovery = {
        "state": "rejected",
        "snapshot_status": "ok",
        "reason": "receipt_rejected",
        "candidate_count": 1,
        "warnings": ["receipt_rejected:sos_target_grid_mismatch"],
        "blockers": ["receipt_rejected"],
        "receipt_status": "rejected",
        "receipt_outcome": "rejected",
        "receipt_reason": "sos_target_grid_mismatch",
        "receipt_sequence": 12,
        "reconciliation_state": "rejected",
    }
    child = {
        "service_id": "automation_recovery",
        "script_id": "pb-bridge-001-sos_automation_recovery",
        "status": "ok",
        "error_bucket": "none",
        "summary": "automation recovery passive",
        "result": {"sos_automation_recovery": automation_recovery},
    }
    telemetry_shapes = (
        {"child_services": [child]},
        {"child_services_by_service_id": {"automation_recovery": child}},
        {"child_services_by_script_id": {"pb-bridge-001-sos_automation_recovery": child}},
    )

    for runtime_telemetry in telemetry_shapes:
        result = run(
            {
                "bridge_id": "pb-bridge-001",
                "sos_ship": {"ship_id": "ship-a", "display_name": "Ship A", "status_surfaces": []},
                "runtime_telemetry": runtime_telemetry,
            }
        )

        assert result["sos_dashboard"]["automation_recovery"]["state"] == "rejected"
        assert result["sos_dashboard"]["automation_recovery"]["reason"] == "receipt_rejected"
        assert result["sos_dashboard"]["automation_recovery"]["candidate_count"] == 1
        assert result["sos_dashboard"]["automation_recovery"]["receipt_status"] == "rejected"
        assert result["sos_dashboard"]["automation_recovery"]["receipt_outcome"] == "rejected"
        assert result["sos_dashboard"]["automation_recovery"]["receipt_reason"] == "sos_target_grid_mismatch"
        assert result["sos_dashboard"]["automation_recovery"]["receipt_sequence"] == 12
        assert result["sos_dashboard"]["automation_recovery"]["reconciliation_state"] == "rejected"
