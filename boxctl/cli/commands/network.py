# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Network connection commands - connect to other Docker containers."""

from pathlib import Path
from typing import Optional

import click
from rich.table import Table

from boxctl.cli import cli
from boxctl.container import ContainerManager
from boxctl.cli.helpers import (
    _get_project_context,
    _load_containers_config,
    _save_containers_config,
    console,
    handle_errors,
)
from boxctl.cli.helpers.completions import (
    _complete_docker_containers,
    _complete_connected_containers,
)
from boxctl.utils.project import resolve_project_dir, get_boxctl_dir


@cli.group()
def network():
    """Connect to other Docker containers."""
    pass


@network.command()
@click.argument("show_all", required=False)
@handle_errors
def available(show_all: Optional[str]):
    """List Docker containers available for connection.

    Pass 'all' to include boxctl containers.

    Examples:
        abox network available      # Non-boxctl containers only
        abox network available all  # All containers
    """
    manager = ContainerManager()
    include_boxctl = show_all == "all"
    containers = manager.get_all_containers(include_boxctl=include_boxctl)

    if not containers:
        console.print("[yellow]No containers found[/yellow]")
        return

    # Load current project's container connections
    project_dir = resolve_project_dir()
    boxctl_dir = get_boxctl_dir(project_dir)

    connected_containers = set()
    if boxctl_dir.exists():
        connections = _load_containers_config(boxctl_dir)
        connected_containers = {conn.get("name") for conn in connections if conn.get("name")}

    table = Table(title="Available Containers")
    table.add_column("Container", style="cyan")
    table.add_column("Image", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Networks", style="blue")
    table.add_column("Ports", style="yellow")
    table.add_column("Connected", style="green")

    for container in containers:
        networks_str = ", ".join(container["networks"]) if container["networks"] else "-"
        ports_str = ", ".join(container["ports"]) if container["ports"] else "-"
        is_connected = "✓" if container["name"] in connected_containers else "-"

        table.add_row(
            container["name"],
            container["image"],
            container["status"],
            networks_str,
            ports_str,
            is_connected,
        )

    console.print(table)
    if connected_containers:
        console.print(
            f"\n[green]Connected containers: {', '.join(sorted(connected_containers))}[/green]"
        )
    console.print("\n[blue]Connect with:[/blue] boxctl network connect <name>")


@network.command()
@handle_errors
def list():
    """Show current container connections for this project."""
    pctx = _get_project_context()

    # Load connections
    connections = _load_containers_config(pctx.boxctl_dir)

    if not connections:
        console.print("[yellow]No container connections configured[/yellow]")
        console.print("\n[blue]Connect to a container with:[/blue] boxctl network connect <name>")
        return

    table = Table(title="Container Connections")
    table.add_column("Container", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Networks", style="blue")
    table.add_column("Image", style="magenta")
    table.add_column("Auto-Reconnect", style="yellow")

    warnings = []

    for connection in connections:
        cname = connection.get("name", "")
        auto_reconnect = connection.get("auto_reconnect", True)

        # Try to get container info
        try:
            target = pctx.manager.client.containers.get(cname)
            networks = pctx.manager.get_container_networks(cname)
            image = target.image.tags[0] if target.image.tags else target.id[:12]
            status = (
                "[green]Running[/green]"
                if target.status == "running"
                else f"[yellow]{target.status.title()}[/yellow]"
            )
        except Exception:
            status = "[red]Not Found[/red]"
            networks = []
            image = "-"
            warnings.append(cname)

        table.add_row(
            cname,
            status,
            ", ".join(networks) if networks else "-",
            image,
            "✓" if auto_reconnect else "-",
        )

    console.print(table)

    if warnings:
        console.print(
            "\n[yellow]⚠ Warning: The following containers are no longer available:[/yellow]"
        )
        for name in warnings:
            console.print(f"  - {name}")
        console.print("\n[blue]Remove with:[/blue] boxctl network disconnect <name>")


@network.command()
@click.argument("target_container", shell_complete=_complete_docker_containers)
@handle_errors
def connect(target_container: str):
    """Connect boxctl to a running container's network.

    This allows agents to communicate with the target container by hostname.

    Example:
        abox network connect postgres
    """
    pctx = _get_project_context()

    # Ensure boxctl container is running
    if not pctx.manager.container_exists(pctx.container_name):
        raise click.ClickException(
            f"boxctl container {pctx.container_name} not found. Start it with: boxctl start"
        )

    if not pctx.manager.is_running(pctx.container_name):
        console.print(f"[blue]Starting boxctl container {pctx.container_name}...[/blue]")
        pctx.manager.start_container(pctx.container_name)

    # Get target container
    try:
        target = pctx.manager.client.containers.get(target_container)
    except Exception:
        containers = pctx.manager.get_all_containers(include_boxctl=False)
        container_names = [c["name"] for c in containers]
        raise click.ClickException(
            f"Container {target_container} not found. Available: {', '.join(container_names)}"
        )

    # Get target container info
    target_networks = pctx.manager.get_container_networks(target_container)
    target_id = target.id[:12]
    target_image = target.image.tags[0] if target.image.tags else target.id[:12]

    # Connect to target networks
    console.print(f"[blue]Connecting to {target_container}...[/blue]")
    pctx.manager.connect_to_networks(pctx.container_name, target_networks)

    # Load existing connections
    connections = _load_containers_config(pctx.boxctl_dir)

    # Check if already connected
    already_connected = any(conn.get("name") == target_container for conn in connections)

    if not already_connected:
        # Add new connection
        connections.append(
            {
                "name": target_container,
                "auto_reconnect": True,
            }
        )
        # Save connections
        _save_containers_config(pctx.boxctl_dir, connections)

    console.print(f"\n[green]✓ Connected to {target_container}[/green]")
    console.print(f"  Container: {target_container} ({target_id})")
    console.print(f"  Image: {target_image}")
    console.print(f"  Networks: {', '.join(target_networks)}")
    console.print(f"\n[blue]You can now access {target_container} by hostname from agents[/blue]")


@network.command()
@click.argument("target_container", shell_complete=_complete_connected_containers)
@handle_errors
def disconnect(target_container: str):
    """Disconnect from a container's network.

    Example:
        abox network disconnect postgres
    """
    pctx = _get_project_context()

    # Load connections
    connections = _load_containers_config(pctx.boxctl_dir)

    # Find connection
    connection = None
    for conn in connections:
        if conn.get("name") == target_container:
            connection = conn
            break

    if not connection:
        current_names = [conn.get("name") for conn in connections]
        raise click.ClickException(
            f"Not connected to {target_container}. Current connections: {', '.join(current_names)}"
        )

    # Get networks from the target container (if it still exists)
    networks = []
    try:
        target = pctx.manager.client.containers.get(target_container)
        networks = pctx.manager.get_container_networks(target_container)
    except Exception:
        pass

    # Disconnect from networks (only if not used by other connections)
    if networks:
        networks_to_keep = set()
        for conn in connections:
            if conn.get("name") != target_container:
                try:
                    other_networks = pctx.manager.get_container_networks(conn.get("name"))
                    networks_to_keep.update(other_networks)
                except Exception:
                    pass

        networks_to_remove = [n for n in networks if n not in networks_to_keep]

        if networks_to_remove and pctx.manager.container_exists(pctx.container_name):
            console.print(
                f"[blue]Disconnecting from networks: {', '.join(networks_to_remove)}[/blue]"
            )
            pctx.manager.disconnect_from_networks(pctx.container_name, networks_to_remove)

        if set(networks) - set(networks_to_remove):
            console.print(
                f"  Kept networks: {', '.join(set(networks) - set(networks_to_remove))} (used by other containers)"
            )

    # Remove from connections
    connections = [c for c in connections if c.get("name") != target_container]
    _save_containers_config(pctx.boxctl_dir, connections)

    console.print(f"\n[green]✓ Disconnected from {target_container}[/green]")
