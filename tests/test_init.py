# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for 'abox init' command."""

import json
from pathlib import Path
from tests.conftest import run_abox


def test_init_creates_boxctl_dir(test_project):
    """Test that 'abox init' creates .boxctl/ with correct structure."""
    boxctl_dir = test_project / ".boxctl"

    assert boxctl_dir.exists(), ".boxctl directory should exist"
    assert boxctl_dir.is_dir(), ".boxctl should be a directory"

    # Check for expected subdirectories created by init
    assert (boxctl_dir / "mcp").exists(), ".boxctl/mcp should exist"
    assert (boxctl_dir / "skills").exists(), ".boxctl/skills should exist"

    # Note: claude/, codex/, gemini/, qwen/ are created at container startup
    # mcp.json is at root level (unified for all agents)
    assert (boxctl_dir / "mcp.json").exists(), ".boxctl/mcp.json should exist"

    # Check for other expected files
    assert (boxctl_dir / "config.yml").exists(), ".boxctl/config.yml should exist"
    assert (boxctl_dir / "agents.md").exists(), ".boxctl/agents.md should exist"
    assert (boxctl_dir / "superagents.md").exists(), ".boxctl/superagents.md should exist"


def test_init_creates_mcp_directory(test_project):
    """Test that 'abox init' copies MCP servers to .boxctl/mcp/."""
    mcp_dir = test_project / ".boxctl" / "mcp"

    assert mcp_dir.exists(), ".boxctl/mcp should exist"
    assert mcp_dir.is_dir(), ".boxctl/mcp should be a directory"

    # Check for expected MCP servers (from library)
    assert (mcp_dir / "agentctl").exists(), "agentctl MCP should be copied"
    assert (mcp_dir / "boxctl-analyst").exists(), "boxctl-analyst MCP should be copied"


def test_init_creates_unified_mcp(test_project):
    """Test that 'abox init' creates unified mcp.json at root level."""
    boxctl_dir = test_project / ".boxctl"
    mcp_file = boxctl_dir / "mcp.json"

    assert mcp_file.exists(), "mcp.json should exist at root"

    with open(mcp_file) as f:
        mcp_config = json.load(f)
    assert isinstance(mcp_config, dict), "mcp.json should be valid JSON"
    assert "mcpServers" in mcp_config, "mcp.json should have mcpServers key"


def test_init_idempotent(tmp_path, docker_available):
    """Test that running 'abox init' twice doesn't break things."""
    # Run init first time
    result1 = run_abox("init", cwd=tmp_path)
    assert result1.returncode == 0, "First init should succeed"

    boxctl_dir = tmp_path / ".boxctl"
    assert boxctl_dir.exists(), ".boxctl should exist after first init"

    # Run init second time
    result2 = run_abox("init", cwd=tmp_path, check=False)

    # Should succeed idempotently (may show warning but still returns 0)
    assert (
        result2.returncode == 0
    ), f"Second init should succeed idempotently. stderr: {result2.stderr}"

    # Should show warning about already existing
    assert (
        "already" in result2.stdout.lower()
    ), "Second init should warn that directory already exists"

    # Directory should still exist
    assert boxctl_dir.exists(), ".boxctl should still exist after second init"
