# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Service management commands for boxctld (notifications + web UI)."""

import os
import subprocess
from pathlib import Path

import click

from boxctl.cli import cli
from boxctl.cli.helpers import console, handle_errors
from boxctl.host_config import get_config

# Timeout for systemctl operations (seconds)
SYSTEMCTL_TIMEOUT = 30


def _get_service_unit_path() -> Path:
    """Get path to systemd user service file."""
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    return systemd_dir / "boxctld.service"


def _get_config_path() -> Path:
    """Get path to boxctld config file."""
    return Path.home() / ".config" / "boxctl" / "config.yml"


def _get_web_url() -> str:
    """Get the configured web UI URL from config."""
    config = get_config()
    url = config.web_server_url
    # Use localhost for display if binding to 127.0.0.1
    return url.replace("http://127.0.0.1:", "http://localhost:")


def _create_service_file() -> str:
    """Create systemd service file content."""
    import shutil

    # Get environment variables for display/dbus
    display = os.environ.get("DISPLAY", ":0")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir}/bus")
    socket_path = str(get_config().socket_path)

    # Find boxctl executable
    boxctl_path = shutil.which("boxctl") or shutil.which("abox")
    if not boxctl_path:
        boxctl_path = "/usr/bin/env boxctl"

    return f"""[Unit]
Description=boxctl Daemon (Notifications + Web UI)
After=network.target graphical-session.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY={display}
Environment=XDG_RUNTIME_DIR={runtime_dir}
Environment=DBUS_SESSION_BUS_ADDRESS={dbus_addr}
Environment=BOXCTLD_SOCKET={socket_path}
ExecStart={boxctl_path} service serve {socket_path}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""


def _create_default_config() -> str:
    """Create default config file content."""
    return """# boxctl Daemon Configuration

web_server:
  enabled: true
  host: 127.0.0.1
  port: 8080
  log_level: info

