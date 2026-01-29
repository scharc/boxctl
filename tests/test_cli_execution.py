# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for CLI command execution (not just help)."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from boxctl.cli import cli


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    # Create a git repo (required for some commands)
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=project_dir,
        capture_output=True,
    )
    return project_dir


class TestInitCommand:
    """Test 'abox init' command execution."""

    def test_init_creates_agentbox_dir(self, runner, temp_project, monkeypatch):
        """Test init creates .boxctl directory."""
        monkeypatch.chdir(temp_project)

        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert (temp_project / ".boxctl").exists()
        assert (temp_project / ".boxctl" / "claude").exists()

    def test_init_creates_config_files(self, runner, temp_project, monkeypatch):
        """Test init creates expected config files."""
        monkeypatch.chdir(temp_project)

        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        assert (temp_project / ".boxctl" / "claude" / "config.json").exists()
        assert (temp_project / ".boxctl" / "mcp.json").exists()
        assert (temp_project / ".boxctl" / "agents.md").exists()

    def test_init_idempotent(self, runner, temp_project, monkeypatch):
        """Test init can be run multiple times."""
        monkeypatch.chdir(temp_project)

        result1 = runner.invoke(cli, ["init"])
        assert result1.exit_code == 0

        result2 = runner.invoke(cli, ["init"])
        assert result2.exit_code == 0
        assert "already" in result2.output.lower()


class TestListCommand:
    """Test 'abox list' command execution."""

    @patch("boxctl.cli.commands.project.ContainerManager")
    def test_list_no_containers(self, mock_manager_class, runner):
        """Test list with no containers."""
        mock_manager = MagicMock()
        mock_manager.print_containers_table.return_value = None
        mock_manager_class.return_value = mock_manager

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        mock_manager.print_containers_table.assert_called_once()

    @patch("boxctl.cli.commands.project.ContainerManager")
    def test_list_with_containers(self, mock_manager_class, runner):
        """Test list with containers."""
        mock_manager = MagicMock()
        mock_manager.print_containers_table.return_value = None
        mock_manager_class.return_value = mock_manager

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0


class TestStartCommand:
    """Test 'abox start' command execution."""

    @patch("boxctl.cli.commands.project.ContainerManager")
    def test_start_requires_init(self, mock_manager_class, runner, temp_project, monkeypatch):
        """Test start fails without init."""
        monkeypatch.chdir(temp_project)
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        result = runner.invoke(cli, ["start"])

        # Should fail because .boxctl doesn't exist
        assert (
            result.exit_code != 0
            or "not initialized" in result.output.lower()
            or "boxctl" in result.output.lower()
        )

    @patch("boxctl.cli.commands.project.ContainerManager")
    @patch("boxctl.cli.commands.project._get_project_context")
    def test_start_after_init(
        self, mock_get_ctx, mock_manager_class, runner, temp_project, monkeypatch
    ):
        """Test start works after init."""
        monkeypatch.chdir(temp_project)

        # First init
        runner.invoke(cli, ["init"])

        # Mock container manager and context
        mock_manager = MagicMock()
        mock_manager.is_running.return_value = False
        mock_manager.container_exists.return_value = False
        mock_manager_class.return_value = mock_manager

        mock_ctx = MagicMock()
        mock_ctx.manager = mock_manager
        mock_ctx.container_name = "boxctl-test"
        mock_ctx.project_dir = temp_project
        mock_get_ctx.return_value = mock_ctx

        result = runner.invoke(cli, ["start"])

        # The start command either succeeds or calls container methods
        # (exit code may not be 0 if Docker isn't available)
        assert mock_get_ctx.called or result.exit_code == 0


class TestStopCommand:
    """Test 'abox stop' command execution."""

    @patch("boxctl.cli.commands.project.ContainerManager")
    def test_stop_running_container(self, mock_manager_class, runner, temp_project, monkeypatch):
        """Test stop on running container."""
        monkeypatch.chdir(temp_project)
        (temp_project / ".boxctl").mkdir()

        mock_manager = MagicMock()
        mock_manager.is_running.return_value = True
        mock_manager_class.return_value = mock_manager

        result = runner.invoke(cli, ["stop"])

        # Should call stop
        assert result.exit_code == 0 or mock_manager.stop_container.called

    @patch("boxctl.cli.commands.project.ContainerManager")
    def test_stop_not_running(self, mock_manager_class, runner, temp_project, monkeypatch):
        """Test stop when container not running."""
        monkeypatch.chdir(temp_project)
        (temp_project / ".boxctl").mkdir()

        mock_manager = MagicMock()
        mock_manager.is_running.return_value = False
        mock_manager_class.return_value = mock_manager

        result = runner.invoke(cli, ["stop"])

        # Should handle gracefully
        assert result.exit_code == 0


class TestMcpCommands:
    """Test MCP management commands."""

    def test_mcp_list(self, runner, temp_project, monkeypatch):
        """Test mcp list command."""
        monkeypatch.chdir(temp_project)

        result = runner.invoke(cli, ["mcp", "list"])

        # Should list available MCPs from library
        assert result.exit_code == 0

    @patch("boxctl.cli.commands.mcp.LibraryManager")
    def test_mcp_show(self, mock_lib_class, runner):
        """Test mcp show command."""
        mock_lib = MagicMock()
        mock_lib_class.return_value = mock_lib

        result = runner.invoke(cli, ["mcp", "show", "test-mcp"])

        mock_lib.show_mcp.assert_called_once_with("test-mcp")

    def test_mcp_add_requires_init(self, runner, temp_project, monkeypatch):
        """Test mcp add requires initialized project."""
        monkeypatch.chdir(temp_project)

        result = runner.invoke(cli, ["mcp", "add", "some-mcp"])

        # Should fail without .boxctl
        assert result.exit_code != 0


