# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests to verify that config files are actually loaded and used in containers."""

import json
import subprocess

import yaml

from tests.conftest import run_abox


def test_claude_config_mounted_in_container(test_project):
    """Test that Claude config files are mounted and accessible in container."""
    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if config files are accessible in container
    result = subprocess.run(
        ["docker", "exec", container_name, "test", "-f", "/home/abox/.claude/config.json"],
        capture_output=True,
    )

    assert (
        result.returncode == 0
    ), "Claude config.json should be accessible in container at /home/abox/.claude/config.json"


def test_claude_super_config_mounted_in_container(test_project):
    """Test that Claude super config is mounted in container."""
    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if super config is accessible
    result = subprocess.run(
        ["docker", "exec", container_name, "test", "-f", "/home/abox/.claude/config-super.json"],
        capture_output=True,
    )

    assert result.returncode == 0, "Claude config-super.json should be accessible in container"


def test_claude_mcp_config_mounted_in_container(test_project):
    """Test that Claude MCP config is mounted in container."""
    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if MCP config is accessible (now at ~/.mcp.json)
    result = subprocess.run(
        ["docker", "exec", container_name, "test", "-f", "/home/abox/.mcp.json"],
        capture_output=True,
    )

    assert result.returncode == 0, "MCP config should be accessible at /home/abox/.mcp.json"


def test_codex_config_mounted_in_container(test_project):
    """Test that Codex config is mounted in container."""
    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if Codex config is accessible (now in home directory from host mount)
    result = subprocess.run(
        ["docker", "exec", container_name, "test", "-f", "/home/abox/.codex/config.toml"],
        capture_output=True,
    )

    assert (
        result.returncode == 0
    ), "Codex config.toml should be accessible at /home/abox/.codex/config.toml"


def test_mcp_config_contains_added_server(test_project):
    """Test that adding an MCP server updates the config in container."""
    # Add an MCP server
    run_abox("mcp", "add", "fetch", cwd=test_project, check=False)

    # Start/rebuild container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Read MCP config from inside container (now at ~/.mcp.json)
    result = subprocess.run(
        ["docker", "exec", container_name, "cat", "/home/abox/.mcp.json"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Should be able to read MCP config from container"

    # Parse and verify
    mcp_config = json.loads(result.stdout)
    assert "mcpServers" in mcp_config, "MCP config should have mcpServers key"
    assert "fetch" in mcp_config["mcpServers"], "fetch MCP should be in config"


def test_workspace_mount_visible_in_container(test_project, workspace_dir):
    """Test that workspace mount is actually visible in container at /context."""
    # Create marker file
    marker_file = workspace_dir / "test_marker.txt"
    marker_content = "test_workspace_content"
    marker_file.write_text(marker_content)

    # Add workspace
    run_abox("workspace", "add", str(workspace_dir), cwd=test_project, check=False)

    # Get mount name from .boxctl.yml
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file) as f:
        config_data = yaml.safe_load(f)
    workspaces_config = config_data.get("workspaces", [])

    workspace_entry = next(
        (w for w in workspaces_config if w.get("path") == str(workspace_dir)), None
    )

    assert workspace_entry is not None, "Workspace should be in config"
    mount_name = workspace_entry.get("mount")

    # Rebuild container to apply mount
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Verify the mount is visible in container
    result = subprocess.run(
        ["docker", "exec", container_name, "cat", f"/context/{mount_name}/test_marker.txt"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Should be able to read file from /context/{mount_name}"
    assert result.stdout.strip() == marker_content, "File content should match"


def test_workspace_mount_read_only(test_project, workspace_dir):
    """Test that read-only workspace mounts are actually read-only in container."""
    # Add workspace as read-only
    run_abox("workspace", "add", str(workspace_dir), "ro", cwd=test_project, check=False)

    # Get mount name from .boxctl.yml
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file) as f:
        config_data = yaml.safe_load(f)
    workspaces_config = config_data.get("workspaces", [])

    workspace_entry = next(
        (w for w in workspaces_config if w.get("path") == str(workspace_dir)), None
    )

    mount_name = workspace_entry.get("mount")

    # Rebuild container
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Try to write to the read-only mount (should fail)
    result = subprocess.run(
        ["docker", "exec", container_name, "touch", f"/context/{mount_name}/test_write.txt"],
        capture_output=True,
        text=True,
    )

    # Should fail with permission denied or read-only filesystem error
    assert result.returncode != 0, "Writing to read-only mount should fail"
    assert (
        "read-only" in result.stderr.lower() or "permission denied" in result.stderr.lower()
    ), "Error should indicate read-only or permission issue"


def test_workspace_mount_read_write(test_project, workspace_dir):
    """Test that read-write workspace mounts allow writing in container."""
    # Add workspace as read-write
    run_abox("workspace", "add", str(workspace_dir), "rw", cwd=test_project, check=False)

    # Get mount name from .boxctl.yml
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file) as f:
        config_data = yaml.safe_load(f)
    workspaces_config = config_data.get("workspaces", [])

    workspace_entry = next(
        (w for w in workspaces_config if w.get("path") == str(workspace_dir)), None
    )

    mount_name = workspace_entry.get("mount")

    # Rebuild container
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Write to the read-write mount (should succeed)
    test_content = "rw_test_content"
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_name,
            "sh",
            "-c",
            f"echo '{test_content}' > /context/{mount_name}/test_rw.txt",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Writing to read-write mount should succeed"

    # Verify file was created on host
    test_file = workspace_dir / "test_rw.txt"
    assert test_file.exists(), "File should be created in workspace dir on host"
    assert test_content in test_file.read_text(), "File content should match"


def test_project_workspace_mounted_at_workspace(test_project):
    """Test that project directory is mounted at /workspace in container."""
    # Create marker file in project
    marker_file = test_project / "project_marker.txt"
    marker_content = "project_test"
    marker_file.write_text(marker_content)

    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Verify file is accessible at /workspace
    result = subprocess.run(
        ["docker", "exec", container_name, "cat", "/workspace/project_marker.txt"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Should be able to read project file from /workspace"
    assert result.stdout.strip() == marker_content, "File content should match"


def test_env_file_loaded_in_container(test_project):
    """Test that .env file is present and can be sourced in container.

    Note: Env vars from container-init.sh don't persist to docker exec sessions.
    This test verifies the env file is mounted and can be sourced by scripts.
    """
    # Create .env file
    env_file = test_project / ".boxctl" / ".env"
    env_file.write_text("TEST_VAR=test_value_123\n")

    # Rebuild container to pick up env
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if env file exists and can be sourced
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_name,
            "bash",
            "-c",
            "source /workspace/.boxctl/.env && echo $TEST_VAR",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Should be able to source env file"
    assert (
        "test_value_123" in result.stdout
    ), "Environment variable should be available after sourcing .env file"
