# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests that all CLI commands exist and have proper help."""

import subprocess
import pytest


# All top-level commands from 'boxctl --help'
ALL_COMMANDS = [
    "base",
    "claude",
    "cleanup",
    "codex",
    "config",
    "connect",
    "devices",
    "docker",
    "fix-terminal",
    "gemini",
    "info",
    "init",
    "list",
    "mcp",
    "mcps",
    "network",
    "packages",
    "ports",
    "project",
    "ps",
    "q",
    "quick",
    "qwen",
    "rebase",
    "rebuild",
    "reconfigure",
    "remove",
    "service",
    "session",
    "setup",
    "shell",
    "skill",
    "skills",
    "start",
    "stop",
    "superclaude",
    "supercodex",
    "supergemini",
    "superqwen",
    "workspace",
    "worktree",
]


class TestCLICommandsExist:
    """Test that all CLI commands exist and respond to --help."""

    @pytest.mark.parametrize("command", ALL_COMMANDS)
    def test_command_has_help(self, command):
        """Test that command exists and has help text."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", command, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Command '{command}' failed: {result.stderr}"
        assert (
            "Usage:" in result.stdout or "usage:" in result.stdout.lower()
        ), f"Command '{command}' has no usage text"


class TestCLIMainHelp:
    """Test main CLI help."""

    def test_main_help_lists_all_commands(self):
        """Test that main --help lists all expected commands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Main help failed: {result.stderr}"

        # Check that all commands are listed
        for command in ALL_COMMANDS:
            assert command in result.stdout, f"Command '{command}' not listed in main help"

    def test_version_flag(self):
        """Test --version flag works."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Version failed: {result.stderr}"
        # Should contain version number pattern
        assert "." in result.stdout, "Version should contain dots"


class TestCLISubcommands:
    """Test that command groups have expected subcommands."""

    def test_project_subcommands(self):
        """Test project command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "project", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["init", "start", "stop", "remove", "list", "info", "shell", "connect"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"project subcommand '{subcmd}' missing"

    def test_mcp_subcommands(self):
        """Test mcp command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "mcp", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "add", "remove", "show", "manage"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"mcp subcommand '{subcmd}' missing"

    def test_workspace_subcommands(self):
        """Test workspace command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "workspace", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "add", "remove"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"workspace subcommand '{subcmd}' missing"

    def test_packages_subcommands(self):
        """Test packages command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "packages", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "add", "remove", "init"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"packages subcommand '{subcmd}' missing"

    def test_service_subcommands(self):
        """Test service command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "service", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["install", "uninstall", "start", "stop", "status", "logs"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"service subcommand '{subcmd}' missing"

    def test_base_subcommands(self):
        """Test base command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "base", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["rebuild"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"base subcommand '{subcmd}' missing"

    def test_session_subcommands(self):
        """Test session command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "session", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "attach", "remove", "rename"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"session subcommand '{subcmd}' missing"

    def test_worktree_subcommands(self):
        """Test worktree command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "worktree", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "add", "remove"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"worktree subcommand '{subcmd}' missing"

    def test_skill_subcommands(self):
        """Test skill command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "skill", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "add", "remove", "show"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"skill subcommand '{subcmd}' missing"

    def test_ports_subcommands(self):
        """Test ports command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "ports", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["list", "expose", "unexpose", "forward", "unforward"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"ports subcommand '{subcmd}' missing"

    def test_config_subcommands(self):
        """Test config command has expected subcommands."""
        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "config", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        expected = ["migrate"]
        for subcmd in expected:
            assert subcmd in result.stdout, f"config subcommand '{subcmd}' missing"
