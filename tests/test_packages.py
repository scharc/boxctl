# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for package management commands (init, add, remove, list)."""

import subprocess

import pytest
import yaml

from tests.conftest import run_abox


def test_packages_init_creates_config(test_project):
    """Test that 'abox packages init' creates packages section in .boxctl/config.yml."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init packages
    result = run_abox("packages", "init", cwd=test_project)

    assert result.returncode == 0, "abox packages init should succeed"
    assert config_file.exists(), ".boxctl/config.yml should exist"

    # Check structure
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "packages" in config, ".boxctl/config.yml should have packages section"
    packages = config["packages"]

    assert "npm" in packages, "packages should have npm key"
    assert "pip" in packages, "packages should have pip key"
    assert "apt" in packages, "packages should have apt key"
    assert "cargo" in packages, "packages should have cargo key"
    assert "post" in packages, "packages should have post key"
    assert isinstance(packages["npm"], list), "npm should be a list"
    assert isinstance(packages["pip"], list), "pip should be a list"
    assert isinstance(packages["apt"], list), "apt should be a list"
    assert isinstance(packages["cargo"], list), "cargo should be a list"
    assert isinstance(packages["post"], list), "post should be a list"


def test_packages_add_npm(test_project):
    """Test that 'abox packages add npm' adds npm package."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init first
    run_abox("packages", "init", cwd=test_project)

    # Add npm package
    result = run_abox("packages", "add", "npm", "cowsay", cwd=test_project)

    assert result.returncode == 0, "abox packages add should succeed"

    # Check config
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "cowsay" in config["packages"]["npm"], "cowsay should be in npm packages"


def test_packages_add_pip(test_project):
    """Test that 'abox packages add pip' adds pip package."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init first
    run_abox("packages", "init", cwd=test_project)

    # Add pip package
    result = run_abox("packages", "add", "pip", "black", cwd=test_project)

    assert result.returncode == 0, "abox packages add should succeed"

    # Check config
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "black" in config["packages"]["pip"], "black should be in pip packages"


def test_packages_add_apt(test_project):
    """Test that 'abox packages add apt' adds apt package."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init first
    run_abox("packages", "init", cwd=test_project)

    # Add apt package
    result = run_abox("packages", "add", "apt", "tree", cwd=test_project)

    assert result.returncode == 0, "abox packages add should succeed"

    # Check config
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "tree" in config["packages"]["apt"], "tree should be in apt packages"


def test_packages_add_cargo(test_project):
    """Test that 'abox packages add cargo' adds cargo package."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init first
    run_abox("packages", "init", cwd=test_project)

    # Add cargo package
    result = run_abox("packages", "add", "cargo", "bat", cwd=test_project)

    assert result.returncode == 0, "abox packages add should succeed"

    # Check config
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "bat" in config["packages"]["cargo"], "bat should be in cargo packages"


def test_packages_add_post(test_project):
    """Test that 'abox packages add post' adds post-install command."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init first
    run_abox("packages", "init", cwd=test_project)

    # Add post-install command
    result = run_abox("packages", "add", "post", "echo 'Hello'", cwd=test_project)

    assert result.returncode == 0, "abox packages add should succeed"

    # Check config
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "echo 'Hello'" in config["packages"]["post"], "post command should be added"


def test_packages_remove(test_project):
    """Test that 'abox packages remove' removes package."""
    config_file = test_project / ".boxctl" / "config.yml"

    # Init and add package
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "npm", "cowsay", cwd=test_project)

    # Verify it was added
    with open(config_file) as f:
        config = yaml.safe_load(f)
    assert "cowsay" in config["packages"]["npm"], "cowsay should be added"

    # Remove package
    result = run_abox("packages", "remove", "npm", "cowsay", cwd=test_project)

    assert result.returncode == 0, "abox packages remove should succeed"

    # Verify it was removed
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "cowsay" not in config["packages"]["npm"], "cowsay should be removed"


