# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Device passthrough management commands."""

import glob
from pathlib import Path
from typing import List, Set, Tuple

import click
import questionary

from boxctl.cli import cli
from boxctl.cli.helpers import (
    _get_project_context,
    _rebuild_container,
    _warn_if_agents_running,
    console,
    handle_errors,
)
from boxctl.config import ProjectConfig
from boxctl.utils.project import resolve_project_dir


# Common device categories with glob patterns
DEVICE_CATEGORIES = {
    "Audio": ["/dev/snd"],
    "GPU (Intel/AMD)": ["/dev/dri/card*", "/dev/dri/renderD*"],
    "GPU (NVIDIA)": ["/dev/nvidia*", "/dev/nvidiactl", "/dev/nvidia-uvm*"],
    "Serial/USB": ["/dev/ttyUSB*", "/dev/ttyACM*"],
    "Video/Camera": ["/dev/video*"],
    "Input": ["/dev/input/event*", "/dev/input/mouse*"],
    "USB Raw": ["/dev/bus/usb/*/*"],
}


def _get_available_devices() -> List[Tuple[str, str]]:
    """Get list of available devices on the system.

    Returns list of (device_path, category) tuples.
    """
    devices = []
    seen = set()

    for category, patterns in DEVICE_CATEGORIES.items():
        for pattern in patterns:
            # Handle both literal paths and glob patterns
            if "*" in pattern:
                matches = glob.glob(pattern)
            else:
                matches = [pattern] if Path(pattern).exists() else []

            for device_path in sorted(matches):
                if device_path not in seen and Path(device_path).exists():
                    seen.add(device_path)
                    devices.append((device_path, category))

    return devices


def _get_configured_devices(config: ProjectConfig) -> List[str]:
    """Get list of configured devices from config."""
    return list(config.devices)


def _save_devices(config: ProjectConfig, devices: List[str]) -> None:
    """Save devices to config."""
    config.devices = devices
    config.save()


@cli.group(invoke_without_command=True)
@click.pass_context
@handle_errors
def devices(ctx):
    """Manage device passthrough for containers.

    Pass through host devices (audio, GPU, serial) to the container.
    Devices that are unavailable at container start are automatically
    skipped - the container won't fail to start.
    """
    # If no subcommand, run interactive chooser
    if ctx.invoked_subcommand is None:
        ctx.invoke(devices_choose)


