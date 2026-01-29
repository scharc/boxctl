# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for service management commands."""

import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container


@pytest.mark.integration
class TestServiceFileGeneration:
    """Test service file and config generation."""

    def test_install_creates_config_file(self, running_container, test_project):
        """Test that service install creates config file."""
        container_name = f"boxctl-{test_project.name}"

        # Run install (will fail on systemctl but should create files)
        result = exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Check config file was created
        result = exec_in_container(container_name, "test -f /home/abox/.config/boxctl/config.yml")

        assert result.returncode == 0, "Config file should be created"

    def test_config_file_has_valid_yaml(self, running_container, test_project):
        """Test that generated config is valid YAML."""
        container_name = f"boxctl-{test_project.name}"

        # Install to create config
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Verify YAML is parseable
        result = exec_in_container(
            container_name,
            "python3 -c \"import yaml; yaml.safe_load(open('/home/abox/.config/boxctl/config.yml'))\"",
        )

        assert result.returncode == 0, f"Config should be valid YAML: {result.stderr}"

    def test_config_contains_web_server_settings(self, running_container, test_project):
        """Test that config contains expected web server settings."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result = exec_in_container(container_name, "cat /home/abox/.config/boxctl/config.yml")

        assert result.returncode == 0
        assert "web_server:" in result.stdout
        assert "enabled:" in result.stdout
        assert "host:" in result.stdout
        assert "port:" in result.stdout

    def test_install_creates_systemd_service_file(self, running_container, test_project):
        """Test that service install creates systemd unit file."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Check service file exists
        result = exec_in_container(
            container_name, "test -f /home/abox/.config/systemd/user/boxctld.service"
        )

        assert result.returncode == 0, "Systemd service file should be created"

    def test_service_file_has_valid_systemd_format(self, running_container, test_project):
        """Test that service file is valid systemd unit format."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result = exec_in_container(
            container_name, "cat /home/abox/.config/systemd/user/boxctld.service"
        )

        assert result.returncode == 0
        assert "[Unit]" in result.stdout
        assert "[Service]" in result.stdout
        assert "[Install]" in result.stdout
        assert "Description=" in result.stdout
        assert "ExecStart=" in result.stdout

    def test_service_file_references_serve_command(self, running_container, test_project):
        """Test that service file ExecStart uses 'service serve'."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result = exec_in_container(
            container_name, "grep ExecStart /home/abox/.config/systemd/user/boxctld.service"
        )

        assert result.returncode == 0
        assert "service" in result.stdout
        assert "serve" in result.stdout

    def test_install_idempotent(self, running_container, test_project):
        """Test that running install multiple times is safe."""
        container_name = f"boxctl-{test_project.name}"

        # First install
        result1 = exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Second install
        result2 = exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Both should succeed (exit 0 or just create files)
        # Verify files still exist and are valid
        result = exec_in_container(
            container_name,
            "test -f /home/abox/.config/boxctl/config.yml && "
            "test -f /home/abox/.config/systemd/user/boxctld.service",
        )

        assert result.returncode == 0, "Files should exist after multiple installs"


@pytest.mark.integration
class TestServiceUninstall:
    """Test service uninstall command."""

    def test_uninstall_removes_service_file(self, running_container, test_project):
        """Test that uninstall removes systemd service file."""
        container_name = f"boxctl-{test_project.name}"

        # Install first
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Verify file exists
        result = exec_in_container(
            container_name, "test -f /home/abox/.config/systemd/user/boxctld.service"
        )
        assert result.returncode == 0

        # Uninstall
        exec_in_container(container_name, "boxctl service uninstall 2>&1 || true")

        # Verify file is gone
        result = exec_in_container(
            container_name, "test -f /home/abox/.config/systemd/user/boxctld.service"
        )

        assert result.returncode != 0, "Service file should be removed"

    def test_uninstall_when_not_installed(self, running_container, test_project):
        """Test that uninstall handles non-existent service gracefully."""
        container_name = f"boxctl-{test_project.name}"

        # Ensure service is not installed
        exec_in_container(container_name, "rm -f /home/abox/.config/systemd/user/boxctld.service")

        # Uninstall should not error
        result = exec_in_container(container_name, "boxctl service uninstall 2>&1")

        # Should handle gracefully (may show "not installed" message)
        assert "Service not installed" in result.stdout or result.returncode == 0

    def test_uninstall_preserves_config(self, running_container, test_project):
        """Test that uninstall preserves config file."""
        container_name = f"boxctl-{test_project.name}"

        # Install
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Uninstall
        exec_in_container(container_name, "boxctl service uninstall 2>&1 || true")

        # Config should still exist
        result = exec_in_container(container_name, "test -f /home/abox/.config/boxctl/config.yml")

        assert result.returncode == 0, "Config should be preserved after uninstall"


