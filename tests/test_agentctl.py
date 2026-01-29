"""Tests for agentctl CLI commands"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from boxctl.agentctl.helpers import (
    get_tmux_sessions,
    session_exists,
    capture_pane,
    get_agent_command,
    kill_session,
    detach_client,
    TMUX_TIMEOUT,
    _tmux_cmd,
)


@pytest.fixture(autouse=True)
def clear_tmux_env():
    """Ensure TMUX env var is not set during tests for consistent behavior."""
    with patch.dict(os.environ, {}, clear=False):
        # Remove TMUX if it exists to ensure tests use default tmux server
        os.environ.pop("TMUX", None)
        yield


class TestAgentctlHelpers:
    """Test agentctl helper functions"""

    def test_get_agent_command_known_agents(self):
        """Test that known agents return valid command paths"""
        assert get_agent_command("claude").endswith("claude")
        assert get_agent_command("superclaude").endswith("claude")
        assert get_agent_command("codex").endswith("codex")
        assert get_agent_command("supercodex").endswith("codex")
        assert get_agent_command("gemini").endswith("gemini")
        assert get_agent_command("supergemini").endswith("gemini")
        assert get_agent_command("shell") == "/bin/bash"

    def test_get_agent_command_unknown_agent(self):
        """Test that unknown agents default to bash"""
        assert get_agent_command("unknown") == "/bin/bash"
        assert get_agent_command("random") == "/bin/bash"

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_get_tmux_sessions_empty(self, mock_run):
        """Test getting sessions when none exist"""
        mock_run.return_value = Mock(returncode=1, stdout="")
        result = get_tmux_sessions()
        assert result == []

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_get_tmux_sessions_with_sessions(self, mock_run):
        """Test getting sessions when they exist"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="claude\t1\t1\tSun Jan 5 10:00:00 2025\ncodex\t2\t0\tSun Jan 5 11:00:00 2025\n",
        )
        result = get_tmux_sessions()

        assert len(result) == 2
        assert result[0]["name"] == "claude"
        assert result[0]["windows"] == 1
        assert result[0]["attached"] is True
        assert result[1]["name"] == "codex"
        assert result[1]["windows"] == 2
        assert result[1]["attached"] is False

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_session_exists_true(self, mock_run):
        """Test session_exists when session exists"""
        mock_run.return_value = Mock(returncode=0)
        assert session_exists("claude") is True
        mock_run.assert_called_once_with(
            ["tmux", "has-session", "-t", "claude"],
            capture_output=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_session_exists_false(self, mock_run):
        """Test session_exists when session doesn't exist"""
        mock_run.return_value = Mock(returncode=1)
        assert session_exists("nonexistent") is False

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_capture_pane_success(self, mock_run):
        """Test capturing pane output"""
        expected_output = "line1\nline2\nline3\n"
        mock_run.return_value = Mock(returncode=0, stdout=expected_output)

        result = capture_pane("claude", 50)

        assert result == expected_output
        mock_run.assert_called_once_with(
            ["tmux", "capture-pane", "-t", "claude", "-p", "-S", "-50"],
            capture_output=True,
            text=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_capture_pane_failure(self, mock_run):
        """Test capturing pane when session doesn't exist"""
        mock_run.return_value = Mock(returncode=1, stdout="")
        result = capture_pane("nonexistent", 50)
        assert result == ""

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_kill_session_success(self, mock_run):
        """Test killing a session successfully"""
        mock_run.return_value = Mock(returncode=0)
        assert kill_session("claude") is True
        mock_run.assert_called_once_with(
            ["tmux", "kill-session", "-t", "claude"],
            capture_output=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_kill_session_failure(self, mock_run):
        """Test killing a session that doesn't exist"""
        mock_run.return_value = Mock(returncode=1)
        assert kill_session("nonexistent") is False

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_detach_client_success(self, mock_run):
        """Test detaching client successfully"""
        mock_run.return_value = Mock(returncode=0)
        assert detach_client() is True
        mock_run.assert_called_once_with(
            ["tmux", "detach-client"], capture_output=True, check=False, timeout=TMUX_TIMEOUT
        )

    @patch("boxctl.agentctl.helpers.subprocess.run")
    def test_detach_client_failure(self, mock_run):
        """Test detaching when not in tmux"""
        mock_run.return_value = Mock(returncode=1)
        assert detach_client() is False


class TestAgentctlCLI:
    """Test agentctl CLI commands"""

    @patch("boxctl.agentctl.cli.get_tmux_sessions")
    def test_ls_command_empty(self, mock_get_sessions):
        """Test ls command with no sessions"""
        mock_get_sessions.return_value = []

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "No tmux sessions found" in result.output

    @patch("boxctl.agentctl.cli.get_tmux_sessions")
    def test_ls_command_with_sessions(self, mock_get_sessions):
        """Test ls command with sessions"""
        mock_get_sessions.return_value = [
            {
                "name": "claude",
                "windows": 1,
                "attached": True,
                "created": "Sun Jan 5 10:00:00 2025",
            },
            {
                "name": "codex",
                "windows": 2,
                "attached": False,
                "created": "Sun Jan 5 11:00:00 2025",
            },
        ]

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "claude" in result.output
        assert "codex" in result.output

    @patch("boxctl.agentctl.cli.get_tmux_sessions")
    def test_ls_command_json_output(self, mock_get_sessions):
        """Test ls command with JSON output"""
        mock_get_sessions.return_value = [
            {"name": "claude", "windows": 1, "attached": True, "created": "Sun Jan 5 10:00:00 2025"}
        ]

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli
        import json

        runner = CliRunner()
        result = runner.invoke(cli, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "sessions" in data
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["name"] == "claude"

    @patch("boxctl.agentctl.cli.session_exists")
    @patch("boxctl.agentctl.cli.capture_pane")
    @patch("boxctl.agentctl.cli.get_tmux_sessions")
    def test_peek_command_existing_session(self, mock_get_sessions, mock_capture, mock_exists):
        """Test peek command on existing session"""
        mock_exists.return_value = True
        mock_capture.return_value = "line1\nline2\nline3\n"
        mock_get_sessions.return_value = [
            {"name": "claude", "windows": 1, "attached": True, "created": "Sun Jan 5 10:00:00 2025"}
        ]

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["peek", "claude", "3"])

        assert result.exit_code == 0
        assert "line1" in result.output
        mock_capture.assert_called_once_with("claude", 3)

    @patch("boxctl.agentctl.cli.session_exists")
    def test_peek_command_nonexistent_session(self, mock_exists):
        """Test peek command on nonexistent session"""
        mock_exists.return_value = False

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["peek", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("boxctl.agentctl.cli.session_exists")
    @patch("boxctl.agentctl.cli.kill_session_helper")
    def test_kill_command_with_force(self, mock_kill, mock_exists):
        """Test kill command with force flag"""
        mock_exists.return_value = True
        mock_kill.return_value = True

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["kill", "claude", "-f"])

        assert result.exit_code == 0
        assert "killed" in result.output
        mock_kill.assert_called_once_with("claude")

    @patch("boxctl.agentctl.cli.session_exists")
    def test_kill_command_nonexistent_session(self, mock_exists):
        """Test kill command on nonexistent session"""
        mock_exists.return_value = False

        from click.testing import CliRunner
        from boxctl.agentctl.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["kill", "nonexistent", "-f"])

        assert result.exit_code == 1
        assert "not found" in result.output
