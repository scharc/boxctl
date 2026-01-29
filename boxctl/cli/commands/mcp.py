# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""MCP server commands."""

import json
from pathlib import Path
from typing import Set

import click
import questionary

from boxctl.cli import cli
from boxctl.cli.helpers import (
    _complete_mcp_names,
    _copy_commands,
    _get_project_context,
    _load_mcp_meta,
    _rebuild_container,
    _remove_commands,
    _require_boxctl_dir,
    _save_mcp_meta,
    _warn_if_agents_running,
    console,
    handle_errors,
    parse_env_file,
)
from boxctl.library import LibraryManager
from boxctl.utils.logging import get_logger
from boxctl.utils.project import resolve_project_dir, get_boxctl_dir

logger = get_logger(__name__)


def _get_unified_mcp_path(boxctl_dir: Path) -> Path:
    """Get path to unified mcp.json."""
    return boxctl_dir / "mcp.json"


def _get_installed_mcps(pctx) -> Set[str]:
    """Get set of currently installed MCP server names from unified config."""
    installed = set()

    # Read from unified mcp.json
    mcp_path = _get_unified_mcp_path(pctx.boxctl_dir)
    if mcp_path.exists():
        try:
            mcp_data = json.loads(mcp_path.read_text())
            installed.update(mcp_data.get("mcpServers", {}).keys())
        except (json.JSONDecodeError, OSError):
            pass

    return installed


def _add_mcp(name: str, lib_manager: LibraryManager, pctx) -> tuple[bool, bool]:
    """Add an MCP server to the project.

    Returns:
        Tuple of (success, needs_rebuild)
    """
    mcp_path = lib_manager.get_mcp_path(name)
    if mcp_path is None:
        return False, False

    template_path = mcp_path / "config.json"
    if not template_path.exists():
        return False, False

    template = json.loads(template_path.read_text())
    mcp_config = template["config"]

    # Load MCP-level .env file if it exists
    # This allows MCPs to ship with their own default env vars
    mcp_env_path = mcp_path / ".env"
    if mcp_env_path.exists():
        mcp_env_vars = parse_env_file(mcp_env_path)
        if mcp_env_vars:
            # Merge MCP .env vars into config (config.json values take precedence)
            existing_env = mcp_config.get("env", {})
            merged_env = {**mcp_env_vars, **existing_env}
            mcp_config["env"] = merged_env

    # Add to unified mcp.json (all agents read from this via symlinks/generation)
    # Note: allowed_agents/blocked_agents from template are no longer used since
    # all agents now read from unified mcp.json. Agent-specific filtering happens
    # at runtime via distribute-mcp-config.py (e.g., SSE servers skipped for Codex).
    unified_mcp_path = _get_unified_mcp_path(pctx.boxctl_dir)
    unified_mcp_path.parent.mkdir(parents=True, exist_ok=True)

    if unified_mcp_path.exists():
        mcp_data = json.loads(unified_mcp_path.read_text())
    else:
        mcp_data = {"mcpServers": {}}

    if name in mcp_data.get("mcpServers", {}):
        return False, False  # Already exists

    mcp_data["mcpServers"][name] = mcp_config
    unified_mcp_path.write_text(json.dumps(mcp_data, indent=2) + "\n")

    # Store MCP metadata (including config for generate-mcp-config.py)
    meta = _load_mcp_meta(pctx.boxctl_dir)

    # Determine source type and name for smart path resolution at runtime
    source_type = lib_manager.get_mcp_source_type(mcp_path)
    source_name = mcp_path.name  # Directory name

    server_meta = {
        "config": mcp_config,  # Store full config for config generation
        "source_type": source_type,  # "library", "custom", or "project"
        "source_name": source_name,  # Directory name for path resolution
    }
    if "install" in template:
        server_meta["install"] = template["install"]
    if "mounts" in template:
        server_meta["mounts"] = template["mounts"]
    # Always save - every MCP needs an entry for config generation
    meta["servers"][name] = server_meta
    _save_mcp_meta(pctx.boxctl_dir, meta)

    # Copy slash commands if the MCP has any (mcp_path is library path)
    copied_commands = _copy_commands(mcp_path, pctx.project_dir, "mcp", name)
    if copied_commands:
        meta["servers"][name]["commands"] = copied_commands
        _save_mcp_meta(pctx.boxctl_dir, meta)

    needs_rebuild = "mounts" in template or "install" in template
    return True, needs_rebuild


