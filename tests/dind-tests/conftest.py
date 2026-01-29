# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""
Root pytest configuration and fixtures for Boxctl True DinD tests.

This runs in a True DinD environment where we have our own Docker daemon.
No special path translation needed - everything works like on a real host.
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Generator

import pytest


# ============================================================================
# pytest configuration
# ============================================================================


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "requires_auth: tests requiring Claude/Codex credentials")
    config.addinivalue_line("markers", "slow: marks tests as slow (>30s)")
    config.addinivalue_line("markers", "pulls_images: tests that pull Docker images")
    config.addinivalue_line("markers", "chain: dependency chain tests")
    config.addinivalue_line("markers", "integration: integration-level DinD tests")


def pytest_collection_modifyitems(config, items):
    """Skip tests based on available resources."""
    # Check for auth
    has_claude = Path("/home/testuser/.claude").is_dir()
    has_codex = Path("/home/testuser/.codex").is_dir()

    skip_auth = pytest.mark.skip(reason="Auth files not mounted")

    for item in items:
        if "requires_auth" in item.keywords:
            if not has_claude and not has_codex:
                item.add_marker(skip_auth)


# ============================================================================
# Session-wide fixtures
# ============================================================================


@pytest.fixture(scope="session")
def docker_available():
    """Verify Docker is available and can create containers.

    This is a True DinD test - we verify not just that Docker is available,
    but that we can actually create and run containers. This catches issues
    like socket permissions, storage driver problems, etc.
    """
    # 1. Check docker info works
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail("Docker is not available - ensure socket is mounted")

    # 2. Verify we can actually create and run a container
    test_container = f"dind-test-{uuid.uuid4().hex[:8]}"
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--name", test_container, "alpine:latest", "echo", "dind-ok"],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            pytest.fail(
                f"Docker cannot create containers. "
                f"This may indicate storage driver issues in DinD. "
                f"stderr: {result.stderr.decode()}"
            )
        if b"dind-ok" not in result.stdout:
            pytest.fail(
                f"Container ran but output unexpected. " f"stdout: {result.stdout.decode()}"
            )
    except subprocess.TimeoutExpired:
        # Clean up just in case
        subprocess.run(["docker", "rm", "-f", test_container], capture_output=True)
        pytest.fail("Docker container creation timed out - possible DinD issue")

    return True


@pytest.fixture(scope="session")
def test_workspace(docker_available) -> Generator[Path, None, None]:
    """Session-wide test workspace directory.

    All test projects are created under this directory.
    """
    workspace = Path(os.environ.get("TEST_WORKSPACE", "/test-workspace"))
    workspace.mkdir(parents=True, exist_ok=True)

    yield workspace

    # Cleanup all test projects
    for item in workspace.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)


@pytest.fixture(scope="session")
def has_claude_auth() -> bool:
    """Check if Claude auth is available."""
    return Path("/home/testuser/.claude").is_dir()


@pytest.fixture(scope="session")
def has_codex_auth() -> bool:
    """Check if Codex auth is available."""
    return Path("/home/testuser/.codex").is_dir()


# ============================================================================
# Module-scoped fixtures
# ============================================================================


@pytest.fixture(scope="module")
def module_workspace(test_workspace) -> Generator[Path, None, None]:
    """Module-scoped workspace directory.

    Provides isolation between test modules while sharing containers
    within a module for efficiency.
    """
    module_id = uuid.uuid4().hex[:8]
    workspace = test_workspace / f"module-{module_id}"
    workspace.mkdir(parents=True, exist_ok=True)

    yield workspace

    # Cleanup containers from this module
    from helpers.docker import run_docker

    result = run_docker(
        "ps",
        "-a",
        "--filter",
        f"name=boxctl-test-{module_id}",
        "--format",
        "{{.Names}}",
    )
    for container in result.stdout.strip().split("\n"):
        if container:
            run_docker("rm", "-f", container)

    # Remove directory
    shutil.rmtree(workspace, ignore_errors=True)


# ============================================================================
# Function-scoped fixtures
# ============================================================================


