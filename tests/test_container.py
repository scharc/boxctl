# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for container management commands (start, stop, rebuild)."""

import subprocess
import time
from tests.conftest import run_abox


def test_start_creates_container(test_project):
    """Test that 'abox start' creates and starts a container."""
    # Start the container
    result = run_abox("start", cwd=test_project)
    assert result.returncode == 0, "abox start should succeed"

    # Get container name
    container_name = f"boxctl-{test_project.name}"

    # Verify container exists and is running
    inspect_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )

    assert inspect_result.returncode == 0, f"Container {container_name} should exist"
    assert inspect_result.stdout.strip() == "true", "Container should be running"


def test_stop_stops_container(test_project):
    """Test that 'abox stop' stops the container."""
    container_name = f"boxctl-{test_project.name}"

    # Start container first
    run_abox("start", cwd=test_project)

    # Verify it's running
    inspect_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    assert inspect_result.stdout.strip() == "true", "Container should be running before stop"

    # Stop the container
    result = run_abox("stop", cwd=test_project)
    assert result.returncode == 0, "abox stop should succeed"

    # Give Docker a moment to stop the container
    time.sleep(1)

    # Verify it's stopped
    inspect_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    assert inspect_result.stdout.strip() == "false", "Container should be stopped"


def test_rebuild_recreates_container(test_project):
    """Test that 'abox rebuild' removes and recreates the container."""
    container_name = f"boxctl-{test_project.name}"

    # Start container first
    run_abox("start", cwd=test_project)

    # Get original container ID
    id_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", container_name], capture_output=True, text=True
    )
    original_id = id_result.stdout.strip()

    # Rebuild the container
    result = run_abox("rebuild", cwd=test_project)
    assert result.returncode == 0, "abox rebuild should succeed"

    # Get new container ID
    new_id_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", container_name], capture_output=True, text=True
    )
    new_id = new_id_result.stdout.strip()

    # IDs should be different (container was recreated)
    assert original_id != new_id, "Container ID should change after rebuild"


def test_container_has_workspace_mount(test_project):
    """Test that container has /workspace mounted correctly."""
    container_name = f"boxctl-{test_project.name}"

    # Start container
    run_abox("start", cwd=test_project)

    # Check mount points
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .Mounts}}{{.Destination}}\n{{end}}",
            container_name,
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Should be able to inspect mounts"
    mount_destinations = result.stdout.strip().split("\n")

    assert "/workspace" in mount_destinations, "/workspace should be mounted in container"