def _remove_mcp(name: str, pctx) -> tuple[bool, bool]:
    """Remove an MCP server from the project.

    Returns:
        Tuple of (removed, had_mounts)
    """
    removed = False
    had_mounts = False

    # Check if MCP had mounts before removing
    meta = _load_mcp_meta(pctx.boxctl_dir)
    if name in meta.get("servers", {}):
        had_mounts = "mounts" in meta["servers"][name]

    # Remove slash commands associated with this MCP
    _remove_commands(pctx.project_dir, "mcp", name)

    # Remove from unified mcp.json
    unified_mcp_path = _get_unified_mcp_path(pctx.boxctl_dir)
    if unified_mcp_path.exists():
        mcp_data = json.loads(unified_mcp_path.read_text())
        if name in mcp_data.get("mcpServers", {}):
            del mcp_data["mcpServers"][name]
            unified_mcp_path.write_text(json.dumps(mcp_data, indent=2) + "\n")
            removed = True

    # Remove from MCP metadata only if we actually removed something
    if removed and name in meta.get("servers", {}):
        del meta["servers"][name]
        _save_mcp_meta(pctx.boxctl_dir, meta)

    return removed, had_mounts


@cli.group(invoke_without_command=True)
@click.pass_context
@handle_errors
def mcp(ctx):
    """Manage MCP servers - select which servers to enable."""
    if ctx.invoked_subcommand is None:
        # Run the manage command by default
        ctx.invoke(mcp_manage)


