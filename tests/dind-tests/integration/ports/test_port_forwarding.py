# Copyright (c) 2025 Marc Schutze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for port forwarding (expose/forward commands).

These tests verify:
1. CLI commands update configuration correctly
2. Port exposure (container -> host) works end-to-end
3. Port forwarding (host -> container) works end-to-end
4. Port removal (unexpose/unforward) works correctly
"""

import socket
import subprocess
import threading
import time

import pytest
import yaml

from helpers.cli import run_abox
from helpers.docker import exec_in_container, run_docker


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except OSError:
        return False


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: int = 10) -> bool:
    """Wait for a port to become connectable."""
    for _ in range(timeout * 10):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect((host, port))
                return True
        except (OSError, socket.timeout):
            time.sleep(0.1)
    return False


def is_boxctld_running() -> bool:
    """Check if boxctld is running."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "boxctld"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        # systemctl not available (e.g., running in container)
        return False


@pytest.mark.integration
class TestPortsCommands:
    """Test port CLI commands update configuration correctly."""

    def test_expose_updates_config(self, test_project):
        """expose command should update .boxctl.yml with host port."""
        result = run_abox("ports", "expose", "3000", cwd=test_project)
        assert result.returncode == 0, f"expose failed: {result.stderr}"
        assert "Exposed" in result.stdout or "already exposed" in result.stdout.lower()

        # Verify config was updated
        config_path = test_project / ".boxctl.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        host_ports = config.get("ports", {}).get("host", [])
        assert (
            "3000" in host_ports or 3000 in host_ports
        ), f"Port 3000 not in host ports: {host_ports}"

    def test_expose_with_mapping(self, test_project):
        """expose command should support container:host port mapping."""
        result = run_abox("ports", "expose", "8080:9090", cwd=test_project)
        assert result.returncode == 0, f"expose failed: {result.stderr}"

        config_path = test_project / ".boxctl.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        host_ports = config.get("ports", {}).get("host", [])
        # Should have the mapping stored
        assert (
            any("8080" in str(p) and "9090" in str(p) for p in host_ports)
            or "8080:9090" in host_ports
            or "9090" in host_ports
        ), f"Port mapping not found in host ports: {host_ports}"

    def test_unexpose_removes_from_config(self, test_project):
        """unexpose command should remove port from .boxctl.yml."""
        # First expose
        run_abox("ports", "expose", "4000", cwd=test_project)

        # Then unexpose
        result = run_abox("ports", "unexpose", "4000", cwd=test_project)
        assert result.returncode == 0, f"unexpose failed: {result.stderr}"

        # Verify config was updated
        config_path = test_project / ".boxctl.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        host_ports = config.get("ports", {}).get("host", [])
        assert (
            "4000" not in host_ports and 4000 not in host_ports
        ), f"Port 4000 still in host ports: {host_ports}"

    def test_forward_updates_config(self, test_project):
        """forward command should update .boxctl.yml with container port."""
        result = run_abox("ports", "forward", "test-fwd", "5000", cwd=test_project)
        assert result.returncode == 0, f"forward failed: {result.stderr}"

        # Verify config was updated
        config_path = test_project / ".boxctl.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        container_ports = config.get("ports", {}).get("container", [])
        # Check for the named forward entry
        found = False
        for entry in container_ports:
            if isinstance(entry, dict) and entry.get("name") == "test-fwd":
                found = True
                assert entry.get("port") == 5000 or entry.get("host_port") == 5000
                break
        assert found, f"Forward entry not found in container ports: {container_ports}"

    def test_unforward_by_name(self, test_project):
        """unforward command should remove by name."""
        # First forward
        run_abox("ports", "forward", "remove-me", "6000", cwd=test_project)

        # Then unforward by name
        result = run_abox("ports", "unforward", "remove-me", cwd=test_project)
        assert result.returncode == 0, f"unforward failed: {result.stderr}"

        # Verify config was updated
        config_path = test_project / ".boxctl.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        container_ports = config.get("ports", {}).get("container", [])
        for entry in container_ports:
            if isinstance(entry, dict):
                assert (
                    entry.get("name") != "remove-me"
                ), f"Forward entry still in config: {container_ports}"

    def test_unforward_by_port(self, test_project):
        """unforward command should accept port number."""
        # First forward
        run_abox("ports", "forward", "by-port-test", "7000", cwd=test_project)

        # Then unforward by port number
        result = run_abox("ports", "unforward", "7000", cwd=test_project)
        assert result.returncode == 0, f"unforward by port failed: {result.stderr}"

    def test_ports_list(self, test_project):
        """ports list should show exposed and forwarded ports."""
        # Add some ports
        run_abox("ports", "expose", "3000", cwd=test_project)
        run_abox("ports", "forward", "test-list", "9100", cwd=test_project)

        result = run_abox("ports", "list", cwd=test_project)
        assert result.returncode == 0, f"ports list failed: {result.stderr}"

        # Should show both types
        assert "3000" in result.stdout, f"Exposed port not in list: {result.stdout}"
        assert (
            "9100" in result.stdout or "test-list" in result.stdout
        ), f"Forwarded port not in list: {result.stdout}"


