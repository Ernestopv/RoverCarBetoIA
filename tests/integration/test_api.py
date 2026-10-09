"""Integration tests for the HTTP API.

The API is exercised end to end against the simulator through ``TestClient``.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.rover.service import RoverService

API = "/api/v1"


def test_health(client: TestClient) -> None:
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["rover_mode"] == "simulator"


def test_status(client: TestClient) -> None:
    response = client.get(f"{API}/rover/status")
    assert response.status_code == 200
    assert response.json()["connection"] == "connected"


def test_move_returns_updated_status(client: TestClient) -> None:
    response = client.post(f"{API}/rover/move", json={"linear": 0.5, "angular": 0.0})
    assert response.status_code == 200
    body = response.json()
    assert body["moving"] is True
    assert body["linear"] == 0.5


def test_stop_always_succeeds(client: TestClient) -> None:
    client.post(f"{API}/rover/move", json={"linear": 1.0, "angular": 0.0})
    response = client.post(f"{API}/rover/stop")
    assert response.status_code == 200
    assert response.json()["moving"] is False


def test_stop_succeeds_even_after_link_loss(client: TestClient) -> None:
    service: RoverService = client.app.state.rover_service
    service.rover.simulate_link_loss()  # type: ignore[attr-defined]

    response = client.post(f"{API}/rover/stop")

    assert response.status_code == 200
    assert response.json()["moving"] is False


def test_follow_status_defaults_to_disabled(client: TestClient) -> None:
    response = client.get(f"{API}/behavior/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["has_target"] is False


def test_follow_can_be_enabled_and_disabled(client: TestClient) -> None:
    enabled = client.post(f"{API}/behavior/follow", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    disabled = client.post(f"{API}/behavior/follow", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_enabling_follow_is_refused_without_a_link(client: TestClient) -> None:
    service: RoverService = client.app.state.rover_service
    service.rover.simulate_link_loss()  # type: ignore[attr-defined]

    response = client.post(f"{API}/behavior/follow", json={"enabled": True})

    assert response.status_code == 409


def test_move_returns_503_when_link_is_lost(client: TestClient) -> None:
    service: RoverService = client.app.state.rover_service
    service.rover.simulate_link_loss()  # type: ignore[attr-defined]

    response = client.post(f"{API}/rover/move", json={"linear": 0.5, "angular": 0.0})

    assert response.status_code == 503


def test_non_finite_values_are_rejected(client: TestClient) -> None:
    for payload in ('{"linear": NaN, "angular": 0}', '{"linear": 0, "angular": Infinity}'):
        response = client.post(
            f"{API}/rover/move", content=payload, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    response = client.post(f"{API}/rover/move", json={"linear": 0.1, "turbo": True})
    assert response.status_code == 422


def test_out_of_range_command_is_clamped(client: TestClient) -> None:
    response = client.post(f"{API}/rover/move", json={"linear": 50.0, "angular": -50.0})
    assert response.status_code == 200
    body = response.json()
    assert body["linear"] == 1.0
    assert body["angular"] == -1.5


def test_watchdog_stops_motion_without_new_commands(client: TestClient) -> None:
    client.post(f"{API}/rover/move", json={"linear": 0.8, "angular": 0.0})

    time.sleep(0.35)  # longer than command_timeout (0.2s) in test settings

    response = client.get(f"{API}/rover/status")
    assert response.status_code == 200
    assert response.json()["moving"] is False


def test_telemetry_snapshot(client: TestClient) -> None:
    response = client.get(f"{API}/telemetry")
    assert response.status_code == 200
    body = response.json()
    assert "rover" in body
    assert body["rover"]["connection"] == "connected"


def test_ai_detections_report_unavailable_without_a_network(client: TestClient) -> None:
    """With CAMERA_MODE=simulator there is no network to infer with."""
    response = client.get(f"{API}/ai/detections")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["detections"] == []
    assert body["model"] is None


def test_telemetry_includes_ai_fields(client: TestClient) -> None:
    response = client.get(f"{API}/telemetry")

    assert response.status_code == 200
    body = response.json()
    assert "ai_inference_ms" in body
    assert "detections" in body


def test_ai_pose_reports_unavailable_without_a_network(client: TestClient) -> None:
    """With CAMERA_MODE=simulator there is no network to infer with."""
    response = client.get(f"{API}/ai/pose")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["people"] == []
    # The joint names and the skeleton travel with the answer, so the interface
    # does not have to hard-code the COCO convention.
    assert len(body["keypoint_names"]) == 17
    assert len(body["skeleton"]) == 16


# --- the AI stream ------------------------------------------------------------


def test_the_ai_stream_says_something_on_connect(client: TestClient) -> None:
    """So the interface is not blank until the first result arrives."""
    with client.websocket_connect(f"{API}/ai/stream") as socket:
        message = socket.receive_json()

    assert "detections" in message
    assert "pose" in message


def test_a_new_result_is_pushed_without_being_asked_for(client: TestClient) -> None:
    """This is the whole point: the sensor decides when there is something new."""
    with client.websocket_connect(f"{API}/ai/stream") as socket:
        socket.receive_json()  # the greeting

        # What the camera does from its own thread on every inference result.
        client.app.state.result_broadcaster.notify()

        message = socket.receive_json()

    assert message["pose"]["available"] is False
    assert message["detections"]["available"] is False


def test_the_stream_cleans_up_when_the_browser_leaves(client: TestClient) -> None:
    with client.websocket_connect(f"{API}/ai/stream") as socket:
        socket.receive_json()
        assert client.app.state.result_broadcaster.listeners == 1

    assert client.app.state.result_broadcaster.listeners == 0


# --- model switching ----------------------------------------------------------


def test_ai_models_lists_the_whitelist(client: TestClient) -> None:
    response = client.get(f"{API}/ai/models")

    assert response.status_code == 200
    body = response.json()
    ids = [model["id"] for model in body["models"]]
    assert ids == ["detection", "pose"]
    # The simulator camera has no loaded network to report.
    assert body["active"] is None


def test_switch_refuses_an_unknown_model(client: TestClient) -> None:
    response = client.post(f"{API}/ai/model", json={"id": "no-such-model"})

    assert response.status_code == 404
    assert "no-such-model" in response.json()["detail"]


def test_switch_refuses_in_simulator_mode(client: TestClient) -> None:
    """Switching needs the IMX500; the simulator has no sensor to load into."""
    response = client.post(f"{API}/ai/model", json={"id": "detection"})

    assert response.status_code == 400
    assert "IMX500" in response.json()["detail"]


def test_switch_refuses_while_the_rover_is_moving(client: TestClient) -> None:
    """Safety before everything: the operator would be driving blind."""
    client.post(f"{API}/rover/move", json={"linear": 0.4, "angular": 0.0})

    response = client.post(f"{API}/ai/model", json={"id": "pose"})

    assert response.status_code == 409
    assert "moving" in response.json()["detail"]
    client.post(f"{API}/rover/stop")


def test_camera_status_exposes_how_the_browser_reaches_the_stream(client: TestClient) -> None:
    response = client.get(f"{API}/camera/status")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "simulator"
    assert body["stream_path"] == "rover"
    assert body["webrtc_port"] == 8889
    # The video publisher is not started in tests.
    assert body["running"] is False
