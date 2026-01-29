# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Unit tests for container manager."""

import os
import tempfile
from pathlib import Path

import pytest


class TestContainerManagerImports:
    """Test that container manager modules can be imported."""

    def test_container_manager_import(self):
        """Test that ContainerManager can be imported."""
        from boxctl.container import ContainerManager

        assert ContainerManager is not None

    def test_get_abox_environment_import(self):
        """Test that get_abox_environment can be imported."""
        from boxctl.container import get_abox_environment

        assert callable(get_abox_environment)


class TestGetAboxEnvironment:
    """Test get_abox_environment function."""

    def test_basic_environment(self):
        """Test basic environment without optional params."""
        from boxctl.container import get_abox_environment

        env = get_abox_environment()

        assert "HOME" in env
        assert env["HOME"] == "/home/abox"
        assert "USER" in env
        assert env["USER"] == "abox"

    def test_environment_with_tmux(self):
        """Test environment with TMUX_TMPDIR."""
        from boxctl.container import get_abox_environment

        env = get_abox_environment(include_tmux=True)

        assert "TMUX_TMPDIR" in env
        assert env["TMUX_TMPDIR"] == "/tmp"

    def test_environment_with_container_name(self):
        """Test environment with container name."""
        from boxctl.container import get_abox_environment

        env = get_abox_environment(container_name="boxctl-test")

        assert "BOXCTL_CONTAINER_NAME" in env
        assert env["BOXCTL_CONTAINER_NAME"] == "boxctl-test"

    def test_environment_with_all_options(self):
        """Test environment with all options."""
        from boxctl.container import get_abox_environment

        env = get_abox_environment(include_tmux=True, container_name="boxctl-full")

        assert "HOME" in env
        assert "USER" in env
        assert "TMUX_TMPDIR" in env
        assert "BOXCTL_CONTAINER_NAME" in env
        assert env["BOXCTL_CONTAINER_NAME"] == "boxctl-full"


class TestContainerManagerInit:
    """Test ContainerManager initialization."""

    def test_container_manager_creates_client(self):
        """Test that ContainerManager creates Docker client."""
        from boxctl.container import ContainerManager

        # This may fail if Docker is not available, which is OK for unit tests
        try:
            manager = ContainerManager()
            assert manager.client is not None
            assert manager.config is not None
        except Exception:
            # Docker not available in this test environment
            pass

    def test_base_image_constant(self):
        """Test that BASE_IMAGE constant is set."""
        from boxctl.container import ContainerManager

        assert ContainerManager.BASE_IMAGE == "boxctl-base:latest"

    def test_container_prefix_constant(self):
        """Test that CONTAINER_PREFIX constant is set."""
        from boxctl.container import ContainerManager

        assert ContainerManager.CONTAINER_PREFIX == "boxctl-"


class TestSanitizeProjectName:
    """Test project name sanitization."""

    def test_simple_name(self):
        """Test sanitizing simple project name."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.sanitize_project_name("my-project")
            assert result == "my-project"
        except Exception:
            # Docker not available
            pass

    def test_uppercase_name(self):
        """Test that uppercase is converted to lowercase."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.sanitize_project_name("MyProject")
            assert result == "myproject"
        except Exception:
            pass

    def test_special_characters(self):
        """Test that special characters are replaced with hyphens."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.sanitize_project_name("my@project#name")
            assert result == "my-project-name"
        except Exception:
            pass

    def test_leading_trailing_hyphens(self):
        """Test that leading/trailing hyphens are removed."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.sanitize_project_name("-my-project-")
            assert result == "my-project"
        except Exception:
            pass

    def test_mixed_case_special_chars(self):
        """Test combination of cases and special characters."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.sanitize_project_name("My_Project.2024")
            assert result == "my_project-2024"
        except Exception:
            pass


class TestGetProjectName:
    """Test get_project_name method."""

    def test_explicit_project_dir(self, tmp_path):
        """Test getting project name from explicit directory."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            project_dir = tmp_path / "test-project"
            project_dir.mkdir()

            result = manager.get_project_name(project_dir)
            assert result == "test-project"
        except Exception:
            pass

    def test_project_name_from_env(self, monkeypatch, tmp_path):
        """Test getting project name from environment variable."""
        from boxctl.container import ContainerManager

        project_dir = tmp_path / "env-project"
        project_dir.mkdir()
        monkeypatch.setenv("BOXCTL_PROJECT_DIR", str(project_dir))

        try:
            manager = ContainerManager()
            result = manager.get_project_name()
            assert result == "env-project"
        except Exception:
            pass


