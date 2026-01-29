# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Port forwarding commands."""

import os
import socket
from pathlib import Path

import click

from boxctl.cli import cli
from boxctl.cli.helpers import _get_project_context, console, handle_errors
from boxctl.config import parse_port_spec, validate_host_port, ProjectConfig
from boxctl.paths import ContainerDefaults
from boxctl.utils.project import resolve_project_dir


def _get_boxctld_socket_path() -> Path:
    """Get the boxctld socket path (platform-aware: macOS vs Linux)."""
    from boxctl.host_config import get_config

    return get_config().socket_path


def _send_boxctld_command(command: dict) -> dict:
    """Send a command to boxctld and get response."""
    import json

    socket_path = _get_boxctld_socket_path()
    if not socket_path.exists():
        raise RuntimeError("boxctld not running. Start with: boxctl service start")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(socket_path))
        sock.settimeout(5.0)
        sock.sendall((json.dumps(command) + "\n").encode())

        # Read response
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        if data:
            return json.loads(data.decode().strip())
        return {"ok": False, "error": "No response from boxctld"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        sock.close()


def _get_container_name() -> str:
    """Get the container name for the current project."""
    return _get_project_context().container_name


def _get_active_ports() -> dict:
    """Get all active ports from all connected containers.

    Returns:
        Dict with 'host_ports' and 'container_ports' lists, each containing
        dicts with 'host_port', 'container_port', and 'container' keys.
        Returns empty lists if daemon is not running.
    """
    response = _send_boxctld_command({"action": "get_active_ports"})
    if response.get("ok"):
        return {
            "host_ports": response.get("host_ports", []),
            "container_ports": response.get("container_ports", []),
        }
    return {"host_ports": [], "container_ports": []}


@cli.group()
def ports():
    """Manage port forwarding (list, add, remove).

    Forward ports between host and container without rebuilds.

    Commands:
      expose    - Expose container port to host (service runs in container)
      forward   - Forward host port into container (service runs on host)
      unexpose  - Remove an exposed port
      unforward - Remove a forwarded port
    """
    pass


@ports.command(name="list", options_metavar="")
@click.argument("scope", required=False, default=None)
@handle_errors
def ports_list(scope: str):
    """List port forwarding configurations.

    SCOPE can be 'all' to show ports from all containers.
    Without SCOPE, shows ports for the current project only.
    """
    if scope == "all":
        _list_all_containers_ports()
    elif scope is not None:
        raise click.ClickException(
            f"Unknown scope: {scope}. Use 'all' or omit for current project."
        )
    else:
        _list_current_project_ports()


def _list_current_project_ports():
    """List ports for the current project only, showing live status."""
    project_dir = resolve_project_dir()
    pctx = _get_project_context()
    container_name = pctx.container_name

    config = ProjectConfig(project_dir)

    # Get configured ports from .boxctl/config.yml
    host_ports = config.ports_host
    container_ports = config.ports_container

    # Get active ports from daemon
    active_ports = _get_active_ports()

    # Build sets of active ports for this container
    active_exposed = set()  # (host_port, container_port)
    active_forwarded = set()  # (host_port, container_port)

    for port_info in active_ports.get("host_ports", []):
        if port_info["container"] == container_name:
            active_exposed.add((port_info["host_port"], port_info["container_port"]))

    for port_info in active_ports.get("container_ports", []):
        if port_info["container"] == container_name:
            active_forwarded.add((port_info["host_port"], port_info["container_port"]))

    # Check container status
    from boxctl.container import ContainerManager

    cm = ContainerManager()
    is_running = cm.is_running(container_name)

    console.print("[bold]Port Configuration[/bold]")
    status_text = "[green]running[/green]" if is_running else "[yellow]stopped[/yellow]"
    console.print(f"Container: {container_name} ({status_text})\n")

    # Legend
    console.print("[dim]● = active (bound)  ○ = configured (not bound)[/dim]\n")

    # Exposed ports (container -> host)
    console.print("[cyan]Exposed Ports[/cyan] (container → host)")
    if host_ports:
        for spec in host_ports:
            parsed = parse_port_spec(spec)
            hp, cp = parsed["host_port"], parsed["container_port"]
            is_active = (hp, cp) in active_exposed
            icon = "[green]●[/green]" if is_active else "[yellow]○[/yellow]"
            console.print(f"  {icon} container:{cp} → host:{hp}")
    else:
        console.print("  [dim]No exposed ports[/dim]")

    console.print()

    # Forwarded ports (host -> container)
    console.print("[cyan]Forwarded Ports[/cyan] (host → container)")
    if container_ports:
        for entry in container_ports:
            # Handle both old dict format and new string format
            if isinstance(entry, dict):
                host_port = entry.get("port", 0)
                container_port = entry.get("container_port", host_port)
            else:
                parts = str(entry).split(":")
                if len(parts) == 2:
                    host_port, container_port = int(parts[0]), int(parts[1])
                else:
                    host_port = container_port = int(parts[0])
            is_active = (host_port, container_port) in active_forwarded
            icon = "[green]●[/green]" if is_active else "[yellow]○[/yellow]"
            console.print(f"  {icon} host:{host_port} → container:{container_port}")
    else:
        console.print("  [dim]No forwarded ports[/dim]")

    console.print()
    console.print("[dim]Add ports: abox ports expose <port> or abox ports forward <port>[/dim]")


def _list_all_containers_ports():
    """List ports from all boxctl containers."""
    from boxctl.container import ContainerManager

    cm = ContainerManager()
    containers = cm.list_containers(all_containers=True)

    if not containers:
        console.print("[dim]No boxctl containers found[/dim]")
        return

    # Get active tunnel ports from daemon
    active_ports = _get_active_ports()
    active_exposed = {}  # container -> [(host, container)]
    active_forwarded = {}  # container -> [(host, container)]

    for port_info in active_ports.get("host_ports", []):
        container = port_info["container"]
        if container not in active_exposed:
            active_exposed[container] = []
        active_exposed[container].append((port_info["host_port"], port_info["container_port"]))

    for port_info in active_ports.get("container_ports", []):
        container = port_info["container"]
        if container not in active_forwarded:
            active_forwarded[container] = []
        active_forwarded[container].append((port_info["host_port"], port_info["container_port"]))

    console.print("[bold]Port Configuration (All Containers)[/bold]\n")

    found_any = False
    for container_info in sorted(containers, key=lambda x: x["project"]):
        project_name = container_info["project"]
        container_name = container_info["name"]
        status = container_info["status"]
        project_path = container_info.get("project_path")

        # Status indicator
        status_color = "green" if status == "running" else "yellow"
        status_icon = "●" if status == "running" else "○"

        # Get configured ports from project config
        config_exposed = []
        config_forwarded = []
        if project_path:
            try:
                config = ProjectConfig(Path(project_path))
                for spec in config.ports_host:
                    parsed = parse_port_spec(spec)
                    config_exposed.append((parsed["host_port"], parsed["container_port"]))
                for entry in config.ports_container:
                    if isinstance(entry, dict):
                        h = entry.get("port", 0)
                        c = entry.get("container_port", h)
                    else:
                        parts = str(entry).split(":")
                        if len(parts) == 2:
                            h, c = int(parts[0]), int(parts[1])
                        else:
                            h = c = int(parts[0])
                    config_forwarded.append((h, c))
            except Exception:
                pass

        # Get Docker port bindings
        docker_ports = _get_docker_port_bindings(container_name)

        # Get active tunnel ports for this container
        tunnel_exposed = active_exposed.get(container_name, [])
        tunnel_forwarded = active_forwarded.get(container_name, [])

        has_ports = config_exposed or config_forwarded or docker_ports

        if not has_ports:
            continue  # Skip containers with no ports

        found_any = True
        console.print(
            f"[{status_color}]{status_icon}[/{status_color}] [bold cyan]{project_name}[/bold cyan] [dim]({status})[/dim]"
        )

        # Show Docker port bindings
        if docker_ports:
            console.print("  [dim]Docker ports:[/dim]")
            for host_port, container_port in sorted(docker_ports):
                console.print(f"    [green]●[/green] container:{container_port} → host:{host_port}")

        # Show configured exposed ports
        if config_exposed:
            console.print("  [dim]Exposed (config):[/dim]")
            for host_port, container_port in sorted(config_exposed):
                # Check if active
                is_active = (host_port, container_port) in tunnel_exposed
                icon = "[green]●[/green]" if is_active else "[yellow]○[/yellow]"
                console.print(f"    {icon} container:{container_port} → host:{host_port}")

        # Show configured forwarded ports
        if config_forwarded:
            console.print("  [dim]Forwarded (config):[/dim]")
            for host_port, container_port in sorted(config_forwarded):
                is_active = (host_port, container_port) in tunnel_forwarded
                icon = "[green]●[/green]" if is_active else "[yellow]○[/yellow]"
                console.print(f"    {icon} host:{host_port} → container:{container_port}")

        console.print()

    if not found_any:
        console.print("[dim]No containers have ports configured[/dim]")


def _get_docker_port_bindings(container_name: str) -> list:
    """Get Docker port bindings for a container.

    Returns list of (host_port, container_port) tuples.
    """
    try:
        import docker

        client = docker.from_env()
        container = client.containers.get(container_name)
        port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})

        result = []
        if port_bindings:
            for port_key, bindings in port_bindings.items():
                if bindings:  # Only if actually bound
                    container_port = int(port_key.split("/")[0])
                    for binding in bindings:
                        host_port = int(binding.get("HostPort", 0))
                        if host_port:
                            result.append((host_port, container_port))
        return result
    except Exception:
        return []


