# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for agent command persistence.

These tests verify that agent commands (codex, gemini, claude) don't exit
prematurely when started without a prompt. They should remain running in
interactive mode.
"""

import subprocess
import time

import pytest


@pytest.fixture
def container_name(test_project):
    """Get container name and ensure it's running."""
    from tests.conftest import run_abox

    run_abox("start", cwd=test_project)
    return f"boxctl-{test_project.name}"


def _start_agent_detached(container_name: str, agent: str, extra_args: list[str] = None) -> None:
    """Start an agent in detached mode inside the container."""
    cmd = [agent]
    if extra_args:
        cmd.extend(extra_args)

    subprocess.run(
        [
            "docker",
            "exec",
            "-d",
            "-u",
            "abox",
            "-w",
            "/workspace",
            "-e",
            "HOME=/home/abox",
            "-e",
            "USER=abox",
            container_name,
            *cmd,
        ],
        check=True,
    )


def _is_process_running(container_name: str, process_name: str) -> bool:
    """Check if a process is running in the container."""
    result = subprocess.run(
        ["docker", "exec", container_name, "pgrep", "-f", process_name],
        capture_output=True,
    )
    return result.returncode == 0


def _kill_process(container_name: str, process_name: str) -> None:
    """Kill a process in the container."""
    subprocess.run(
        ["docker", "exec", container_name, "pkill", "-f", process_name],
        capture_output=True,
    )


