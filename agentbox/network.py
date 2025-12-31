# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Network management for Agentbox containers."""

import subprocess
from typing import Optional

import docker
from rich.console import Console

console = Console()


class NetworkManager:
    """Manages network configuration for Agentbox containers."""

    def __init__(self, container_name: str):
        """Initialize network manager.

        Args:
            container_name: Name of container to manage
        """
        self.container_name = container_name
        try:
            self.client = docker.from_env()
            self.container = self.client.containers.get(container_name)
        except docker.errors.NotFound:
            console.print(f"[red]Container {container_name} not found[/red]")
            raise
        except docker.errors.DockerException as e:
            console.print(f"[red]Docker error: {e}[/red]")
            raise

    def get_ip(self) -> Optional[str]:
        """Get container IP address on Docker network.

        Returns:
            IP address string or None if not found
        """
        try:
            # Reload container to get fresh network settings
            self.container.reload()
            network_settings = self.container.attrs.get("NetworkSettings", {})
            ip = network_settings.get("IPAddress")

            if not ip:
                # Try to get IP from Networks
                networks = network_settings.get("Networks", {})
                if networks:
                    # Get first network's IP
                    first_network = next(iter(networks.values()))
                    ip = first_network.get("IPAddress")

            return ip
        except Exception as e:
            console.print(f"[red]Error getting IP: {e}[/red]")
            return None

    def generate_hostname(self, custom_hostname: Optional[str] = None) -> str:
        """Generate hostname for /etc/hosts.

        Args:
            custom_hostname: Custom hostname (optional)

        Returns:
            Hostname string
        """
        if custom_hostname:
            return custom_hostname

        # Generate from container name: agentbox-web-app → web-app.local
        project_name = self.container_name.replace("agentbox-", "")
        return f"{project_name}.local"

    def add_hosts_entry(self, hostname: Optional[str] = None) -> bool:
        """Add /etc/hosts entry for container.

        Args:
            hostname: Custom hostname (defaults to auto-generated)

        Returns:
            True if successful
        """
        ip = self.get_ip()
        if not ip:
            console.print("[red]Could not get container IP[/red]")
            return False

        hostname = self.generate_hostname(hostname)

        # Check if entry already exists
        try:
            with open("/etc/hosts", "r") as f:
                hosts_content = f.read()
                if hostname in hosts_content:
                    console.print(f"[yellow]Hostname {hostname} already exists in /etc/hosts[/yellow]")
                    # Update the IP if it changed
                    self.remove_hosts_entry(hostname)
        except Exception as e:
            console.print(f"[red]Error reading /etc/hosts: {e}[/red]")
            return False

        # Add entry to /etc/hosts (requires sudo)
        try:
            result = subprocess.run(
                ["sudo", "sh", "-c", f'echo "{ip} {hostname}" >> /etc/hosts'],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                console.print(f"[red]Error adding /etc/hosts entry: {result.stderr}[/red]")
                return False

            console.print(f"[green]Added {hostname} → {ip} to /etc/hosts[/green]")
            console.print(f"[blue]You can now access the container at: http://{hostname}[/blue]")
            return True

        except Exception as e:
            console.print(f"[red]Error executing sudo command: {e}[/red]")
            return False

    def remove_hosts_entry(self, hostname: str) -> bool:
        """Remove /etc/hosts entry.

        Args:
            hostname: Hostname to remove

        Returns:
            True if successful
        """
        try:
            # Use sed to remove lines containing the hostname
            result = subprocess.run(
                ["sudo", "sed", "-i", f"/{hostname}/d", "/etc/hosts"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                console.print(f"[red]Error removing /etc/hosts entry: {result.stderr}[/red]")
                return False

            console.print(f"[green]Removed {hostname} from /etc/hosts[/green]")
            return True

        except Exception as e:
            console.print(f"[red]Error executing sudo command: {e}[/red]")
            return False

    def list_hosts_entries(self) -> None:
        """List all Agentbox entries in /etc/hosts."""
        try:
            with open("/etc/hosts", "r") as f:
                lines = f.readlines()

            agentbox_entries = [
                line.strip() for line in lines if ".local" in line and not line.strip().startswith("#")
            ]

            if not agentbox_entries:
                console.print("[yellow]No .local entries found in /etc/hosts[/yellow]")
                return

            console.print("[blue]/etc/hosts entries:[/blue]")
            for entry in agentbox_entries:
                console.print(f"  {entry}")

        except Exception as e:
            console.print(f"[red]Error reading /etc/hosts: {e}[/red]")

    def show_access_info(self) -> None:
        """Show how to access the container."""
        ip = self.get_ip()
        if not ip:
            console.print("[red]Could not get container IP[/red]")
            return

        console.print(f"[green]Container: {self.container_name}[/green]")
        console.print(f"[blue]IP Address: {ip}[/blue]")
        console.print("\n[yellow]Access services directly via IP:[/yellow]")
        console.print(f"  http://{ip}:8000")
        console.print(f"  http://{ip}:5173")
        console.print(f"  http://{ip}:<port>")
        console.print("\n[yellow]Or add a hostname alias:[/yellow]")
        hostname = self.generate_hostname()
        console.print(f"  agentbox hosts add {self.container_name.replace('agentbox-', '')}")
        console.print(f"  Then use: http://{hostname}:<port>")