# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Chain tests for package installation persistence."""

import pytest
import yaml

from helpers.cli import run_abox
from helpers.docker import (
    exec_in_container,
    wait_for_container_ready,
)


@pytest.mark.chain
@pytest.mark.slow
class TestPackagesPersistence:
    """Test package installation persists across rebuilds."""

    def test_npm_package_survives_rebuild(self, test_project):
        """Test npm package persists after rebuild."""
        container_name = f"boxctl-{test_project.name}"

        # 1. Add npm package to config
        result = run_abox("packages", "add", "npm", "cowsay", cwd=test_project)
        assert result.returncode == 0, f"Failed to add package: {result.stderr}"

        # Verify package is in config
        config_path = test_project / ".boxctl.yml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            assert "cowsay" in config.get("packages", {}).get("npm", [])

        # 2. Start container (this should install package)
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name, timeout=120)

        # Give time for package installation
        import time

        time.sleep(5)

        # 3. Verify package is installed
        result = exec_in_container(container_name, "npm list -g cowsay 2>/dev/null")
        assert result.returncode == 0, (
            f"cowsay not installed after start. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert "cowsay" in result.stdout, f"cowsay not in npm list output: {result.stdout}"

        # 4. Rebuild container
        result = run_abox("rebuild", cwd=test_project, timeout=300)
        assert result.returncode == 0, f"Rebuild failed: {result.stderr}"

        wait_for_container_ready(container_name, timeout=120)
        time.sleep(5)

        # 5. Verify package still installed after rebuild
        result = exec_in_container(container_name, "npm list -g cowsay 2>/dev/null")
        assert result.returncode == 0, (
            f"cowsay not installed after rebuild. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert "cowsay" in result.stdout, f"cowsay not in npm list after rebuild: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_pip_package_survives_rebuild(self, test_project):
        """Test pip package persists after rebuild."""
        container_name = f"boxctl-{test_project.name}"

        # 1. Add pip package to config
        result = run_abox("packages", "add", "pip", "httpie", cwd=test_project)
        assert result.returncode == 0, f"Failed to add package: {result.stderr}"

        # 2. Start container
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name, timeout=120)

        import time

        time.sleep(5)

        # 3. Rebuild
        result = run_abox("rebuild", cwd=test_project, timeout=300)
        assert result.returncode == 0

        wait_for_container_ready(container_name, timeout=120)
        time.sleep(5)

        # 4. Verify package is in config
        config_path = test_project / ".boxctl.yml"
        assert config_path.exists(), ".boxctl.yml not created"
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        assert "httpie" in config.get("packages", {}).get(
            "pip", []
        ), f"httpie not in pip packages config: {config}"

        # 5. Verify package is actually installed in container
        result = exec_in_container(container_name, "pip show httpie 2>/dev/null")
        assert result.returncode == 0, (
            f"httpie not installed after rebuild. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert "httpie" in result.stdout.lower(), f"httpie not in pip show output: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_apt_package_survives_rebuild(self, test_project):
        """Test apt package persists after rebuild."""
        container_name = f"boxctl-{test_project.name}"

        # 1. Add apt package to config
        result = run_abox("packages", "add", "apt", "tree", cwd=test_project)
        assert result.returncode == 0, f"Failed to add package: {result.stderr}"

        # 2. Start and rebuild
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name, timeout=120)

        # Rebuild triggers installation
        result = run_abox("rebuild", cwd=test_project, timeout=300)
        assert result.returncode == 0

        wait_for_container_ready(container_name, timeout=120)

        import time

        time.sleep(10)  # Give time for apt install

        # 3. Verify package is in config
        config_path = test_project / ".boxctl.yml"
        assert config_path.exists(), ".boxctl.yml not created"
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        assert "tree" in config.get("packages", {}).get(
            "apt", []
        ), f"tree not in apt packages config: {config}"

        # 4. Verify package is actually installed in container
        result = exec_in_container(container_name, "which tree")
        assert result.returncode == 0, (
            f"tree not installed after rebuild. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert (
            "/tree" in result.stdout or "tree" in result.stdout
        ), f"tree path not found: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)


@pytest.mark.chain
class TestPackagesConfig:
    """Test packages configuration operations."""

    def test_packages_list_shows_configured(self, test_project):
        """Test packages list shows configured packages."""
        # Add some packages
        run_abox("packages", "add", "npm", "cowsay", cwd=test_project)
        run_abox("packages", "add", "pip", "httpie", cwd=test_project)

        # List packages
        result = run_abox("packages", "list", cwd=test_project)

        assert result.returncode == 0, f"packages list failed: {result.stderr}"
        assert (
            "cowsay" in result.stdout
        ), f"cowsay not shown in packages list output: {result.stdout}"
        assert (
            "httpie" in result.stdout
        ), f"httpie not shown in packages list output: {result.stdout}"

    def test_packages_remove_cleans_config(self, test_project):
        """Test package removal cleans configuration."""
        # Add package
        run_abox("packages", "add", "npm", "cowsay", cwd=test_project)

        config_path = test_project / ".boxctl.yml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            assert "cowsay" in config.get("packages", {}).get("npm", [])

        # Remove package
        result = run_abox("packages", "remove", "npm", "cowsay", cwd=test_project)
        assert result.returncode == 0

        # Verify removed from config
        if config_path.exists():
            with open(config_path) as f:
                config_after = yaml.safe_load(f) or {}
            assert "cowsay" not in config_after.get("packages", {}).get("npm", [])
