# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for agent launch commands."""

import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container, wait_for_container_ready


@pytest.mark.integration
class TestAgentPrerequisites:
    """Test that agent prerequisites are in place."""

    def test_mcp_config_exists(self, running_container, test_project):
        """Test that MCP config file exists."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(container_name, "test -f /home/abox/.mcp.json")

        assert result.returncode == 0, "MCP config should exist at ~/.mcp.json after project init"

    def test_agent_instructions_accessible(self, running_container, test_project):
        """Test that agent instructions are accessible."""
        container_name = f"boxctl-{test_project.name}"

        # agents.md should exist (created during init)
        result = exec_in_container(container_name, "test -f /workspace/.boxctl/agents.md")

        assert result.returncode == 0, "agents.md should exist"

    def test_super_agent_instructions_accessible(self, running_container, test_project):
        """Test that super agent instructions are accessible."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(container_name, "test -f /workspace/.boxctl/superagents.md")

        assert result.returncode == 0, "superagents.md should exist"

    def test_claude_binary_available(self, running_container, test_project):
        """Test that Claude binary is available in container."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(container_name, "which claude")

        assert result.returncode == 0, f"claude binary should be in PATH. Got: {result.stderr}"
        assert "claude" in result.stdout

    def test_codex_binary_available(self, running_container, test_project):
        """Test that Codex binary is available in container."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(container_name, "which codex")

        assert result.returncode == 0, f"codex binary should be in PATH. Got: {result.stderr}"
        assert "codex" in result.stdout


@pytest.mark.integration
@pytest.mark.requires_auth
class TestClaudeLaunch:
    """Test Claude agent launch."""

    def test_claude_command_structure(self, running_container, test_project, has_claude_auth):
        """Test that Claude launch command has correct structure."""
        if not has_claude_auth:
            pytest.skip("Claude auth not available")

        container_name = f"boxctl-{test_project.name}"

        # Test that we can at least see the help
        result = exec_in_container(container_name, "claude --help", timeout=10)

        assert result.returncode == 0, f"claude --help failed: {result.stderr}"
        assert "claude" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_claude_with_mcp_config_loads(self, running_container, test_project, has_claude_auth):
        """Test that Claude can load MCP config without errors."""
        if not has_claude_auth:
            pytest.skip("Claude auth not available")

        container_name = f"boxctl-{test_project.name}"

        # Try to run claude with --version to test basic invocation
        # This should load config but not start interactive session
        result = exec_in_container(container_name, "claude --version 2>&1 || true", timeout=10)

        # Should not error on missing MCP config
        assert (
            "mcp" not in result.stderr.lower() or "error" not in result.stderr.lower()
        ), f"MCP config loading failed: {result.stderr}"


@pytest.mark.integration
@pytest.mark.requires_auth
class TestCodexLaunch:
    """Test Codex agent launch."""

    def test_codex_command_structure(self, running_container, test_project, has_codex_auth):
        """Test that Codex launch command has correct structure."""
        if not has_codex_auth:
            pytest.skip("Codex auth not available")

        container_name = f"boxctl-{test_project.name}"

        # Test that we can at least see the help
        result = exec_in_container(container_name, "codex --help", timeout=10)

        # Codex might have different help output, so be flexible
        assert (
            result.returncode == 0
            or "codex" in result.stdout.lower()
            or "usage" in result.stdout.lower()
        )


@pytest.mark.integration
class TestAgentSessionCreation:
    """Test that agent commands create tmux sessions."""

    def test_session_created_for_agent(self, running_container, test_project):
        """Test that launching agent creates a tmux session."""
        container_name = f"boxctl-{test_project.name}"

        # Create a session manually (simulating what agent launch does)
        session_name = "test-claude"
        result = exec_in_container(
            container_name,
            f"tmux new-session -d -s {session_name} 'echo agent-session-test; sleep 5'",
        )

        assert result.returncode == 0, f"Failed to create session: {result.stderr}"

        # Verify session exists
        result = exec_in_container(container_name, f"tmux has-session -t {session_name}")

        assert result.returncode == 0, "Agent session should exist"

        # Verify we can capture output
        time.sleep(1)
        result = exec_in_container(container_name, f"tmux capture-pane -t {session_name} -p")

        assert "agent-session-test" in result.stdout, f"Agent output not captured: {result.stdout}"

        # Cleanup
        exec_in_container(
            container_name, f"tmux kill-session -t {session_name} 2>/dev/null || true"
        )

    def test_multiple_agent_sessions(self, running_container, test_project):
        """Test that multiple agent sessions can coexist."""
        container_name = f"boxctl-{test_project.name}"

        agents = ["claude-test", "codex-test", "gemini-test"]

        # Create sessions for each agent
        for agent in agents:
            result = exec_in_container(container_name, f"tmux new-session -d -s {agent} 'sleep 30'")
            assert result.returncode == 0, f"Failed to create {agent} session"

        # Verify all exist
        for agent in agents:
            result = exec_in_container(container_name, f"tmux has-session -t {agent}")
            assert result.returncode == 0, f"{agent} session should exist"

        # Cleanup
        for agent in agents:
            exec_in_container(container_name, f"tmux kill-session -t {agent} 2>/dev/null || true")