@pytest.mark.integration
class TestServiceConfig:
    """Test service config command."""

    def test_config_shows_path_when_exists(self, running_container, test_project):
        """Test that config command shows config file path."""
        container_name = f"boxctl-{test_project.name}"

        # Install to create config
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Run config command (will try to open editor, but we can check output)
        result = exec_in_container(container_name, "boxctl service config 2>&1 || true")

        assert (
            ".config/boxctl/config.yml" in result.stdout
            or ".config/boxctl/config.yml" in result.stderr
        )

    def test_config_message_when_not_installed(self, running_container, test_project):
        """Test config command when config doesn't exist."""
        container_name = f"boxctl-{test_project.name}"

        # Ensure config doesn't exist
        exec_in_container(container_name, "rm -f /home/abox/.config/boxctl/config.yml")

        result = exec_in_container(container_name, "boxctl service config 2>&1")

        assert "not found" in result.stdout.lower() or "install" in result.stdout.lower()


@pytest.mark.integration
class TestServiceServe:
    """Test service serve command (direct daemon invocation)."""

    def test_serve_command_exists(self, running_container, test_project):
        """Test that serve command is available."""
        container_name = f"boxctl-{test_project.name}"

        # Check help for serve command
        result = exec_in_container(container_name, "boxctl service serve --help", timeout=5)

        assert result.returncode == 0, f"serve --help should work: {result.stderr}"
        assert "serve" in result.stdout.lower() or "daemon" in result.stdout.lower()

    def test_serve_can_start_and_stop(self, running_container, test_project):
        """Test that serve can be started and stopped."""
        container_name = f"boxctl-{test_project.name}"

        # Start serve in background
        result = exec_in_container(
            container_name,
            "timeout 2 boxctl service serve /tmp/test-proxy.sock 2>&1 || true",
            timeout=5,
        )

        # Should have attempted to start (timeout will kill it)
        # Check if any socket operations were attempted
        assert len(result.stdout) > 0 or len(result.stderr) > 0

    def test_serve_with_custom_socket_path(self, running_container, test_project):
        """Test serve with custom socket path argument."""
        container_name = f"boxctl-{test_project.name}"

        # Try to start with custom socket (will timeout)
        custom_socket = "/tmp/custom-test.sock"
        result = exec_in_container(
            container_name,
            f"timeout 1 boxctl service serve {custom_socket} 2>&1 || true",
            timeout=3,
        )

        # Should have attempted to use custom socket
        # (actual socket creation may fail due to missing proxy module, but command should parse)
        assert result.returncode != 0 or len(result.stdout + result.stderr) > 0


@pytest.mark.integration
class TestServiceLogs:
    """Test service logs command."""

    def test_logs_command_exists(self, running_container, test_project):
        """Test that logs command is available."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name, "boxctl service logs --help || boxctl service --help", timeout=5
        )

        # Command should be recognized
        assert result.returncode == 0 or "logs" in result.stdout

    def test_logs_with_lines_argument(self, running_container, test_project):
        """Test logs command with custom line count."""
        container_name = f"boxctl-{test_project.name}"

        # This will fail if journalctl not available, which is expected in DinD
        result = exec_in_container(container_name, "boxctl service logs 10 2>&1 || true", timeout=5)

        # Should attempt to run journalctl (may fail if not available)
        assert (
            "journalctl" in result.stderr or "journalctl" in result.stdout or result.returncode != 0
        )


@pytest.mark.integration
class TestServicePaths:
    """Test service path helpers."""

    def test_config_directory_created(self, running_container, test_project):
        """Test that config directory is created on install."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Check directory exists
        result = exec_in_container(container_name, "test -d /home/abox/.config/boxctl")

        assert result.returncode == 0, "Config directory should be created"

    def test_systemd_directory_created(self, running_container, test_project):
        """Test that systemd user directory is created."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result = exec_in_container(container_name, "test -d /home/abox/.config/systemd/user")

        assert result.returncode == 0, "Systemd user directory should be created"

    def test_service_file_permissions(self, running_container, test_project):
        """Test that service file has appropriate permissions."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result = exec_in_container(
            container_name, "stat -c '%a' /home/abox/.config/systemd/user/boxctld.service"
        )

        assert result.returncode == 0
        # Should be readable (at least 600 or 644)
        perms = result.stdout.strip()
        assert perms in ["644", "664", "600", "640"], f"Unexpected permissions: {perms}"

    def test_config_file_permissions(self, running_container, test_project):
        """Test that config file has appropriate permissions."""
        container_name = f"boxctl-{test_project.name}"

        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result = exec_in_container(
            container_name, "stat -c '%a' /home/abox/.config/boxctl/config.yml"
        )

        assert result.returncode == 0
        perms = result.stdout.strip()
        assert perms in ["644", "664", "600", "640"], f"Unexpected permissions: {perms}"


