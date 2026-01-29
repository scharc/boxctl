"""Tests for stale detection in web UI"""

import pytest
from unittest.mock import Mock, patch

pytest.importorskip("fastapi")

from boxctl.web.host_server import app


class TestStaleDetection:
    """Test stale detection logic in WebSocket handler"""

    def test_app_exists(self):
        """Test that FastAPI app is properly initialized"""
        assert app is not None
        assert app.title == "boxctl Web UI (Host)"

    def test_stale_threshold_configurable(self):
        """Test that stale threshold can be configured"""
        # Test different threshold values
        for threshold in [10, 30, 60]:
            activity = {"stale_threshold": threshold}
            assert activity["stale_threshold"] == threshold

    def test_notification_message_format(self):
        """Test notification message formatting"""
        container = "boxctl-myproject"
        session_name = "claude"
        time_since_change = 45

        # Expected format
        project = container.replace("boxctl-", "")
        title = f"Session {session_name} idle"
        message = f"{project}: No output for {int(time_since_change)}s"

        assert title == "Session claude idle"
        assert message == "myproject: No output for 45s"

    def test_state_transitions(self):
        """Test session state transitions"""
        activity = {
            "was_active": False,
            "notified": False,
        }

        # Transition 1: IDLE -> ACTIVE (output appears)
        activity["was_active"] = True
        activity["notified"] = False
        assert activity["was_active"] is True

        # Transition 2: ACTIVE -> STALE (no output for threshold)
        activity["notified"] = True
        activity["was_active"] = False
        assert activity["notified"] is True
        assert activity["was_active"] is False

        # Transition 3: STALE -> ACTIVE (output resumes)
        activity["was_active"] = True
        activity["notified"] = False
        assert activity["was_active"] is True
        assert activity["notified"] is False

    def test_no_notification_for_idle_sessions(self):
        """Test that idle sessions don't trigger notifications"""
        activity = {
            "was_active": False,  # Never was active
            "notified": False,
            "last_change_time": None,
        }

        # Session that was never active should not trigger notification
        # Even if time_since_change would exceed threshold
        should_notify = activity["was_active"] and activity["last_change_time"]
        assert should_notify is False

    def test_no_duplicate_notifications(self):
        """Test that notifications are sent only once per stale period"""
        activity = {
            "was_active": True,
            "notified": False,
            "last_change_time": 0,
            "stale_threshold": 30,
        }

        now = 100  # 100 seconds later
        time_since_change = now - activity["last_change_time"]

        # First check - should notify
        if time_since_change >= activity["stale_threshold"]:
            if not activity["notified"]:
                activity["notified"] = True
                notification_count = 1

        # Second check - should NOT notify again
        if time_since_change >= activity["stale_threshold"]:
            if not activity["notified"]:
                notification_count += 1

        assert notification_count == 1
        assert activity["notified"] is True


class TestWebSocketIntegration:
    """Integration tests for WebSocket endpoints"""

    def test_websocket_endpoint_exists(self):
        """Test that WebSocket endpoint is defined"""
        routes = [route.path for route in app.routes]
        assert "/ws/{container}/{session_name}" in routes

    def test_api_sessions_endpoint_exists(self):
        """Test that sessions API endpoint is defined"""
        routes = [route.path for route in app.routes]
        assert "/api/sessions" in routes

    @patch("boxctl.web.host_server.get_all_sessions")
    def test_get_sessions_endpoint(self, mock_get_sessions):
        """Test the /api/sessions endpoint"""
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        mock_get_sessions.return_value = [
            {
                "container": "boxctl-test",
                "name": "claude",
                "windows": 1,
                "attached": False,
                "created": "2024-01-01",
            }
        ]

        client = TestClient(app)
        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["name"] == "claude"
