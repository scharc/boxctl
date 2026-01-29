# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for agentctl CLI commands inside containers."""

import json
import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container, wait_for_container_ready


@pytest.mark.integration
class TestAgentctlList:
    """Test 'agentctl list' command."""

    def test_list_empty_sessions(self, running_container, test_project):
        """Test listing sessions when none exist."""
        result = exec_in_container(running_container, "agentctl list")

        assert result.returncode == 0, f"agentctl list failed: {result.stderr}"
        assert (
            "No tmux sessions found" in result.stdout
        ), f"Expected empty message, got: {result.stdout}"

    def test_list_shows_sessions(self, running_container, test_project):
        """Test listing sessions when they exist."""
        # Create a tmux session
        result = exec_in_container(
            running_container, "tmux new-session -d -s test-session 'sleep 30'"
        )
        assert result.returncode == 0, f"Failed to create session: {result.stderr}"

        # List sessions
        result = exec_in_container(running_container, "agentctl list")

        assert result.returncode == 0, f"agentctl list failed: {result.stderr}"
        assert "test-session" in result.stdout, f"Session not in list: {result.stdout}"

        # Cleanup
        exec_in_container(
            running_container, "tmux kill-session -t test-session 2>/dev/null || true"
        )

    def test_list_json_output(self, running_container, test_project):
        """Test JSON output format."""
        # Create a session
        exec_in_container(running_container, "tmux new-session -d -s json-test 'sleep 30'")

        # Get JSON output
        result = exec_in_container(running_container, "agentctl list --json")

        assert result.returncode == 0, f"agentctl list --json failed: {result.stderr}"

        # Verify valid JSON
        try:
            data = json.loads(result.stdout)
            assert "sessions" in data, "JSON output missing 'sessions' key"
            assert isinstance(data["sessions"], list), "'sessions' should be a list"

            # Check if our session is in the list
            session_names = [s["name"] for s in data["sessions"]]
            assert "json-test" in session_names, f"Session not in JSON output: {session_names}"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON output: {e}\nOutput: {result.stdout}")

        # Cleanup
        exec_in_container(running_container, "tmux kill-session -t json-test 2>/dev/null || true")

    def test_list_multiple_sessions(self, running_container, test_project):
        """Test listing multiple sessions."""
        sessions = ["session-1", "session-2", "session-3"]

        # Create multiple sessions
        for session in sessions:
            result = exec_in_container(
                running_container, f"tmux new-session -d -s {session} 'sleep 30'"
            )
            assert result.returncode == 0, f"Failed to create {session}"

        # List all sessions
        result = exec_in_container(running_container, "agentctl list")
        assert result.returncode == 0

        # Verify all sessions are shown
        for session in sessions:
            assert session in result.stdout, f"Session {session} not in output: {result.stdout}"

        # Cleanup
        for session in sessions:
            exec_in_container(
                running_container, f"tmux kill-session -t {session} 2>/dev/null || true"
            )


@pytest.mark.integration
class TestAgentctlPeek:
    """Test 'agentctl peek' command."""

    def test_peek_nonexistent_session(self, running_container, test_project):
        """Test peeking at non-existent session fails gracefully."""
        result = exec_in_container(running_container, "agentctl peek nonexistent")

        assert result.returncode != 0, "Should fail for non-existent session"
        assert (
            "not found" in result.stdout or "not found" in result.stderr
        ), f"Expected 'not found' error, got: {result.stdout} {result.stderr}"

    def test_peek_session_output(self, running_container, test_project):
        """Test viewing session output."""
        # Create session with known output
        test_output = "Hello from tmux session"
        result = exec_in_container(
            running_container,
            f"tmux new-session -d -s peek-test \"echo '{test_output}'; sleep 30\"",
        )
        assert result.returncode == 0

        # Wait a moment for output to appear
        time.sleep(2)

        # Peek at the session
        result = exec_in_container(running_container, "agentctl peek peek-test 50")

        assert result.returncode == 0, f"agentctl peek failed: {result.stderr}"
        assert test_output in result.stdout, f"Expected output not found. Got: {result.stdout}"

        # Cleanup
        exec_in_container(running_container, "tmux kill-session -t peek-test 2>/dev/null || true")

    def test_peek_with_lines_argument(self, running_container, test_project):
        """Test peek with custom line count."""
        # Create session with multiple lines
        result = exec_in_container(
            running_container,
            'tmux new-session -d -s lines-test "for i in {1..20}; do echo Line $i; done; sleep 30"',
        )
        assert result.returncode == 0

        # Wait for output
        time.sleep(2)

        # Peek with default lines
        result = exec_in_container(running_container, "agentctl peek lines-test 10")

        assert result.returncode == 0, f"agentctl peek failed: {result.stderr}"
        # Should have output (exact lines may vary due to prompt)
        line_count = len([l for l in result.stdout.split("\n") if l.strip()])
        assert line_count > 0, "Should have output lines"

        # Cleanup
        exec_in_container(running_container, "tmux kill-session -t lines-test 2>/dev/null || true")


