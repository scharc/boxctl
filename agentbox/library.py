# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Library management for Agentbox MCP servers and skills."""

import json
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

console = Console()


class LibraryManager:
    """Manages Agentbox library system."""

    AGENTBOX_DIR = Path("/x/coding/agentbox")

    def __init__(self):
        """Initialize library manager."""
        library_dir = self.AGENTBOX_DIR / "library"
        self.config_dir = library_dir / "config"
        self.mcp_dir = library_dir / "mcp"
        self.skills_dir = library_dir / "skills"

    def list_configs(self) -> List[Dict[str, str]]:
        """List available config presets.

        Returns:
            List of config info dicts
        """
        if not self.config_dir.exists():
            return []

        configs = []
        for config_path in self.config_dir.iterdir():
            if config_path.is_dir():
                config_file = config_path / "config.json"
                readme_file = config_path / "README.md"

                description = "No description"
                if readme_file.exists():
                    description = readme_file.read_text().split("\n")[0].replace("#", "").strip()

                configs.append({
                    "name": config_path.name,
                    "path": str(config_path),
                    "description": description,
                    "has_config": config_file.exists(),
                })

        return configs

    def list_mcp_servers(self) -> List[Dict[str, str]]:
        """List available MCP servers.

        Returns:
            List of MCP server info dicts
        """
        if not self.mcp_dir.exists():
            return []

        servers = []
        for server_path in self.mcp_dir.iterdir():
            if server_path.is_dir():
                if server_path.name == "notify":
                    continue
                package_json = server_path / "package.json"
                readme_file = server_path / "README.md"

                description = "No description"
                if readme_file.exists():
                    description = readme_file.read_text().split("\n")[0].replace("#", "").strip()
                elif package_json.exists():
                    try:
                        pkg_data = json.loads(package_json.read_text())
                        description = pkg_data.get("description", "No description")
                    except Exception:
                        pass

                servers.append({
                    "name": server_path.name,
                    "path": str(server_path),
                    "description": description,
                })

        return servers


    def list_skills(self) -> List[Dict[str, str]]:
        """List available skills.

        Returns:
            List of skill info dicts
        """
        if not self.skills_dir.exists():
            return []

        skills = []
        for skill_path in self.skills_dir.iterdir():
            if skill_path.is_file() and skill_path.suffix in [".json", ".yaml", ".yml"]:
                description = "No description"
                readme_file = skill_path.parent / f"{skill_path.stem}.md"
                if readme_file.exists():
                    description = readme_file.read_text().split("\n")[0].replace("#", "").strip()

                skills.append({
                    "name": skill_path.name,
                    "path": str(skill_path),
                    "description": description,
                })

        return skills

    def print_configs_table(self) -> None:
        """Print a formatted table of config presets."""
        configs = self.list_configs()

        if not configs:
            console.print("[yellow]No config presets found in library[/yellow]")
            console.print(f"[blue]Create presets in: {self.config_dir}[/blue]")
            return

        table = Table(title="Config Presets")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Path", style="blue")

        for config in configs:
            table.add_row(
                config["name"],
                config["description"],
                config["path"],
            )

        console.print(table)

    def print_mcp_table(self) -> None:
        """Print a formatted table of MCP servers."""
        servers = self.list_mcp_servers()

        if not servers:
            console.print("[yellow]No MCP servers found in library[/yellow]")
            console.print(f"[blue]Add MCP servers to: {self.mcp_dir}[/blue]")
            return

        table = Table(title="MCP Servers")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Path", style="blue")

        for server in servers:
            table.add_row(
                server["name"],
                server["description"],
                server["path"],
            )

        console.print(table)

    def print_skills_table(self) -> None:
        """Print a formatted table of skills."""
        skills = self.list_skills()

        if not skills:
            console.print("[yellow]No skills found in library[/yellow]")
            console.print(f"[blue]Add skills to: {self.skills_dir}[/blue]")
            return

        table = Table(title="Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Path", style="blue")

        for skill in skills:
            table.add_row(
                skill["name"],
                skill["description"],
                skill["path"],
            )

        console.print(table)

    def show_config(self, name: str) -> None:
        """Show details of a config preset.

        Args:
            name: Config preset name
        """
        config_path = self.config_dir / name
        if not config_path.exists():
            console.print(f"[red]Config preset '{name}' not found[/red]")
            return

        console.print(f"[cyan]Config Preset: {name}[/cyan]")
        console.print(f"[blue]Path: {config_path}[/blue]\n")

        # Show README if exists
        readme_file = config_path / "README.md"
        if readme_file.exists():
            console.print("[yellow]README:[/yellow]")
            console.print(readme_file.read_text())
            console.print()

        # Show config.json if exists
        config_file = config_path / "config.json"
        if config_file.exists():
            console.print("[yellow]Config:[/yellow]")
            config_content = config_file.read_text()
            syntax = Syntax(config_content, "json", theme="monokai", line_numbers=True)
            console.print(syntax)

    def show_mcp(self, name: str) -> None:
        """Show details of an MCP server.

        Args:
            name: MCP server name
        """
        mcp_path = self.mcp_dir / name
        if not mcp_path.exists():
            console.print(f"[red]MCP server '{name}' not found[/red]")
            return

        console.print(f"[cyan]MCP Server: {name}[/cyan]")
        console.print(f"[blue]Path: {mcp_path}[/blue]\n")

        # Show README if exists
        readme_file = mcp_path / "README.md"
        if readme_file.exists():
            console.print("[yellow]README:[/yellow]")
            console.print(readme_file.read_text())
            console.print()

        # Show package.json if exists
        package_file = mcp_path / "package.json"
        if package_file.exists():
            console.print("[yellow]package.json:[/yellow]")
            package_content = package_file.read_text()
            syntax = Syntax(package_content, "json", theme="monokai", line_numbers=True)
            console.print(syntax)

    def show_skill(self, name: str) -> None:
        """Show details of a skill.

        Args:
            name: Skill filename
        """
        skill_path = self.skills_dir / name
        if not skill_path.exists():
            console.print(f"[red]Skill '{name}' not found[/red]")
            return

        console.print(f"[cyan]Skill: {name}[/cyan]")
        console.print(f"[blue]Path: {skill_path}[/blue]\n")

        # Show README if exists
        readme_file = skill_path.parent / f"{skill_path.stem}.md"
        if readme_file.exists():
            console.print("[yellow]README:[/yellow]")
            console.print(readme_file.read_text())
            console.print()

        # Show skill content
        skill_content = skill_path.read_text()
        lexer = "yaml" if skill_path.suffix in [".yaml", ".yml"] else "json"
        syntax = Syntax(skill_content, lexer, theme="monokai", line_numbers=True)
        console.print(syntax)