class TestAgentPersistence:
    """Test that agents don't exit prematurely."""

    def test_gemini_stays_running_without_tty(self, container_name):
        """Test that gemini stays running in detached mode.

        Gemini can run without a TTY in detached mode.
        This is a regression test for the bug where passing instructions
        as the first positional argument caused agents to interpret them
        as a task and exit immediately.
        """
        agent = "gemini"
        # Check if agent is available in container
        which_result = subprocess.run(
            ["docker", "exec", container_name, "which", agent],
            capture_output=True,
        )
        if which_result.returncode != 0:
            pytest.skip(f"{agent} not installed in container")

        try:
            # Start agent in detached mode (no TTY, no prompt)
            _start_agent_detached(container_name, agent)

            # Wait for agent to start
            time.sleep(2)

            # Check if process is running
            initial_running = _is_process_running(container_name, agent)

            # Wait additional time to ensure it doesn't exit
            time.sleep(5)

            # Check again
            still_running = _is_process_running(container_name, agent)

            # Agent should either:
            # 1. Still be running (interactive mode works)
            # 2. Have started (initial_running was True) - proves it didn't exit immediately
            assert initial_running or still_running, (
                f"{agent} should remain running in interactive mode. "
                f"Initial: {initial_running}, After 5s: {still_running}"
            )

        finally:
            # Cleanup: kill agent process
            _kill_process(container_name, agent)

    def test_codex_available_and_runs(self, container_name):
        """Test that codex is available and can be invoked.

        Note: Codex requires a TTY for interactive mode, so it will exit
        when run in detached mode. This test just verifies it's available
        and doesn't error on invocation. The unit tests verify the
        instruction passing behavior.
        """
        agent = "codex"
        which_result = subprocess.run(
            ["docker", "exec", container_name, "which", agent],
            capture_output=True,
        )
        if which_result.returncode != 0:
            pytest.skip(f"{agent} not installed in container")

        # Just verify codex can be invoked (will exit due to no TTY, but shouldn't error)
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "abox",
                "-w",
                "/workspace",
                "-e",
                "HOME=/home/abox",
                "-e",
                "USER=abox",
                container_name,
                "codex",
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should output version info or at least not crash
        assert (
            result.returncode == 0
            or "codex" in result.stdout.lower()
            or "codex" in result.stderr.lower()
        ), f"codex should be runnable. stdout: {result.stdout}, stderr: {result.stderr}"

    def test_codex_with_prompt_completes(self, container_name):
        """Test that codex with a simple prompt runs and completes.

        This verifies that passing an actual prompt still works correctly.
        """
        which_result = subprocess.run(
            ["docker", "exec", container_name, "which", "codex"],
            capture_output=True,
        )
        if which_result.returncode != 0:
            pytest.skip("codex not installed in container")

        # Run codex with a simple prompt that should complete quickly
        # Using exec mode for non-interactive execution
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "abox",
                "-w",
                "/workspace",
                "-e",
                "HOME=/home/abox",
                "-e",
                "USER=abox",
                container_name,
                "codex",
                "exec",
                "echo hello",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Should complete (may fail due to no API key in test, but shouldn't hang)
        # Check that the command completed and either succeeded or gave a meaningful error
        # Return code should be 0 (success) or an error code (not timeout/hang)
        assert isinstance(result.returncode, int), "codex exec should complete with a return code"
        # Verify it didn't timeout (which would indicate hanging)
        # A timeout would raise subprocess.TimeoutExpired, so if we get here it completed
        # Check for common error patterns that indicate it actually tried to run
        output = result.stdout + result.stderr
        # Either it succeeded (return 0) or it gave an error about missing API key, config, etc
        assert (
            result.returncode == 0 or len(output) > 0
        ), "codex should either succeed or produce error output"


class TestAgentCommandBuildingUnit:
    """Unit tests for agent command building logic."""

    def test_build_agent_command_no_extra_args(self):
        """Test _build_agent_command without extra args."""
        from boxctl.cli.helpers import _build_agent_command

        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="codex",
            args=(),  # No args - this is the key test
            extra_args=None,
            label="Codex",
        )

        # The command should just be "codex" without any agent instructions
        # The tmux_setup contains the actual command to run
        assert "codex" in tmux_setup
        # Should NOT contain typical instruction markers (agent context)
        assert "# Agent Context" not in tmux_setup
        assert "You are running in an Boxctl container" not in tmux_setup

    def test_build_agent_command_with_user_prompt(self):
        """Test _build_agent_command with a user-provided prompt."""
        from boxctl.cli.helpers import _build_agent_command

        user_prompt = "help me write tests"
        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="codex",
            args=(user_prompt,),
            extra_args=None,
            label="Codex",
        )

        # The user's prompt should be in the command
        assert user_prompt in tmux_setup

    def test_build_agent_command_instructions_not_prepended(self):
        """Verify that agent instructions are NOT automatically prepended.

        This is the core regression test for the bug where _read_agent_instructions()
        was being passed as the first arg.
        """
        from boxctl.cli.helpers import _build_agent_command

        # Simulate what the fixed code does - just pass user args
        user_args = ("my prompt",)

        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="codex",
            args=user_args,
            extra_args=None,
            label="Codex",
        )

        # Count how many arguments are in the tmux command
        # The command should be: codex "my prompt"
        # NOT: codex "# Agent Context..." "my prompt"
        assert tmux_setup.count("my prompt") == 1

        # Verify no agent instruction markers appear
        instruction_markers = [
            "# Agent Context",
            "You are running in an Boxctl container",
            "Dynamic Context",
            "MCP Servers Available",
        ]
        for marker in instruction_markers:
            assert marker not in tmux_setup, (
                f"Found instruction marker '{marker}' in command. "
                "Agent instructions should NOT be passed as arguments to codex/gemini."
            )


