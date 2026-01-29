# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Chain tests for MCP configuration persistence."""

import json
import pytest

from helpers.cli import run_abox
from helpers.docker import (
    exec_in_container,
    wait_for_container_ready,
)


@pytest.mark.chain
class TestMCPPersistence:
    """Test MCP configuration persists across operations."""

    def test_mcp_config_persists_after_rebuild(self, test_project):
        """Test MCP config survives container rebuild."""
        container_name = f"boxctl-{test_project.name}"

        # 1. Add MCP (use litellm which is available in library)
        result = run_abox("mcp", "add", "litellm", cwd=test_project)
        assert result.returncode == 0, f"Failed to add MCP: {result.stderr}"

        # Verify MCP was added to config (now at .boxctl/mcp.json)
        mcp_file = test_project / ".boxctl" / "mcp.json"
        assert mcp_file.exists(), f"MCP config not found at {mcp_file}"

        with open(mcp_file) as f:
            config = json.load(f)
        assert "litellm" in config.get("mcpServers", {})

        # 2. Start container
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        # 3. Rebuild container
        result = run_abox("rebuild", cwd=test_project, timeout=180)
        assert result.returncode == 0, f"Rebuild failed: {result.stderr}"

        wait_for_container_ready(container_name)

        # 4. Verify MCP config still exists
        with open(mcp_file) as f:
            config_after = json.load(f)
        assert "litellm" in config_after.get("mcpServers", {})

        # 5. Verify MCP config is visible in container (now at ~/.mcp.json)
        result = exec_in_container(
            container_name,
            "cat /home/abox/.mcp.json",
        )
        assert result.returncode == 0
        assert "litellm" in result.stdout

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_multiple_mcps_persist(self, test_project):
        """Test multiple MCPs persist correctly."""
        container_name = f"boxctl-{test_project.name}"

        # Add multiple MCPs (use available MCPs from library)
        mcps = ["litellm", "boxctl-analyst"]
        for mcp in mcps:
            result = run_abox("mcp", "add", mcp, cwd=test_project)
            # May already exist, that's fine
            assert result.returncode == 0 or "already" in result.stdout.lower()

        # Verify all MCPs in config (stored in mcp.json on host)
        mcp_file = test_project / ".boxctl" / "mcp.json"
        with open(mcp_file) as f:
            config = json.load(f)

        for mcp in mcps:
            assert mcp in config.get("mcpServers", {}), f"MCP {mcp} not in config"

        # Start and verify (deployed to ~/.mcp.json in container)
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        result = exec_in_container(
            container_name,
            "cat /home/abox/.mcp.json",
        )
        for mcp in mcps:
            assert mcp in result.stdout, f"MCP {mcp} not visible in container"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_mcp_remove_cleans_config(self, test_project):
        """Test MCP removal cleans configuration."""
        # Add MCP first (use available MCP from library)
        run_abox("mcp", "add", "litellm", cwd=test_project)

        mcp_file = test_project / ".boxctl" / "mcp.json"
        with open(mcp_file) as f:
            config = json.load(f)
        assert "litellm" in config.get("mcpServers", {})

        # Remove MCP
        result = run_abox("mcp", "remove", "litellm", cwd=test_project)
        assert result.returncode == 0

        # Verify removed from config
        with open(mcp_file) as f:
            config_after = json.load(f)
        assert "litellm" not in config_after.get("mcpServers", {})


@pytest.mark.chain
class TestMCPInWorktree:
    """Test MCP configuration in worktrees."""

    def test_mcp_available_in_worktree(self, test_project, fake_git_repo):
        """Test MCP is available when using worktree."""
        import shutil

        container_name = f"boxctl-{test_project.name}"

        # Copy fake git repo content to test project
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name)
                else:
                    shutil.copy2(item, test_project / item.name)

        # 1. Add MCP to main project (use available MCP from library)
        result = run_abox("mcp", "add", "litellm", cwd=test_project)
        assert result.returncode == 0 or "already" in result.stdout.lower()

        # 2. Start container
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        # 3. Create worktree using boxctl command
        result = run_abox("worktree", "add", "feature-1", cwd=test_project)
        # May need to handle if branch doesn't exist
        if result.returncode != 0:
            # Try creating branch first
            exec_in_container(
                container_name,
                "cd /workspace && git branch feature-1 2>/dev/null || true",
            )
            result = run_abox("worktree", "add", "feature-1", cwd=test_project)

        # 4. Verify worktree was actually created
        result = exec_in_container(
            container_name,
            "ls -la /git-worktrees/",
        )
        assert result.returncode == 0, f"Failed to list worktrees: {result.stderr}"
        assert "worktree-feature-1" in result.stdout, (
            f"Worktree 'worktree-feature-1' not found in /git-worktrees/. "
            f"Contents: {result.stdout}"
        )

        # 5. Verify MCP config is accessible (now in home directory)
        # MCP config is at ~/.mcp.json in the new architecture
        result = exec_in_container(
            container_name,
            "cat /home/abox/.mcp.json",
        )
        assert result.returncode == 0, f"MCP config not accessible: {result.stderr}"
        assert (
            "litellm" in result.stdout
        ), f"MCP 'litellm' not in config at ~/.mcp.json. Got: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)
