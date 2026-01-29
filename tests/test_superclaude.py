# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for superclaude command availability in container."""

import subprocess


def test_superclaude_available_in_container(test_project):
    """Test that superclaude command exists in container."""
    from tests.conftest import run_abox

    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if superclaude command exists
    result = subprocess.run(
        ["docker", "exec", container_name, "which", "superclaude"], capture_output=True, text=True
    )

    assert result.returncode == 0, "superclaude command should exist in container"
    assert (
        "/superclaude" in result.stdout or "superclaude" in result.stdout
    ), "which should return path to superclaude"


def test_superclaude_finds_config(test_project):
    """Test that superclaude can run --version without config error."""
    from tests.conftest import run_abox

    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Try to run superclaude --version (should work even without API key)
    result = subprocess.run(
        ["docker", "exec", container_name, "superclaude", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Should not fail with config error
    # It might fail if no API key is set, but shouldn't complain about missing config files
    assert (
        "config" not in result.stderr.lower() or result.returncode == 0
    ), "superclaude should find its config files"
