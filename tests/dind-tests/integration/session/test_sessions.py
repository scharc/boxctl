# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for tmux session management."""

import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container


@pytest.mark.integration
class TestSessionManagement:
    """Validate session list/rename/remove flows without interactive attach."""

    def test_session_list_empty(self, running_container, test_project):
        result = run_abox("session", "list", cwd=test_project)
        assert result.returncode == 0, f"session list failed: {result.stderr}"
        assert (
            "No tmux sessions found" in result.stdout
        ), f"expected empty session message. stdout: {result.stdout}"

    def test_session_rename_and_remove(self, running_container, test_project):
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(container_name, "tmux new-session -d -s shell-test 'sleep 60'")
        assert result.returncode == 0, f"failed to create tmux session: {result.stderr}"

        result = run_abox("session", "list", cwd=test_project)
        assert result.returncode == 0, f"session list failed: {result.stderr}"
        assert "shell-test" in result.stdout, f"created session not listed. stdout: {result.stdout}"

        result = run_abox("session", "rename", "shell-test", "renamed", cwd=test_project)
        assert result.returncode == 0, f"session rename failed: {result.stderr}"

        result = run_abox("session", "list", cwd=test_project)
        assert (
            "shell-renamed" in result.stdout
        ), f"renamed session not listed. stdout: {result.stdout}"

        result = run_abox("session", "remove", "shell-renamed", cwd=test_project)
        assert result.returncode == 0, f"session remove failed: {result.stderr}"

        result = exec_in_container(container_name, "tmux has-session -t shell-renamed")
        assert result.returncode != 0, "session still exists after remove"


@pytest.mark.integration
class TestSessionCreation:
    """Test session creation with different configurations."""

    def test_session_new_requires_initialization(self, tmp_path):
        """Test that session new fails in un-initialized directory."""
        # Run in an empty directory (not initialized)
        result = run_abox("session", "new", "shell", cwd=tmp_path)

        # Should fail with initialization error
        assert result.returncode != 0, "session new should fail in un-initialized directory"
        assert (
            "not initialized" in result.stdout or "not initialized" in result.stderr
        ), f"Should show initialization error. stdout: {result.stdout}, stderr: {result.stderr}"

    def test_session_new_creates_session(self, running_container, test_project):
        """Test creating a new session."""
        result = run_abox("session", "new", "shell", "test-session", cwd=test_project)

        assert result.returncode == 0, f"session new failed: {result.stderr}"

        # Verify session exists
        result = run_abox("session", "list", cwd=test_project)
        assert "shell-test-session" in result.stdout, "Session should be listed"

        # Cleanup
        run_abox("session", "remove", "shell-test-session", cwd=test_project)

    def test_session_new_with_agent_prefix(self, running_container, test_project):
        """Test session naming follows agent prefix convention."""
        container_name = f"boxctl-{test_project.name}"

        # Create session with agent-style naming
        result = exec_in_container(container_name, "tmux new-session -d -s claude-test 'sleep 30'")
        assert result.returncode == 0

        result = run_abox("session", "list", cwd=test_project)
        assert "claude-test" in result.stdout or "claude" in result.stdout

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t claude-test 2>/dev/null || true")

    def test_multiple_sessions_different_agents(self, running_container, test_project):
        """Test creating multiple sessions for different agents."""
        container_name = f"boxctl-{test_project.name}"

        agents = ["claude", "codex", "gemini", "shell"]

        # Create sessions for different agents
        for agent in agents:
            result = exec_in_container(
                container_name, f"tmux new-session -d -s {agent}-test 'sleep 30'"
            )
            assert result.returncode == 0, f"Failed to create {agent} session"

        # List and verify all sessions
        result = run_abox("session", "list", cwd=test_project)
        assert result.returncode == 0

        for agent in agents:
            assert agent in result.stdout, f"{agent} session not in list"

        # Cleanup
        for agent in agents:
            exec_in_container(
                container_name, f"tmux kill-session -t {agent}-test 2>/dev/null || true"
            )


@pytest.mark.integration
class TestSessionRemoval:
    """Test session removal and cleanup."""

    def test_remove_session_with_running_process(self, running_container, test_project):
        """Test removing session with active process."""
        container_name = f"boxctl-{test_project.name}"

        # Create session with long-running process
        result = exec_in_container(
            container_name, "tmux new-session -d -s long-running 'sleep 300'"
        )
        assert result.returncode == 0

        # Verify session is running
        result = exec_in_container(container_name, "tmux has-session -t long-running")
        assert result.returncode == 0

        # Remove session
        result = run_abox("session", "remove", "long-running", cwd=test_project)
        assert result.returncode == 0, f"session remove failed: {result.stderr}"

        # Verify session is gone
        result = exec_in_container(container_name, "tmux has-session -t long-running")
        assert result.returncode != 0, "Session should be removed"

    def test_remove_nonexistent_session(self, running_container, test_project):
        """Test removing non-existent session fails gracefully."""
        result = run_abox("session", "remove", "nonexistent-session", cwd=test_project)

        # Should fail or warn
        assert (
            result.returncode != 0
            or "not found" in result.stdout.lower()
            or "not found" in result.stderr.lower()
        ), f"Should handle non-existent session gracefully"

    def test_remove_all_sessions(self, running_container, test_project):
        """Test removing multiple sessions."""
        container_name = f"boxctl-{test_project.name}"

        # Create multiple sessions
        sessions = ["session-1", "session-2", "session-3"]
        for session in sessions:
            exec_in_container(container_name, f"tmux new-session -d -s {session} 'sleep 30'")

        # Remove all sessions
        for session in sessions:
            result = run_abox("session", "remove", session, cwd=test_project)
            assert result.returncode == 0, f"Failed to remove {session}"

        # Verify all gone
        result = run_abox("session", "list", cwd=test_project)
        assert "No tmux sessions found" in result.stdout


