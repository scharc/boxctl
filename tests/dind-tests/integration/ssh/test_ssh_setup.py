# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for SSH configuration modes."""

from pathlib import Path

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container, wait_for_container_ready


@pytest.mark.integration
class TestSSHModes:
    """Validate SSH mode configuration behavior."""

    def test_ssh_mode_disabled(self, test_project):
        """Test disabled SSH mode - no SSH access."""
        config_file = test_project / ".boxctl.yml"
        config_file.write_text(
            """version: "1.0"
ssh:
  enabled: false
""",
            encoding="utf-8",
        )

        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"start failed: {result.stderr}"

        container_name = f"boxctl-{test_project.name}"
        assert wait_for_container_ready(container_name, timeout=60), "container not ready"

        # SSH directory should not exist or be empty
        result = exec_in_container(container_name, "test -d /home/abox/.ssh")
        assert result.returncode != 0, "SSH directory exists in disabled mode"

        run_abox("stop", cwd=test_project)

    def test_ssh_mode_keys(self, test_project):
        """Test keys SSH mode - isolated writable known_hosts."""
        config_file = test_project / ".boxctl.yml"
        config_file.write_text(
            """version: "1.0"
ssh:
  mode: "keys"
""",
            encoding="utf-8",
        )

        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"start failed: {result.stderr}"

        container_name = f"boxctl-{test_project.name}"
        assert wait_for_container_ready(container_name, timeout=60), "container not ready"

        # Test 1: SSH directory exists
        result = exec_in_container(container_name, "test -d /home/abox/.ssh")
        assert result.returncode == 0, "SSH directory not created"

        # Test 2: known_hosts is writable
        result = exec_in_container(container_name, "test -w /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "known_hosts not writable in copy mode"

        # Test 3: Write succeeds
        result = exec_in_container(
            container_name, 'echo "test.example.com ssh-rsa FAKE" >> /home/abox/.ssh/known_hosts'
        )
        assert result.returncode == 0, f"Cannot write to known_hosts: {result.stderr}"

        # Test 4: Verify write persisted
        result = exec_in_container(
            container_name, "grep test.example.com /home/abox/.ssh/known_hosts"
        )
        assert result.returncode == 0, "Write to known_hosts did not persist"

        # Test 5: SSH directory has correct permissions (700)
        result = exec_in_container(container_name, "stat -c '%a' /home/abox/.ssh")
        assert result.returncode == 0
        assert "700" in result.stdout, f"SSH directory has wrong permissions: {result.stdout}"

        run_abox("stop", cwd=test_project)

    def test_ssh_mode_mount(self, test_project):
        """Test mount SSH mode - bind mount read-write."""
        config_file = test_project / ".boxctl.yml"
        config_file.write_text(
            """version: "1.0"
ssh:
  mode: "mount"
""",
            encoding="utf-8",
        )

        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"start failed: {result.stderr}"

        container_name = f"boxctl-{test_project.name}"
        assert wait_for_container_ready(container_name, timeout=60), "container not ready"

        # Test 1: SSH directory exists
        result = exec_in_container(container_name, "test -d /home/abox/.ssh")
        assert result.returncode == 0, "SSH directory not present"

        # Test 2: known_hosts is writable
        result = exec_in_container(container_name, "test -w /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "known_hosts not writable in mount mode"

        # Test 3: Write succeeds (would sync to host in real usage)
        result = exec_in_container(
            container_name,
            'echo "mount-test.example.com ssh-rsa FAKE" >> /home/abox/.ssh/known_hosts',
        )
        assert result.returncode == 0, f"Cannot write to known_hosts: {result.stderr}"

        run_abox("stop", cwd=test_project)

    def test_ssh_mode_config(self, test_project):
        """Test config SSH mode - config/known_hosts only, no keys."""
        config_file = test_project / ".boxctl.yml"
        config_file.write_text(
            """version: "1.0"
ssh:
  mode: "config"
""",
            encoding="utf-8",
        )

        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"start failed: {result.stderr}"

        container_name = f"boxctl-{test_project.name}"
        assert wait_for_container_ready(container_name, timeout=60), "container not ready"

        # Test 1: Config and known_hosts exist
        result = exec_in_container(container_name, "test -f /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "known_hosts missing in config mode"

        # Test 2: known_hosts is writable
        result = exec_in_container(container_name, "test -w /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "known_hosts not writable in config mode"

        # Test 3: Private keys are NOT present
        result = exec_in_container(container_name, "ls /home/abox/.ssh/id_* 2>/dev/null")
        assert result.returncode != 0, "Private keys found in config mode"

        run_abox("stop", cwd=test_project)

    def test_ssh_mode_keys_with_forward_agent(self, test_project):
        """Test keys mode combined with agent forwarding."""
        config_file = test_project / ".boxctl.yml"
        config_file.write_text(
            """version: "1.0"
ssh:
  mode: "keys"
  forward_agent: true
""",
            encoding="utf-8",
        )

        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"start failed: {result.stderr}"

        container_name = f"boxctl-{test_project.name}"
        assert wait_for_container_ready(container_name, timeout=60), "container not ready"

        # Test: SSH directory exists with keys (copy mode)
        result = exec_in_container(container_name, "test -d /home/abox/.ssh")
        assert result.returncode == 0, "SSH directory not created"

        # Test: known_hosts is writable
        result = exec_in_container(container_name, "test -w /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "known_hosts not writable"

        run_abox("stop", cwd=test_project)

    def test_known_hosts_created_if_missing(self, test_project):
        """Test that known_hosts is created if it doesn't exist."""
        config_file = test_project / ".boxctl.yml"
        config_file.write_text(
            """version: "1.0"
ssh:
  mode: "keys"
""",
            encoding="utf-8",
        )

        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"start failed: {result.stderr}"

        container_name = f"boxctl-{test_project.name}"
        assert wait_for_container_ready(container_name, timeout=60), "container not ready"

        # Test: known_hosts should exist even if not in host SSH
        result = exec_in_container(container_name, "test -f /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "known_hosts not auto-created"

        result = exec_in_container(container_name, "test -w /home/abox/.ssh/known_hosts")
        assert result.returncode == 0, "auto-created known_hosts not writable"

        run_abox("stop", cwd=test_project)