@ports.command(name="expose", options_metavar="")
@click.argument("port_spec")
@handle_errors
def expose(port_spec: str):
    """Expose a container port to the host.

    PORT_SPEC format is container:host (source:destination):
      3000       - Expose container:3000 on host:3000
      3000:8080  - Expose container:3000 on host:8080

    Use this when your service runs INSIDE the container and you
    want to access it from the host (e.g., browser at localhost:8080).

    Note: Host ports below 1024 require root and are not allowed.
    """
    # Parse as container:host format
    parts = port_spec.split(":")
    if len(parts) == 1:
        container_port = host_port = int(parts[0])
    elif len(parts) == 2:
        container_port = int(parts[0])
        host_port = int(parts[1])
    else:
        raise click.ClickException(
            f"Invalid port format: {port_spec}. Use 'port' or 'container:host'"
        )

    # Validate host port
    validate_host_port(host_port)

    # Load and update config
    project_dir = resolve_project_dir()

    config = ProjectConfig(project_dir)
    if not config.exists():
        raise click.ClickException("No .boxctl/config.yml found. Run: boxctl init")

    # Check if already configured in this project
    current_ports = config.ports_host
    for existing in current_ports:
        existing_parsed = parse_port_spec(existing)
        if existing_parsed["host_port"] == host_port:
            console.print(f"[yellow]Host port {host_port} already exposed[/yellow]")
            return

    # Check if port is in use by another boxctl container
    container_name = _get_container_name()
    active_ports = _get_active_ports()
    for port_info in active_ports["host_ports"]:
        if port_info["host_port"] == host_port and port_info["container"] != container_name:
            other_project = port_info["container"].replace(
                ContainerDefaults.CONTAINER_PREFIX, "", 1
            )
            console.print(
                f"[red]Error: Host port {host_port} is already exposed by project '{other_project}'[/red]"
            )
            return

    # Update config - store in host:container format for backward compatibility
    raw_ports = config.ports.copy()

    if "host" not in raw_ports:
        raw_ports["host"] = []

    # Store as host:container format
    if host_port == container_port:
        storage_spec = str(host_port)
    else:
        storage_spec = f"{host_port}:{container_port}"
    raw_ports["host"].append(storage_spec)
    config.ports = raw_ports
    config.save()

    # Try to add to running proxy (dynamically, no rebuild needed)
    response = _send_boxctld_command(
        {
            "action": "add_host_port",
            "container": container_name,
            "host_port": host_port,
            "container_port": container_port,
        }
    )

    if response.get("ok"):
        console.print(f"[green]✓ Exposed container:{container_port} → host:{host_port}[/green]")
        if response.get("message"):
            console.print(f"[dim]{response.get('message')}[/dim]")
    elif "No response" in response.get("error", "") or "not running" in response.get("error", ""):
        console.print(
            "[yellow]Port saved to config. Start proxy with: boxctl service start[/yellow]"
        )
    else:
        error = response.get("error", "")
        console.print(f"[yellow]Port saved to config but could not activate now:[/yellow]")
        console.print(f"[red]{error}[/red]")

        # Provide helpful guidance for Docker conflicts
        if "Docker" in error or "in use" in error.lower():
            console.print("\n[bold]To fix this:[/bold]")
            console.print("  1. Add 'mode: tunnel' under 'ports:' in .boxctl/config.yml")
            console.print("  2. Run: abox rebuild")
            console.print("  3. The port will be exposed via tunnel instead of Docker")


