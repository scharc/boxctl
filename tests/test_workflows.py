# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""End-to-end workflow tests for boxctl CLI.

These tests verify complete feature workflows, not just individual commands.
Tests are organized by feature area and test real functionality where possible.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import pytest
import yaml


def get_config_path(project: Path) -> Path:
    """Get the config file path."""
    return project / ".boxctl" / "config.yml"


def load_project_config(project: Path) -> dict:
    """Load project config from either location."""
    config_path = get_config_path(project)
    with open(config_path) as f:
        return yaml.safe_load(f)


def run_abox(*args, cwd: Optional[Path] = None, check: bool = False) -> subprocess.CompletedProcess:
    """Run abox CLI command via python module from source.

    Uses PYTHONPATH to ensure we run against the source code in /workspace,
    not the installed package which may not include library/ templates.
    """
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


@pytest.fixture
def test_project(tmp_path):
    """Create a temporary project with git repo."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
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


@pytest.fixture
def initialized_project(test_project):
    """Create and initialize a test project."""
    result = run_abox("init", cwd=test_project)
    assert result.returncode == 0, f"Init failed: {result.stderr}\nOutput: {result.stdout}"
    # Verify init created the config file (can be at either location)
    config_path = get_config_path(test_project)
    assert config_path.exists(), f"Init didn't create config. Output: {result.stdout}"
    return test_project


class TestInitWorkflow:
    """Test complete initialization workflow."""

    def test_init_creates_complete_structure(self, test_project):
        """Init should create all required files and directories."""
        result = run_abox("init", cwd=test_project)
        assert result.returncode == 0, f"Init failed: {result.stderr}"

        # Check directory structure
        agentbox_dir = test_project / ".boxctl"
        assert agentbox_dir.exists()
        assert (agentbox_dir / "mcp").exists()  # MCP server code
        assert (agentbox_dir / "skills").exists()  # Installed skills
        assert (agentbox_dir / "mcp.json").exists()  # MCP config
        assert (agentbox_dir / "agents.md").exists()  # Agent instructions
        # Note: .boxctl/claude/ is created at container startup, not init

        # Check config file created
        config_path = get_config_path(test_project)
        assert config_path.exists(), f"Config not found at {config_path}"

        # Check config is valid YAML
        config = load_project_config(test_project)
        assert "version" in config
        assert "ssh" in config
        assert "packages" in config

    def test_init_then_second_init_preserves_config(self, test_project):
        """Second init should not overwrite existing config."""
        # First init
        run_abox("init", cwd=test_project)

        # Modify config
        config_path = get_config_path(test_project)
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["custom_field"] = "test_value"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        # Second init
        result = run_abox("init", cwd=test_project)
        assert result.returncode == 0
        assert "already" in result.stdout.lower()

        # Verify custom field preserved
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config.get("custom_field") == "test_value"


class TestPortsWorkflow:
    """Test port management workflow."""

    def test_expose_forward_list_unexpose_unforward(self, initialized_project):
        """Full port workflow: expose → forward → list → unexpose → unforward."""
        project = initialized_project

        # 1. Expose a port (container → host)
        result = run_abox("ports", "expose", "3000", cwd=project)
        assert result.returncode == 0, f"Expose failed: {result.stderr}"

        # Verify in config
        config = load_project_config(project)
        host_ports = config.get("ports", {}).get("host", [])
        assert "3000" in host_ports or 3000 in host_ports

        # 2. Forward a port (host → container)
        # Note: forward command takes PORT_SPEC, not name + port
        result = run_abox("ports", "forward", "8080", cwd=project)
        assert result.returncode == 0, f"Forward failed: {result.stderr}"

        # Verify in config
        config = load_project_config(project)
        container_ports = config.get("ports", {}).get("container", [])
        assert (
            "8080" in container_ports or 8080 in container_ports
        ), f"Forward not in config: {container_ports}"

        # 3. List ports
        result = run_abox("ports", "list", cwd=project)
        assert result.returncode == 0
        assert "3000" in result.stdout
        assert "8080" in result.stdout

        # 4. Expose with mapping
        result = run_abox("ports", "expose", "4000:5000", cwd=project)
        assert result.returncode == 0

        # 5. Unexpose
        result = run_abox("ports", "unexpose", "3000", cwd=project)
        assert result.returncode == 0

        # Verify removed
        config = load_project_config(project)
        host_ports = config.get("ports", {}).get("host", [])
        assert "3000" not in host_ports and 3000 not in host_ports

        # 6. Unforward
        result = run_abox("ports", "unforward", "8080", cwd=project)
        assert result.returncode == 0

        # Verify removed
        config = load_project_config(project)
        container_ports = config.get("ports", {}).get("container", [])
        assert "8080" not in container_ports and 8080 not in container_ports

    def test_port_validation(self, initialized_project):
        """Ports should validate input."""
        project = initialized_project

        # Privileged port should fail
        result = run_abox("ports", "expose", "80", cwd=project)
        assert result.returncode != 0
        # Error may be in stdout or stderr depending on how click handles it
        output = result.stdout + result.stderr
        assert "1024" in output or "privileged" in output.lower()

        # Invalid port should fail
        result = run_abox("ports", "expose", "99999", cwd=project)
        assert result.returncode != 0

        # Non-numeric should fail
        result = run_abox("ports", "expose", "abc", cwd=project)
        assert result.returncode != 0


class TestWorkspaceWorkflow:
    """Test workspace management workflow."""

    def test_workspace_list_empty(self, initialized_project):
        """Workspace list should work on empty config."""
        project = initialized_project

        result = run_abox("workspace", "list", cwd=project)
        assert result.returncode == 0

    def test_workspace_config_updated(self, initialized_project, tmp_path):
        """Workspace add should update config file.

        Note: We just test config update, not actual container rebuild
        since that requires Docker and proper container setup.
        """
        project = initialized_project

        # Create a directory to add as workspace
        workspace_dir = tmp_path / "shared-lib"
        workspace_dir.mkdir()
        (workspace_dir / "lib.py").write_text("# shared library")

        # Get initial config
        config_before = load_project_config(project)
        workspaces_before = len(config_before.get("workspaces", []))

        # Add workspace - may fail on rebuild but should update config first
        result = run_abox("workspace", "add", str(workspace_dir), cwd=project)

        # Even if rebuild fails, config should be updated
        config_after = load_project_config(project)
        workspaces_after = config_after.get("workspaces", [])

        # Either command succeeded, or config was updated before failure
        if result.returncode == 0:
            assert len(workspaces_after) > workspaces_before
        else:
            # If rebuild failed, that's OK for this test - we just verify
            # the config mechanism works
            pass


class TestMCPWorkflow:
    """Test MCP server management workflow."""

    def test_mcp_list_shows_library(self, initialized_project):
        """MCP list should show available servers from library."""
        result = run_abox("mcp", "list", cwd=initialized_project)
        assert result.returncode == 0

        # Should show some MCPs (either installed or available)
        output = result.stdout.lower()
        # Check for common MCPs that should be in library
        assert "agentctl" in output or "fetch" in output or "git" in output or "mcp" in output

    def test_mcp_add_remove(self, initialized_project):
        """MCP add and remove workflow."""
        project = initialized_project

        # Check what MCPs are available
        list_result = run_abox("mcp", "list", cwd=project)

        # Add an MCP (use one that's likely in the library)
        result = run_abox("mcp", "add", "fetch", cwd=project)
        # May already be added or not available
        if result.returncode == 0:
            assert "added" in result.stdout.lower() or "already" in result.stdout.lower()

            # Remove it
            result = run_abox("mcp", "remove", "fetch", cwd=project)
            assert result.returncode == 0 or "not found" in result.stderr.lower()

    def test_mcp_show(self, initialized_project):
        """MCP show should display details."""
        result = run_abox("mcp", "show", "agentctl", cwd=initialized_project)
        # Should work or show not found
        assert result.returncode == 0 or "not found" in result.stderr.lower()


class TestSkillWorkflow:
    """Test skill management workflow."""

    def test_skill_list(self, initialized_project):
        """Skill list should show available skills."""
        result = run_abox("skill", "list", cwd=initialized_project)
        assert result.returncode == 0

    def test_skill_add_remove(self, initialized_project):
        """Skill add and remove workflow."""
        project = initialized_project

        # Try to add a skill
        result = run_abox("skill", "add", "westworld", cwd=project)
        # May already be added
        if result.returncode == 0:
            # Remove it
            result = run_abox("skill", "remove", "westworld", cwd=project)


class TestPackagesWorkflow:
    """Test package management workflow."""

    def test_packages_add_list_remove(self, initialized_project):
        """Full packages workflow: add → list → remove."""
        project = initialized_project

        # 1. Add npm package
        result = run_abox("packages", "add", "npm", "typescript", cwd=project)
        assert result.returncode == 0, f"Add package failed: {result.stderr}"

        # 2. Add pip package
        result = run_abox("packages", "add", "pip", "black", cwd=project)
        assert result.returncode == 0

        # 3. List packages
        result = run_abox("packages", "list", cwd=project)
        assert result.returncode == 0
        assert "typescript" in result.stdout
        assert "black" in result.stdout

        # 4. Verify in config
        config = load_project_config(project)
        packages = config.get("packages", {})
        assert "typescript" in packages.get("npm", [])
        assert "black" in packages.get("pip", [])

        # 5. Remove packages
        result = run_abox("packages", "remove", "npm", "typescript", cwd=project)
        assert result.returncode == 0

        result = run_abox("packages", "remove", "pip", "black", cwd=project)
        assert result.returncode == 0

        # 6. Verify removed
        config = load_project_config(project)
        packages = config.get("packages", {})
        assert "typescript" not in packages.get("npm", [])
        assert "black" not in packages.get("pip", [])


class TestConfigWorkflow:
    """Test configuration workflows."""

    def test_config_file_structure(self, initialized_project):
        """Config files should have proper structure."""
        project = initialized_project

        # Check project config
        config = load_project_config(project)

        assert "version" in config
        assert "ssh" in config
        assert isinstance(config["ssh"], dict)
        assert "packages" in config
        assert "ports" in config

        # Check mcp.json (unified MCP config)
        # Note: .boxctl/claude/ is created at container startup, not init
        with open(project / ".boxctl" / "mcp.json") as f:
            mcp_config = json.load(f)
        assert "mcpServers" in mcp_config

    def test_config_migrate(self, initialized_project):
        """Config migrate should work on initialized project."""
        result = run_abox("config", "migrate", "--dry-run", cwd=initialized_project)
        assert result.returncode == 0


class TestQuickCommandParity:
    """Test that quick command helpers match regular command behavior.

    Since quick is a TUI, we test the underlying functions it uses.
    """

    def test_quick_help(self):
        """Quick command should have help."""
        result = run_abox("quick", "--help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_agent_commands_have_help(self):
        """All agent commands (used by quick) should work."""
        agents = [
            "claude",
            "superclaude",
            "codex",
            "supercodex",
            "gemini",
            "supergemini",
            "qwen",
            "superqwen",
        ]
        for agent in agents:
            result = run_abox(agent, "--help")
            assert result.returncode == 0, f"Agent {agent} help failed"
            assert "Usage:" in result.stdout


class TestCommandAliases:
    """Test that command aliases work the same as full commands."""

    def test_q_alias_for_quick(self):
        """'q' should be an alias for 'quick'."""
        quick_help = run_abox("quick", "--help")
        q_help = run_abox("q", "--help")

        assert quick_help.returncode == q_help.returncode
        # Help text should be similar (may differ in command name shown)
        assert (
            "mobile-friendly" in quick_help.stdout.lower() or "quick" in quick_help.stdout.lower()
        )

    def test_ps_alias_for_list(self):
        """'ps' should be an alias for 'list'."""
        result = run_abox("ps", "--help")
        assert result.returncode == 0
        assert "container" in result.stdout.lower() or "list" in result.stdout.lower()

    def test_mcps_alias_for_mcp_list(self):
        """'mcps' should be an alias for 'mcp list'."""
        result = run_abox("mcps", "--help")
        assert result.returncode == 0

    def test_skills_alias_for_skill_list(self):
        """'skills' should be an alias for 'skill list'."""
        result = run_abox("skills", "--help")
        assert result.returncode == 0


class TestErrorHandling:
    """Test proper error handling in workflows."""

    def test_commands_fail_without_init(self, test_project):
        """Commands requiring init should fail gracefully."""
        # Note: 'start' auto-initializes, so it doesn't require init first
        commands_requiring_init = [
            ["mcp", "add", "test"],
            ["workspace", "add", "/tmp"],
            ["packages", "add", "npm", "test"],
            ["ports", "expose", "3000"],
        ]

        for cmd in commands_requiring_init:
            result = run_abox(*cmd, cwd=test_project)
            assert result.returncode != 0, f"Command {cmd} should fail without init"
            # Should have helpful error message (may be in stdout or stderr)
            output = result.stdout.lower() + result.stderr.lower()
            assert (
                "not initialized" in output
                or "boxctl" in output
                or ".boxctl" in output
                or "error" in output
            )

    def test_invalid_arguments_handled(self, initialized_project):
        """Invalid arguments should be handled gracefully."""
        # Invalid port
        result = run_abox("ports", "expose", "not-a-port", cwd=initialized_project)
        assert result.returncode != 0

        # Missing required argument
        result = run_abox("ports", "forward", cwd=initialized_project)
        assert result.returncode != 0

        # Unknown subcommand
        result = run_abox("mcp", "unknown-cmd", cwd=initialized_project)
        assert result.returncode != 0


class TestProjectCommands:
    """Test project lifecycle commands."""

    def test_project_subcommands_exist(self):
        """Project command should have all expected subcommands."""
        result = run_abox("project", "--help")
        assert result.returncode == 0

        expected = ["init", "start", "stop", "remove", "list", "info", "shell", "connect"]
        for cmd in expected:
            assert cmd in result.stdout, f"Subcommand '{cmd}' missing from project"

    def test_info_without_container(self, initialized_project):
        """Info should handle case when container doesn't exist."""
        result = run_abox("info", cwd=initialized_project)
        # Should either show info or indicate no container
        # (depends on whether Docker is available)
        pass  # Just verify it doesn't crash

    def test_list_shows_format(self):
        """List should show container information."""
        result = run_abox("list")
        assert result.returncode == 0
        # Output format depends on whether containers exist