# Optional: notification hook script
# notify_hook: ~/.config/boxctl/notify-hook.sh
"""


@cli.group()
def service():
    """Manage boxctld service (notifications + web UI)."""
    pass


@service.command("install")
@handle_errors
def service_install():
    """Install and start the systemd service."""
    unit_path = _get_service_unit_path()
    config_path = _get_config_path()

    # Create config directory
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Create default config if it doesn't exist
    if not config_path.exists():
        config_path.write_text(_create_default_config())
        console.print(f"[green]Created config at {config_path}[/green]")
    else:
        console.print(f"[blue]Config exists at {config_path}[/blue]")

    # Create systemd service
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    service_content = _create_service_file()
    unit_path.write_text(service_content)

    console.print(f"[green]Installed service at {unit_path}[/green]")

    # Reload, enable, and start
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"], check=False, timeout=SYSTEMCTL_TIMEOUT
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "boxctld"], check=False, timeout=SYSTEMCTL_TIMEOUT
        )
        subprocess.run(
            ["systemctl", "--user", "start", "boxctld"], check=False, timeout=SYSTEMCTL_TIMEOUT
        )

        console.print("[green]Service enabled and started[/green]")
        console.print(f"[blue]Web UI: {_get_web_url()}[/blue]")
        console.print("[blue]Logs: abox service logs[/blue]")
    except FileNotFoundError:
        console.print("[yellow]systemctl not found - service file created but not loaded[/yellow]")
    except subprocess.TimeoutExpired:
        console.print("[red]systemctl command timed out[/red]")


@service.command("uninstall")
@handle_errors
def service_uninstall():
    """Uninstall the systemd service."""
    unit_path = _get_service_unit_path()

    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "boxctld"], check=False, timeout=SYSTEMCTL_TIMEOUT
        )
        subprocess.run(
            ["systemctl", "--user", "disable", "boxctld"], check=False, timeout=SYSTEMCTL_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if unit_path.exists():
        unit_path.unlink()
        console.print(f"[green]Uninstalled service from {unit_path}[/green]")
        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"], check=False, timeout=SYSTEMCTL_TIMEOUT
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    else:
        console.print("[yellow]Service not installed[/yellow]")


@service.command("start")
@handle_errors
def service_start():
    """Start the service."""
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "boxctld"], check=True, timeout=SYSTEMCTL_TIMEOUT
        )
        console.print("[green]Service started[/green]")
        console.print(f"[blue]Web UI: {_get_web_url()}[/blue]")
    except subprocess.CalledProcessError:
        raise click.ClickException("Failed to start service. Check: abox service status")
    except FileNotFoundError:
        raise click.ClickException("systemctl not found")
    except subprocess.TimeoutExpired:
        raise click.ClickException("systemctl command timed out")


@service.command("stop")
@handle_errors
def service_stop():
    """Stop the service."""
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "boxctld"], check=True, timeout=SYSTEMCTL_TIMEOUT
        )
        console.print("[green]Service stopped[/green]")
    except subprocess.CalledProcessError:
        raise click.ClickException("Failed to stop service")
    except FileNotFoundError:
        raise click.ClickException("systemctl not found")
    except subprocess.TimeoutExpired:
        raise click.ClickException("systemctl command timed out")


@service.command("restart")
@handle_errors
def service_restart():
    """Restart the service."""
    try:
        subprocess.run(
            ["systemctl", "--user", "restart", "boxctld"], check=True, timeout=SYSTEMCTL_TIMEOUT
        )
        console.print("[green]Service restarted[/green]")
        console.print(f"[blue]Web UI: {_get_web_url()}[/blue]")
    except subprocess.CalledProcessError:
        raise click.ClickException("Failed to restart service")
    except FileNotFoundError:
        raise click.ClickException("systemctl not found")
    except subprocess.TimeoutExpired:
        raise click.ClickException("systemctl command timed out")


@service.command("status")
@handle_errors
def service_status():
    """Show service status."""
    try:
        subprocess.run(["systemctl", "--user", "status", "boxctld"])
    except FileNotFoundError:
        raise click.ClickException("systemctl not found")


@service.command("logs")
@click.argument("lines", required=False, default="50")
@handle_errors
def service_logs(lines: str):
    """Show service logs.

    Pass number of lines to show (default: 50).

    Examples:
        abox service logs      # Show last 50 lines
        abox service logs 100  # Show last 100 lines
    """
    try:
        num_lines = int(lines)
    except ValueError:
        raise click.ClickException(f"Invalid number of lines: {lines}")

    cmd = ["journalctl", "--user", "-u", "boxctld", "-n", str(num_lines)]

    try:
        subprocess.run(cmd)
    except FileNotFoundError:
        raise click.ClickException("journalctl not found")


@service.command("follow")
@handle_errors
def service_follow():
    """Follow service logs in real-time (Ctrl+C to stop)."""
    cmd = ["journalctl", "--user", "-u", "boxctld", "-f"]

    try:
        subprocess.run(cmd)
    except FileNotFoundError:
        raise click.ClickException("journalctl not found")


@service.command("serve")
@click.argument("socket_path", required=False)
@handle_errors
def service_serve(socket_path: str = None):
    """Run boxctld in foreground for debugging.

    Pass optional socket path as argument (default: auto-detected).

    Examples:
        abox service serve                      # Use default socket
        abox service serve /tmp/custom.sock     # Custom socket path
    """
    from boxctl.boxctld import run_boxctld

    run_boxctld(socket_path)


@service.command("config")
@handle_errors
def service_config():
    """Show config file location and edit it."""
    config_path = _get_config_path()

    if config_path.exists():
        console.print(f"[blue]Config: {config_path}[/blue]")

        # Try to open in editor
        editor = os.environ.get("EDITOR", "nano")
        try:
            subprocess.run([editor, str(config_path)])
        except FileNotFoundError:
            console.print(f"[yellow]Editor '{editor}' not found[/yellow]")
            console.print(f"[yellow]Edit manually: {config_path}[/yellow]")
    else:
        console.print(f"[yellow]Config not found at {config_path}[/yellow]")
        console.print("[blue]Run: abox service install[/blue]")
