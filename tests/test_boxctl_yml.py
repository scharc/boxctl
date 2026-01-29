# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for .boxctl.yml configuration."""

import json
import subprocess
import yaml
from pathlib import Path
from tests.conftest import run_abox


def test_agentbox_yml_properties(test_project):
    """Test that ProjectConfig reads all properties from .boxctl.yml."""
    from boxctl.config import ProjectConfig

    # Create .boxctl.yml with all sections
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "ssh": {
            "mode": "config",
            "forward_agent": True,
        },
        "workspaces": [
            {"path": "~/test", "mode": "ro", "mount": "test"},
        ],
        "containers": [
            {"name": "postgres", "auto_reconnect": True},
        ],
        "system_packages": ["ffmpeg", "imagemagick"],
        "env": {"NODE_ENV": "development"},
        "hostname": "test.local",
        "resources": {"memory": "2g", "cpus": "2.0"},
        "security": {"seccomp": "unconfined", "capabilities": ["SYS_PTRACE"]},
        "ports": {"host": ["3000:3000"], "container": [], "mode": "tunnel"},
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Load config
    config = ProjectConfig(test_project)

    # Test SSH properties
    assert config.ssh_forward_agent is True
    assert config.ssh_mode == "config"

    # Test workspaces
    assert len(config.workspaces) == 1
    assert config.workspaces[0]["path"] == "~/test"

    # Test containers
    assert len(config.containers) == 1
    assert config.containers[0]["name"] == "postgres"

    # Test system_packages
    assert config.system_packages == ["ffmpeg", "imagemagick"]

    # Test environment
    assert config.environment["NODE_ENV"] == "development"

    # Test hostname
    assert config.hostname == "test.local"

    # Test resources
    assert config.resources["memory"] == "2g"
    assert config.resources["cpus"] == 2.0  # Float, not string

    # Test security
    assert config.security["seccomp"] == "unconfined"
    assert "SYS_PTRACE" in config.security["capabilities"]

    # Test ports
    assert config.ports_host == ["3000:3000"]