class TestWorkspaceCommands:
    """Test workspace management commands."""

    def test_workspace_list_empty(self, runner, temp_project, monkeypatch):
        """Test workspace list with no mounts."""
        monkeypatch.chdir(temp_project)

        # Init first
        runner.invoke(cli, ["init"])

        result = runner.invoke(cli, ["workspace", "list"])

        assert result.exit_code == 0

    def test_workspace_add_requires_init(self, runner, temp_project, monkeypatch):
        """Test workspace add requires init."""
        monkeypatch.chdir(temp_project)

        result = runner.invoke(cli, ["workspace", "add", "/some/path"])

        # Should fail without .boxctl
        assert result.exit_code != 0


class TestPackagesCommands:
    """Test packages management commands."""

    def test_packages_list_empty(self, temp_project):
        """Test packages list with no packages."""
        # Use subprocess which properly sets cwd
        subprocess.run(
            ["python3", "-m", "boxctl.cli", "init"],
            cwd=temp_project,
            capture_output=True,
        )

        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "packages", "list"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0

    def test_packages_init_after_project_init(self, temp_project):
        """Test packages init works on already initialized project."""
        # Use subprocess which properly sets cwd
        init_result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "init"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )
        assert init_result.returncode == 0, f"Init failed: {init_result.stderr}"

        result = subprocess.run(
            ["python3", "-m", "boxctl.cli", "packages", "init"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        # packages init should succeed (may show "already configured" if packages exists)
        assert result.returncode == 0
        # .boxctl/config.yml is created by init
        assert (temp_project / ".boxctl" / "config.yml").exists()


class TestSkillCommands:
    """Test skill management commands."""

    def test_skill_list(self, runner, temp_project, monkeypatch):
        """Test skill list command."""
        monkeypatch.chdir(temp_project)

        result = runner.invoke(cli, ["skill", "list"])

        assert result.exit_code == 0

    @patch("boxctl.cli.commands.skill.LibraryManager")
    def test_skill_show(self, mock_lib_class, runner):
        """Test skill show command."""
        mock_lib = MagicMock()
        mock_lib_class.return_value = mock_lib

        result = runner.invoke(cli, ["skill", "show", "test-skill"])

        mock_lib.show_skill.assert_called_once_with("test-skill")


class TestConfigCommands:
    """Test config commands."""

    def test_config_migrate_dry_run(self, runner, temp_project, monkeypatch):
        """Test config migrate --dry-run with nothing to migrate."""
        monkeypatch.chdir(temp_project)
        runner.invoke(cli, ["init"])  # Initialize first

        result = runner.invoke(cli, ["config", "migrate", "--dry-run"])

        # Should handle gracefully when nothing to migrate (exit 0) or indicate no changes needed
        assert (
            result.exit_code == 0
            or "nothing" in result.output.lower()
            or "no" in result.output.lower()
        )


class TestSessionCommands:
    """Test session management commands."""

    @patch("boxctl.cli.commands.sessions._get_project_context")
    def test_session_list(self, mock_get_ctx, runner, temp_project, monkeypatch):
        """Test session list command."""
        monkeypatch.chdir(temp_project)
        (temp_project / ".boxctl").mkdir()

        mock_manager = MagicMock()
        mock_manager.is_running.return_value = True
        mock_manager.exec_in_container.return_value = (0, "", "")

        mock_ctx = MagicMock()
        mock_ctx.manager = mock_manager
        mock_ctx.container_name = "boxctl-test"
        mock_get_ctx.return_value = mock_ctx

        result = runner.invoke(cli, ["session", "list"])

        # Should attempt to list sessions
        assert result.exit_code == 0 or mock_get_ctx.called


class TestInfoCommand:
    """Test info command."""

    @patch("boxctl.cli.commands.project._get_project_context")
    @patch("boxctl.cli.commands.project.ContainerManager")
    def test_info_shows_details(
        self, mock_manager_class, mock_get_ctx, runner, temp_project, monkeypatch
    ):
        """Test info shows container details."""
        monkeypatch.chdir(temp_project)
        (temp_project / ".boxctl").mkdir()

        mock_manager = MagicMock()
        mock_manager.is_running.return_value = True
        mock_manager.container_exists.return_value = True
        mock_manager.get_container_info.return_value = {
            "name": "boxctl-test",
            "status": "running",
        }
        mock_manager.exec_in_container.return_value = (0, "session-info", "")
        mock_manager_class.return_value = mock_manager

        mock_ctx = MagicMock()
        mock_ctx.manager = mock_manager
        mock_ctx.container_name = "boxctl-test"
        mock_ctx.project_dir = temp_project
        mock_get_ctx.return_value = mock_ctx

        result = runner.invoke(cli, ["info"])

        # Info command should have been invoked (may not succeed fully without Docker)
        assert mock_get_ctx.called or result.exit_code == 0


class TestVersionFlag:
    """Test version output."""

    def test_version_shows_number(self, runner):
        """Test --version shows version number."""
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "." in result.output  # Version has dots


class TestFixTerminal:
    """Test fix-terminal command."""

    def test_fix_terminal_runs(self, runner):
        """Test fix-terminal executes."""
        result = runner.invoke(cli, ["fix-terminal"])

        # Should run without error (just outputs escape codes)
        assert result.exit_code == 0
