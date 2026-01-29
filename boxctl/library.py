# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Library management for boxctl MCP servers and skills."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import yaml
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

from boxctl.paths import ContainerPaths, HostPaths

console = Console()


def auto_detect_mcp_config(mcp_path: Path) -> Optional[Dict[str, Any]]:
    """Auto-detect MCP configuration from a Python package.

    Examines pyproject.toml to extract:
    - Entry point command from [project.scripts]
    - Name and description from [project]

    No hardcoded paths are generated. Path resolution happens at runtime
    via generate-mcp-config.py using source_type/source_name metadata.

    Args:
        mcp_path: Path to MCP directory

    Returns:
        Generated config dict, or None if detection fails
    """
    pyproject_path = mcp_path / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    try:
        content = pyproject_path.read_text()
        data = tomllib.loads(content)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = data.get("project", {})
    name = project.get("name", mcp_path.name)
    description = project.get("description", f"MCP server: {name}")

    # Find entry point from [project.scripts]
    scripts = project.get("scripts", {})
    command = None

    if scripts:
        # Use first script as the command
        command, _ = next(iter(scripts.items()))

    if command:
        # Has entry point script - just specify the command name
        # Path resolution (uv --directory) happens at runtime
        config = {
            "name": name,
            "description": description,
            "config": {"command": command, "env": {}},
            "auto_detected": True,
        }
    else:
        # No entry point - try to find server module
        src_dir = mcp_path / "src"
        if src_dir.exists():
            # Look for a server.py or __main__.py
            for pkg_dir in src_dir.iterdir():
                if pkg_dir.is_dir() and not pkg_dir.name.startswith((".", "_")):
                    module_name = pkg_dir.name
                    # Use relative module path - resolution happens at runtime
                    config = {
                        "name": name,
                        "description": description,
                        "config": {
                            "command": "python3",
                            "args": ["-m", f"{module_name}.server"],
                            "env": {},
                        },
                        "auto_detected": True,
                    }
                    break
            else:
                return None
        else:
            return None

    # Check for .env file and note it
    env_path = mcp_path / ".env"
    if env_path.exists():
        config["has_env_file"] = True

    return config


