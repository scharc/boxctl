# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Docker helpers for boxctl DinD tests."""

import subprocess
import time
from typing import Optional


def run_docker(
    *args,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run docker command.

    Args:
        *args: Docker command arguments
        check: Raise on non-zero exit
        capture_output: Capture stdout/stderr
        text: Decode output as text
        timeout: Command timeout in seconds

    Returns:
        CompletedProcess result
    """
    return subprocess.run(
        ["docker", *[str(a) for a in args]],
        check=check,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
    )


def container_exists(container_name: str) -> bool:
    """Check if container exists (running or stopped).

    Args:
        container_name: Name of the container

    Returns:
        True if container exists
    """
    result = run_docker("ps", "-a", "-f", f"name=^{container_name}$", "--format", "{{.Names}}")
    return container_name in result.stdout.strip().split("\n")


def container_is_running(container_name: str) -> bool:
    """Check if container is running.

    Args:
        container_name: Name of the container

    Returns:
        True if container is running
    """
    result = run_docker("ps", "-f", f"name=^{container_name}$", "--format", "{{.Names}}")
    return container_name in result.stdout.strip().split("\n")


def wait_for_container_ready(
    container_name: str,
    timeout: int = 60,
    check_command: str = "echo ready",
) -> bool:
    """Wait for container to be ready (can execute commands).

    Args:
        container_name: Name of the container
        timeout: Maximum wait time in seconds
        check_command: Command to run to check readiness

    Returns:
        True if container is ready, False if timeout
    """
    for _ in range(timeout):
        result = run_docker("exec", container_name, "bash", "-c", check_command)
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False


def get_container_ip(container_name: str) -> Optional[str]:
    """Get container IP address.

    Args:
        container_name: Name of the container

    Returns:
        IP address string or None if not found
    """
    result = run_docker(
        "inspect",
        "-f",
        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        container_name,
    )
    if result.returncode == 0:
        ip = result.stdout.strip()
        return ip if ip else None
    return None


def exec_in_container(
    container_name: str,
    command: str,
    user: str = "abox",
    workdir: str = "/workspace",
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Execute command inside container.

    Args:
        container_name: Name of the container
        command: Shell command to execute
        user: User to run command as
        workdir: Working directory inside container
        timeout: Command timeout in seconds

    Returns:
        CompletedProcess result
    """
    return run_docker(
        "exec",
        "-u",
        user,
        "-w",
        workdir,
        container_name,
        "bash",
        "-c",
        command,
        timeout=timeout,
    )


def get_container_logs(container_name: str, tail: int = 100) -> str:
    """Get container logs.

    Args:
        container_name: Name of the container
        tail: Number of lines to retrieve

    Returns:
        Log output as string
    """
    result = run_docker("logs", "--tail", str(tail), container_name)
    return result.stdout + result.stderr


def remove_container(container_name: str, force: bool = True) -> bool:
    """Remove a container.

    Args:
        container_name: Name of the container
        force: Force remove if running

    Returns:
        True if removed successfully
    """
    args = ["rm"]
    if force:
        args.append("-f")
    args.append(container_name)

    result = run_docker(*args)
    return result.returncode == 0


def create_network(network_name: str) -> bool:
    """Create a Docker network.

    Args:
        network_name: Name of the network

    Returns:
        True if created successfully
    """
    result = run_docker("network", "create", network_name)
    return result.returncode == 0


def remove_network(network_name: str) -> bool:
    """Remove a Docker network.

    Args:
        network_name: Name of the network

    Returns:
        True if removed successfully
    """
    result = run_docker("network", "rm", network_name)
    return result.returncode == 0