@pytest.mark.integration
class TestSessionRename:
    """Test session renaming functionality."""

    def test_rename_basic(self, running_container, test_project):
        """Test basic session rename."""
        container_name = f"boxctl-{test_project.name}"

        # Create session
        exec_in_container(container_name, "tmux new-session -d -s old-name 'sleep 30'")

        # Rename
        result = run_abox("session", "rename", "old-name", "new-name", cwd=test_project)
        assert result.returncode == 0, f"rename failed: {result.stderr}"

        # Verify new name exists
        result = exec_in_container(container_name, "tmux has-session -t shell-new-name")
        assert result.returncode == 0, "Renamed session should exist"

        # Verify old name gone
        result = exec_in_container(container_name, "tmux has-session -t old-name")
        assert result.returncode != 0, "Old session name should be gone"

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t shell-new-name 2>/dev/null || true")

    def test_rename_to_existing_name_fails(self, running_container, test_project):
        """Test renaming to existing session name fails."""
        container_name = f"boxctl-{test_project.name}"

        # Create two sessions
        exec_in_container(container_name, "tmux new-session -d -s session-a 'sleep 30'")
        exec_in_container(container_name, "tmux new-session -d -s session-b 'sleep 30'")

        # Try to rename session-a to session-b
        result = run_abox("session", "rename", "session-a", "session-b", cwd=test_project)

        # Should fail
        assert result.returncode != 0, "Should fail when renaming to existing name"

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t session-a 2>/dev/null || true")
        exec_in_container(
            container_name, "tmux kill-session -t shell-session-b 2>/dev/null || true"
        )

    def test_rename_nonexistent_session(self, running_container, test_project):
        """Test renaming non-existent session fails."""
        result = run_abox("session", "rename", "nonexistent", "new-name", cwd=test_project)

        assert result.returncode != 0, "Should fail for non-existent session"


@pytest.mark.integration
class TestSessionAttach:
    """Test session attach behavior (non-interactive tests)."""

    def test_attach_command_available(self, running_container, test_project):
        """Test that attach command exists."""
        # Note: We can't test interactive attach, but we can verify the command exists
        result = run_abox("session", "attach", "--help", cwd=test_project)

        # Should show help or at least not error completely
        assert "attach" in result.stdout.lower() or result.returncode == 0


@pytest.mark.integration
class TestSessionIntegration:
    """Integration tests for complete session workflows."""

    def test_session_full_lifecycle(self, running_container, test_project):
        """Test complete session lifecycle."""
        container_name = f"boxctl-{test_project.name}"

        session_name = "lifecycle-test"

        # 1. Create session
        exec_in_container(
            container_name, f"tmux new-session -d -s {session_name} 'echo marker; sleep 30'"
        )

        # 2. List and verify
        result = run_abox("session", "list", cwd=test_project)
        assert session_name in result.stdout

        # 3. Rename
        result = run_abox("session", "rename", session_name, "renamed", cwd=test_project)
        assert result.returncode == 0

        # 4. Verify rename
        result = run_abox("session", "list", cwd=test_project)
        assert "renamed" in result.stdout

        # 5. Remove
        result = run_abox("session", "remove", "shell-renamed", cwd=test_project)
        assert result.returncode == 0

        # 6. Verify removal
        result = run_abox("session", "list", cwd=test_project)
        assert "No tmux sessions found" in result.stdout or "renamed" not in result.stdout

    def test_multiple_operations_on_same_session(self, running_container, test_project):
        """Test multiple operations on the same session."""
        container_name = f"boxctl-{test_project.name}"

        # Create session
        exec_in_container(container_name, "tmux new-session -d -s multi-op 'sleep 60'")

        # Multiple list operations
        for _ in range(3):
            result = run_abox("session", "list", cwd=test_project)
            assert result.returncode == 0
            assert "multi-op" in result.stdout
            time.sleep(0.5)

        # Rename
        result = run_abox("session", "rename", "multi-op", "renamed-multi", cwd=test_project)
        assert result.returncode == 0

        # More list operations
        for _ in range(3):
            result = run_abox("session", "list", cwd=test_project)
            assert result.returncode == 0
            assert "renamed-multi" in result.stdout
            time.sleep(0.5)

        # Cleanup
        run_abox("session", "remove", "shell-renamed-multi", cwd=test_project)

    def test_sessions_persist_across_docker_exec(self, running_container, test_project):
        """Test that sessions persist across multiple docker exec calls."""
        container_name = f"boxctl-{test_project.name}"

        # Create session in first exec
        result = exec_in_container(container_name, "tmux new-session -d -s persist-test 'sleep 60'")
        assert result.returncode == 0

        # Verify in second exec
        result = exec_in_container(container_name, "tmux has-session -t persist-test")
        assert result.returncode == 0

        # List in third exec (via abox)
        result = run_abox("session", "list", cwd=test_project)
        assert "persist-test" in result.stdout

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t persist-test 2>/dev/null || true")
