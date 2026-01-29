# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for ProjectConfig hostname functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from boxctl.config import ProjectConfig


def test_config_hostname_property():
    """Test that hostname property works."""
    # Create a temporary config file
    import tempfile
    import yaml

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        config_file = project_dir / ".boxctl" / "config.yml"
        config_file.parent.mkdir(exist_ok=True)

        # Create config with hostname
        config_data = {"version": "1.0", "hostname": "test-host"}

        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        # Load config
        config = ProjectConfig(project_dir)

        # Verify hostname is read correctly
        assert config.hostname == "test-host"


def test_config_no_hostname():
    """Test that hostname returns None when not configured."""
    import tempfile
    import yaml

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        config_file = project_dir / ".boxctl" / "config.yml"
        config_file.parent.mkdir(exist_ok=True)

        # Create config without hostname
        config_data = {"version": "1.0"}

        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        # Load config
        config = ProjectConfig(project_dir)

        # Verify hostname is None
        assert config.hostname is None


def test_config_rebuild_with_hostname_doesnt_crash():
    """Test that rebuild with hostname doesn't crash (even though feature not implemented)."""
    import tempfile
    import yaml

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        config_file = project_dir / ".boxctl" / "config.yml"
        config_file.parent.mkdir(exist_ok=True)

        # Create config with hostname
        config_data = {"version": "1.0", "hostname": "test-host"}

        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        # Load config
        config = ProjectConfig(project_dir)

        # Mock the container manager
        mock_manager = Mock()

        # This should not crash even though NetworkManager doesn't exist
        # The code now prints a warning instead of importing non-existent module
        with patch("boxctl.config.console"):
            # Should not raise ImportError
            config.rebuild(mock_manager, "test-container")


def test_config_rebuild_without_hostname():
    """Test that rebuild without hostname works normally."""
    import tempfile
    import yaml

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        config_file = project_dir / ".boxctl" / "config.yml"
        config_file.parent.mkdir(exist_ok=True)

        # Create config without hostname
        config_data = {"version": "1.0"}

        with open(config_file, "w") as f:
            yaml.safe_dump(config_data, f)

        # Load config
        config = ProjectConfig(project_dir)

        # Mock the container manager
        mock_manager = Mock()

        # Should work fine
        with patch("boxctl.config.console"):
            config.rebuild(mock_manager, "test-container")
