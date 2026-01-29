# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Pytest fixtures for Boxctl integration tests.

These tests run on the HOST, not inside the container.
They use subprocess to call the boxctl CLI via python module.
"""

import os
import subprocess
import sys
import pytest
from pathlib import Path


def run_abox(*args, cwd=None, check=True, capture_output=True, text=True):
    """Run abox CLI via python module (tests actual code, not installed version).

    Uses: python -m boxctl.cli instead of 'abox' command.
    This ensures tests run against local code changes, not whatever is installed.

    Args:
        *args: Command arguments to pass to abox
        cwd: Working directory to run command in
        check: Whether to raise exception on non-zero exit
        capture_output: Whether to capture stdout/stderr
        text: Whether to decode output as text

    Returns:
        subprocess.CompletedProcess
    """
    # Get project root (parent of tests/)
    project_root = Path(__file__).parent.parent

    # Set up environment to find boxctl module
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    return subprocess.run(
        [sys.executable, "-m", "boxctl.cli", *args],
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=text,
        env=env,
    )


@pytest.fixture(scope="session")
def docker_available():
    """Check if Docker is available. Skip tests if not."""
    result = subprocess.run(["docker", "info"], capture_output=True)
    if result.returncode != 0:
        pytest.skip("Docker not available")


@pytest.fixture(scope="module")
def test_project(tmp_path_factory, docker_available):
    """Create a temp project dir and initialize it.

    This fixture is scoped to module (not per-test) because container
    creation/cleanup is slow. Tests within a module share the same
    temp project directory.

    Yields:
        Path: Temporary project directory with .boxctl/ initialized
    """
    project_dir = tmp_path_factory.mktemp("abox-test")

    # Run abox init
    run_abox("init", cwd=project_dir)

    yield project_dir

    # Cleanup: stop and remove container
    container_name = f"boxctl-{project_dir.name}"
    subprocess.run(
        ["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


@pytest.fixture
def workspace_dir(tmp_path_factory):
    """Create a temporary directory for workspace mount tests.

    This is a separate directory that can be added as a workspace mount.
    Function-scoped so each test gets a fresh directory.

    Yields:
        Path: Temporary directory for workspace testing
    """
    return tmp_path_factory.mktemp("workspace")
