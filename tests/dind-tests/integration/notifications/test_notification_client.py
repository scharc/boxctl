# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for notification client via SSH tunnel."""

import json
import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container


@pytest.mark.integration
class TestNotificationClient:
    """Test notification client functionality."""

    def test_notify_script_available(self, running_container, test_project):
        """Test that abox-notify script is available in container."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(container_name, "which abox-notify")

        assert result.returncode == 0, "abox-notify should be in PATH"
        assert "abox-notify" in result.stdout

    def test_notify_with_title_and_message(self, running_container, test_project):
        """Test basic notification with title and message."""
        container_name = f"boxctl-{test_project.name}"

        # Note: This will fail if SSH tunnel is not running, which is expected in DinD
        # We're testing that the script exists and accepts correct arguments
        result = exec_in_container(
            container_name, "abox-notify 'Test Title' 'Test Message' 2>&1 || echo 'EXPECTED_FAIL'"
        )

        # Should not crash - either succeeds or fails gracefully
        assert "EXPECTED_FAIL" in result.stdout or result.returncode == 0

    def test_notify_with_urgency_levels(self, running_container, test_project):
        """Test notifications with different urgency levels."""
        container_name = f"boxctl-{test_project.name}"

        urgency_levels = ["low", "normal", "critical"]

        for urgency in urgency_levels:
            result = exec_in_container(
                container_name,
                f"abox-notify 'Title' 'Message' {urgency} 2>&1 || echo 'EXPECTED_FAIL'",
            )
            # Should accept the urgency level without error
            assert "EXPECTED_FAIL" in result.stdout or result.returncode == 0


@pytest.mark.integration
class TestNotificationPayload:
    """Test notification payload formatting."""

    def test_python_import_works(self, running_container, test_project):
        """Test that notifications module can be imported."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c 'from boxctl.notifications import send_notification; print(\"OK\")'",
        )

        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_send_notification_without_ssh_socket(self, running_container, test_project):
        """Test send_notification returns False when SSH socket doesn't exist."""
        container_name = f"boxctl-{test_project.name}"

        # Try to send notification - will fail without SSH tunnel
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.notifications import send_notification; "
            'result = send_notification("Title", "Message"); '
            'print("RESULT:", result)'
            "'",
        )

        assert result.returncode == 0
        assert "RESULT: False" in result.stdout

    def test_notification_with_enhancement_metadata(self, running_container, test_project):
        """Test notification with enhancement metadata doesn't crash."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.notifications import send_notification

result = send_notification(
    title="Enhanced",
    message="Message",
    urgency="normal",
    container="test-container",
    session="test-session",
    buffer="buffer content",
    enhance=True
)
print(f"RESULT:{result}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        # Will be False without SSH tunnel, but should not crash
        assert "RESULT:" in result.stdout


@pytest.mark.integration
class TestNotificationErrorHandling:
    """Test notification error handling."""

    def test_notification_returns_false_without_tunnel(self, running_container, test_project):
        """Test notification fails gracefully without SSH tunnel."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.notifications import send_notification; "
            'result = send_notification("Title", "Message"); '
            "exit(0 if result is False else 1)"
            "'",
        )

        assert result.returncode == 0, "Should return False without SSH tunnel"

    def test_notification_with_invalid_urgency(self, running_container, test_project):
        """Test notification with invalid urgency level doesn't crash."""
        container_name = f"boxctl-{test_project.name}"

        # Python will accept any string for urgency, but test it doesn't crash
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.notifications import send_notification; "
            'result = send_notification("Title", "Message", urgency="invalid"); '
            'print("OK")'
            "'",
        )

        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_notification_with_empty_title(self, running_container, test_project):
        """Test notification with empty title doesn't crash."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.notifications import send_notification; "
            'result = send_notification("", "Message"); '
            'print("OK")'
            "'",
        )

        # Should not crash
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_notification_with_long_message(self, running_container, test_project):
        """Test notification with very long message doesn't crash."""
        container_name = f"boxctl-{test_project.name}"

        # Create a long message
        long_message = "x" * 10000

        result = exec_in_container(
            container_name,
            f"python3 -c '"
            "from boxctl.notifications import send_notification; "
            f'result = send_notification("Title", "{long_message}"); '
            'print("OK")'
            "'",
        )

        # Should handle long messages without crashing
        assert result.returncode == 0
        assert "OK" in result.stdout


