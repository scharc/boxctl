# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Unit tests for host configuration management."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

# Import from the boxctl package
import sys

sys.path.insert(0, "/workspace")

from boxctl.host_config import HostConfig, get_config, get_tailscale_ip


class TestHostConfigDefaults:
    """Test default configuration values."""

    def test_defaults_loaded_when_no_file(self, tmp_path, monkeypatch):
        """Test that defaults are used when config file doesn't exist."""
        # Set home to temp dir so config doesn't exist
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        assert config._config["version"] == "1.0"
        assert config._config["web_server"]["enabled"] is True
        assert config._config["web_server"]["port"] == 8080

    def test_default_web_server_config(self, tmp_path, monkeypatch):
        """Test default web server configuration."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        web_config = config._config["web_server"]
        assert web_config["enabled"] is True
        # hosts defaults to empty, host defaults to 127.0.0.1 (fallback)
        assert web_config["hosts"] == []
        assert web_config["host"] == "127.0.0.1"
        assert web_config["port"] == 8080
        assert web_config["log_level"] == "info"

    def test_default_notifications_config(self, tmp_path, monkeypatch):
        """Test default notifications configuration."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        notif_config = config._config["notifications"]
        assert notif_config["timeout"] == 2.0
        assert notif_config["timeout_enhanced"] == 60.0
        assert "deduplication_window" in notif_config

    def test_default_timeouts_config(self, tmp_path, monkeypatch):
        """Test default timeouts configuration."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        timeouts = config._config["timeouts"]
        assert timeouts["container_wait"] == 6.0
        assert "web_connection" in timeouts
        assert "proxy_connection" in timeouts


class TestHostConfigLoading:
    """Test configuration file loading."""

    def test_load_valid_config_file(self, tmp_path, monkeypatch):
        """Test loading a valid config file."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"web_server": {"port": 9090, "enabled": False}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config._config["web_server"]["port"] == 9090
        assert config._config["web_server"]["enabled"] is False

    def test_merge_with_defaults(self, tmp_path, monkeypatch):
        """Test that loaded config merges with defaults."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {
            "web_server": {
                "port": 9090,
            }
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        # Custom value
        assert config._config["web_server"]["port"] == 9090
        # Default values still present
        assert config._config["web_server"]["enabled"] is True
        assert "timeouts" in config._config

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path, monkeypatch, caplog):
        """Test that invalid YAML falls back to defaults."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        with open(config_file, "w") as f:
            f.write("invalid: yaml: content: [[[")

        config = HostConfig()

        # Should fall back to defaults
        assert config._config["version"] == "1.0"
        assert "web_server" in config._config

        # Should have logged warning
        assert any("Failed" in record.message for record in caplog.records)

    def test_empty_config_file_uses_defaults(self, tmp_path, monkeypatch):
        """Test that empty config file uses defaults."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_file.write_text("")

        config = HostConfig()

        assert config._config["version"] == "1.0"
        assert config._config["web_server"]["port"] == 8080


class TestHostConfigProperties:
    """Test configuration properties."""

    def test_agentbox_dir_from_env(self, tmp_path, monkeypatch):
        """Test agentbox_dir from BOXCTL_DIR environment variable."""
        test_dir = tmp_path / "custom_agentbox"
        monkeypatch.setenv("BOXCTL_DIR", str(test_dir))
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        assert config.boxctl_dir == test_dir

    def test_agentbox_dir_from_config(self, tmp_path, monkeypatch):
        """Test agentbox_dir from config file."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        test_dir = tmp_path / "config_agentbox"
        config_file = config_dir / "config.yml"
        config_data = {"paths": {"agentbox_dir": str(test_dir)}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.boxctl_dir == test_dir

    def test_socket_path_default(self, tmp_path, monkeypatch):
        """Test default socket path."""
        monkeypatch.setenv("HOME", str(tmp_path))
        # Socket path uses XDG_RUNTIME_DIR, not HOME
        runtime_dir = tmp_path / "run"
        runtime_dir.mkdir()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))

        config = HostConfig()

        socket_path = config.socket_path
        assert str(socket_path).startswith(str(runtime_dir))
        assert "boxctl" in str(socket_path)
        assert ".sock" in str(socket_path)

    def test_web_server_url(self, tmp_path, monkeypatch):
        """Test web server URL generation."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        url = config.web_server_url
        assert url.startswith("http://")
        assert ":8080" in url

    def test_web_server_url_with_custom_port(self, tmp_path, monkeypatch):
        """Test web server URL with custom port."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"web_server": {"port": 9999}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        url = config.web_server_url
        assert ":9999" in url

    def test_get_web_server_hosts(self, tmp_path, monkeypatch):
        """Test getting web server hosts list."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        hosts = config.get_web_server_hosts()
        assert isinstance(hosts, list)
        assert len(hosts) > 0
        assert "127.0.0.1" in hosts


class TestHostConfigGet:
    """Test config.get() method."""

    def test_get_nested_value(self, tmp_path, monkeypatch):
        """Test getting nested config values."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        port = config.get("web_server", "port")
        assert port == 8080

    def test_get_with_default(self, tmp_path, monkeypatch):
        """Test get() with default value."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        value = config.get("nonexistent", "key", default="default_value")
        assert value == "default_value"

    def test_get_deep_nested(self, tmp_path, monkeypatch):
        """Test getting deeply nested values."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        timeout = config.get("timeouts", "container_wait")
        assert timeout == 6.0