def parse_yaml_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Markdown content with optional YAML frontmatter

    Returns:
        Tuple of (frontmatter dict, remaining content)
    """
    frontmatter: Dict[str, Any] = {}
    body = content

    # Check for YAML frontmatter (starts with ---)
    if content.startswith("---"):
        # Find the closing ---
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if match:
            yaml_content = match.group(1)
            body = match.group(2)

            try:
                frontmatter = yaml.safe_load(yaml_content) or {}
            except yaml.YAMLError:
                frontmatter = {}

    return frontmatter, body


class LibraryManager:
    """Manages boxctl library system."""

    def __init__(self, library_root: Optional[Path] = None):
        """Initialize library manager.

        Args:
            library_root: Optional path to library root. If not provided,
                         discovers it from container path or relative to package.
        """
        if library_root is None:
            # First check container standard path
            container_library = Path(ContainerPaths.LIBRARY)
            if container_library.exists():
                library_root = container_library
            else:
                # Fall back to path relative to package installation
                # boxctl/library.py -> boxctl/ -> workspace/ -> library/
                package_dir = Path(__file__).parent  # boxctl/
                project_root = package_dir.parent  # workspace/
                library_root = project_root / "library"

        self.library_root = library_root
        self.config_dir = library_root / "config"
        self.mcp_dir = library_root / "mcp"
        self.skills_dir = library_root / "skills"

    @property
    def user_mcp_dir(self) -> Path:
        """User's custom MCP directory (~/.config/boxctl/mcp/)."""
        return HostPaths.user_mcp_dir()

    @property
    def user_skills_dir(self) -> Path:
        """User's custom skills directory (~/.config/boxctl/skills/)."""
        return HostPaths.user_skills_dir()

    def get_mcp_path(self, name: str) -> Optional[Path]:
        """Get path to MCP directory, checking custom first then library.

        Args:
            name: MCP server name

        Returns:
            Path to MCP directory, or None if not found
        """
        # Check custom directory first (user takes precedence)
        custom_path = self.user_mcp_dir / name
        if custom_path.exists() and custom_path.is_dir():
            return custom_path

        # Fall back to library
        library_path = self.mcp_dir / name
        if library_path.exists() and library_path.is_dir():
            return library_path

        return None

    def get_mcp_source_type(self, mcp_path: Path) -> str:
        """Determine the source type of an MCP based on its path.

        Args:
            mcp_path: Path to the MCP directory

        Returns:
            Source type: "library", "custom", or "project"
        """
        mcp_path_str = str(mcp_path.resolve())
        user_mcp_str = str(self.user_mcp_dir.resolve())
        library_mcp_str = str(self.mcp_dir.resolve())

        if mcp_path_str.startswith(user_mcp_str):
            return "custom"
        elif mcp_path_str.startswith(library_mcp_str):
            return "library"
        else:
            return "project"

    def get_skill_path(self, name: str) -> Optional[Path]:
        """Get path to skill SKILL.md, checking custom first then library.

        Args:
            name: Skill name (folder name)

        Returns:
            Path to SKILL.md, or None if not found
        """
        for skills_dir in [self.user_skills_dir, self.skills_dir]:
            if not skills_dir.exists():
                continue

            folder_path = skills_dir / name
            if folder_path.is_dir():
                skill_md = folder_path / "SKILL.md"
                if skill_md.exists():
                    return skill_md

        return None

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

                configs.append(
                    {
                        "name": config_path.name,
                        "path": str(config_path),
                        "description": description,
                        "has_config": config_file.exists(),
                    }
                )

        return configs

    def _get_mcp_info(self, server_path: Path, source: str) -> Dict[str, str]:
        """Extract MCP server info from a directory.

        Args:
            server_path: Path to MCP server directory
            source: Source identifier ("library" or "custom")

        Returns:
            Dict with server info
        """
        package_json = server_path / "package.json"
        readme_file = server_path / "README.md"

        description = "No description"
        if readme_file.exists():
            description = readme_file.read_text().split("\n")[0].replace("#", "").strip()
        elif package_json.exists():
            try:
                pkg_data = json.loads(package_json.read_text())
                description = pkg_data.get("description", "No description")
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "name": server_path.name,
            "path": str(server_path),
            "description": description,
            "source": source,
        }

    def list_mcp_servers(self) -> List[Dict[str, str]]:
        """List available MCP servers from library and custom directories.

        Custom MCPs override library MCPs with the same name.

        Returns:
            List of MCP server info dicts with 'source' field
        """
        servers_by_name: Dict[str, Dict[str, str]] = {}

        # First add library MCPs
        if self.mcp_dir.exists():
            for server_path in self.mcp_dir.iterdir():
                if server_path.is_dir():
                    info = self._get_mcp_info(server_path, "library")
                    servers_by_name[info["name"]] = info

        # Then add custom MCPs (override library if same name)
        if self.user_mcp_dir.exists():
            for server_path in self.user_mcp_dir.iterdir():
                if server_path.is_dir():
                    info = self._get_mcp_info(server_path, "custom")
                    servers_by_name[info["name"]] = info

        return sorted(servers_by_name.values(), key=lambda x: x["name"])

    def _get_skill_info(self, skill_path: Path, source: str) -> Dict[str, str]:
        """Extract skill info from SKILL.md.

        Args:
            skill_path: Path to SKILL.md file
            source: Source identifier ("library" or "custom")

        Returns:
            Dict with skill info
        """
        description = "No description"
        name = skill_path.parent.name  # Folder name is the skill name

        try:
            content = skill_path.read_text()
            frontmatter, _ = parse_yaml_frontmatter(content)
            # Ensure description is a string
            desc = frontmatter.get("description")
            if desc is not None:
                description = str(desc)
            # Use name from frontmatter if available
            if "name" in frontmatter:
                name = str(frontmatter["name"])
        except (OSError, UnicodeDecodeError):
            pass

        return {
            "name": name,
            "path": str(skill_path),
            "description": description,
            "source": source,
        }

    def _collect_skills_from_dir(self, skills_dir: Path, source: str) -> Dict[str, Dict[str, str]]:
        """Collect skills from a directory recursively.

        Scans for SKILL.md files at any depth, allowing cloned repos
        to be placed directly in the skills directory.

        Args:
            skills_dir: Directory to scan for skills
            source: Source identifier ("library" or "custom")

        Returns:
            Dict mapping skill names to skill info
        """
        skills: Dict[str, Dict[str, str]] = {}

        if not skills_dir.exists():
            return skills

        # Recursively find all SKILL.md files
        for skill_md in skills_dir.rglob("SKILL.md"):
            # Skip hidden directories (like .git) - only check relative path
            relative_parts = skill_md.relative_to(skills_dir).parts
            if any(part.startswith(".") for part in relative_parts):
                continue
            info = self._get_skill_info(skill_md, source)
            skills[info["name"]] = info

        return skills

    def list_skills(self) -> List[Dict[str, str]]:
        """List available skills from library and custom directories.

        Skills use the SKILL.md format: skill-name/SKILL.md folder with YAML frontmatter.
        Custom skills override library skills with the same name.

        Returns:
            List of skill info dicts with 'source' field
        """
        skills_by_name: Dict[str, Dict[str, str]] = {}

        # First add library skills
        skills_by_name.update(self._collect_skills_from_dir(self.skills_dir, "library"))

        # Then add custom skills (override library if same name)
        skills_by_name.update(self._collect_skills_from_dir(self.user_skills_dir, "custom"))

        return sorted(skills_by_name.values(), key=lambda x: x["name"])

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
        import json
        import os
        from pathlib import Path

        servers = self.list_mcp_servers()

        if not servers:
            console.print("[yellow]No MCP servers found[/yellow]")
            console.print(f"[blue]Add MCP servers to: {self.mcp_dir}[/blue]")
            console.print(f"[blue]Or add custom MCPs to: {self.user_mcp_dir}[/blue]")
            return

        # Load current project's MCP configuration
        env_project_dir = os.getenv("BOXCTL_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        boxctl_dir = project_dir / ".boxctl"

        added_mcps = set()
        if boxctl_dir.exists():
            # Check Claude MCP config
            claude_mcp_path = boxctl_dir / "claude" / "mcp.json"
            if claude_mcp_path.exists():
                try:
                    claude_mcp_data = json.loads(claude_mcp_path.read_text())
                    added_mcps.update(claude_mcp_data.get("mcpServers", {}).keys())
                except (json.JSONDecodeError, OSError):
                    pass

        table = Table(title="MCP Servers")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Source", style="blue")
        table.add_column("Added", style="green")

        for server in servers:
            is_added = "✓" if server["name"] in added_mcps else "-"
            table.add_row(
                server["name"],
                server["description"],
                server.get("source", "library"),
                is_added,
            )

        console.print(table)
        if added_mcps:
            console.print(f"\n[green]Added MCPs: {', '.join(sorted(added_mcps))}[/green]")

    def print_skills_table(self) -> None:
        """Print a formatted table of skills."""
        skills = self.list_skills()

        if not skills:
            console.print("[yellow]No skills found[/yellow]")
            console.print(f"[blue]Add skills to: {self.skills_dir}[/blue]")
            console.print(f"[blue]Or add custom skills to: {self.user_skills_dir}[/blue]")
            return

        table = Table(title="Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Source", style="blue")

        for skill in skills:
            table.add_row(
                skill["name"],
                skill["description"],
                skill.get("source", "library"),
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
        mcp_path = self.get_mcp_path(name)
        if mcp_path is None:
            console.print(f"[red]MCP server '{name}' not found[/red]")
            console.print(f"[blue]Check library: {self.mcp_dir}[/blue]")
            console.print(f"[blue]Or custom: {self.user_mcp_dir}[/blue]")
            return

        # Determine source
        source = "custom" if str(mcp_path).startswith(str(self.user_mcp_dir)) else "library"

        console.print(f"[cyan]MCP Server: {name}[/cyan]")
        console.print(f"[blue]Source: {source}[/blue]")
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
            name: Skill name (folder name)
        """
        skill_path = self.get_skill_path(name)
        if skill_path is None:
            console.print(f"[red]Skill '{name}' not found[/red]")
            console.print(f"[blue]Check library: {self.skills_dir}[/blue]")
            console.print(f"[blue]Or custom: {self.user_skills_dir}[/blue]")
            return

        # Determine source
        source = "custom" if str(skill_path).startswith(str(self.user_skills_dir)) else "library"
        display_name = skill_path.parent.name

        console.print(f"[cyan]Skill: {display_name}[/cyan]")
        console.print(f"[blue]Source: {source}[/blue]")
        console.print(f"[blue]Path: {skill_path}[/blue]\n")

        skill_content = skill_path.read_text()
        frontmatter, body = parse_yaml_frontmatter(skill_content)

        if frontmatter:
            console.print("[yellow]Frontmatter:[/yellow]")
            for key, value in frontmatter.items():
                console.print(f"  {key}: {value}")
            console.print()

        console.print("[yellow]Instructions:[/yellow]")
        syntax = Syntax(body.strip(), "markdown", theme="monokai", line_numbers=True)
        console.print(syntax)

        # List additional files in skill folder
        skill_dir = skill_path.parent
        other_files = [f.name for f in skill_dir.iterdir() if f.name != "SKILL.md"]
        if other_files:
            console.print(f"\n[yellow]Additional files:[/yellow]")
            for f in sorted(other_files):
                console.print(f"  - {f}")
