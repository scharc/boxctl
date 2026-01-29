# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for workspace management commands (list, add, remove)."""

import subprocess

import yaml

from tests.conftest import run_abox


def test_workspace_add_creates_config(test_project, workspace_dir):
    """Test that 'abox workspace add' creates config entry in .boxctl.yml."""
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)

    # Create a test file in workspace dir to mount
    test_file = workspace_dir / "test.txt"
    test_file.write_text("test content")

    # Add workspace
    result = run_abox("workspace", "add", str(workspace_dir), cwd=test_project, check=False)

    # Should succeed
    assert result.returncode == 0, "abox workspace add should succeed"

    # Check .boxctl.yml was created/updated
    assert config_file.exists(), ".boxctl.yml should exist after adding workspace"

    with open(config_file) as f:
        config_data = yaml.safe_load(f)

    assert isinstance(config_data, dict), ".boxctl.yml should be a dict"
    workspaces_config = config_data.get("workspaces", [])
    assert len(workspaces_config) > 0, "Should have at least one workspace entry"

    # Find our workspace in the config
    workspace_paths = [w.get("path") for w in workspaces_config]
    assert str(workspace_dir) in workspace_paths, "Workspace path should be in config"


def test_workspace_list_shows_mounts(test_project, workspace_dir):
    """Test that 'abox workspace list' shows configured mounts."""
    # Add a workspace first
    add_result = run_abox("workspace", "add", str(workspace_dir), cwd=test_project, check=False)
    assert add_result.returncode == 0, f"workspace add should succeed: {add_result.stderr}"

    # List workspaces
    result = run_abox("workspace", "list", cwd=test_project)

    assert result.returncode == 0, f"workspace list should succeed: {result.stderr}"

    # Output MUST contain the workspace we just added
    # Check for the path we added
    workspace_path_str = str(workspace_dir)
    assert (
        workspace_path_str in result.stdout or workspace_dir.name in result.stdout
    ), f"Workspace list must show the added workspace '{workspace_path_str}'. Output: {result.stdout}"


def test_workspace_remove_cleans_config(test_project, workspace_dir):
    """Test that 'abox workspace remove' removes from .boxctl.yml."""
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)

    # Add workspace first
    run_abox("workspace", "add", str(workspace_dir), cwd=test_project, check=False)

    # Verify it was added
    with open(config_file) as f:
        config_data = yaml.safe_load(f)
    workspaces_config = config_data.get("workspaces", [])
    workspace_paths = [w.get("path") for w in workspaces_config]
    assert str(workspace_dir) in workspace_paths, "Workspace should be added"

    # Get the mount name for the workspace
    workspace_entry = next(w for w in workspaces_config if w.get("path") == str(workspace_dir))
    mount_name = workspace_entry.get("mount")

    # Remove workspace
    result = run_abox("workspace", "remove", mount_name, cwd=test_project, check=False)

    assert result.returncode == 0, "abox workspace remove should succeed"

    # Verify it was removed
    with open(config_file) as f:
        config_data = yaml.safe_load(f)
    workspaces_config = config_data.get("workspaces", [])

    workspace_paths = [w.get("path") for w in workspaces_config]
    assert str(workspace_dir) not in workspace_paths, "Workspace should be removed from config"


def test_workspace_mounted_in_container(test_project, workspace_dir):
    """Test that workspace is actually mounted at /context/<name> in container."""
    # Create a marker file in workspace
    marker_file = workspace_dir / "marker.txt"
    marker_content = "workspace mount test"
    marker_file.write_text(marker_content)

    # Add workspace
    run_abox("workspace", "add", str(workspace_dir), cwd=test_project, check=False)

    # Get the mount name from .boxctl.yml
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file) as f:
        config_data = yaml.safe_load(f)
    workspaces_config = config_data.get("workspaces", [])

    workspace_entry = next(w for w in workspaces_config if w.get("path") == str(workspace_dir))
    mount_name = workspace_entry.get("mount")

    # Start/rebuild container to pick up the new mount
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if the file is visible in the container at /context/<name>
    result = subprocess.run(
        ["docker", "exec", container_name, "cat", f"/context/{mount_name}/marker.txt"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Should be able to read file at /context/{mount_name}"
    assert result.stdout.strip() == marker_content, "File content should match"


def test_workspace_self_reference_skipped(test_project):
    """Test that adding project directory itself shows warning/is skipped."""
    # Try to add the project directory as a workspace
    result = run_abox("workspace", "add", str(test_project), cwd=test_project, check=False)

    # Should produce output indicating the issue
    output = result.stdout + result.stderr

    # Check that some feedback was provided (warning or error)
    assert len(output) > 0, "Should provide feedback about self-reference"

    # Should either fail with error or show warning
    # Check for common warning/error keywords
    output_lower = output.lower()
    has_warning_indicator = any(
        word in output_lower
        for word in ["warning", "error", "invalid", "cannot", "already", "skip", "same"]
    )

    # If no clear warning/error message, verify workspace wasn't added
    if not has_warning_indicator:
        config_file = test_project / ".boxctl" / "config.yml"
        config_file.parent.mkdir(exist_ok=True)
        if config_file.exists():
            with open(config_file) as f:
                config_data = yaml.safe_load(f)
            workspaces_config = config_data.get("workspaces", []) if config_data else []

            # Count how many times the project path appears
            project_path_count = sum(
                1 for w in workspaces_config if w.get("path") == str(test_project)
            )

            # Workspace should not be added (count should be 0)
            assert project_path_count == 0, "Self-reference workspace should not be added to config"
    else:
        # If warning was shown, that's also acceptable
        assert has_warning_indicator, "Should warn about self-reference"