class TestDeepMerge:
    """Test deep merge functionality."""

    def test_deep_merge_preserves_base(self, tmp_path, monkeypatch):
        """Test that deep merge preserves base values."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {
            "web_server": {
                "port": 9090,
            }
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        # Custom value overrides
        assert config._config["web_server"]["port"] == 9090
        # Base values preserved
        assert config._config["web_server"]["enabled"] is True
        assert "hosts" in config._config["web_server"]

    def test_deep_merge_nested_dicts(self, tmp_path, monkeypatch):
        """Test deep merge with nested dictionaries."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {
            "timeouts": {
                "container_wait": 10.0,
            }
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        # Custom nested value
        assert config._config["timeouts"]["container_wait"] == 10.0
        # Other timeout values preserved
        assert "web_connection" in config._config["timeouts"]


class TestGetConfigSingleton:
    """Test get_config() function."""

    def test_get_config_returns_instance(self, tmp_path, monkeypatch):
        """Test that get_config() returns HostConfig instance."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = get_config()

        assert isinstance(config, HostConfig)
        assert hasattr(config, "web_server_url")

    def test_get_config_has_defaults(self, tmp_path, monkeypatch):
        """Test that get_config() instance has defaults."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = get_config()

        assert config._config["version"] == "1.0"
        assert "web_server" in config._config


class TestTailscaleIntegration:
    """Test Tailscale-related functionality."""

    def test_get_tailscale_ip(self, monkeypatch):
        """Test getting Tailscale IP (may fail if not installed)."""
        # This test is informational - Tailscale may not be available
        ip = get_tailscale_ip()

        # Should return None or valid IP
        assert ip is None or (isinstance(ip, str) and len(ip) > 0)

    def test_has_tailscale_in_hosts(self, tmp_path, monkeypatch):
        """Test checking for Tailscale in hosts."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"web_server": {"hosts": ["127.0.0.1", "tailscale"]}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.has_tailscale_in_hosts() is True

    def test_has_tailscale_in_hosts_false(self, tmp_path, monkeypatch):
        """Test has_tailscale_in_hosts when not present."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        # Default doesn't have tailscale
        assert config.has_tailscale_in_hosts() is False