@devices.command(name="choose")
@handle_errors
def devices_choose():
    """Interactive device selection.

    Shows available devices with checkboxes. Pre-selects currently
    configured devices. Changes trigger a container rebuild.
    """
    project_dir = resolve_project_dir()
    config = ProjectConfig(project_dir)

    if not config.exists():
        raise click.ClickException(
            f"No .boxctl/config.yml found in {project_dir}. Run: boxctl init"
        )

    # Get available and configured devices
    available = _get_available_devices()
    configured = set(_get_configured_devices(config))

    if not available:
        console.print("[yellow]No devices found on this system[/yellow]")
        console.print(
            "[dim]Common device paths checked: /dev/snd, /dev/dri/*, /dev/ttyUSB*, etc.[/dim]"
        )
        return

    # Build choices grouped by category
    choices = []
    current_category = None

    for device_path, category in available:
        # Add category separator
        if category != current_category:
            if current_category is not None:
                choices.append(questionary.Separator())
            choices.append(questionary.Separator(f"── {category} ──"))
            current_category = category

        choices.append(
            questionary.Choice(
                title=device_path, value=device_path, checked=device_path in configured
            )
        )

    # Add any configured devices that aren't currently available
    missing_configured = configured - {d[0] for d in available}
    if missing_configured:
        choices.append(questionary.Separator())
        choices.append(questionary.Separator("── Configured (currently unavailable) ──"))
        for device_path in sorted(missing_configured):
            choices.append(
                questionary.Choice(
                    title=f"{device_path} [not found]", value=device_path, checked=True
                )
            )

    console.print("[bold]Select devices to pass through to container:[/bold]")
    console.print("[dim]Space to toggle, Enter to confirm, Ctrl+C to cancel[/dim]")
    console.print(
        "[dim]Unavailable devices are skipped at container start (won't cause failures)[/dim]\n"
    )

    try:
        selected = questionary.checkbox(
            "Devices:",
            choices=choices,
        ).ask()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
        return

    if selected is None:
        console.print("[yellow]Cancelled[/yellow]")
        return

    selected_set = set(selected)

    # Check what changed
    if selected_set == configured:
        console.print("[blue]No changes[/blue]")
        return

    added = selected_set - configured
    removed = configured - selected_set

    # Save changes
    _save_devices(config, sorted(selected_set))

    # Report changes
    if added:
        for device in sorted(added):
            console.print(f"[green]+ {device}[/green]")
    if removed:
        for device in sorted(removed):
            console.print(f"[red]- {device}[/red]")

    # Rebuild container if it exists
    pctx = _get_project_context()
    if pctx.manager.container_exists(pctx.container_name):
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("\n[yellow]Config updated but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready to apply[/blue]")
            return
        console.print("\n[blue]Rebuilding container to apply device changes...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)
    else:
        console.print("\n[green]✓ Devices configured[/green]")
        console.print("[dim]Changes will apply on next container start[/dim]")


@devices.command(name="list")
@handle_errors
def devices_list():
    """List configured and available devices."""
    project_dir = resolve_project_dir()
    config = ProjectConfig(project_dir)

    if not config.exists():
        raise click.ClickException(
            f"No .boxctl/config.yml found in {project_dir}. Run: boxctl init"
        )

    configured = _get_configured_devices(config)
    available = _get_available_devices()
    available_paths = {d[0] for d in available}

    console.print("[bold]Configured Devices[/bold]")
    if configured:
        for device in configured:
            if device in available_paths:
                console.print(f"  [green]✓[/green] {device}")
            else:
                console.print(
                    f"  [yellow]![/yellow] {device} [dim](not found - will be skipped)[/dim]"
                )
    else:
        console.print("  [dim]None[/dim]")

    console.print("\n[bold]Available Devices[/bold]")
    if available:
        current_category = None
        for device_path, category in available:
            if category != current_category:
                console.print(f"\n  [cyan]{category}[/cyan]")
                current_category = category
            marker = "[green]✓[/green]" if device_path in configured else "[dim]○[/dim]"
            console.print(f"    {marker} {device_path}")
    else:
        console.print("  [dim]No devices found[/dim]")

    console.print("\n[dim]Run 'boxctl devices' to configure interactively[/dim]")


@devices.command(name="add")
@click.argument("device", required=True)
@handle_errors
def devices_add(device: str):
    """Add a device to passthrough.

    DEVICE is the path to the device (e.g., /dev/snd, /dev/ttyUSB0).
    The device doesn't need to exist - unavailable devices are skipped
    at container start.
    """
    project_dir = resolve_project_dir()
    config = ProjectConfig(project_dir)

    if not config.exists():
        raise click.ClickException(
            f"No .boxctl/config.yml found in {project_dir}. Run: boxctl init"
        )

    # Validate device path format
    if not device.startswith("/dev/"):
        raise click.ClickException(f"Invalid device path: {device}. Must start with /dev/")

    configured = _get_configured_devices(config)

    if device in configured:
        console.print(f"[blue]Device already configured: {device}[/blue]")
        return

    # Check if device exists
    if not Path(device).exists():
        console.print(f"[yellow]Warning: Device not found: {device}[/yellow]")
        console.print("[dim]Device will be skipped if unavailable at container start[/dim]")

    # Add device
    configured.append(device)
    _save_devices(config, configured)
    console.print(f"[green]✓ Added device: {device}[/green]")

    # Rebuild container if it exists
    pctx = _get_project_context()
    if pctx.manager.container_exists(pctx.container_name):
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("\n[yellow]Device added but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready to apply[/blue]")
            return
        console.print("\n[blue]Rebuilding container to apply device changes...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)


@devices.command(name="remove")
@click.argument("device", required=True)
@handle_errors
def devices_remove(device: str):
    """Remove a device from passthrough.

    DEVICE is the path to the device (e.g., /dev/snd, /dev/ttyUSB0).
    """
    project_dir = resolve_project_dir()
    config = ProjectConfig(project_dir)

    if not config.exists():
        raise click.ClickException(
            f"No .boxctl/config.yml found in {project_dir}. Run: boxctl init"
        )

    configured = _get_configured_devices(config)

    if device not in configured:
        console.print(f"[yellow]Device not configured: {device}[/yellow]")
        return

    # Remove device
    configured.remove(device)
    _save_devices(config, configured)
    console.print(f"[green]✓ Removed device: {device}[/green]")

    # Rebuild container if it exists
    pctx = _get_project_context()
    if pctx.manager.container_exists(pctx.container_name):
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("\n[yellow]Device removed but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready to apply[/blue]")
            return
        console.print("\n[blue]Rebuilding container to apply device changes...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)


@devices.command(name="clear")
@handle_errors
def devices_clear():
    """Remove all configured devices."""
    project_dir = resolve_project_dir()
    config = ProjectConfig(project_dir)

    if not config.exists():
        raise click.ClickException(
            f"No .boxctl/config.yml found in {project_dir}. Run: boxctl init"
        )

    configured = _get_configured_devices(config)

    if not configured:
        console.print("[blue]No devices configured[/blue]")
        return

    # Clear devices
    _save_devices(config, [])
    console.print(f"[green]✓ Removed {len(configured)} device(s)[/green]")

    # Rebuild container if it exists
    pctx = _get_project_context()
    if pctx.manager.container_exists(pctx.container_name):
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("\n[yellow]Devices cleared but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready to apply[/blue]")
            return
        console.print("\n[blue]Rebuilding container to apply device changes...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)