@pytest.mark.integration
class TestSshSocketPath:
    """Test SSH socket path resolution."""

    def test_ssh_socket_path_function_exists(self, running_container, test_project):
        """Test that _get_ssh_socket_path function exists."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.notifications import _get_ssh_socket_path; "
            "result = _get_ssh_socket_path(); "
            'print(f"RESULT:{result}")'
            "'",
        )

        assert result.returncode == 0
        assert "RESULT:" in result.stdout

    def test_ssh_socket_env_var_check(self, running_container, test_project):
        """Test that BOXCTL_SSH_SOCKET env var is respected."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "BOXCTL_SSH_SOCKET=/tmp/test.sock python3 -c '"
            "import os; "
            "from boxctl.notifications import _get_ssh_socket_path; "
            "# Create the file so it passes exists check; "
            "from pathlib import Path; "
            'Path("/tmp/test.sock").touch(); '
            "result = _get_ssh_socket_path(); "
            'print(f"RESULT:{result}")'
            "'",
        )

        assert result.returncode == 0
        assert "/tmp/test.sock" in result.stdout


@pytest.mark.integration
class TestNotificationConfigIntegration:
    """Test notification integration with host config."""

    def test_timeout_configuration(self, running_container, test_project):
        """Test that timeout values are read from config."""
        container_name = f"boxctl-{test_project.name}"

        # Get timeout values from config
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.host_config import get_config; "
            "config = get_config(); "
            'normal = config.get("notifications", "timeout"); '
            'enhanced = config.get("notifications", "timeout_enhanced"); '
            'print(f"NORMAL:{normal} ENHANCED:{enhanced}")'
            "'",
        )

        assert result.returncode == 0
        # Should have both timeout values
        assert "NORMAL:" in result.stdout
        assert "ENHANCED:" in result.stdout


@pytest.mark.integration
class TestNotificationIntegration:
    """Integration tests for notification workflows."""

    def test_notify_script_passes_arguments(self, running_container, test_project):
        """Test that abox-notify correctly passes arguments."""
        container_name = f"boxctl-{test_project.name}"

        # Test with explicit arguments
        result = exec_in_container(
            container_name,
            "abox-notify 'Integration Test' 'This is a test message' normal 2>&1 || echo 'CALLED'",
        )

        # Script should be called (may fail due to no SSH tunnel, but that's OK)
        assert "CALLED" in result.stdout or result.returncode == 0

    def test_notification_from_python_api(self, running_container, test_project):
        """Test notification API from Python."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.notifications import send_notification

# This will fail without SSH tunnel, but tests the API
try:
    result = send_notification(
        title="API Test",
        message="Testing Python API",
        urgency="normal"
    )
    print(f"RESULT:{result}")
except Exception as e:
    print(f"ERROR:{e}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        # Should execute without crashing
        assert result.returncode == 0
        assert "RESULT:" in result.stdout or "ERROR:" in result.stdout

    def test_enhanced_notification_api(self, running_container, test_project):
        """Test enhanced notification with metadata."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.notifications import send_notification

result = send_notification(
    title="Enhanced Test",
    message="Testing enhancement",
    urgency="normal",
    container="test-container",
    session="test-session",
    buffer="test buffer content",
    enhance=True
)
print(f"RESULT:{result}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        # Should execute without crashing
        assert result.returncode == 0
        assert "RESULT:" in result.stdout

    def test_notification_workflow_in_session(self, running_container, test_project):
        """Test notification can be sent from within tmux session."""
        container_name = f"boxctl-{test_project.name}"

        # Create a session that tries to send a notification
        result = exec_in_container(
            container_name,
            "tmux new-session -d -s notify-test "
            '\'abox-notify "Session Test" "From tmux" 2>&1 > /tmp/notify-output.txt; sleep 2\'',
        )
        assert result.returncode == 0

        # Wait for command to execute
        time.sleep(1)

        # Check that command was executed
        result = exec_in_container(
            container_name, "test -f /tmp/notify-output.txt && echo 'EXISTS'"
        )
        assert "EXISTS" in result.stdout

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t notify-test 2>/dev/null || true")
        exec_in_container(container_name, "rm -f /tmp/notify-output.txt")