@ports.command(name="forward", options_metavar="")
@click.argument("port_spec")
@handle_errors
def forward(port_spec: str):
    """Forward a host port into the container.

    PORT_SPEC format:
      9222       - Forward host:9222 to container:9222
      9222:9223  - Forward host:9222 to container:9223

    Use this when your service runs ON THE HOST and you want
    to access it from inside the container (e.g., host MCP servers).

    Example: abox ports forward 9222
    """
    # Parse port spec
    parts = port_spec.split(":")
    if len(parts) == 1:
        port = container_port = int(parts[0])
    elif len(parts) == 2:
        port = int(parts[0])
        container_port = int(parts[1])
    else:
        raise click.ClickException(
            f"Invalid port format: {port_spec}. Use 'port' or 'host:container'"
        )

    # Load and update config
    project_dir = resolve_project_dir()

    config = ProjectConfig(project_dir)
    if not config.exists():
        raise click.ClickException("No .boxctl/config.yml found. Run: boxctl init")

    # Check if already configured in this project
    current_ports = config.ports_container
    for entry in current_ports:
        existing_port = (
            entry.get("port") if isinstance(entry, dict) else int(str(entry).split(":")[0])
        )
        if existing_port == port:
            console.print(f"[yellow]Port {port} already forwarded[/yellow]")
            return

    # Check if port is in use by another boxctl container
    container_name = _get_container_name()
    active_ports = _get_active_ports()
    for port_info in active_ports["container_ports"]:
        if port_info["host_port"] == port and port_info["container"] != container_name:
            other_project = port_info["container"].replace(
                ContainerDefaults.CONTAINER_PREFIX, "", 1
            )
            console.print(
                f"[red]Error: Host port {port} is already forwarded by project '{other_project}'[/red]"
            )
            return

    # Update config - store as simple port spec string (like host ports)
    raw_ports = config.ports.copy()

    if "container" not in raw_ports:
        raw_ports["container"] = []

    # Store as "port" or "host:container" string
    raw_ports["container"].append(port_spec)
    config.ports = raw_ports
    config.save()

    console.print(f"[green]✓ Forwarding host:{port} → container:{container_port}[/green]")

    # Try to dynamically add the listener via proxy socket
    response = _send_boxctld_command(
        {
            "action": "add_container_port",
            "container": container_name,
            "host_port": port,
            "container_port": container_port,
        }
    )

    if response.get("ok"):
        console.print(f"[green]✓ Listener active now on container:{container_port}[/green]")
    elif "not connected" in response.get("error", ""):
        console.print(
            "[blue]Tunnel client not connected. Will be active when container starts.[/blue]"
        )
    else:
        console.print(
            "[yellow]Could not add listener dynamically. Will be active on container restart.[/yellow]"
        )


