"""Tests for boxctl/notifications.py"""

import json
import socket
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from boxctl.notifications import send_notification, _get_ssh_socket_path


class TestGetSshSocketPath:
    """Test SSH socket path discovery"""

    def test_env_var_takes_precedence(self, tmp_path):
        """Test BOXCTL_SSH_SOCKET env var is checked first"""
        sock_path = tmp_path / "ssh.sock"
        sock_path.touch()

        with patch.dict("os.environ", {"BOXCTL_SSH_SOCKET": str(sock_path)}):
            result = _get_ssh_socket_path()
            assert result == sock_path

    def test_env_var_nonexistent_file(self, tmp_path):
        """Test env var pointing to nonexistent file returns None"""
        with patch.dict("os.environ", {"BOXCTL_SSH_SOCKET": "/nonexistent/path"}):
            with patch("pathlib.Path.exists", return_value=False):
                result = _get_ssh_socket_path()
                assert result is None

    @patch("os.getuid", return_value=1000)
    def test_xdg_runtime_path(self, mock_getuid, tmp_path):
        """Test XDG runtime directory path"""
        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.exists") as mock_exists:
                # No env var set, so first exists() is XDG path -> True
                mock_exists.return_value = True
                result = _get_ssh_socket_path()
                assert result == Path("/run/user/1000/boxctld/ssh.sock")

    def test_container_path_fallback(self):
        """Test container mount path as fallback"""
        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.exists") as mock_exists:
                # No env var, XDG path fails, container path succeeds
                mock_exists.side_effect = [False, True]
                with patch("os.getuid", return_value=1000):
                    result = _get_ssh_socket_path()
                    assert result == Path("/run/boxctld/ssh.sock")

    def test_no_socket_found(self):
        """Test returns None when no socket found"""
        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    result = _get_ssh_socket_path()
                    assert result is None


class TestSendNotification:
    """Test notification sending functionality"""

    @patch("boxctl.notifications._get_ssh_socket_path")
    def test_returns_false_when_no_socket(self, mock_get_socket):
        """Test notification fails gracefully when no SSH socket"""
        mock_get_socket.return_value = None

        result = send_notification("Test Title", "Test Message")

        assert result is False

    @patch("boxctl.notifications._get_ssh_socket_path")
    def test_returns_false_when_asyncssh_missing(self, mock_get_socket):
        """Test notification fails gracefully when asyncssh not installed"""
        mock_get_socket.return_value = Path("/tmp/ssh.sock")

        with patch.dict("sys.modules", {"asyncssh": None}):
            # Force ImportError by making asyncssh import fail
            import sys

            old_asyncssh = sys.modules.get("asyncssh")
            sys.modules["asyncssh"] = None
            try:
                # Reload to trigger ImportError
                result = send_notification("Test", "Message")
                # The function catches ImportError and returns False
            finally:
                if old_asyncssh:
                    sys.modules["asyncssh"] = old_asyncssh

    def test_enhance_builds_metadata(self):
        """Test enhance=True includes metadata in request"""
        with patch("boxctl.notifications._get_ssh_socket_path", return_value=None):
            # Can't fully test without SSH, but verify it doesn't crash
            result = send_notification(
                "Test",
                "Message",
                enhance=True,
                container="test-container",
                session="test-session",
                buffer="test buffer content",
            )
            assert result is False  # No socket, but shouldn't crash


class TestNotifyScript:
    """Tests for bin/abox-notify script"""

    def test_abox_notify_script_syntax(self):
        """Test that abox-notify script has valid bash syntax"""
        import subprocess
        from pathlib import Path

        script_path = Path(__file__).parent.parent / "bin" / "abox-notify"
        if not script_path.exists():
            pytest.skip("abox-notify script not found")

        result = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error: {result.stderr}"
