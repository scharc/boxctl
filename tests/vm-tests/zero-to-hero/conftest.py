# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""
Pytest configuration for zero-to-hero installation tests.

These tests run on a minimal VM image without Docker pre-installed.
The fixtures here are intentionally minimal - tests are responsible
for installing and configuring everything from scratch.
"""

import os
import subprocess
from pathlib import Path
from typing import Generator

import pytest


# ============================================================================
# pytest configuration
# ============================================================================


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "zero_to_hero: tests for fresh installation flow")
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "docker_install: tests requiring Docker installation")
    config.addinivalue_line("markers", "boxctl_install: tests requiring boxctl installation")


# ============================================================================
# Session-wide fixtures
# ============================================================================


@pytest.fixture(scope="session")
def is_minimal_vm() -> bool:
    """Check if we're running on a minimal VM (no Docker)."""
    result = subprocess.run(
        ["which", "docker"],
        capture_output=True,
    )
    return result.returncode != 0


@pytest.fixture(scope="session")
def test_workspace() -> Generator[Path, None, None]:
    """Session-wide test workspace directory."""
    workspace = Path(os.environ.get("TEST_WORKSPACE", "/test-workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    yield workspace


@pytest.fixture(scope="session")
def boxctl_source() -> Path:
    """Path to boxctl source code."""
    # In VM, boxctl is at /opt/boxctl
    path = Path(os.environ.get("BOXCTL_ROOT", "/opt/boxctl"))
    if not path.exists():
        pytest.skip("boxctl source not found at /opt/boxctl")
    return path


# ============================================================================
# Module-scoped fixtures
# ============================================================================


@pytest.fixture(scope="module")
def fresh_system(test_workspace) -> Generator[Path, None, None]:
    """Provide a fresh system state for installation tests.

    This fixture provides minimal setup - tests are responsible for
    installing everything they need.
    """
    module_dir = test_workspace / "hero-test"
    module_dir.mkdir(parents=True, exist_ok=True)

    yield module_dir


# ============================================================================
# Helper functions (not fixtures)
# ============================================================================


def run_cmd(
    cmd: list,
    cwd: Path = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command with standard options."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def run_as_root(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a command with sudo."""
    return run_cmd(["sudo"] + cmd, **kwargs)
