# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for MCP management commands (list, add, remove)."""

import json
import subprocess
import pytest
from tests.conftest import run_abox


def test_mcp_list_shows_library(test_project):
    """Test that 'abox mcp list' shows available MCPs from library."""
    result = run_abox("mcp", "list", cwd=test_project)

    assert result.returncode == 0, "abox mcp list should succeed"

    # Check that output has table structure (not specific MCPs)
    output = result.stdout
    # Should have headers or meaningful content (more than just empty/error message)
    assert len(output) > 100, "Output should have substantial content"
    # Should have table-like structure or list format
    assert (
        "name" in output.lower() or "mcp" in output.lower() or "\n" in output
    ), "Output should be formatted (table or list)"


def test_mcp_add_creates_config(test_project):
    """Test that 'abox mcp add' adds MCP to unified config."""
    # MCP is now stored in unified .boxctl/mcp.json (not per-agent)
    mcp_file = test_project / ".boxctl" / "mcp.json"
    mcp_meta_file = test_project / ".boxctl" / "mcp-meta.json"

    # Add an MCP (using fetch - simple, no install requirements, no credentials needed)
    result = run_abox("mcp", "add", "fetch", cwd=test_project, check=False)

    # Should succeed (or warn if already exists)
    assert (
        result.returncode == 0 or "already" in result.stdout.lower()
    ), "abox mcp add should succeed or warn if exists"

    # Check mcp.json was created/updated
    assert mcp_file.exists(), "mcp.json should exist after adding MCP"

    with open(mcp_file) as f:
        mcp_config = json.load(f)

    assert "mcpServers" in mcp_config, "mcp.json should have mcpServers"
    assert "fetch" in mcp_config["mcpServers"], "fetch should be in mcpServers"

    # Check mcp-meta.json if it exists (fetch doesn't have install requirements)
    if mcp_meta_file.exists():
        with open(mcp_meta_file) as f:
            meta_config = json.load(f)
        assert isinstance(meta_config, dict), "mcp-meta.json should be valid JSON"


def test_mcp_add_triggers_rebuild(test_project):
    """Test that adding an MCP with install requirements triggers container rebuild."""
    # Start container first
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Get container created timestamp before add
    created_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Created}}", container_name],
        capture_output=True,
        text=True,
    )
    assert created_result.returncode == 0, f"Container {container_name} should exist"
    original_created = created_result.stdout.strip()

    # Check if docker MCP is already added (from previous tests due to module-scoped fixture)
    mcp_file = test_project / ".boxctl" / "mcp.json"
    if mcp_file.exists():
        with open(mcp_file) as f:
            existing_config = json.load(f)
        if "docker" in existing_config.get("mcpServers", {}):
            # Remove it first to ensure we can test the add behavior
            run_abox("mcp", "remove", "docker", cwd=test_project, check=False)
            import time

            time.sleep(2)
            # Get new timestamp after removal rebuild
            created_result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Created}}", container_name],
                capture_output=True,
                text=True,
            )
            original_created = created_result.stdout.strip()

    # Add MCP with install requirements (docker MCP has install requirements)
    # This should trigger rebuild
    run_abox("mcp", "add", "docker", cwd=test_project, check=False)

    # Wait a moment for rebuild to complete
    import time

    time.sleep(2)

    # Container should have been rebuilt (new creation time)
    new_created_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Created}}", container_name],
        capture_output=True,
        text=True,
    )

    assert new_created_result.returncode == 0, "Container should still exist after MCP add"
    new_created = new_created_result.stdout.strip()

    # Creation time should be different (container was rebuilt)
    assert new_created != original_created, (
        f"Container should be rebuilt when adding MCP with install requirements. "
        f"Original: {original_created}, New: {new_created}"
    )


def test_mcp_remove_cleans_config(test_project):
    """Test that 'abox mcp remove' removes MCP from config."""
    mcp_file = test_project / ".boxctl" / "mcp.json"

    # Add MCP first (use sqlite to avoid conflicts with other tests)
    run_abox("mcp", "add", "sqlite", cwd=test_project, check=False)

    # Verify it was added
    with open(mcp_file) as f:
        mcp_config = json.load(f)
    assert "sqlite" in mcp_config.get("mcpServers", {}), "sqlite should be added"

    # Remove the MCP
    result = run_abox("mcp", "remove", "sqlite", cwd=test_project, check=False)

    # Should succeed
    assert result.returncode == 0, "abox mcp remove should succeed"

    # Verify it was removed
    with open(mcp_file) as f:
        mcp_config = json.load(f)

    assert "sqlite" not in mcp_config.get(
        "mcpServers", {}
    ), "sqlite should be removed from mcpServers"


# Package installation tests have been moved to tests/dind/test_mcp_packages.py
# since they require real Docker container access to verify package installation