@mcp.command(name="manage")
@handle_errors
def mcp_manage():
    """Interactive MCP server selection with checkboxes."""
    pctx = _get_project_context()
    _require_boxctl_dir(pctx.boxctl_dir, pctx.project_dir)

    lib_manager = LibraryManager()
    available_mcps = lib_manager.list_mcp_servers()

    if not available_mcps:
        console.print("[yellow]No MCP servers available in library[/yellow]")
        console.print(f"[blue]Add MCP servers to: {lib_manager.mcp_dir}[/blue]")
        return

    installed = _get_installed_mcps(pctx)

    # Build choices with pre-selection
    choices = []
    for mcp_info in available_mcps:
        name = mcp_info["name"]
        desc = (
            mcp_info["description"][:50] + "..."
            if len(mcp_info["description"]) > 50
            else mcp_info["description"]
        )
        source = mcp_info.get("source", "library")
        label = f"{name} ({source}) - {desc}"
        choices.append(questionary.Choice(title=label, value=name, checked=name in installed))

    console.print("[bold]Select MCP servers to enable:[/bold]")
    console.print("[dim]Space to toggle, Enter to confirm, Ctrl+C to cancel[/dim]\n")

    try:
        selected = questionary.checkbox(
            "MCP Servers:",
            choices=choices,
        ).ask()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
        return

    if selected is None:
        console.print("[yellow]Cancelled[/yellow]")
        return

    selected_set = set(selected)

    # Determine what to add and remove
    to_add = selected_set - installed
    to_remove = installed - selected_set

    if not to_add and not to_remove:
        console.print("[green]No changes needed[/green]")
        return

    # Track if rebuild is needed
    needs_rebuild = False
    added = []
    removed = []
    env_templates = {}
    notes = []

    # Add new MCPs
    for name in to_add:
        success, rebuild_needed = _add_mcp(name, lib_manager, pctx)
        if success:
            added.append(name)
            if rebuild_needed:
                needs_rebuild = True

            # Collect env templates and notes
            mcp_path = lib_manager.get_mcp_path(name)
            if mcp_path:
                template_path = mcp_path / "config.json"
                if template_path.exists():
                    template = json.loads(template_path.read_text())
                    if "env_template" in template:
                        env_templates[name] = template["env_template"]
                    if "notes" in template:
                        notes.append(f"{name}: {template['notes']}")
        else:
            console.print(f"[red]Failed to add MCP server '{name}'[/red]")

    # Remove MCPs
    for name in to_remove:
        success, had_mounts = _remove_mcp(name, pctx)
        if success:
            removed.append(name)
            if had_mounts:
                needs_rebuild = True

    # Print summary
    if added:
        console.print(f"[green]Added MCP servers: {', '.join(sorted(added))}[/green]")
    if removed:
        console.print(f"[yellow]Removed MCP servers: {', '.join(sorted(removed))}[/yellow]")

    # Show env templates
    if env_templates:
        console.print("\n[yellow]Configure environment variables:[/yellow]")
        for name, env in env_templates.items():
            console.print(f"  [cyan]{name}:[/cyan]")
            for key, value in env.items():
                console.print(f"    {key}={value}")
        console.print("\n[blue]Add to .boxctl/.env or set in your shell[/blue]")

    # Show notes
    if notes:
        console.print("\n[blue]Notes:[/blue]")
        for note in notes:
            console.print(f"  {note}")

    # Rebuild container if needed
    if needs_rebuild:
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("[yellow]Changes applied but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready to apply changes[/blue]")
            return

        console.print("\n[blue]Rebuilding container to apply changes...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)
        console.print("[green]Container rebuilt[/green]")


@mcp.command(name="show")
@click.argument("name", shell_complete=_complete_mcp_names)
@handle_errors
def mcp_show(name: str):
    """Show details of an MCP server."""
    lib_manager = LibraryManager()
    lib_manager.show_mcp(name)


@mcp.command(name="list")
@handle_errors
def mcp_list():
    """List available MCP servers from library."""
    lib_manager = LibraryManager()
    lib_manager.print_mcp_table()


@mcp.command(name="add")
@click.argument("name", shell_complete=_complete_mcp_names)
@handle_errors
def mcp_add(name: str):
    """Add an MCP server from library to current project."""
    pctx = _get_project_context()
    _require_boxctl_dir(pctx.boxctl_dir, pctx.project_dir)

    lib_manager = LibraryManager()
    success, needs_rebuild = _add_mcp(name, lib_manager, pctx)

    if not success:
        raise click.ClickException(f"MCP server '{name}' not found or already added")

    console.print(f"[green]✓ Added '{name}' to .boxctl/mcp.json[/green]")

    # Show env template if present
    mcp_path = lib_manager.get_mcp_path(name)
    if mcp_path:
        template_path = mcp_path / "config.json"
        if template_path.exists():
            template = json.loads(template_path.read_text())
            if "env_template" in template:
                console.print("\n[yellow]Configure environment variables:[/yellow]")
                for key, value in template["env_template"].items():
                    console.print(f"  {key}={value}")
                console.print("\n[blue]Add to .boxctl/.env or set in your shell[/blue]")
            if "notes" in template:
                console.print(f"\n[blue]Note: {template['notes']}[/blue]")

    # Rebuild container if needed
    if needs_rebuild:
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("[yellow]MCP added but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready[/blue]")
            return

        console.print("\n[blue]Rebuilding container to apply changes...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)
        console.print("[green]✓ Container rebuilt[/green]")
    else:
        console.print("[yellow]Restart container for changes to take effect[/yellow]")


@mcp.command(name="remove")
@click.argument("name", shell_complete=_complete_mcp_names)
@handle_errors
def mcp_remove(name: str):
    """Remove an MCP server from current project."""
    pctx = _get_project_context()

    removed, had_mounts = _remove_mcp(name, pctx)

    if not removed:
        console.print(f"[yellow]MCP server '{name}' not found in project[/yellow]")
        return

    console.print(f"[green]✓ Removed '{name}' from .boxctl/mcp.json[/green]")

    if had_mounts:
        if not _warn_if_agents_running(pctx.manager, pctx.container_name, "container rebuild"):
            console.print("[yellow]MCP removed but container rebuild cancelled[/yellow]")
            console.print("[blue]Run 'boxctl rebase' when ready[/blue]")
            return

        console.print("\n[blue]Rebuilding container to remove mounts...[/blue]")
        _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)
        console.print("[green]✓ Container rebuilt[/green]")
    else:
        console.print("[yellow]Restart container for changes to take effect[/yellow]")


MCP_INIT_PROMPT = """Analyze this MCP server folder and generate a config.json for boxctl.

The config.json format is:
```json
{
  "name": "server-name",
  "description": "Brief description of what this MCP does",
  "config": {
    "command": "python3|npx|uvx|node|<binary>",
    "args": ["arg1", "arg2"],
    "env": {
      "API_KEY": "${API_KEY}"
    }
  },
  "install": {
    "pip": ["package1", "package2"],
    "npm": ["@scope/package"],
    "post": ["shell command to run after install"]
  },
  "env_template": {
    "API_KEY": "your-api-key-here"
  },
  "notes": "Any usage notes or where to get API keys"
}
```

Important paths:
- MCP folder in container: /home/abox/.config/boxctl/mcp/MCP_NAME
- Use this path for PYTHONPATH or script references

Common patterns:
- Python with pyproject.toml scripts: {"command": "script-name"} + install with pip
- Python module: {"command": "python3", "args": ["-m", "module.server"]}
- npm package: {"command": "npx", "args": ["-y", "@scope/package"]}
- uvx: {"command": "uvx", "args": ["package-name"]}

Files in this MCP folder:
"""


@mcp.command(name="init")
@click.argument("path", required=False, type=click.Path(exists=True))
@click.option("--agent", default="claude", help="Agent to use (claude, codex)")
@handle_errors
def mcp_init(path: str | None, agent: str):
    """Generate config.json for an MCP using AI.

    Run in an MCP folder or pass PATH to the folder.
    Uses Claude/Codex to analyze the folder and generate config.json.
    """
    import os
    import subprocess

    # Determine MCP path:
    # 1. Explicit path argument takes priority
    # 2. BOXCTL_PROJECT_DIR if set (shell wrapper sets this to actual CWD)
    # 3. Fall back to os.getcwd()
    if path:
        mcp_path = Path(path)
    elif os.environ.get("BOXCTL_PROJECT_DIR"):
        mcp_path = Path(os.environ["BOXCTL_PROJECT_DIR"])
    else:
        mcp_path = Path.cwd()

    if not mcp_path.is_dir():
        raise click.ClickException(f"Not a directory: {mcp_path}")

    config_path = mcp_path / "config.json"
    if config_path.exists():
        if not click.confirm(f"config.json already exists. Overwrite?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # Collect relevant files (skip boxctl-specific files)
    relevant_files = [
        "pyproject.toml",
        "package.json",
        "server.json",
        "README.md",
        "setup.py",
        "setup.cfg",
        ".env.example",
        "claude_desktop_config.example.json",
        "Cargo.toml",  # Rust
        "go.mod",  # Go
    ]

    file_contents = []
    for filename in relevant_files:
        file_path = mcp_path / filename
        if file_path.exists():
            try:
                content = file_path.read_text()
                # Truncate large files
                if len(content) > 4000:
                    content = content[:4000] + "\n... (truncated)"
                file_contents.append(f"=== {filename} ===\n{content}")
            except (OSError, UnicodeDecodeError):
                pass

    # List directory structure (skip irrelevant folders)
    skip_dirs = {
        ".git",
        ".boxctl",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
    }
    dir_listing = []
    for item in sorted(mcp_path.rglob("*")):
        if item.is_file():
            # Skip files in ignored directories
            if any(skip_dir in item.parts for skip_dir in skip_dirs):
                continue
            rel_path = item.relative_to(mcp_path)
            dir_listing.append(str(rel_path))

    prompt = MCP_INIT_PROMPT.replace("MCP_NAME", mcp_path.name)
    prompt += f"\nDirectory listing:\n{chr(10).join(dir_listing[:50])}\n\n"
    prompt += "\n\n".join(file_contents)
    prompt += "\n\nGenerate ONLY the config.json content, no explanation or markdown blocks."

    console.print(f"[blue]Analyzing {mcp_path.name} with {agent}...[/blue]")

    # Call the agent
    try:
        result = subprocess.run(
            [agent, "--print", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise click.ClickException(f"{agent} failed: {result.stderr}")

        output = result.stdout.strip()

        # Try to extract JSON from response
        # Remove markdown code blocks if present
        if "```json" in output:
            output = output.split("```json")[1].split("```")[0].strip()
        elif "```" in output:
            output = output.split("```")[1].split("```")[0].strip()

        # Validate JSON
        try:
            config = json.loads(output)
        except json.JSONDecodeError as e:
            console.print(f"[red]Failed to parse AI response as JSON: {e}[/red]")
            console.print("[dim]Raw output:[/dim]")
            console.print(output[:500])
            raise click.ClickException("AI did not return valid JSON")

        # Write config
        config_path.write_text(json.dumps(config, indent=2))
        console.print(f"[green]✓ Generated {config_path}[/green]")

        # Show what was generated
        console.print("\n[yellow]Generated config:[/yellow]")
        console.print(json.dumps(config, indent=2))

        if "env_template" in config:
            console.print("\n[blue]Don't forget to create .env with your credentials:[/blue]")
            for key, val in config["env_template"].items():
                console.print(f"  {key}={val}")

    except subprocess.TimeoutExpired:
        raise click.ClickException(f"{agent} timed out")
    except FileNotFoundError:
        raise click.ClickException(f"{agent} not found. Is it installed?")