@ports.command(name="unexpose", options_metavar="")
@click.argument("port", type=int)
@handle_errors
def unexpose(port: int):
    """Remove an exposed port.

    PORT is the host port number to stop exposing.
    """
    project_dir = resolve_project_dir()

    config = ProjectConfig(project_dir)
    if not config.exists():
        raise click.ClickException("No .boxctl/config.yml found")

    # Find and remove matching port spec
    raw_ports = config.ports.copy()

    host_ports = raw_ports.get("host", [])
    found = False
    new_host_ports = []

    for spec in host_ports:
        parsed = parse_port_spec(spec)
        if parsed["host_port"] == port:
            found = True
        else:
            new_host_ports.append(spec)

    if not found:
        console.print(f"[yellow]Port {port} not exposed[/yellow]")
        return

    raw_ports["host"] = new_host_ports
    config.ports = raw_ports
    config.save()

    # Try to remove from running proxy
    container_name = _get_container_name()
    response = _send_boxctld_command(
        {
            "action": "remove_host_port",
            "container": container_name,
            "host_port": port,
        }
    )

    if response.get("ok"):
        console.print(f"[green]✓ Unexposed port {port}[/green]")
        console.print(f"[green]✓ Listener stopped[/green]")
    else:
        error = response.get("error", "")
        if "not connected" in error:
            console.print(f"[green]✓ Unexposed port {port}[/green]")
            console.print("[blue]Container not connected. Config updated.[/blue]")
        else:
            console.print(f"[green]✓ Unexposed port {port} (config updated)[/green]")


