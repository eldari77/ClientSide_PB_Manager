from bridge.mailbox import BridgeConfig, decode_mailbox, encode_mailbox, request_payload, validate_result


def test_request_payload_requires_allowlisted_script():
    config = BridgeConfig("bridge-a")
    payload = request_payload(
        config,
        1,
        "sample_status_adapter",
        {"block_count": 1},
        {"last_runtime_ms": 0.01, "limiter_state": "ok"},
    )
    assert payload["bridge_id"] == "bridge-a"
    assert payload["message_kind"] == "request"
    assert payload["sequence"] == 1
    assert payload["runtime_telemetry"]["limiter_state"] == "ok"


def test_mailbox_round_trip():
    payload = {"schema": "novali.client_side_pb_bridge.v1", "bridge_id": "bridge-a", "sequence": 1}
    assert decode_mailbox(encode_mailbox(payload)) == payload


def test_validate_result_rejects_stale_sequence():
    config = BridgeConfig("bridge-a")
    result = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "result",
        "bridge_id": "bridge-a",
        "sequence": 2,
        "script_id": "sample_status_adapter",
        "status": "ok",
    }
    assert validate_result(config, 1, result) == "sequence_mismatch"


def test_validate_result_rejects_request_echo():
    config = BridgeConfig("bridge-a")
    result = {
        "schema": "novali.client_side_pb_bridge.v1",
        "message_kind": "request",
        "bridge_id": "bridge-a",
        "sequence": 1,
        "script_id": "sample_status_adapter",
        "status": "ok",
    }
    assert validate_result(config, 1, result) == "message_kind_invalid"
