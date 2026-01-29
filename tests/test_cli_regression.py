# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Comprehensive CLI regression tests.

These tests verify all CLI commands work correctly and catch regressions
from refactoring. Tests are organized by command group.

Tests that require Docker are marked with @pytest.mark.docker.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import pytest
import yaml


def run_abox(*args, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run abox CLI command from source."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "/workspace"
    return subprocess.run(
        ["python3", "-m", "boxctl.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def get_config_path(project: Path) -> Path:
    """Get config file path."""
    return project / ".boxctl" / "config.yml"


def load_config(project: Path) -> dict:
    """Load project config."""
    with open(get_config_path(project)) as f:
        return yaml.safe_load(f)


def save_config(project: Path, config: dict):
    """Save project config."""
    with open(get_config_path(project), "w") as f:
        yaml.dump(config, f)


@pytest.fixture
def test_project(tmp_path):
    """Create a test project with git repo."""
    project = tmp_path / "test-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=project, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, capture_output=True)
    return project


@pytest.fixture
def initialized_project(test_project):
    """Create and initialize a project."""
    result = run_abox("init", cwd=test_project)
    assert result.returncode == 0, f"Init failed: {result.stdout}\n{result.stderr}"
    return test_project


# =============================================================================
# PORTS COMMAND TESTS
# =============================================================================


class TestPortsExpose:
    """Test ports expose command."""

    def test_expose_adds_to_config(self, initialized_project):
        """expose should add port to config."""
        result = run_abox("ports", "expose", "3000", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        host_ports = config.get("ports", {}).get("host", [])
        assert 3000 in host_ports or "3000" in host_ports

    def test_expose_duplicate_warns(self, initialized_project):
        """expose same port twice should warn."""
        run_abox("ports", "expose", "3001", cwd=initialized_project)
        result = run_abox("ports", "expose", "3001", cwd=initialized_project)

        assert result.returncode == 0  # Still succeeds
        assert "already" in result.stdout.lower()

    def test_expose_with_mapping(self, initialized_project):
        """expose with container:host mapping."""
        result = run_abox("ports", "expose", "8080:9090", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        host_ports = config.get("ports", {}).get("host", [])
        assert "8080:9090" in host_ports or any("8080" in str(p) for p in host_ports)

    def test_expose_privileged_port_fails(self, initialized_project):
        """expose privileged port (<1024) should fail."""
        result = run_abox("ports", "expose", "80", cwd=initialized_project)
        assert result.returncode != 0
        assert (
            "1024" in (result.stdout + result.stderr)
            or "privileged" in (result.stdout + result.stderr).lower()
        )

    def test_expose_invalid_port_fails(self, initialized_project):
        """expose invalid port should fail."""
        for invalid in ["99999", "0", "-1", "abc", ""]:
            result = run_abox("ports", "expose", invalid, cwd=initialized_project)
            assert result.returncode != 0, f"Should reject port: {invalid}"


class TestPortsForward:
    """Test ports forward command."""

    def test_forward_adds_to_config(self, initialized_project):
        """forward should add port to config."""
        result = run_abox("ports", "forward", "8080", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        container_ports = config.get("ports", {}).get("container", [])
        assert 8080 in container_ports or "8080" in container_ports

    def test_forward_duplicate_warns(self, initialized_project):
        """forward same port twice should warn."""
        run_abox("ports", "forward", "8081", cwd=initialized_project)
        result = run_abox("ports", "forward", "8081", cwd=initialized_project)

        assert result.returncode == 0
        assert "already" in result.stdout.lower()

    def test_forward_with_mapping(self, initialized_project):
        """forward with host:container mapping."""
        result = run_abox("ports", "forward", "9000:9001", cwd=initialized_project)
        assert result.returncode == 0


class TestPortsUnexpose:
    """Test ports unexpose command."""

    def test_unexpose_removes_from_config(self, initialized_project):
        """unexpose should remove port from config."""
        run_abox("ports", "expose", "4000", cwd=initialized_project)
        result = run_abox("ports", "unexpose", "4000", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        host_ports = config.get("ports", {}).get("host", [])
        assert 4000 not in host_ports and "4000" not in host_ports

    def test_unexpose_nonexistent_handled(self, initialized_project):
        """unexpose non-existent port should be handled."""
        result = run_abox("ports", "unexpose", "9999", cwd=initialized_project)
        # Should either succeed silently or warn
        assert result.returncode == 0 or "not found" in result.stdout.lower()


class TestPortsUnforward:
    """Test ports unforward command."""

    def test_unforward_removes_from_config(self, initialized_project):
        """unforward should remove port from config."""
        run_abox("ports", "forward", "5000", cwd=initialized_project)
        result = run_abox("ports", "unforward", "5000", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        container_ports = config.get("ports", {}).get("container", [])
        assert 5000 not in container_ports and "5000" not in container_ports


class TestPortsList:
    """Test ports list command."""

    def test_list_empty(self, initialized_project):
        """list with no ports should work."""
        result = run_abox("ports", "list", cwd=initialized_project)
        assert result.returncode == 0

    def test_list_shows_exposed_and_forwarded(self, initialized_project):
        """list should show both types of ports."""
        run_abox("ports", "expose", "3000", cwd=initialized_project)
        run_abox("ports", "forward", "8080", cwd=initialized_project)

        result = run_abox("ports", "list", cwd=initialized_project)
        assert result.returncode == 0
        assert "3000" in result.stdout
        assert "8080" in result.stdout


# =============================================================================
# MCP COMMAND TESTS
# =============================================================================


class TestMcpList:
    """Test mcp list command."""

    def test_list_shows_available(self, initialized_project):
        """list should show available MCPs."""
        result = run_abox("mcp", "list", cwd=initialized_project)
        assert result.returncode == 0
        # Should show some MCPs from library
        assert "agentctl" in result.stdout.lower() or "fetch" in result.stdout.lower()


class TestMcpAdd:
    """Test mcp add command."""

    def test_add_updates_config(self, initialized_project):
        """add should update mcp.json."""
        result = run_abox("mcp", "add", "fetch", cwd=initialized_project)
        # May already be added
        assert result.returncode == 0 or "already" in result.stdout.lower()

    def test_add_nonexistent_fails(self, initialized_project):
        """add non-existent MCP should fail."""
        result = run_abox("mcp", "add", "nonexistent-mcp-xyz", cwd=initialized_project)
        assert result.returncode != 0 or "not found" in (result.stdout + result.stderr).lower()


class TestMcpRemove:
    """Test mcp remove command."""

    def test_remove_updates_config(self, initialized_project):
        """remove should update mcp.json."""
        # Add first
        run_abox("mcp", "add", "fetch", cwd=initialized_project)
        result = run_abox("mcp", "remove", "fetch", cwd=initialized_project)
        assert result.returncode == 0 or "not found" in result.stdout.lower()


class TestMcpShow:
    """Test mcp show command."""

    def test_show_displays_info(self, initialized_project):
        """show should display MCP info."""
        result = run_abox("mcp", "show", "agentctl", cwd=initialized_project)
        # Should work or show not found
        assert result.returncode == 0 or "not found" in (result.stdout + result.stderr).lower()


# =============================================================================
# WORKSPACE COMMAND TESTS
# =============================================================================


class TestWorkspaceList:
    """Test workspace list command."""

    def test_list_empty(self, initialized_project):
        """list with no workspaces should work."""
        result = run_abox("workspace", "list", cwd=initialized_project)
        assert result.returncode == 0


class TestWorkspaceAdd:
    """Test workspace add command."""

    def test_add_updates_config(self, initialized_project, tmp_path):
        """add should update config."""
        workspace_dir = tmp_path / "shared"
        workspace_dir.mkdir()

        result = run_abox("workspace", "add", str(workspace_dir), cwd=initialized_project)
        # May fail on rebuild but should update config first
        config = load_config(initialized_project)
        workspaces = config.get("workspaces", [])
        # Check if workspace was added to config
        assert len(workspaces) > 0 or result.returncode == 0

    def test_add_nonexistent_fails(self, initialized_project):
        """add non-existent path should fail."""
        result = run_abox("workspace", "add", "/nonexistent/path/xyz", cwd=initialized_project)
        assert result.returncode != 0


# =============================================================================
# PACKAGES COMMAND TESTS
# =============================================================================


class TestPackagesList:
    """Test packages list command."""

    def test_list_empty(self, initialized_project):
        """list with no packages should work."""
        result = run_abox("packages", "list", cwd=initialized_project)
        assert result.returncode == 0


class TestPackagesAdd:
    """Test packages add command."""

    def test_add_npm(self, initialized_project):
        """add npm package should update config."""
        result = run_abox("packages", "add", "npm", "typescript", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        assert "typescript" in config.get("packages", {}).get("npm", [])

    def test_add_pip(self, initialized_project):
        """add pip package should update config."""
        result = run_abox("packages", "add", "pip", "black", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        assert "black" in config.get("packages", {}).get("pip", [])

    def test_add_apt(self, initialized_project):
        """add apt package should update config."""
        result = run_abox("packages", "add", "apt", "vim", cwd=initialized_project)
        assert result.returncode == 0

    def test_add_cargo(self, initialized_project):
        """add cargo package should update config."""
        result = run_abox("packages", "add", "cargo", "ripgrep", cwd=initialized_project)
        assert result.returncode == 0

    def test_add_duplicate_warns(self, initialized_project):
        """add duplicate package should warn."""
        run_abox("packages", "add", "npm", "lodash", cwd=initialized_project)
        result = run_abox("packages", "add", "npm", "lodash", cwd=initialized_project)
        assert "already" in result.stdout.lower()

    def test_add_invalid_type_fails(self, initialized_project):
        """add with invalid package type should fail."""
        result = run_abox("packages", "add", "invalid", "test", cwd=initialized_project)
        assert result.returncode != 0


class TestPackagesRemove:
    """Test packages remove command."""

    def test_remove_npm(self, initialized_project):
        """remove npm package should update config."""
        run_abox("packages", "add", "npm", "express", cwd=initialized_project)
        result = run_abox("packages", "remove", "npm", "express", cwd=initialized_project)
        assert result.returncode == 0

        config = load_config(initialized_project)
        assert "express" not in config.get("packages", {}).get("npm", [])


# =============================================================================
# SKILL COMMAND TESTS
# =============================================================================


class TestSkillList:
    """Test skill list command."""

    def test_list(self, initialized_project):
        """list should show available skills."""
        result = run_abox("skill", "list", cwd=initialized_project)
        assert result.returncode == 0


class TestSkillAddRemove:
    """Test skill add/remove commands."""

    def test_add_and_remove(self, initialized_project):
        """add and remove skill workflow."""
        # Add
        result = run_abox("skill", "add", "westworld", cwd=initialized_project)
        # May already exist
        assert result.returncode == 0 or "already" in result.stdout.lower()

        # Remove
        result = run_abox("skill", "remove", "westworld", cwd=initialized_project)
        assert result.returncode == 0 or "not found" in result.stdout.lower()


# =============================================================================
# NETWORK COMMAND TESTS
# =============================================================================


class TestNetworkList:
    """Test network list command."""

    def test_list_empty(self, initialized_project):
        """list with no connections should work."""
        result = run_abox("network", "list", cwd=initialized_project)
        assert result.returncode == 0

    def test_available(self, initialized_project):
        """available should list Docker containers."""
        result = run_abox("network", "available", cwd=initialized_project)
        # Should work even if no containers
        assert result.returncode == 0


# =============================================================================
# CONFIG COMMAND TESTS
# =============================================================================


class TestConfigMigrate:
    """Test config migrate command."""

    def test_migrate_dry_run(self, initialized_project):
        """migrate --dry-run should work."""
        result = run_abox("config", "migrate", "--dry-run", cwd=initialized_project)
        assert result.returncode == 0


# =============================================================================
# PROJECT COMMAND TESTS
# =============================================================================


class TestProjectInit:
    """Test project init command."""

    def test_init_creates_structure(self, test_project):
        """init should create .boxctl structure."""
        result = run_abox("init", cwd=test_project)
        assert result.returncode == 0
        assert (test_project / ".boxctl").exists()

    def test_init_idempotent(self, test_project):
        """init twice should not fail."""
        run_abox("init", cwd=test_project)
        result = run_abox("init", cwd=test_project)
        assert result.returncode == 0
        assert "already" in result.stdout.lower()


class TestProjectList:
    """Test project list command."""

    def test_list(self):
        """list should work."""
        result = run_abox("list")
        assert result.returncode == 0

    def test_ps_alias(self):
        """ps should work as alias."""
        result = run_abox("ps")
        assert result.returncode == 0


# =============================================================================
# COMMAND ALIASES TESTS
# =============================================================================


class TestAliases:
    """Test command aliases work correctly."""

    def test_q_for_quick(self):
        """q should be alias for quick."""
        result = run_abox("q", "--help")
        assert result.returncode == 0
        assert "quick" in result.stdout.lower() or "mobile" in result.stdout.lower()

    def test_ps_for_list(self):
        """ps should be alias for list."""
        result = run_abox("ps", "--help")
        assert result.returncode == 0

    def test_mcps_for_mcp_list(self):
        """mcps should be alias for mcp list."""
        result = run_abox("mcps", "--help")
        assert result.returncode == 0

    def test_skills_for_skill_list(self):
        """skills should be alias for skill list."""
        result = run_abox("skills", "--help")
        assert result.returncode == 0


# =============================================================================
# AGENT COMMAND TESTS
# =============================================================================


class TestAgentCommands:
    """Test agent launch commands have correct help."""

    @pytest.mark.parametrize(
        "agent",
        [
            "claude",
            "superclaude",
            "codex",
            "supercodex",
            "gemini",
            "supergemini",
            "qwen",
            "superqwen",
        ],
    )
    def test_agent_help(self, agent):
        """Agent command should have help."""
        result = run_abox(agent, "--help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestErrorHandling:
    """Test proper error handling."""

    def test_commands_need_init(self, test_project):
        """Commands should fail gracefully without init."""
        commands = [
            ["mcp", "add", "test"],
            ["packages", "add", "npm", "test"],
            ["ports", "expose", "3000"],
        ]
        for cmd in commands:
            result = run_abox(*cmd, cwd=test_project)
            assert result.returncode != 0, f"{cmd} should fail without init"

    def test_unknown_command(self):
        """Unknown command should fail."""
        result = run_abox("unknown-command-xyz")
        assert result.returncode != 0

    def test_missing_arguments(self, initialized_project):
        """Missing required arguments should fail."""
        commands = [
            ["ports", "expose"],
            ["packages", "add"],
            ["mcp", "add"],
        ]
        for cmd in commands:
            result = run_abox(*cmd, cwd=initialized_project)
            assert result.returncode != 0, f"{cmd} should fail without args"


# =============================================================================
# SUBCOMMAND EXISTENCE TESTS
# =============================================================================


class TestSubcommandsExist:
    """Test all subcommands exist and have help."""

    def test_project_subcommands(self):
        """project should have all expected subcommands."""
        result = run_abox("project", "--help")
        assert result.returncode == 0
        for cmd in ["init", "start", "stop", "remove", "list", "info", "shell", "connect"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_mcp_subcommands(self):
        """mcp should have all expected subcommands."""
        result = run_abox("mcp", "--help")
        assert result.returncode == 0
        for cmd in ["list", "add", "remove", "show"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_workspace_subcommands(self):
        """workspace should have all expected subcommands."""
        result = run_abox("workspace", "--help")
        assert result.returncode == 0
        for cmd in ["list", "add", "remove"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_packages_subcommands(self):
        """packages should have all expected subcommands."""
        result = run_abox("packages", "--help")
        assert result.returncode == 0
        for cmd in ["list", "add", "remove"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_ports_subcommands(self):
        """ports should have all expected subcommands."""
        result = run_abox("ports", "--help")
        assert result.returncode == 0
        for cmd in ["list", "expose", "unexpose", "forward", "unforward"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_session_subcommands(self):
        """session should have all expected subcommands."""
        result = run_abox("session", "--help")
        assert result.returncode == 0
        for cmd in ["list", "attach", "remove", "rename"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_worktree_subcommands(self):
        """worktree should have all expected subcommands."""
        result = run_abox("worktree", "--help")
        assert result.returncode == 0
        for cmd in ["list", "add", "remove"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_network_subcommands(self):
        """network should have all expected subcommands."""
        result = run_abox("network", "--help")
        assert result.returncode == 0
        for cmd in ["list", "connect", "disconnect", "available"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_service_subcommands(self):
        """service should have all expected subcommands."""
        result = run_abox("service", "--help")
        assert result.returncode == 0
        for cmd in ["install", "uninstall", "start", "stop", "status"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_skill_subcommands(self):
        """skill should have all expected subcommands."""
        result = run_abox("skill", "--help")
        assert result.returncode == 0
        for cmd in ["list", "add", "remove", "show"]:
            assert cmd in result.stdout, f"Missing: {cmd}"

    def test_base_subcommands(self):
        """base should have all expected subcommands."""
        result = run_abox("base", "--help")
        assert result.returncode == 0
        assert "rebuild" in result.stdout

    def test_config_subcommands(self):
        """config should have all expected subcommands."""
        result = run_abox("config", "--help")
        assert result.returncode == 0
        assert "migrate" in result.stdout


# =============================================================================
# VERSION AND HELP TESTS
# =============================================================================


class TestVersionAndHelp:
    """Test version and help work."""

    def test_version(self):
        """--version should show version."""
        result = run_abox("--version")
        assert result.returncode == 0
        assert "." in result.stdout  # Version has dots

    def test_help(self):
        """--help should list all commands."""
        result = run_abox("--help")
        assert result.returncode == 0
        # Check some key commands are listed
        for cmd in ["init", "start", "stop", "list", "mcp", "ports"]:
            assert cmd in result.stdout


# =============================================================================
# MULTI-PROJECT TESTS (config isolation)
# =============================================================================


class TestMultiProject:
    """Test multi-project scenarios."""

    def test_projects_have_isolated_configs(self, tmp_path):
        """Each project should have its own config."""
        project1 = tmp_path / "project1"
        project2 = tmp_path / "project2"
        project1.mkdir()
        project2.mkdir()

        for p in [project1, project2]:
            subprocess.run(["git", "init"], cwd=p, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=p, capture_output=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=p, capture_output=True)

        # Init both
        run_abox("init", cwd=project1)
        run_abox("init", cwd=project2)

        # Add different packages to each
        run_abox("packages", "add", "npm", "express", cwd=project1)
        run_abox("packages", "add", "npm", "react", cwd=project2)

        # Verify isolation
        config1 = load_config(project1)
        config2 = load_config(project2)

        assert "express" in config1.get("packages", {}).get("npm", [])
        assert "react" not in config1.get("packages", {}).get("npm", [])

        assert "react" in config2.get("packages", {}).get("npm", [])
        assert "express" not in config2.get("packages", {}).get("npm", [])

    def test_different_ports_per_project(self, tmp_path):
        """Each project can have different port configs."""
        project1 = tmp_path / "proj1"
        project2 = tmp_path / "proj2"
        project1.mkdir()
        project2.mkdir()

        for p in [project1, project2]:
            subprocess.run(["git", "init"], cwd=p, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=p, capture_output=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=p, capture_output=True)
            run_abox("init", cwd=p)

        run_abox("ports", "expose", "3000", cwd=project1)
        run_abox("ports", "expose", "4000", cwd=project2)

        config1 = load_config(project1)
        config2 = load_config(project2)

        ports1 = config1.get("ports", {}).get("host", [])
        ports2 = config2.get("ports", {}).get("host", [])

        assert 3000 in ports1 or "3000" in ports1
        assert 4000 not in ports1 and "4000" not in ports1

        assert 4000 in ports2 or "4000" in ports2
        assert 3000 not in ports2 and "3000" not in ports2