class TestConfigEdgeCases:
    """Test edge cases and error handling."""

    def test_config_with_null_values(self, tmp_path, monkeypatch):
        """Test config with null values."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"web_server": None}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        # Null sections override defaults in current implementation
        # The model falls back to defaults but deep_merge replaces with null
        # This is a known limitation - should use the model for access
        assert "web_server" in config._config
        # Use accessor method instead of raw config for null handling
        hosts = config.get_web_server_hosts()
        assert "127.0.0.1" in hosts

    def test_config_with_extra_keys(self, tmp_path, monkeypatch):
        """Test config with keys not in defaults."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"custom_section": {"custom_key": "custom_value"}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        # Custom keys should be preserved
        assert "custom_section" in config._config
        assert config._config["custom_section"]["custom_key"] == "custom_value"

    def test_config_path_property(self, tmp_path, monkeypatch):
        """Test that config_path is set correctly."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        assert config.config_path == tmp_path / ".config" / "boxctl" / "config.yml"


class TestNetworkBindAddresses:
    """Test network.bind_addresses configuration."""

    def test_default_bind_addresses(self, tmp_path, monkeypatch):
        """Test default bind addresses include localhost and tailscale."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        network_config = config._config.get("network", {})
        bind_addresses = network_config.get("bind_addresses", [])

        assert "127.0.0.1" in bind_addresses
        assert "tailscale" in bind_addresses

    def test_get_port_bind_addresses_returns_list(self, tmp_path, monkeypatch):
        """Test get_port_bind_addresses returns a list."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        addresses = config.get_port_bind_addresses()
        assert isinstance(addresses, list)
        assert len(addresses) > 0

    def test_get_port_bind_addresses_includes_localhost(self, tmp_path, monkeypatch):
        """Test get_port_bind_addresses always includes localhost."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config = HostConfig()

        addresses = config.get_port_bind_addresses()
        assert "127.0.0.1" in addresses

    def test_custom_bind_addresses(self, tmp_path, monkeypatch):
        """Test custom bind addresses from config."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"network": {"bind_addresses": ["127.0.0.1", "10.0.0.1"]}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        addresses = config.get_port_bind_addresses()
        assert "127.0.0.1" in addresses
        assert "10.0.0.1" in addresses

    def test_has_tailscale_in_bind_addresses_true(self, tmp_path, monkeypatch):
        """Test has_tailscale_in_bind_addresses when tailscale is present."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"network": {"bind_addresses": ["127.0.0.1", "tailscale"]}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.has_tailscale_in_bind_addresses() is True

    def test_has_tailscale_in_bind_addresses_false(self, tmp_path, monkeypatch):
        """Test has_tailscale_in_bind_addresses when tailscale is not present."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"network": {"bind_addresses": ["127.0.0.1"]}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.has_tailscale_in_bind_addresses() is False

    def test_uses_tailscale_web_server_only(self, tmp_path, monkeypatch):
        """Test uses_tailscale when only web_server has tailscale."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {
            "web_server": {"hosts": ["127.0.0.1", "tailscale"]},
            "network": {"bind_addresses": ["127.0.0.1"]},
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.uses_tailscale() is True

    def test_uses_tailscale_bind_addresses_only(self, tmp_path, monkeypatch):
        """Test uses_tailscale when only bind_addresses has tailscale."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {
            "web_server": {"hosts": ["127.0.0.1"]},
            "network": {"bind_addresses": ["127.0.0.1", "tailscale"]},
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.uses_tailscale() is True

    def test_uses_tailscale_neither(self, tmp_path, monkeypatch):
        """Test uses_tailscale when neither has tailscale."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {
            "web_server": {"hosts": ["127.0.0.1"]},
            "network": {"bind_addresses": ["127.0.0.1"]},
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        assert config.uses_tailscale() is False

    def test_bind_addresses_localhost_only(self, tmp_path, monkeypatch):
        """Test bind addresses with only localhost (no tailscale)."""
        monkeypatch.setenv("HOME", str(tmp_path))

        config_dir = tmp_path / ".config" / "boxctl"
        config_dir.mkdir(parents=True)

        config_file = config_dir / "config.yml"
        config_data = {"network": {"bind_addresses": ["127.0.0.1"]}}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = HostConfig()

        addresses = config.get_port_bind_addresses()
        assert addresses == ["127.0.0.1"]