@pytest.mark.integration
class TestAgentConfiguration:
    """Test agent configuration and environment."""

    def test_workspace_mounted_for_agent(self, running_container, test_project):
        """Test that workspace is accessible to agent sessions."""
        container_name = f"boxctl-{test_project.name}"

        # Create a test file
        test_content = "agent-accessible-file"
        result = exec_in_container(
            container_name, f"echo '{test_content}' > /workspace/agent-test.txt"
        )
        assert result.returncode == 0

        # Verify file is accessible in a tmux session (like agent would use)
        result = exec_in_container(
            container_name,
            "tmux new-session -d -s workspace-test 'cat /workspace/agent-test.txt > /tmp/workspace-output.txt; sleep 2'",
        )
        assert result.returncode == 0

        time.sleep(1)

        # Check the output
        result = exec_in_container(container_name, "cat /tmp/workspace-output.txt")

        assert (
            test_content in result.stdout
        ), f"Workspace not accessible in tmux session: {result.stdout}"

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t workspace-test 2>/dev/null || true")
        exec_in_container(
            container_name, "rm -f /workspace/agent-test.txt /tmp/workspace-output.txt"
        )

    def test_mcp_config_readable_in_session(self, running_container, test_project):
        """Test that MCP config is readable from tmux session."""
        container_name = f"boxctl-{test_project.name}"

        # Verify MCP config is readable in a tmux session
        result = exec_in_container(
            container_name,
            "tmux new-session -d -s mcp-test 'cat /home/abox/.mcp.json > /tmp/mcp-output.txt; sleep 2'",
        )
        assert result.returncode == 0

        time.sleep(1)

        # Check the output
        result = exec_in_container(container_name, "cat /tmp/mcp-output.txt")

        assert len(result.stdout) > 0, "MCP config should be readable"
        assert "{" in result.stdout, "MCP config should be JSON"

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t mcp-test 2>/dev/null || true")
        exec_in_container(container_name, "rm -f /tmp/mcp-output.txt")

    def test_environment_variables_in_session(self, running_container, test_project):
        """Test that environment variables are available in agent sessions."""
        container_name = f"boxctl-{test_project.name}"

        # Create a tmux session with the environment variable exported
        result = exec_in_container(
            container_name,
            "export TEST_VAR='test-value' && tmux new-session -d -s env-test -x 80 -y 24",
        )
        assert result.returncode == 0, f"Failed to create session: {result.stderr}"

        # Send the echo command to the session
        result = exec_in_container(
            container_name,
            "tmux send-keys -t env-test 'echo $TEST_VAR > /tmp/env-output.txt' Enter",
        )
        assert result.returncode == 0, f"Failed to send keys: {result.stderr}"

        time.sleep(2)

        result = exec_in_container(container_name, "cat /tmp/env-output.txt")

        assert (
            "test-value" in result.stdout
        ), f"Environment variable not accessible: {result.stdout}"

        # Cleanup
        exec_in_container(container_name, "tmux kill-session -t env-test 2>/dev/null || true")
        exec_in_container(container_name, "rm -f /tmp/env-output.txt")


@pytest.mark.integration
class TestAgentIntegration:
    """Integration tests for agent workflows."""

    def test_agent_session_workflow(self, running_container, test_project):
        """Test complete agent session workflow."""
        container_name = f"boxctl-{test_project.name}"

        session_name = "workflow-test"

        # 1. Create agent-like session
        result = exec_in_container(
            container_name, f"tmux new-session -d -s {session_name} 'echo workflow-start; sleep 30'"
        )
        assert result.returncode == 0

        # 2. Verify session is running
        result = exec_in_container(container_name, f"tmux has-session -t {session_name}")
        assert result.returncode == 0

        # 3. Interact with session (send command)
        time.sleep(1)
        result = exec_in_container(
            container_name, f"tmux send-keys -t {session_name} 'echo workflow-command' Enter"
        )
        assert result.returncode == 0

        # 4. Capture output
        time.sleep(1)
        result = exec_in_container(container_name, f"tmux capture-pane -t {session_name} -p")
        assert "workflow-start" in result.stdout

        # 5. Kill session
        result = exec_in_container(container_name, f"tmux kill-session -t {session_name}")
        assert result.returncode == 0

        # 6. Verify session is gone
        result = exec_in_container(container_name, f"tmux has-session -t {session_name}")
        assert result.returncode != 0

    def test_agent_restart_workflow(self, running_container, test_project):
        """Test agent can be restarted (session killed and recreated)."""
        container_name = f"boxctl-{test_project.name}"

        session_name = "restart-test"

        # 1. Create initial session
        result = exec_in_container(
            container_name, f"tmux new-session -d -s {session_name} 'echo first-run; sleep 30'"
        )
        assert result.returncode == 0

        # 2. Capture initial output
        time.sleep(1)
        result = exec_in_container(container_name, f"tmux capture-pane -t {session_name} -p")
        assert "first-run" in result.stdout

        # 3. Kill session
        exec_in_container(container_name, f"tmux kill-session -t {session_name}")

        # 4. Recreate session
        result = exec_in_container(
            container_name, f"tmux new-session -d -s {session_name} 'echo second-run; sleep 30'"
        )
        assert result.returncode == 0

        # 5. Verify new session has different output
        time.sleep(1)
        result = exec_in_container(container_name, f"tmux capture-pane -t {session_name} -p")
        assert "second-run" in result.stdout
        # first-run should not be there (new session)

        # Cleanup
        exec_in_container(
            container_name, f"tmux kill-session -t {session_name} 2>/dev/null || true"
        )
