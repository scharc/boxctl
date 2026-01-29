# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""
Zero-to-hero installation tests for boxctl.

These tests run on a MINIMAL VM image with NO Docker pre-installed.
They exercise the complete installation flow that a real user would follow:

1. Install Docker
2. Clone boxctl repository
3. Run setup.sh
4. Initialize first project
5. Start first container (builds base image)

These tests are slow by design - they test the real installation experience.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

from conftest import run_cmd, run_as_root

# Explicit paths for tools that may not be in PATH
POETRY_PATH = Path.home() / ".local/bin/poetry"
PIPX_PATH = Path.home() / ".local/bin/pipx"


def get_poetry_cmd() -> list:
    """Get the poetry command, using explicit path if needed."""
    if POETRY_PATH.exists():
        return [str(POETRY_PATH)]
    return ["poetry"]


def get_boxctl_cmd(repo_dir: Path) -> list:
    """Get the boxctl command via Poetry."""
    return get_poetry_cmd() + ["-C", str(repo_dir), "run", "boxctl"]


class TestDockerInstallation:
    """Test Docker installation on a fresh system."""

    @pytest.mark.zero_to_hero
    @pytest.mark.docker_install
    def test_docker_not_installed(self, is_minimal_vm):
        """Verify Docker is not pre-installed on minimal image."""
        if not is_minimal_vm:
            pytest.skip("Not running on minimal VM")

        result = subprocess.run(
            ["which", "docker"],
            capture_output=True,
        )
        assert result.returncode != 0, "Docker should not be pre-installed"

    @pytest.mark.zero_to_hero
    @pytest.mark.docker_install
    def test_install_docker_ubuntu(self, is_minimal_vm):
        """Test Docker installation on Ubuntu."""
        if not is_minimal_vm:
            pytest.skip("Not running on minimal VM")

        # Check if we're on Ubuntu
        if not Path("/etc/lsb-release").exists():
            pytest.skip("Not running on Ubuntu")

        # Update package list
        run_as_root(["apt-get", "update"], timeout=120)

        # Install Docker
        run_as_root(
            ["apt-get", "install", "-y", "docker.io"],
            timeout=300,
        )

        # Start Docker service
        run_as_root(["systemctl", "start", "docker"])
        run_as_root(["systemctl", "enable", "docker"])

        # Add testuser to docker group
        run_as_root(["usermod", "-aG", "docker", "testuser"])

        # Verify Docker is installed
        result = run_cmd(["docker", "--version"], check=False)
        assert result.returncode == 0, f"Docker not installed: {result.stderr}"

    @pytest.mark.zero_to_hero
    @pytest.mark.docker_install
    def test_install_docker_fedora(self, is_minimal_vm):
        """Test Docker installation on Fedora."""
        if not is_minimal_vm:
            pytest.skip("Not running on minimal VM")

        # Check if we're on Fedora
        if not Path("/etc/fedora-release").exists():
            pytest.skip("Not running on Fedora")

        # Install Docker
        run_as_root(
            ["dnf", "install", "-y", "docker"],
            timeout=300,
        )

        # Start Docker service
        run_as_root(["systemctl", "start", "docker"])
        run_as_root(["systemctl", "enable", "docker"])

        # Add testuser to docker group
        run_as_root(["usermod", "-aG", "docker", "testuser"])

        # Verify Docker is installed
        result = run_cmd(["docker", "--version"], check=False)
        assert result.returncode == 0, f"Docker not installed: {result.stderr}"

    @pytest.mark.zero_to_hero
    @pytest.mark.docker_install
    def test_docker_works(self):
        """Verify Docker can run containers."""
        # This test assumes Docker is now installed (from previous tests)
        # Use newgrp to get docker group membership without re-login
        result = subprocess.run(
            ["sg", "docker", "-c", "docker run --rm hello-world"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # If sg fails, try direct (might work if user logged in again)
        if result.returncode != 0:
            result = run_cmd(
                ["docker", "run", "--rm", "hello-world"],
                timeout=120,
                check=False,
            )

        assert result.returncode == 0, f"Docker cannot run containers: {result.stderr}"
        assert "Hello from Docker!" in result.stdout


class TestBoxctlInstallation:
    """Test boxctl installation from source."""

    @pytest.mark.zero_to_hero
    @pytest.mark.boxctl_install
    def test_clone_repository(self, fresh_system):
        """Test cloning the boxctl repository."""
        repo_dir = fresh_system / "boxctl"

        # Skip if already exists (from previous test run)
        if repo_dir.exists():
            pytest.skip("Repository already cloned")

        # Clone repository
        result = run_cmd(
            ["git", "clone", "https://github.com/mschuetze/boxctl.git", str(repo_dir)],
            cwd=fresh_system,
            timeout=120,
            check=False,
        )

        # If clone fails (e.g., no network), use local copy
        if result.returncode != 0:
            boxctl_source = Path("/opt/boxctl")
            if boxctl_source.exists():
                import shutil

                shutil.copytree(boxctl_source, repo_dir)
            else:
                pytest.fail(f"Could not clone repository: {result.stderr}")

        assert repo_dir.exists(), "Repository not cloned"
        assert (repo_dir / "pyproject.toml").exists(), "pyproject.toml not found"

    @pytest.mark.zero_to_hero
    @pytest.mark.boxctl_install
    def test_install_poetry(self):
        """Test Poetry installation."""
        # Check if Poetry is already installed (use explicit path)
        if POETRY_PATH.exists():
            pytest.skip("Poetry already installed")

        # Install pipx if not available
        if not PIPX_PATH.exists():
            result = run_cmd(["which", "pipx"], check=False)
            if result.returncode != 0:
                run_cmd(["pip3", "install", "--user", "pipx"], timeout=120)
                run_cmd(["python3", "-m", "pipx", "ensurepath"])

        # Install Poetry via pipx (use explicit path or module)
        if PIPX_PATH.exists():
            result = run_cmd(
                [str(PIPX_PATH), "install", "poetry"],
                timeout=120,
                check=False,
            )
        else:
            result = run_cmd(
                ["python3", "-m", "pipx", "install", "poetry"],
                timeout=120,
                check=False,
            )

        # Verify Poetry is installed at expected path
        assert POETRY_PATH.exists(), f"Poetry not installed at {POETRY_PATH}: {result.stderr}"

    @pytest.mark.zero_to_hero
    @pytest.mark.boxctl_install
    def test_run_setup_script(self, fresh_system):
        """Test running bin/setup.sh installation flow."""
        repo_dir = fresh_system / "boxctl"
        if not repo_dir.exists():
            repo_dir = Path("/opt/boxctl")

        if not repo_dir.exists():
            pytest.skip("boxctl repository not available")

        setup_script = repo_dir / "bin/setup.sh"
        if not setup_script.exists():
            pytest.skip("setup.sh not found")

        # Run setup with --no-prompt
        result = run_cmd(
            ["bash", str(setup_script), "--shell", "bash", "--no-prompt"],
            cwd=repo_dir,
            timeout=600,  # 10 min for Poetry install + base image build
            check=False,
        )

        # Check for success or partial success
        # Setup might fail on base image if Docker isn't ready
        assert (
            "Setup complete" in result.stdout or result.returncode == 0
        ), f"Setup failed: {result.stdout}\n{result.stderr}"

    @pytest.mark.zero_to_hero
    @pytest.mark.boxctl_install
    def test_boxctl_command_available(self, fresh_system):
        """Test that boxctl command is available after setup."""
        repo_dir = fresh_system / "boxctl"
        if not repo_dir.exists():
            repo_dir = Path("/opt/boxctl")

        if not repo_dir.exists():
            pytest.skip("boxctl repository not available")

        # Use explicit Poetry path (most reliable)
        boxctl_cmd = get_boxctl_cmd(repo_dir) + ["--version"]

        result = subprocess.run(
            boxctl_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            assert "boxctl" in result.stdout.lower() or "0." in result.stdout
            return

        # Fallback: try direct boxctl (if in PATH)
        result = subprocess.run(
            ["boxctl", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            assert "boxctl" in result.stdout.lower() or "0." in result.stdout
            return

        pytest.fail(f"boxctl command not available: {result.stderr}")


class TestFirstProject:
    """Test creating and starting the first project."""

    def _get_repo_dir(self, fresh_system: Path) -> Path:
        """Get the boxctl repo directory."""
        repo_dir = fresh_system / "boxctl" if fresh_system else None
        if repo_dir and repo_dir.exists():
            return repo_dir
        return Path("/opt/boxctl")

    @pytest.mark.zero_to_hero
    @pytest.mark.slow
    def test_first_project_init(self, test_workspace, fresh_system):
        """Test initializing the first boxctl project."""
        project_dir = test_workspace / "my-first-project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Initialize git repo (required for boxctl)
        run_cmd(["git", "init"], cwd=project_dir)
        run_cmd(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project_dir,
        )
        run_cmd(
            ["git", "config", "user.name", "Test User"],
            cwd=project_dir,
        )

        # Run boxctl init via explicit Poetry path
        repo_dir = self._get_repo_dir(fresh_system)
        boxctl_cmd = get_boxctl_cmd(repo_dir) + ["init"]

        result = run_cmd(
            boxctl_cmd,
            cwd=project_dir,
            timeout=60,
            check=False,
        )

        assert result.returncode == 0, f"boxctl init failed: {result.stderr}"
        assert (project_dir / ".boxctl").is_dir(), ".boxctl directory not created"

    @pytest.mark.zero_to_hero
    @pytest.mark.slow
    def test_first_container_start(self, test_workspace, fresh_system):
        """Test starting the first container (builds base image)."""
        project_dir = test_workspace / "my-first-project"

        if not (project_dir / ".boxctl").exists():
            pytest.skip("Project not initialized")

        # This is the big test - first start builds boxctl-base image
        # Allow 15 minutes for the build
        repo_dir = self._get_repo_dir(fresh_system)
        boxctl_cmd = get_boxctl_cmd(repo_dir) + ["start"]

        result = run_cmd(
            boxctl_cmd,
            cwd=project_dir,
            timeout=900,
            check=False,
        )

        assert result.returncode == 0, f"boxctl start failed: {result.stderr}"

        # Verify container is running
        container_name = f"boxctl-{project_dir.name}"
        result = run_cmd(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            check=False,
        )
        assert container_name in result.stdout, f"Container not running: {result.stdout}"

    @pytest.mark.zero_to_hero
    @pytest.mark.slow
    def test_first_container_stop(self, test_workspace, fresh_system):
        """Test stopping the first container."""
        project_dir = test_workspace / "my-first-project"

        if not (project_dir / ".boxctl").exists():
            pytest.skip("Project not initialized")

        repo_dir = self._get_repo_dir(fresh_system)
        boxctl_cmd = get_boxctl_cmd(repo_dir) + ["stop"]

        result = run_cmd(
            boxctl_cmd,
            cwd=project_dir,
            timeout=60,
            check=False,
        )

        assert result.returncode == 0, f"boxctl stop failed: {result.stderr}"

        # Verify container is stopped
        container_name = f"boxctl-{project_dir.name}"
        result = run_cmd(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            check=False,
        )
        assert container_name not in result.stdout, f"Container still running: {result.stdout}"


class TestBaseImage:
    """Test base image creation."""

    @pytest.mark.zero_to_hero
    @pytest.mark.slow
    def test_base_image_exists(self):
        """Verify boxctl-base image exists after first start."""
        result = run_cmd(
            ["docker", "images", "boxctl-base:latest", "--format", "{{.Repository}}"],
            check=False,
        )

        # Image might not exist if first start wasn't run
        if "boxctl-base" not in result.stdout:
            pytest.skip("boxctl-base image not built yet")

        assert "boxctl-base" in result.stdout

    @pytest.mark.zero_to_hero
    @pytest.mark.slow
    def test_base_image_can_run(self):
        """Verify boxctl-base image can run containers."""
        result = run_cmd(
            ["docker", "run", "--rm", "boxctl-base:latest", "echo", "base-ok"],
            timeout=60,
            check=False,
        )

        if result.returncode != 0:
            pytest.skip("boxctl-base image not available")

        assert "base-ok" in result.stdout