def test_packages_list_empty(test_project):
    """Test that 'abox packages list' shows message when no packages."""
    # Force re-init packages to get empty state (previous tests may have added packages)
    config_file = test_project / ".boxctl" / "config.yml"

    # Create a config with empty packages
    config_content = {
        "container_name": test_project.name,
        "packages": {"npm": [], "pip": [], "apt": [], "cargo": [], "post": []},
    }
    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    result = run_abox("packages", "list", cwd=test_project)

    assert result.returncode == 0, "abox packages list should succeed"
    assert "no packages" in result.stdout.lower(), "Should indicate no packages configured"


def test_packages_list_with_packages(test_project):
    """Test that 'abox packages list' shows configured packages."""
    # Init and add some packages
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "npm", "typescript", cwd=test_project)
    run_abox("packages", "add", "pip", "black", cwd=test_project)

    result = run_abox("packages", "list", cwd=test_project)

    assert result.returncode == 0, "abox packages list should succeed"
    assert "typescript" in result.stdout, "Should show npm package"
    assert "black" in result.stdout, "Should show pip package"


def test_packages_add_duplicate(test_project):
    """Test that adding duplicate package shows warning."""
    # Init and add package
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "npm", "cowsay", cwd=test_project)

    # Add same package again
    result = run_abox("packages", "add", "npm", "cowsay", cwd=test_project)

    assert result.returncode == 0, "Should not fail on duplicate"
    assert "already" in result.stdout.lower(), "Should warn about duplicate"


def test_packages_install_in_container(test_project):
    """Test that packages are installed in container on start."""
    # Init and add a simple apt package
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "apt", "tree", cwd=test_project)

    # Start container (this should install packages)
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if tree command is available
    result = subprocess.run(
        ["docker", "exec", container_name, "which", "tree"], capture_output=True, text=True
    )

    assert result.returncode == 0, "tree should be installed in container"
    assert "/usr/bin/tree" in result.stdout, "tree should be in /usr/bin"


@pytest.mark.slow
@pytest.mark.requires_network
def test_packages_install_pip_in_container(test_project):
    """Test that pip packages are installed in container."""
    # Init and add a pip package
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "pip", "httpie", cwd=test_project)

    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if httpie is installed
    result = subprocess.run(
        ["docker", "exec", container_name, "which", "http"], capture_output=True, text=True
    )

    assert result.returncode == 0, "httpie should be installed"


@pytest.mark.slow
@pytest.mark.requires_network
def test_packages_install_npm_in_container(test_project):
    """Test that npm packages are installed in container."""
    import time

    # Init and add an npm package
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "npm", "cowsay", cwd=test_project)

    # Rebuild container to trigger package installation (rebuild re-runs container-init.sh)
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Wait for container initialization to complete (npm install takes a few seconds)
    # Check for "Container initialization complete!" in logs
    for _ in range(30):  # Max 30 seconds
        result = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True)
        if "Container initialization complete!" in result.stdout:
            break
        time.sleep(1)

    # Check if cowsay is available - need bash -lc to get PATH from .bashrc
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "abox",
            container_name,
            "bash",
            "-lc",
            "which cowsay || cowsay --version",
        ],
        capture_output=True,
        text=True,
    )

    # cowsay should be available
    assert (
        result.returncode == 0 or "cowsay" in result.stdout
    ), f"cowsay should be installed. stdout: {result.stdout}, stderr: {result.stderr}"


def test_packages_post_command_runs(test_project):
    """Test that post-install commands are executed."""
    import time

    # Init and add a post-install command that creates a file
    run_abox("packages", "init", cwd=test_project)
    run_abox("packages", "add", "post", "touch /tmp/packages-test-marker", cwd=test_project)

    # Rebuild container to trigger package installation (rebuild re-runs container-init.sh)
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Wait for container initialization to complete
    for _ in range(30):  # Max 30 seconds
        result = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True)
        if "Container initialization complete!" in result.stdout:
            break
        time.sleep(1)

    # Check if the marker file was created
    result = subprocess.run(
        ["docker", "exec", container_name, "test", "-f", "/tmp/packages-test-marker"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "post-install command should have created marker file"