@pytest.fixture
def test_project(module_workspace, docker_available) -> Generator[Path, None, None]:
    """Create an isolated test project with boxctl initialized.

    Each test gets a fresh project directory with .boxctl/ set up.
    Cleanup is automatic after the test.
    """
    from helpers.cli import run_abox
    from helpers.docker import run_docker

    project_id = uuid.uuid4().hex[:8]
    project_dir = module_workspace / f"test-{project_id}"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Initialize boxctl
    result = run_abox("init", cwd=project_dir)
    assert result.returncode == 0, f"Failed to init project: {result.stderr}"

    yield project_dir

    # Cleanup container
    container_name = f"boxctl-{project_dir.name}"
    run_docker("rm", "-f", container_name)

    # Cleanup directory
    shutil.rmtree(project_dir, ignore_errors=True)


@pytest.fixture
def running_container(test_project) -> Generator[str, None, None]:
    """Start an boxctl container and return its name.

    Container is automatically stopped after test.
    """
    from helpers.cli import run_abox
    from helpers.docker import wait_for_container_ready

    # Start container
    result = run_abox("start", cwd=test_project)
    assert result.returncode == 0, f"Failed to start container: {result.stderr}"

    container_name = f"boxctl-{test_project.name}"

    # Wait for ready
    ready = wait_for_container_ready(container_name, timeout=60)
    assert ready, "Container failed to become ready"

    yield container_name

    # Stop container
    run_abox("stop", cwd=test_project)


@pytest.fixture
def fake_git_repo(module_workspace) -> Generator[Path, None, None]:
    """Create a fake git repository for testing.

    Creates a git repo with initial commit and feature branches
    suitable for worktree testing.
    """
    from helpers.git import init_git_repo

    repo_dir = module_workspace / f"repo-{uuid.uuid4().hex[:8]}"

    init_git_repo(
        repo_dir,
        initial_commit=True,
        branches=["feature-1", "feature-2", "bugfix-1"],
    )

    yield repo_dir

    # Cleanup
    shutil.rmtree(repo_dir, ignore_errors=True)


@pytest.fixture
def test_network(docker_available) -> Generator[str, None, None]:
    """Create an isolated Docker network for tests."""
    from helpers.docker import create_network, remove_network

    network_name = f"test-net-{uuid.uuid4().hex[:8]}"

    created = create_network(network_name)
    assert created, f"Failed to create network: {network_name}"

    yield network_name

    remove_network(network_name)


# ============================================================================
# Service container fixtures
# ============================================================================


@pytest.fixture
def nginx_container(docker_available, test_network) -> Generator[str, None, None]:
    """Start nginx container for networking tests."""
    from helpers.docker import run_docker, wait_for_container_ready

    container_name = "test-nginx-dind"

    # Remove if exists
    run_docker("rm", "-f", container_name)

    # Start nginx
    result = run_docker(
        "run",
        "-d",
        "--name",
        container_name,
        "--network",
        test_network,
        "nginx:alpine",
    )

    if result.returncode != 0:
        pytest.skip("Failed to start nginx container")

    # Wait for ready
    wait_for_container_ready(container_name, timeout=30)

    yield container_name

    # Cleanup
    run_docker("rm", "-f", container_name)


@pytest.fixture(scope="session")
def postgres_container(docker_available) -> Generator[str, None, None]:
    """Start postgres container for database tests."""
    from helpers.docker import run_docker
    import time

    container_name = "test-postgres-dind"

    # Remove if exists
    run_docker("rm", "-f", container_name)

    # Start postgres
    result = run_docker(
        "run",
        "-d",
        "--name",
        container_name,
        "-e",
        "POSTGRES_PASSWORD=testpass",
        "-e",
        "POSTGRES_DB=testdb",
        "postgres:16-alpine",
    )

    if result.returncode != 0:
        pytest.skip("Failed to start postgres container")

    # Wait for postgres to be ready
    for _ in range(30):
        result = run_docker(
            "exec",
            container_name,
            "pg_isready",
            "-U",
            "postgres",
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        pytest.skip("Postgres failed to become ready")

    yield container_name

    # Cleanup
    run_docker("rm", "-f", container_name)