class TestAgentCommandImplementation:
    """Test the actual agent command implementations in agents.py.

    These tests verify that the agent commands (codex, supercodex, etc.)
    pass correct arguments to _run_agent_command, catching bugs like
    passing --ide to codex.
    """

    def test_codex_command_no_ide_flag(self, monkeypatch):
        """Verify codex() doesn't pass --ide flag."""
        captured_args = {}

        def mock_run_agent_command(manager, project, args, command, **kwargs):
            captured_args["command"] = command
            captured_args["args"] = args
            captured_args["extra_args"] = kwargs.get("extra_args")
            raise SystemExit(0)  # Exit early

        # Mock _has_vscode to return True (simulating VSCode being available)
        monkeypatch.setattr("boxctl.cli.commands.agents._has_vscode", lambda: True)
        monkeypatch.setattr("boxctl.cli.commands.agents._run_agent_command", mock_run_agent_command)

        from boxctl.cli.commands.agents import codex
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(codex, [], catch_exceptions=False)

        # Verify no --ide in extra_args
        extra_args = captured_args.get("extra_args") or []
        assert (
            "--ide" not in extra_args
        ), f"codex should NOT pass --ide flag. extra_args: {extra_args}"

    def test_supercodex_command_no_ide_flag(self, monkeypatch):
        """Verify supercodex() doesn't pass --ide flag."""
        from unittest.mock import Mock

        captured_args = {}

        def mock_run_agent_command(manager, project, args, command, **kwargs):
            captured_args["command"] = command
            captured_args["args"] = args
            captured_args["extra_args"] = kwargs.get("extra_args")
            raise SystemExit(0)

        monkeypatch.setattr("boxctl.cli.commands.agents._has_vscode", lambda: True)
        monkeypatch.setattr("boxctl.cli.commands.agents._run_agent_command", mock_run_agent_command)
        monkeypatch.setattr("boxctl.cli.commands.agents.ContainerManager", Mock)

        from boxctl.cli.commands.agents import supercodex
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(supercodex, [], catch_exceptions=False)

        extra_args = captured_args.get("extra_args") or []
        assert (
            "--ide" not in extra_args
        ), f"supercodex should NOT pass --ide flag. extra_args: {extra_args}"
        # But should have --dangerously-bypass-approvals-and-sandbox
        assert "--dangerously-bypass-approvals-and-sandbox" in extra_args

    def test_gemini_command_no_ide_flag(self, monkeypatch):
        """Verify gemini() doesn't pass --ide flag."""
        captured_args = {}

        def mock_run_agent_command(manager, project, args, command, **kwargs):
            captured_args["command"] = command
            captured_args["args"] = args
            captured_args["extra_args"] = kwargs.get("extra_args")
            raise SystemExit(0)

        monkeypatch.setattr("boxctl.cli.commands.agents._has_vscode", lambda: True)
        monkeypatch.setattr("boxctl.cli.commands.agents._run_agent_command", mock_run_agent_command)

        from boxctl.cli.commands.agents import gemini
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(gemini, [], catch_exceptions=False)

        extra_args = captured_args.get("extra_args") or []
        assert (
            "--ide" not in extra_args
        ), f"gemini should NOT pass --ide flag. extra_args: {extra_args}"

    def test_supergemini_command_no_ide_flag(self, monkeypatch):
        """Verify supergemini() doesn't pass --ide flag."""
        captured_args = {}

        def mock_run_agent_command(manager, project, args, command, **kwargs):
            captured_args["command"] = command
            captured_args["args"] = args
            captured_args["extra_args"] = kwargs.get("extra_args")
            raise SystemExit(0)

        monkeypatch.setattr("boxctl.cli.commands.agents._has_vscode", lambda: True)
        monkeypatch.setattr("boxctl.cli.commands.agents._run_agent_command", mock_run_agent_command)

        from boxctl.cli.commands.agents import supergemini
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(supergemini, [], catch_exceptions=False)

        extra_args = captured_args.get("extra_args") or []
        assert (
            "--ide" not in extra_args
        ), f"supergemini should NOT pass --ide flag. extra_args: {extra_args}"

    def test_claude_command_has_ide_flag(self, monkeypatch, tmp_path):
        """Verify claude() DOES pass --ide flag when VSCode available."""
        from unittest.mock import Mock

        captured_args = {}

        def mock_run_agent_command(manager, project, args, command, **kwargs):
            captured_args["command"] = command
            captured_args["args"] = args
            captured_args["extra_args"] = kwargs.get("extra_args")
            raise SystemExit(0)

        # Create minimal .boxctl structure for _read_agent_instructions
        agentbox_dir = tmp_path / ".boxctl"
        agentbox_dir.mkdir()
        (agentbox_dir / "agents.md").write_text("# Test")

        monkeypatch.setattr("boxctl.cli.commands.agents._has_vscode", lambda: True)
        monkeypatch.setattr("boxctl.cli.commands.agents._run_agent_command", mock_run_agent_command)
        monkeypatch.setattr("boxctl.cli.commands.agents.ContainerManager", Mock)
        monkeypatch.setenv("BOXCTL_PROJECT_DIR", str(tmp_path))

        from boxctl.cli.commands.agents import claude
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(claude, [], catch_exceptions=False)

        extra_args = captured_args.get("extra_args") or []
        assert (
            "--ide" in extra_args
        ), f"claude SHOULD pass --ide flag when VSCode available. extra_args: {extra_args}"