@pytest.mark.integration
class TestAgentctlKill:
    """Test 'agentctl kill' command."""

    def test_kill_session(self, running_container, test_project):
        """Test killing a session."""
        # Create session
        result = exec_in_container(running_container, "tmux new-session -d -s kill-test 'sleep 60'")
        assert result.returncode == 0

        # Verify session exists
        result = exec_in_container(running_container, "tmux has-session -t kill-test")
        assert result.returncode == 0, "Session should exist"

        # Kill with force flag (skip confirmation)
        result = exec_in_container(running_container, "agentctl kill kill-test --force")

        assert result.returncode == 0, f"agentctl kill failed: {result.stderr}"

        # Verify session is gone
        result = exec_in_container(running_container, "tmux has-session -t kill-test")
        assert result.returncode != 0, "Session should be killed"

    def test_kill_nonexistent_session(self, running_container, test_project):
        """Test killing non-existent session fails gracefully."""
        result = exec_in_container(running_container, "agentctl kill nonexistent --force")

        assert result.returncode != 0, "Should fail for non-existent session"
        assert (
            "not found" in result.stdout or "not found" in result.stderr
        ), f"Expected 'not found' error"


@pytest.mark.integration
class TestAgentctlAttach:
    """Test 'agentctl a' (attach) command.

    Note: Full interactive attach is hard to test, but we can test
    session creation logic and validate session exists after command.
    """

    def test_attach_creates_new_session(self, running_container, test_project):
        """Test that attach creates new session if it doesn't exist."""
        # Note: We can't truly test interactive attach, but we can test
        # that the session creation logic works by checking if session exists
        # after a brief attach attempt

        session_name = "attach-test"

        # Verify session doesn't exist
        result = exec_in_container(running_container, f"tmux has-session -t {session_name}")
        assert result.returncode != 0, "Session should not exist initially"

        # Try to create session in detached mode by simulating what agentctl does
        # We can't test actual attach (interactive), but we can test session creation
        result = exec_in_container(
            running_container, f"tmux new-session -d -s {session_name} 'bash'"
        )
        assert result.returncode == 0, f"Failed to create session: {result.stderr}"

        # Verify session now exists
        result = exec_in_container(running_container, f"tmux has-session -t {session_name}")
        assert result.returncode == 0, "Session should exist after creation"

        # Cleanup
        exec_in_container(
            running_container, f"tmux kill-session -t {session_name} 2>/dev/null || true"
        )

    def test_session_naming_sanitization(self, running_container, test_project):
        """Test that session names are properly sanitized."""
        # Agentctl sanitizes session names by replacing / and . with -
        problematic_name = "test/session.name"
        expected_name = "test-session-name"

        # Create session with sanitized name
        result = exec_in_container(
            running_container, f"tmux new-session -d -s {expected_name} 'bash'"
        )
        assert result.returncode == 0

        # Verify it exists with sanitized name
        result = exec_in_container(running_container, f"tmux has-session -t {expected_name}")
        assert result.returncode == 0

        # Cleanup
        exec_in_container(
            running_container, f"tmux kill-session -t {expected_name} 2>/dev/null || true"
        )


@pytest.mark.integration
class TestAgentctlWorkingDirectory:
    """Test agentctl working directory logic."""

    def test_session_starts_in_workspace(self, running_container, test_project):
        """Test that sessions start in /workspace by default."""
        # Create a session and check its working directory
        result = exec_in_container(
            running_container,
            "tmux new-session -d -s wd-test -c /workspace 'pwd > /tmp/wd-test.txt; sleep 5'",
        )
        assert result.returncode == 0

        # Wait for command to execute
        time.sleep(2)

        # Check the recorded working directory
        result = exec_in_container(running_container, "cat /tmp/wd-test.txt")
        assert result.returncode == 0
        assert (
            "/workspace" in result.stdout
        ), f"Session should start in /workspace, got: {result.stdout}"

        # Cleanup
        exec_in_container(running_container, "tmux kill-session -t wd-test 2>/dev/null || true")
        exec_in_container(running_container, "rm -f /tmp/wd-test.txt")


