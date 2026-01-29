# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for session warning functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from boxctl.cli.helpers import _warn_if_agents_running
from boxctl.container import ContainerManager


class TestWarnIfAgentsRunning:
    """Test the _warn_if_agents_running helper function."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock ContainerManager."""
        manager = Mock(spec=ContainerManager)
        manager.container_exists.return_value = True
        manager.is_running.return_value = True
        # Mock exec_command to return expected tuple (exit_code, output)
        manager.exec_command.return_value = (0, "1000")
        return manager

    def test_no_warning_if_container_doesnt_exist(self, mock_manager):
        """Should return True without warning if container doesn't exist."""
        mock_manager.container_exists.return_value = False

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        mock_manager.container_exists.assert_called_once_with("test-container")

    def test_no_warning_if_container_not_running(self, mock_manager):
        """Should return True without warning if container is not running."""
        mock_manager.is_running.return_value = False

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        mock_manager.container_exists.assert_called_once_with("test-container")
        mock_manager.is_running.assert_called_once_with("test-container")

    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_no_warning_if_no_sessions(self, mock_get_sessions, mock_manager):
        """Should return True without warning if no tmux sessions exist."""
        mock_get_sessions.return_value = []

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        mock_get_sessions.assert_called_once_with(mock_manager, "test-container")

    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_no_warning_if_only_non_agent_sessions(self, mock_get_sessions, mock_manager):
        """Should return True without warning if only non-agent sessions exist."""
        mock_get_sessions.return_value = [
            {"name": "shell", "windows": 1, "attached": False, "created": ""},
            {"name": "custom-session", "windows": 1, "attached": False, "created": ""},
        ]

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_warning_shown_for_claude_session(self, mock_get_sessions, mock_confirm, mock_manager):
        """Should show warning and ask for confirmation when claude session exists."""
        mock_get_sessions.return_value = [
            {"name": "claude", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = True

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        mock_confirm.assert_called_once_with("\nProceed with rebuild?", default=False)

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_warning_shown_for_superclaude_session(
        self, mock_get_sessions, mock_confirm, mock_manager
    ):
        """Should show warning for superclaude session."""
        mock_get_sessions.return_value = [
            {"name": "superclaude", "windows": 1, "attached": True, "created": ""},
        ]
        mock_confirm.return_value = True

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        mock_confirm.assert_called_once()

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_warning_shown_for_codex_session(self, mock_get_sessions, mock_confirm, mock_manager):
        """Should show warning for codex session."""
        mock_get_sessions.return_value = [
            {"name": "codex", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = True

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_warning_shown_for_gemini_session(self, mock_get_sessions, mock_confirm, mock_manager):
        """Should show warning for gemini session."""
        mock_get_sessions.return_value = [
            {"name": "gemini", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = True

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_warning_shown_for_multiple_agent_sessions(
        self, mock_get_sessions, mock_confirm, mock_manager
    ):
        """Should show warning for multiple agent sessions."""
        mock_get_sessions.return_value = [
            {"name": "claude", "windows": 1, "attached": False, "created": ""},
            {"name": "superclaude", "windows": 1, "attached": True, "created": ""},
            {"name": "shell", "windows": 1, "attached": False, "created": ""},  # Should be ignored
        ]
        mock_confirm.return_value = True

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        mock_confirm.assert_called_once()

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_returns_false_when_user_declines(self, mock_get_sessions, mock_confirm, mock_manager):
        """Should return False when user declines to proceed."""
        mock_get_sessions.return_value = [
            {"name": "claude", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = False

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is False

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    @patch("boxctl.cli.helpers.tmux_ops.console")
    def test_displays_session_info(
        self, mock_console, mock_get_sessions, mock_confirm, mock_manager
    ):
        """Should display session information in warning."""
        mock_get_sessions.return_value = [
            {"name": "superclaude", "windows": 1, "attached": True, "created": ""},
            {"name": "claude", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = True

        _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        # Check that console.print was called with warning messages
        assert mock_console.print.call_count >= 3  # Warning header + at least 2 sessions

        # Verify warning message contains expected text
        calls = [str(call) for call in mock_console.print.call_args_list]
        warning_text = "".join(calls)
        assert (
            "Warning: Active agent sessions detected" in warning_text
            or "Active agent sessions" in warning_text
        )

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_custom_action_message(self, mock_get_sessions, mock_confirm, mock_manager):
        """Should use custom action message in confirmation."""
        mock_get_sessions.return_value = [
            {"name": "claude", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = True

        _warn_if_agents_running(mock_manager, "test-container", "workspace update")

        mock_confirm.assert_called_once_with("\nProceed with workspace update?", default=False)

    @patch("boxctl.cli.helpers.tmux_ops.click.confirm")
    @patch("boxctl.cli.helpers.tmux_ops._get_tmux_sessions")
    def test_case_insensitive_agent_detection(self, mock_get_sessions, mock_confirm, mock_manager):
        """Should detect agent sessions case-insensitively."""
        mock_get_sessions.return_value = [
            {"name": "CLAUDE", "windows": 1, "attached": False, "created": ""},
            {"name": "SuperClaude", "windows": 1, "attached": False, "created": ""},
            {"name": "CODEX-123", "windows": 1, "attached": False, "created": ""},
        ]
        mock_confirm.return_value = True

        result = _warn_if_agents_running(mock_manager, "test-container", "rebuild")

        assert result is True
        # Should show warning for all 3 sessions
        mock_confirm.assert_called_once()