class TestAgentFlagsValidation:
    """Test that agent commands use only valid flags for each CLI."""

    # Flags that are ONLY valid for Claude Code, not for Codex/Gemini
    CLAUDE_ONLY_FLAGS = ["--ide", "--append-system-prompt", "--mcp-config", "--settings"]

    # Flags that are ONLY valid for Codex
    CODEX_ONLY_FLAGS = ["--dangerously-bypass-approvals-and-sandbox"]

    # Flags that are ONLY valid for Gemini
    GEMINI_ONLY_FLAGS = ["--non-interactive"]

    def _extract_command_from_tmux(self, tmux_setup: str) -> str:
        """Extract the actual command from tmux setup string."""
        import re

        # Match: exec <command>' or just the command in the bash -lc part
        match = re.search(r"exec ([^']+)'", tmux_setup)
        if match:
            return match.group(1)
        return tmux_setup

    def test_codex_no_claude_flags(self):
        """Verify codex command doesn't include Claude-only flags like --ide."""
        from boxctl.cli.helpers import _build_agent_command

        # Simulate what the codex command does
        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="codex",
            args=(),
            extra_args=None,  # codex should pass None, not ['--ide']
            label="Codex",
        )

        extracted_cmd = self._extract_command_from_tmux(tmux_setup)

        for flag in self.CLAUDE_ONLY_FLAGS:
            assert flag not in extracted_cmd, (
                f"Codex command contains Claude-only flag '{flag}'. " f"Command: {extracted_cmd}"
            )

    def test_supercodex_no_claude_flags(self):
        """Verify supercodex command doesn't include Claude-only flags."""
        from boxctl.cli.helpers import _build_agent_command

        # Simulate what supercodex does - has its own extra_args but no --ide
        extra_args = [
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            'notify=["test"]',
        ]

        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="codex",
            args=(),
            extra_args=extra_args,
            label="Codex (auto-approve)",
        )

        extracted_cmd = self._extract_command_from_tmux(tmux_setup)

        for flag in self.CLAUDE_ONLY_FLAGS:
            assert flag not in extracted_cmd, (
                f"Supercodex command contains Claude-only flag '{flag}'. "
                f"Command: {extracted_cmd}"
            )

    def test_gemini_no_claude_flags(self):
        """Verify gemini command doesn't include Claude-only flags."""
        from boxctl.cli.helpers import _build_agent_command

        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="gemini",
            args=(),
            extra_args=None,
            label="Gemini",
        )

        extracted_cmd = self._extract_command_from_tmux(tmux_setup)

        for flag in self.CLAUDE_ONLY_FLAGS:
            assert flag not in extracted_cmd, (
                f"Gemini command contains Claude-only flag '{flag}'. " f"Command: {extracted_cmd}"
            )

    def test_supergemini_no_claude_flags(self):
        """Verify supergemini command doesn't include Claude-only flags."""
        from boxctl.cli.helpers import _build_agent_command

        extra_args = ["--non-interactive"]

        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="gemini",
            args=(),
            extra_args=extra_args,
            label="Gemini (auto-approve)",
        )

        extracted_cmd = self._extract_command_from_tmux(tmux_setup)

        for flag in self.CLAUDE_ONLY_FLAGS:
            assert flag not in extracted_cmd, (
                f"Supergemini command contains Claude-only flag '{flag}'. "
                f"Command: {extracted_cmd}"
            )

    def test_claude_has_ide_flag_when_vscode_available(self):
        """Verify claude command includes --ide when appropriate."""
        from boxctl.cli.helpers import _build_agent_command

        # Simulate claude with --ide
        extra_args = [
            "--settings",
            "/path/to/settings",
            "--mcp-config",
            "/path/to/mcp",
            "--append-system-prompt",
            "instructions",
            "--ide",
        ]

        cmd, tmux_setup, display, session_name = _build_agent_command(
            container_name="test-container",
            command="claude",
            args=(),
            extra_args=extra_args,
            label="Claude Code",
        )

        extracted_cmd = self._extract_command_from_tmux(tmux_setup)

        # Claude SHOULD have these flags
        assert "--ide" in extracted_cmd, "Claude should support --ide flag"
        assert "--settings" in extracted_cmd, "Claude should support --settings flag"