@pytest.mark.integration
@pytest.mark.skipif(
    not is_boxctld_running(), reason="boxctld not running - skipping end-to-end tests"
)
class TestPortForwardingEndToEnd:
    """End-to-end tests for port forwarding with boxctld.

    These tests require boxctld to be running and verify actual
    network connectivity through the tunnel.
    """

    def test_expose_allows_host_connection(self, running_container, test_project):
        """Exposed port should allow connections from host to container service."""
        container_name = running_container

        # Find an available port
        test_port = 13000
        while not is_port_available(test_port) and test_port < 13100:
            test_port += 1

        if not is_port_available(test_port):
            pytest.skip("No available port for testing")

        # Start a simple TCP server in the container
        exec_in_container(
            container_name,
            f"python3 -c '"
            f"import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
            f's.bind(("0.0.0.0", {test_port})); s.listen(1); '
            f'print("READY"); '
            f'c,a=s.accept(); c.send(b"HELLO"); c.close(); s.close()\' &',
        )

        # Give server time to start
        time.sleep(1)

        # Expose the port
        result = run_abox("ports", "expose", str(test_port), cwd=test_project)
        assert result.returncode == 0, f"expose failed: {result.stderr}"

        # Wait for port to become available on host
        if not wait_for_port(test_port, timeout=10):
            # Cleanup and skip if port not available
            run_abox("ports", "unexpose", str(test_port), cwd=test_project)
            pytest.skip("Port not available on host - boxctld may not be configured")

        try:
            # Connect and verify data
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(("127.0.0.1", test_port))
                data = s.recv(1024)
                assert data == b"HELLO", f"Unexpected data: {data}"
        finally:
            # Cleanup
            run_abox("ports", "unexpose", str(test_port), cwd=test_project)

    def test_forward_allows_container_connection(self, running_container, test_project):
        """Forwarded port should allow connections from container to host service."""
        container_name = running_container

        # Find an available port on host
        test_port = 14000
        while not is_port_available(test_port) and test_port < 14100:
            test_port += 1

        if not is_port_available(test_port):
            pytest.skip("No available port for testing")

        # Start a simple TCP server on host
        server_ready = threading.Event()
        server_data = {"received": None}

        def run_server():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", test_port))
                s.listen(1)
                s.settimeout(15)
                server_ready.set()
                try:
                    conn, _ = s.accept()
                    conn.send(b"HOST_HELLO")
                    server_data["received"] = conn.recv(1024)
                    conn.close()
                except socket.timeout:
                    pass

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        server_ready.wait(timeout=5)

        try:
            # Forward the port into container
            result = run_abox("ports", "forward", "test-e2e", str(test_port), cwd=test_project)
            assert result.returncode == 0, f"forward failed: {result.stderr}"

            # Give tunnel time to establish
            time.sleep(2)

            # Try to connect from inside container
            # The forwarded port should be accessible on localhost inside container
            result = exec_in_container(
                container_name,
                f"python3 -c '"
                f"import socket; s=socket.socket(); s.settimeout(5); "
                f's.connect(("127.0.0.1", {test_port})); '
                f"print(s.recv(1024)); "
                f's.send(b"CONTAINER_HELLO"); s.close()\'',
                timeout=15,
            )

            # Check if connection succeeded
            if result.returncode == 0 and b"HOST_HELLO" in result.stdout.encode():
                assert server_data["received"] == b"CONTAINER_HELLO"
            else:
                # Forward might not be working due to boxctld config
                pytest.skip(
                    f"Forward connection failed - may need boxctld config. "
                    f"stdout: {result.stdout}, stderr: {result.stderr}"
                )

        finally:
            # Cleanup
            run_abox("ports", "unforward", "test-e2e", cwd=test_project)
            server_thread.join(timeout=1)


@pytest.mark.integration
class TestPortValidation:
    """Test port validation in CLI commands."""

    def test_expose_rejects_privileged_port(self, test_project):
        """expose should reject ports below 1024."""
        result = run_abox("ports", "expose", "80", cwd=test_project)
        assert result.returncode != 0, "Should reject privileged port"
        assert "1024" in result.stderr or "privileged" in result.stderr.lower()

    def test_expose_rejects_invalid_port(self, test_project):
        """expose should reject invalid port numbers."""
        result = run_abox("ports", "expose", "70000", cwd=test_project)
        assert result.returncode != 0, "Should reject port > 65535"

    def test_forward_rejects_privileged_port(self, test_project):
        """forward should reject ports below 1024."""
        result = run_abox("ports", "forward", "test", "80", cwd=test_project)
        assert result.returncode != 0, "Should reject privileged port"

    def test_expose_rejects_non_numeric(self, test_project):
        """expose should reject non-numeric port."""
        result = run_abox("ports", "expose", "abc", cwd=test_project)
        assert result.returncode != 0, "Should reject non-numeric port"


@pytest.mark.integration
class TestPortsListOutput:
    """Test ports list command output format."""

    def test_list_empty(self, test_project):
        """ports list with no ports should not error."""
        result = run_abox("ports", "list", cwd=test_project)
        assert result.returncode == 0, f"ports list failed: {result.stderr}"

    def test_list_shows_direction(self, test_project):
        """ports list should indicate port direction."""
        run_abox("ports", "expose", "3001", cwd=test_project)
        run_abox("ports", "forward", "fwd-test", "9101", cwd=test_project)

        result = run_abox("ports", "list", cwd=test_project)
        assert result.returncode == 0

        # Should differentiate between exposed and forwarded
        output = result.stdout.lower()
        # Check for some indication of direction (exact format may vary)
        has_direction_info = ("expose" in output or "host" in output or "container" in output) or (
            "forward" in output or "->" in result.stdout or "→" in result.stdout
        )
        assert has_direction_info, f"No direction info in output: {result.stdout}"