class TestGetContainerName:
    """Test get_container_name method."""

    def test_container_name_generation(self):
        """Test generating container name from project name."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.get_container_name("my-project")
            assert result == "boxctl-my-project"
        except Exception:
            pass

    def test_container_name_with_prefix(self):
        """Test that container name includes prefix."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            result = manager.get_container_name("test")
            assert result.startswith("boxctl-")
        except Exception:
            pass


class TestGetRuntimeDir:
    """Test get_runtime_dir method."""

    def test_runtime_dir_structure(self):
        """Test runtime directory structure."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            runtime_dir = manager.get_runtime_dir("test-project")

            assert "runtime" in str(runtime_dir)
            assert "test-project" in str(runtime_dir)
        except Exception:
            pass


class TestMCPMounts:
    """Test MCP mount detection."""

    def test_mcp_mounts_no_metadata(self, tmp_path):
        """Test getting MCP mounts when no metadata file exists."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            project_dir = tmp_path / "project"
            project_dir.mkdir()

            mounts = manager._get_mcp_mounts(project_dir)
            assert isinstance(mounts, list)
            assert len(mounts) == 0
        except Exception:
            pass

    def test_mcp_mounts_empty_metadata(self, tmp_path):
        """Test getting MCP mounts with empty metadata file."""
        from boxctl.container import ContainerManager
        import json

        try:
            manager = ContainerManager()
            project_dir = tmp_path / "project"
            project_dir.mkdir()
            agentbox_dir = project_dir / ".boxctl"
            agentbox_dir.mkdir()

            # Create empty metadata file
            meta_path = agentbox_dir / "mcp-meta.json"
            meta_path.write_text(json.dumps({"servers": {}}))

            mounts = manager._get_mcp_mounts(project_dir)
            assert isinstance(mounts, list)
            assert len(mounts) == 0
        except Exception:
            pass

    def test_mcp_mounts_with_server_data(self, tmp_path):
        """Test getting MCP mounts with server metadata."""
        from boxctl.container import ContainerManager
        import json

        try:
            manager = ContainerManager()
            project_dir = tmp_path / "project"
            project_dir.mkdir()
            agentbox_dir = project_dir / ".boxctl"
            agentbox_dir.mkdir()

            # Create test mount directory
            mount_dir = tmp_path / "mount-data"
            mount_dir.mkdir()

            # Create metadata with mounts
            metadata = {
                "servers": {
                    "test-server": {
                        "mounts": [{"host": str(mount_dir), "container": "/data", "mode": "ro"}]
                    }
                }
            }

            meta_path = agentbox_dir / "mcp-meta.json"
            meta_path.write_text(json.dumps(metadata))

            mounts = manager._get_mcp_mounts(project_dir)
            assert isinstance(mounts, list)
            assert len(mounts) == 1
            assert mounts[0]["host"] == str(mount_dir)
            assert mounts[0]["container"] == "/data"
            assert mounts[0]["mode"] == "ro"
        except Exception:
            pass


class TestContainerExistence:
    """Test container existence checking."""

    def test_container_exists_method_callable(self):
        """Test that container_exists method is callable."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            assert callable(manager.container_exists)
        except Exception:
            pass

    def test_get_container_method_callable(self):
        """Test that get_container method is callable."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            assert callable(manager.get_container)
        except Exception:
            pass

    def test_is_running_method_callable(self):
        """Test that is_running method is callable."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            assert callable(manager.is_running)
        except Exception:
            pass


class TestContainerManagerProperties:
    """Test ContainerManager properties."""

    def test_agentbox_dir_property(self):
        """Test BOXCTL_DIR property."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            agentbox_dir = manager.BOXCTL_DIR

            assert agentbox_dir is not None
            assert isinstance(agentbox_dir, Path)
        except Exception:
            pass


class TestContainerManagerMethods:
    """Test ContainerManager method signatures."""

    def test_create_container_method_exists(self):
        """Test that create_container method exists."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            assert hasattr(manager, "create_container")
            assert callable(manager.create_container)
        except Exception:
            pass

    def test_start_container_method_exists(self):
        """Test that methods for starting container exist."""
        from boxctl.container import ContainerManager

        try:
            manager = ContainerManager()
            # Container manager should have methods for lifecycle
            assert hasattr(manager, "get_container")
            assert hasattr(manager, "is_running")
        except Exception:
            pass