@ports.command(name="unforward", options_metavar="")
@click.argument("port", type=int)
@handle_errors
def unforward(port: int):
    """Remove a forwarded port.

    PORT is the host port number to stop forwarding.
    """
    project_dir = resolve_project_dir()

    config = ProjectConfig(project_dir)
    if not config.exists():
        raise click.ClickException("No .boxctl/config.yml found")

    # Find and remove matching entry
    raw_ports = config.ports.copy()

    container_ports = raw_ports.get("container", [])
    found = False
    new_container_ports = []

    for entry in container_ports:
        # Handle both old dict format and new string format
        if isinstance(entry, dict):
            entry_port = entry.get("port", 0)
        else:
            entry_port = int(str(entry).split(":")[0])

        if entry_port == port:
            found = True
        else:
            new_container_ports.append(entry)

    if not found:
        console.print(f"[yellow]Port {port} not forwarded[/yellow]")
        return

    raw_ports["container"] = new_container_ports
    config.ports = raw_ports
    config.save()

    console.print(f"[green]✓ Unforwarded port {port}[/green]")

    # Try to dynamically remove the listener via proxy socket
    container_name = _get_container_name()
    response = _send_boxctld_command(
        {
            "action": "remove_container_port",
            "container": container_name,
            "host_port": port,
        }
    )

    if response.get("ok"):
        console.print(f"[green]✓ Listener stopped[/green]")
    elif "not connected" in response.get("error", ""):
        console.print("[blue]Container not connected. Config updated.[/blue]")
    else:
        console.print("[yellow]Listener will stop on container restart.[/yellow]")


@ports.command(name="status", options_metavar="")
@handle_errors
def ports_status():
    """Show active port tunnels (runtime status)."""
    # Get active ports from daemon
    active_ports = _get_active_ports()

    # Check if daemon is running
    if not active_ports["host_ports"] and not active_ports["container_ports"]:
        # Try to verify daemon is actually running
        response = _send_boxctld_command({"action": "get_active_ports"})
        if not response.get("ok"):
            console.print("[yellow]Could not connect to boxctld. Is the service running?[/yellow]")
            console.print("[dim]Start with: boxctl service start[/dim]")
            return

    console.print("[bold]Active Port Tunnels[/bold]\n")

    # Group ports by container
    exposed_by_container = {}  # container -> list of (host_port, container_port)
    forwarded_by_container = {}  # container -> list of (host_port, container_port)

    for port_info in active_ports["host_ports"]:
        container = port_info["container"]
        if container not in exposed_by_container:
            exposed_by_container[container] = []
        exposed_by_container[container].append(
            (port_info["host_port"], port_info["container_port"])
        )

    for port_info in active_ports["container_ports"]:
        container = port_info["container"]
        if container not in forwarded_by_container:
            forwarded_by_container[container] = []
        forwarded_by_container[container].append(
            (port_info["host_port"], port_info["container_port"])
        )

    # Get all unique containers
    all_containers = set(exposed_by_container.keys()) | set(forwarded_by_container.keys())

    if not all_containers:
        console.print("[dim]No active port tunnels[/dim]")
        return

    # Show ports grouped by container
    for container in sorted(all_containers):
        project_name = ContainerDefaults.project_from_container(container)
        console.print(f"[cyan]{project_name}[/cyan]")

        exposed = exposed_by_container.get(container, [])
        forwarded = forwarded_by_container.get(container, [])

        if exposed:
            console.print("  [dim]Exposed (container → host):[/dim]")
            for host_port, container_port in sorted(exposed):
                if host_port == container_port:
                    console.print(f"    [green]●[/green] :{host_port}")
                else:
                    console.print(
                        f"    [green]●[/green] container:{container_port} → host:{host_port}"
                    )

        if forwarded:
            console.print("  [dim]Forwarded (host → container):[/dim]")
            for host_port, container_port in sorted(forwarded):
                if host_port == container_port:
                    console.print(f"    [green]●[/green] :{host_port}")
                else:
                    console.print(
                        f"    [green]●[/green] host:{host_port} → container:{container_port}"
                    )

        console.print()
