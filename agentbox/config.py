# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Configuration management for Agentbox projects."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml
from rich.console import Console

console = Console()


class ProjectConfig:
    """Manages .agentbox.yml configuration for projects."""

    CONFIG_FILENAME = ".agentbox.yml"
    SUPPORTED_VERSION = "1.0"

    def __init__(self, project_dir: Optional[Path] = None):
        """Initialize config manager.

        Args:
            project_dir: Project directory (defaults to current dir)
        """
        if project_dir is None:
            # Check for environment variable set by wrapper script
            env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
            if env_project_dir:
                project_dir = Path(env_project_dir)
            else:
                project_dir = Path.cwd()
        self.project_dir = project_dir
        self.config_path = project_dir / self.CONFIG_FILENAME
        self.config: Dict[str, Any] = {}
        self._load()

    def exists(self) -> bool:
        """Check if config file exists.

        Returns:
            True if .agentbox.yml exists
        """
        return self.config_path.exists()

    def _load(self) -> None:
        """Load configuration from file."""
        if not self.exists():
            return

        try:
            with open(self.config_path, "r") as f:
                self.config = yaml.safe_load(f) or {}

            # Validate version
            version = self.config.get("version")
            if version != self.SUPPORTED_VERSION:
                console.print(
                    f"[yellow]Warning: Unsupported config version {version}, "
                    f"expected {self.SUPPORTED_VERSION}[/yellow]"
                )

        except yaml.YAMLError as e:
            console.print(f"[red]Error parsing {self.CONFIG_FILENAME}: {e}[/red]")
            self.config = {}
        except Exception as e:
            console.print(f"[red]Error loading config: {e}[/red]")
            self.config = {}

    def save(self) -> None:
        """Save configuration to file."""
        try:
            with open(self.config_path, "w") as f:
                yaml.safe_dump(self.config, f, default_flow_style=False, sort_keys=False)
            console.print(f"[green]Config saved to {self.config_path}[/green]")
        except Exception as e:
            console.print(f"[red]Error saving config: {e}[/red]")

    @property
    def system_packages(self) -> List[str]:
        """Get list of system packages to install.

        Returns:
            List of apt package names
        """
        return self.config.get("system_packages", [])

    @property
    def mcp_servers(self) -> List[str]:
        """Get list of MCP servers to enable.

        Returns:
            List of MCP server names from library
        """
        return self.config.get("mcp_servers", [])

    @property
    def skills(self) -> List[str]:
        """Get list of skills to enable.

        Returns:
            List of skill names from library
        """
        return self.config.get("skills", [])

    @property
    def hostname(self) -> Optional[str]:
        """Get hostname alias for /etc/hosts.

        Returns:
            Hostname string or None
        """
        return self.config.get("hostname")

    @property
    def environment(self) -> Dict[str, str]:
        """Get environment variables.

        Returns:
            Dictionary of environment variables
        """
        return self.config.get("env", {})

    @property
    def ports(self) -> List[str]:
        """Get port mappings (legacy, not used in current design).

        Returns:
            List of port mapping strings (e.g., "3000:3000")
        """
        return self.config.get("ports", [])

    def rebuild(self, container_manager, container_name: str) -> None:
        """Rebuild container environment from config.

        Args:
            container_manager: ContainerManager instance
            container_name: Name of container to configure
        """
        if not self.exists():
            console.print(
                f"[yellow]No {self.CONFIG_FILENAME} found in {self.project_dir}[/yellow]"
            )
            return

        console.print(f"[blue]Rebuilding from {self.CONFIG_FILENAME}...[/blue]")

        # Install system packages
        if self.system_packages:
            console.print(f"[blue]Installing system packages: {', '.join(self.system_packages)}[/blue]")
            packages = " ".join(self.system_packages)
            exit_code, output = container_manager.exec_command(
                container_name,
                ["sh", "-c", f"apt-get update && apt-get install -y {packages}"],
            )
            if exit_code != 0:
                console.print(f"[red]Error installing packages: {output}[/red]")
            else:
                console.print("[green]System packages installed[/green]")

        # Enable MCP servers
        if self.mcp_servers:
            console.print(f"[blue]Enabling MCP servers: {', '.join(self.mcp_servers)}[/blue]")
            # TODO: Implement MCP server installation from library
            console.print("[yellow]MCP server installation not yet implemented[/yellow]")

        # Enable skills
        if self.skills:
            console.print(f"[blue]Enabling skills: {', '.join(self.skills)}[/blue]")
            # TODO: Implement skill installation from library
            console.print("[yellow]Skill installation not yet implemented[/yellow]")

        # Set environment variables
        if self.environment:
            console.print(f"[blue]Setting environment variables[/blue]")
            # TODO: Persist environment variables in container
            console.print("[yellow]Environment variable persistence not yet implemented[/yellow]")

        # Set up hostname
        if self.hostname:
            console.print(f"[blue]Setting up hostname: {self.hostname}[/blue]")
            # This will be handled by network.py
            from agentbox.network import NetworkManager

            net_mgr = NetworkManager(container_name)
            net_mgr.add_hosts_entry(self.hostname)

        console.print("[green]Rebuild complete[/green]")

    def create_template(self) -> None:
        """Create a template .agentbox.yml file."""
        if self.exists():
            console.print(f"[yellow]{self.CONFIG_FILENAME} already exists[/yellow]")
            return

        template = {
            "version": self.SUPPORTED_VERSION,
            "system_packages": [
                "# Example: ffmpeg",
                "# Example: imagemagick",
            ],
            "mcp_servers": [
                "# Example: filesystem",
                "# Example: github",
            ],
            "skills": [
                "# Example: custom-skill",
            ],
            "hostname": "# Example: my-app.local",
            "env": {
                "# NODE_ENV": "development",
                "# DATABASE_URL": "postgres://localhost/mydb",
            },
        }

        self.config = template
        self.save()
        console.print(f"[green]Created template {self.CONFIG_FILENAME}[/green]")
        console.print("[blue]Edit the file and uncomment/modify the sections you need[/blue]")