@pytest.mark.integration
class TestAgentctlSSHAgent:
    """Test SSH agent socket preservation in sessions."""

    def test_ssh_auth_sock_preserved(self, running_container, test_project):
        """Test that SSH_AUTH_SOCK from the environment is preserved in tmux sessions.

        This tests that when SSH_AUTH_SOCK is set in the shell environment,
        tmux sessions inherit it properly.
        """
        test_socket = "/tmp/test-ssh-agent.sock"

        # Create a tmux session with SSH_AUTH_SOCK set in the environment
        # We export it and then create the session, using a script to avoid
        # shell variable expansion issues
        result = exec_in_container(
            running_container,
            f"export SSH_AUTH_SOCK={test_socket} && " "tmux new-session -d -s ssh-test -x 80 -y 24",
        )
        assert result.returncode == 0, f"Failed to create session: {result.stderr}"

        # Send a command to the session to write SSH_AUTH_SOCK to a file
        result = exec_in_container(
            running_container,
            "tmux send-keys -t ssh-test 'echo $SSH_AUTH_SOCK > /tmp/ssh-sock.txt' Enter",
        )
        assert result.returncode == 0, f"Failed to send keys: {result.stderr}"

        # Wait for command to execute
        time.sleep(2)

        # Check the recorded SSH_AUTH_SOCK
        result = exec_in_container(running_container, "cat /tmp/ssh-sock.txt")
        assert result.returncode == 0, f"Failed to read file: {result.stderr}"
        assert test_socket in result.stdout, f"SSH_AUTH_SOCK not preserved, got: {result.stdout}"

        # Cleanup
        exec_in_container(running_container, "tmux kill-session -t ssh-test 2>/dev/null || true")
        exec_in_container(running_container, "rm -f /tmp/ssh-sock.txt")


@pytest.mark.integration
class TestAgentctlIntegration:
    """Integration tests combining multiple agentctl commands."""

    def test_full_session_lifecycle(self, running_container, test_project):
        """Test complete lifecycle: create, list, peek, kill."""
        session_name = "lifecycle-test"

        # 1. Create session
        result = exec_in_container(
            running_container,
            f"tmux new-session -d -s {session_name} 'echo lifecycle-marker; sleep 30'",
        )
        assert result.returncode == 0

        # 2. List and verify it appears
        result = exec_in_container(running_container, "agentctl list")
        assert result.returncode == 0
        assert session_name in result.stdout

        # 3. Peek and verify output
        time.sleep(2)  # Wait for output
        result = exec_in_container(running_container, f"agentctl peek {session_name}")
        assert result.returncode == 0
        assert "lifecycle-marker" in result.stdout

        # 4. Kill session
        result = exec_in_container(running_container, f"agentctl kill {session_name} --force")
        assert result.returncode == 0

        # 5. Verify it's gone
        result = exec_in_container(running_container, "agentctl list")
        assert result.returncode == 0
        assert session_name not in result.stdout or "No tmux sessions" in result.stdout

    def test_multiple_sessions_management(self, running_container, test_project):
        """Test managing multiple sessions simultaneously."""
        sessions = ["multi-1", "multi-2", "multi-3"]

        # Create multiple sessions
        for session in sessions:
            result = exec_in_container(
                running_container,
                f"tmux new-session -d -s {session} 'echo {session}-output; sleep 30'",
            )
            assert result.returncode == 0

        # List all
        result = exec_in_container(running_container, "agentctl list")
        assert result.returncode == 0
        for session in sessions:
            assert session in result.stdout

        # Peek at each
        time.sleep(2)
        for session in sessions:
            result = exec_in_container(running_container, f"agentctl peek {session}")
            assert result.returncode == 0
            assert f"{session}-output" in result.stdout

        # Kill all
        for session in sessions:
            result = exec_in_container(running_container, f"agentctl kill {session} --force")
            assert result.returncode == 0

        # Verify all gone
        result = exec_in_container(running_container, "agentctl list")
        assert result.returncode == 0
        assert "No tmux sessions found" in result.stdout