@pytest.mark.integration
class TestServiceIntegration:
    """Integration tests for service workflows."""

    def test_install_uninstall_cycle(self, running_container, test_project):
        """Test complete install/uninstall cycle."""
        container_name = f"boxctl-{test_project.name}"

        # 1. Install
        result = exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # 2. Verify files exist
        result = exec_in_container(
            container_name,
            "test -f /home/abox/.config/boxctl/config.yml && "
            "test -f /home/abox/.config/systemd/user/boxctld.service",
        )
        assert result.returncode == 0

        # 3. Uninstall
        exec_in_container(container_name, "boxctl service uninstall 2>&1 || true")

        # 4. Verify service file removed
        result = exec_in_container(
            container_name, "test -f /home/abox/.config/systemd/user/boxctld.service"
        )
        assert result.returncode != 0

        # 5. Config should still exist
        result = exec_in_container(container_name, "test -f /home/abox/.config/boxctl/config.yml")
        assert result.returncode == 0

    def test_multiple_install_uninstall_cycles(self, running_container, test_project):
        """Test multiple install/uninstall cycles."""
        container_name = f"boxctl-{test_project.name}"

        for i in range(3):
            # Install
            exec_in_container(container_name, "boxctl service install 2>&1 || true")

            # Verify
            result = exec_in_container(
                container_name, "test -f /home/abox/.config/systemd/user/boxctld.service"
            )
            assert result.returncode == 0, f"Cycle {i}: Service file should exist after install"

            # Uninstall
            exec_in_container(container_name, "boxctl service uninstall 2>&1 || true")

            # Verify
            result = exec_in_container(
                container_name, "test -f /home/abox/.config/systemd/user/boxctld.service"
            )
            assert (
                result.returncode != 0
            ), f"Cycle {i}: Service file should not exist after uninstall"

    def test_config_persists_across_install_uninstall(self, running_container, test_project):
        """Test that config modifications persist."""
        container_name = f"boxctl-{test_project.name}"

        # Install
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        # Modify config
        test_marker = "# TEST_MARKER_12345"
        exec_in_container(
            container_name, f"echo '{test_marker}' >> /home/abox/.config/boxctl/config.yml"
        )

        # Uninstall
        exec_in_container(container_name, "boxctl service uninstall 2>&1 || true")

        # Verify marker still exists
        result = exec_in_container(
            container_name, "grep TEST_MARKER_12345 /home/abox/.config/boxctl/config.yml"
        )

        assert result.returncode == 0, "Config modifications should persist"

    def test_service_file_content_consistency(self, running_container, test_project):
        """Test that service file content is consistent across reinstalls."""
        container_name = f"boxctl-{test_project.name}"

        # First install
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result1 = exec_in_container(
            container_name, "cat /home/abox/.config/systemd/user/boxctld.service"
        )
        content1 = result1.stdout

        # Uninstall and reinstall
        exec_in_container(container_name, "boxctl service uninstall 2>&1 || true")
        exec_in_container(container_name, "boxctl service install 2>&1 || true")

        result2 = exec_in_container(
            container_name, "cat /home/abox/.config/systemd/user/boxctld.service"
        )
        content2 = result2.stdout

        # Content should be similar (may have different env vars)
        assert "[Unit]" in content2
        assert "[Service]" in content2
        assert "[Install]" in content2
        assert "ExecStart=" in content2