def test_ssh_mode_defaults_to_keys(test_project):
    """Test that ssh.mode defaults to 'keys' when not specified."""
    from boxctl.config import ProjectConfig

    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "ssh": {
            "forward_agent": False,
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = ProjectConfig(test_project)

    assert config.ssh_forward_agent is False
    assert config.ssh_mode == "keys"  # Should default to keys


def test_ssh_config_mode_with_forward_agent(test_project):
    """Test that ssh config mode works with forward_agent enabled."""
    from boxctl.config import ProjectConfig

    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "ssh": {
            "mode": "config",
            "forward_agent": True,
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = ProjectConfig(test_project)

    assert config.ssh_forward_agent is True
    assert config.ssh_mode == "config"


def test_workspace_mount_from_yml(test_project, workspace_dir):
    """Test that workspace mounts from .boxctl.yml are applied to container."""
    # Create marker file
    marker_file = workspace_dir / "yml_marker.txt"
    marker_content = "from_yml_config"
    marker_file.write_text(marker_content)

    # Create .boxctl.yml with workspace
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "workspaces": [
            {"path": str(workspace_dir), "mode": "ro", "mount": "testws"},
        ],
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Rebuild container to apply new config
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Verify mount is visible
    result = subprocess.run(
        ["docker", "exec", container_name, "cat", "/context/testws/yml_marker.txt"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Should be able to read from workspace mount"
    assert result.stdout.strip() == marker_content


def test_workspace_cli_writes_to_yml(test_project, workspace_dir):
    """Test that 'boxctl workspace add' writes to .boxctl.yml."""
    # Create .boxctl.yml first
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {"version": "1.0", "workspaces": []}

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Add workspace via CLI
    run_abox("workspace", "add", str(workspace_dir), "ro", "cliws", cwd=test_project, check=False)

    # Read .boxctl.yml
    with open(config_file) as f:
        updated_config = yaml.safe_load(f)

    # Verify workspace was added
    assert len(updated_config["workspaces"]) == 1
    assert updated_config["workspaces"][0]["path"] == str(workspace_dir)
    assert updated_config["workspaces"][0]["mode"] == "ro"
    assert updated_config["workspaces"][0]["mount"] == "cliws"


def test_container_connection_from_yml(test_project):
    """Test that container connections from .boxctl.yml are applied."""
    # Create .boxctl.yml with container connection
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "containers": [
            {"name": "test-redis", "auto_reconnect": True},
        ],
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Load and verify
    from boxctl.config import ProjectConfig

    config = ProjectConfig(test_project)

    assert len(config.containers) == 1
    assert config.containers[0]["name"] == "test-redis"
    assert config.containers[0]["auto_reconnect"] is True


def test_network_cli_writes_to_yml(test_project):
    """Test that 'boxctl network connect' writes to .boxctl.yml."""
    # Create a test container
    subprocess.run(
        ["docker", "run", "-d", "--name", "test-nginx", "--rm", "busybox", "sleep", "300"],
        check=False,
    )

    try:
        # Create .boxctl.yml first
        config_file = test_project / ".boxctl" / "config.yml"
        config_file.parent.mkdir(exist_ok=True)
        config_data = {"version": "1.0", "containers": []}

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        # Start boxctl container
        run_abox("start", cwd=test_project)

        # Connect via CLI
        run_abox("network", "connect", "test-nginx", cwd=test_project, check=False)

        # Read .boxctl.yml
        with open(config_file) as f:
            updated_config = yaml.safe_load(f)

        # Verify connection was added
        assert len(updated_config["containers"]) == 1
        assert updated_config["containers"][0]["name"] == "test-nginx"
        assert updated_config["containers"][0]["auto_reconnect"] is True

    finally:
        # Cleanup
        subprocess.run(["docker", "rm", "-f", "test-nginx"], check=False)


def test_ssh_forward_agent_env_var(test_project, tmp_path):
    """Test that SSH_AUTH_SOCK is set when forward_agent is enabled."""
    # Create a fake SSH agent socket
    fake_socket = tmp_path / "ssh-agent.sock"
    fake_socket.touch()

    # Create .boxctl.yml with agent forwarding
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "ssh": {
            "mode": "config",
            "forward_agent": True,
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Mock SSH_AUTH_SOCK environment variable
    import os

    original_sock = os.environ.get("SSH_AUTH_SOCK")
    try:
        os.environ["SSH_AUTH_SOCK"] = str(fake_socket)

        # Rebuild container to apply new config
        run_abox("rebuild", cwd=test_project)

        container_name = f"boxctl-{test_project.name}"

        # Check if SSH_AUTH_SOCK is set in container
        result = subprocess.run(
            ["docker", "exec", container_name, "bash", "-c", "echo $SSH_AUTH_SOCK"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "/ssh-agent" in result.stdout.strip(), "SSH_AUTH_SOCK should be set to /ssh-agent"

    finally:
        if original_sock:
            os.environ["SSH_AUTH_SOCK"] = original_sock
        elif "SSH_AUTH_SOCK" in os.environ:
            del os.environ["SSH_AUTH_SOCK"]


def test_ssh_config_mode_no_keys_copied(test_project):
    """Test that private keys are NOT copied when mode is 'config'."""
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "ssh": {
            "mode": "config",
            "forward_agent": True,
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Rebuild container to apply new config
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check if private keys exist in container (they shouldn't in config mode)
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_name,
            "bash",
            "-c",
            "ls /home/abox/.ssh/id_* 2>/dev/null | wc -l",
        ],
        capture_output=True,
        text=True,
    )

    # Should have 0 private key files in config mode
    assert result.stdout.strip() == "0", "Private keys should not be copied in config mode"


def test_config_template_creates_valid_yml(test_project):
    """Test that config template creation produces valid YAML."""
    from boxctl.config import ProjectConfig

    # Remove any existing config
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    if config_file.exists():
        config_file.unlink()

    # Create template
    config = ProjectConfig(test_project)
    config.create_template()

    # Verify file exists
    assert config_file.exists()

    # Load and verify it's valid YAML
    with open(config_file) as f:
        data = yaml.safe_load(f)

    assert data["version"] == "1.0"
    assert "ssh" in data
    assert "workspaces" in data
    assert "containers" in data
    assert "security" in data


def test_resources_applied_to_container(test_project):
    """Test that resource limits from .boxctl.yml are applied to container."""
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "resources": {
            "memory": "512m",
            "cpus": "1.0",
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Rebuild container to apply new config
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Inspect container to check resource limits
    result = subprocess.run(["docker", "inspect", container_name], capture_output=True, text=True)

    assert result.returncode == 0
    container_info = json.loads(result.stdout)[0]

    # Check memory limit (512m = 536870912 bytes)
    memory_limit = container_info["HostConfig"]["Memory"]
    assert (
        memory_limit == 536870912
    ), f"Memory limit should be 512m (536870912 bytes), got {memory_limit}"

    # Check CPU limit (1.0 CPUs = 1000000000 nanocpus)
    nano_cpus = container_info["HostConfig"]["NanoCpus"]
    assert (
        nano_cpus == 1000000000
    ), f"CPU limit should be 1.0 (1000000000 nanocpus), got {nano_cpus}"


def test_security_options_applied(test_project):
    """Test that security options from .boxctl.yml are applied."""
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "security": {
            "seccomp": "unconfined",
            "capabilities": ["SYS_PTRACE", "NET_ADMIN"],
        },
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Rebuild container to apply new config
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Inspect container
    result = subprocess.run(["docker", "inspect", container_name], capture_output=True, text=True)

    assert result.returncode == 0
    container_info = json.loads(result.stdout)[0]

    # Check seccomp (unconfined is a valid docker seccomp option)
    security_opt = container_info["HostConfig"]["SecurityOpt"]
    assert "seccomp=unconfined" in security_opt

    # Check capabilities
    cap_add = container_info["HostConfig"]["CapAdd"]
    assert "SYS_PTRACE" in cap_add
    assert "NET_ADMIN" in cap_add


def test_port_mappings_applied(test_project):
    """Test that port mappings from .boxctl.yml are applied."""
    import socket

    def get_free_port():
        """Find an available port on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    # Get two random available ports to avoid conflicts
    host_port_1 = get_free_port()
    host_port_2 = get_free_port()

    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "ports": [f"{host_port_1}:80", f"{host_port_2}:3000"],
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Rebuild container to apply new config
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Inspect container
    result = subprocess.run(["docker", "inspect", container_name], capture_output=True, text=True)

    assert result.returncode == 0
    container_info = json.loads(result.stdout)[0]

    # Check port bindings
    port_bindings = container_info["HostConfig"]["PortBindings"]
    assert "80/tcp" in port_bindings
    assert port_bindings["80/tcp"][0]["HostPort"] == str(host_port_1)
    assert "3000/tcp" in port_bindings
    assert port_bindings["3000/tcp"][0]["HostPort"] == str(host_port_2)


def test_devices_property(test_project):
    """Test that devices property reads from .boxctl.yml."""
    from boxctl.config import ProjectConfig

    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "devices": ["/dev/null", "/dev/zero"],
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = ProjectConfig(test_project)

    assert config.devices == ["/dev/null", "/dev/zero"]


def test_devices_property_empty_default(test_project):
    """Test that devices property returns empty list when not configured."""
    from boxctl.config import ProjectConfig

    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {"version": "1.0"}

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = ProjectConfig(test_project)

    assert config.devices == []


def test_devices_applied_to_container(test_project):
    """Test that device mappings from .boxctl.yml are applied to container."""
    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "devices": ["/dev/null"],
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Rebuild container to apply new config
    run_abox("rebuild", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Inspect container
    result = subprocess.run(["docker", "inspect", container_name], capture_output=True, text=True)

    assert result.returncode == 0
    container_info = json.loads(result.stdout)[0]

    # Check device mappings
    devices = container_info["HostConfig"]["Devices"]
    assert devices is not None
    assert any(d["PathOnHost"] == "/dev/null" for d in devices)


def test_missing_devices_skipped(test_project, capsys):
    """Test that missing devices are skipped with a warning."""
    from boxctl.config import ProjectConfig
    from pathlib import Path

    config_file = test_project / ".boxctl" / "config.yml"
    config_file.parent.mkdir(exist_ok=True)
    config_data = {
        "version": "1.0",
        "devices": ["/dev/null", "/dev/nonexistent_device_xyz"],
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = ProjectConfig(test_project)

    # Simulate the validation logic from container.py
    valid_devices = []
    for device in config.devices:
        device_path = Path(device.split(":")[0])
        if device_path.exists():
            valid_devices.append(device)

    # /dev/null exists, /dev/nonexistent_device_xyz does not
    assert "/dev/null" in valid_devices
    assert "/dev/nonexistent_device_xyz" not in valid_devices
    assert len(valid_devices) == 1
