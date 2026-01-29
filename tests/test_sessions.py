"""Tests for boxctl/core/sessions.py (and boxctl.core.sessions)"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from boxctl.core.sessions import (
    get_sessions_for_container,
    get_all_sessions,
    capture_session_output,
    send_keys_to_session,
    resize_session,
)


class TestGetSessionsForContainer:
    """Test getting sessions for a specific container"""

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.list_tmux_sessions")
    def test_get_sessions_running_container(self, mock_list_tmux, mock_manager_class):
        """Test getting sessions from a running container"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager

        mock_sessions = [
            {"name": "claude", "windows": 1, "attached": False, "created": "2024-01-01"}
        ]
        mock_list_tmux.return_value = mock_sessions

        result = get_sessions_for_container("boxctl-test")

        assert result == mock_sessions
        mock_manager.is_running.assert_called_once_with("boxctl-test")
        mock_list_tmux.assert_called_once_with(mock_manager, "boxctl-test")

    @patch("boxctl.container.ContainerManager")
    def test_get_sessions_stopped_container(self, mock_manager_class):
        """Test getting sessions from a stopped container"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = False
        mock_manager_class.return_value = mock_manager

        result = get_sessions_for_container("boxctl-test")

        assert result == []

    @patch("boxctl.container.ContainerManager")
    def test_get_sessions_exception_handling(self, mock_manager_class):
        """Test exception handling in get_sessions_for_container"""
        mock_manager_class.side_effect = Exception("Connection failed")

        result = get_sessions_for_container("boxctl-test")

        assert result == []


class TestGetAllSessions:
    """Test getting sessions across all containers"""

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.list_tmux_sessions")
    def test_get_all_sessions_multiple_containers(self, mock_list_tmux, mock_manager_class):
        """Test getting sessions from multiple containers"""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager

        # Mock Docker containers
        mock_container1 = Mock()
        mock_container1.name = "boxctl-project1"
        mock_container2 = Mock()
        mock_container2.name = "boxctl-project2"
        mock_manager.client.containers.list.return_value = [mock_container1, mock_container2]

        # Mock sessions for each container
        def mock_sessions(manager, container_name):
            if container_name == "boxctl-project1":
                return [
                    {"name": "claude", "windows": 1, "attached": False, "created": "2024-01-01"}
                ]
            elif container_name == "boxctl-project2":
                return [{"name": "codex", "windows": 2, "attached": True, "created": "2024-01-02"}]
            return []

        mock_list_tmux.side_effect = mock_sessions

        result = get_all_sessions()

        assert len(result) == 2
        assert result[0]["container"] == "boxctl-project1"
        assert result[0]["name"] == "claude"
        assert result[1]["container"] == "boxctl-project2"
        assert result[1]["name"] == "codex"

    @patch("boxctl.container.ContainerManager")
    def test_get_all_sessions_no_containers(self, mock_manager_class):
        """Test getting sessions when no containers exist"""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        mock_manager.client.containers.list.return_value = []

        result = get_all_sessions()

        assert result == []

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.list_tmux_sessions")
    def test_get_all_sessions_filters_non_agentbox(self, mock_list_tmux, mock_manager_class):
        """Test that non-boxctl containers are filtered out"""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager

        mock_container1 = Mock()
        mock_container1.name = "boxctl-project1"
        mock_container2 = Mock()
        mock_container2.name = "other-container"
        mock_manager.client.containers.list.return_value = [mock_container1, mock_container2]

        mock_list_tmux.return_value = [{"name": "test", "windows": 1, "attached": False}]

        result = get_all_sessions()

        # Should only get sessions from boxctl container
        assert len(result) == 1
        assert result[0]["container"] == "boxctl-project1"

    @patch("boxctl.container.ContainerManager")
    def test_get_all_sessions_exception_handling(self, mock_manager_class):
        """Test exception handling in get_all_sessions"""
        mock_manager_class.side_effect = Exception("Docker connection failed")

        result = get_all_sessions()

        assert result == []


class TestCaptureSessionOutput:
    """Test capturing session output"""

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.capture_pane")
    def test_capture_output_success(self, mock_capture, mock_manager_class):
        """Test successfully capturing session output"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager
        mock_capture.return_value = "Test output\nLine 2\nLine 3"

        result = capture_session_output("boxctl-test", "claude", lines=50)

        assert result == "Test output\nLine 2\nLine 3"
        mock_capture.assert_called_once_with(mock_manager, "boxctl-test", "claude", 50)

    @patch("boxctl.container.ContainerManager")
    def test_capture_output_stopped_container(self, mock_manager_class):
        """Test capturing output from stopped container"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = False
        mock_manager_class.return_value = mock_manager

        result = capture_session_output("boxctl-test", "claude")

        assert result == ""

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.capture_pane")
    def test_capture_output_command_failure(self, mock_capture, mock_manager_class):
        """Test handling command failure"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager
        mock_capture.return_value = ""

        result = capture_session_output("boxctl-test", "claude")

        assert result == ""

    @patch("boxctl.container.ContainerManager")
    def test_capture_output_exception_handling(self, mock_manager_class):
        """Test exception handling in capture_session_output"""
        mock_manager_class.side_effect = Exception("Failed")

        result = capture_session_output("boxctl-test", "claude")

        assert result == ""


class TestSendKeysToSession:
    """Test sending keys to a session"""

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.send_keys")
    def test_send_keys_success(self, mock_send, mock_manager_class):
        """Test successfully sending keys"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager
        mock_send.return_value = True

        result = send_keys_to_session("boxctl-test", "claude", "ls\n")

        assert result is True
        mock_send.assert_called_once_with(mock_manager, "boxctl-test", "claude", "ls\n", True)

    @patch("boxctl.container.ContainerManager")
    def test_send_keys_stopped_container(self, mock_manager_class):
        """Test sending keys to stopped container"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = False
        mock_manager_class.return_value = mock_manager

        result = send_keys_to_session("boxctl-test", "claude", "test")

        assert result is False

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.send_keys")
    def test_send_keys_failure(self, mock_send, mock_manager_class):
        """Test handling send keys failure"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager
        mock_send.return_value = False

        result = send_keys_to_session("boxctl-test", "claude", "test")

        assert result is False


class TestResizeSession:
    """Test resizing a session"""

    @patch("boxctl.container.ContainerManager")
    @patch("boxctl.core.sessions.resize_window")
    def test_resize_success(self, mock_resize, mock_manager_class):
        """Test successfully resizing a session"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager
        mock_resize.return_value = True

        result = resize_session("boxctl-test", "claude", 80, 24)

        assert result is True
        mock_resize.assert_called_once_with(mock_manager, "boxctl-test", "claude", 80, 24)

    @patch("boxctl.container.ContainerManager")
    def test_resize_stopped_container(self, mock_manager_class):
        """Test resizing session in stopped container"""
        mock_manager = Mock()
        mock_manager.is_running.return_value = False
        mock_manager_class.return_value = mock_manager

        result = resize_session("boxctl-test", "claude", 80, 24)

        assert result is False
