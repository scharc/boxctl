# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Quick access command - mobile-friendly TUI for boxctl."""

import json
import os
import sys
import threading
import time
import tty
import termios
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

# =============================================================================
# Module-level cache for port configuration (avoids repeated YAML reads)
# =============================================================================
_port_config_cache: Dict[str, Dict[str, Any]] = {}
_port_config_cache_time: Dict[str, float] = {}
_port_config_cache_lock = threading.Lock()
_PORT_CONFIG_CACHE_TTL = 5.0  # 5 seconds

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from boxctl.cli import cli
from boxctl.container import ContainerManager
from boxctl.paths import ContainerPaths, ContainerDefaults
from boxctl.cli.helpers import (
    _get_tmux_sessions,
    _attach_tmux_session,
    get_sessions_from_daemon,
    get_session_counts_from_daemon,
)
from boxctl.cli.commands.project import (
    shell,
    info,
    stop,
    rebase,
    remove,
    init as project_init,
    start as project_start,
)
from boxctl.cli.commands.agents import claude, superclaude, codex, supercodex, gemini, supergemini
from boxctl.cli.commands.mcp import mcp_add, _add_mcp, _get_installed_mcps
from boxctl.cli.commands.skill import skill_add, _add_skill, _get_installed_skills
from boxctl.cli.commands.network import connect as network_connect, disconnect as network_disconnect
from boxctl.cli.commands.workspace import workspace_add
from boxctl.cli.commands.worktree import worktree_add, _run_worktree_agent, _run_worktree_shell
from boxctl.cli.commands.ports import expose, forward, unexpose, unforward
from boxctl.cli.helpers import (
    _load_containers_config,
    _load_workspaces_config,
    _ensure_container_running,
)
from boxctl.library import LibraryManager

console = Console()


def clear_screen():
    """Clear the terminal screen."""
    console.print("\033[2J\033[H", end="")


def get_letter(index: int) -> str:
    """Convert index to letter (a-z)."""
    return chr(ord("a") + index)


def paginate(items: list, page: int, items_per_page: int = 20) -> tuple[list, int, int]:
    """Paginate a list of items.

    Args:
        items: Full list to paginate
        page: Current page number (0-indexed)
        items_per_page: Items per page (default 20)

    Returns:
        Tuple of (page_items, current_page, total_pages)
    """
    total = len(items)
    total_pages = max(1, (total + items_per_page - 1) // items_per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * items_per_page
    end = min(start + items_per_page, total)
    return items[start:end], page, total_pages


def add_pagination_actions(actions: list, page: int, total_pages: int) -> None:
    """Add pagination actions (next/prev page) to actions list.

    Args:
        actions: List to append actions to (modified in place)
        page: Current page number (0-indexed)
        total_pages: Total number of pages
    """
    if total_pages > 1:
        if page < total_pages - 1:
            actions.append(("1", "Next page"))
        if page > 0:
            actions.append(("2", "Prev page"))


def show_page_indicator(page: int, total_pages: int) -> None:
    """Show page indicator if paginated."""
    if total_pages > 1:
        console.print(f"[dim]Page {page + 1}/{total_pages}[/dim]\n")


def render_menu(
    title: str,
    sections: list[tuple[str, list[tuple[str, str, any]]]],
    actions: list[tuple[str, str]] = None,
) -> int:
    """Render a menu with sections and actions.

    Args:
        title: Menu title
        sections: List of (section_title, items) where items are (label, description, data) tuples
        actions: List of (key, description) tuples - selected with numbers

    Returns:
        Total item count across all sections (for letter indexing)
    """
    clear_screen()

    # Title
    console.print(Panel(Text(title, style="bold cyan"), expand=False))
    console.print()

    total_items = 0
    has_any_items = any(items for _, items in sections)

    if not has_any_items and not actions:
        console.print("[dim]No items available[/dim]")
        console.print()

    # Sections with items (letter selection)
    for section_title, items in sections:
        if items:
            console.print(f"[bold]{section_title}[/bold]")
            for i, (label, desc, _) in enumerate(items):
                letter = get_letter(total_items + i)
                if desc:
                    console.print(
                        f"  [bold yellow]{letter})[/bold yellow] {label} [dim]({desc})[/dim]"
                    )
                else:
                    console.print(f"  [bold yellow]{letter})[/bold yellow] {label}")
            total_items += len(items)
            console.print()

    # Actions (number selection)
    if actions:
        console.print("[dim]─" * 30 + "[/dim]")
        for key, desc in actions:
            console.print(f"  [bold green]{key})[/bold green] {desc}")

    console.print()
    return total_items


def get_char() -> str:
    """Get single character from terminal without Enter."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        # Handle Ctrl+C
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def get_input(prompt: str = "Select") -> str:
    """Get single character input from user."""
    try:
        console.print(f"[bold]{prompt}:[/bold] ", end="")
        ch = get_char()
        console.print(ch)  # Echo the character
        return ch
    except (KeyboardInterrupt, EOFError):
        console.print()
        return "0"


def get_text_input(prompt: str = "Name") -> str:
    """Get text input (requires Enter). Empty for default."""
    try:
        console.print(f"[bold]{prompt}:[/bold] ", end="")
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return ""


def get_path_input(prompt: str = "Path", start_path: str = None) -> str:
    """Get path input with tab completion for directories."""
    import readline

    def path_completer(text, state):
        """Readline completer for directory paths."""
        # Expand ~ to home directory
        if text.startswith("~"):
            expanded = os.path.expanduser(text)
        else:
            expanded = text

        # Get the directory part and the partial name
        if "/" in expanded:
            dir_part = os.path.dirname(expanded)
            name_part = os.path.basename(expanded)
        else:
            dir_part = "." if not expanded else expanded
            name_part = ""

        # If dir_part is empty, use current directory
        if not dir_part:
            dir_part = "."

        try:
            # List directories that match
            matches = []
            search_dir = Path(dir_part).expanduser()
            if search_dir.is_dir():
                for entry in search_dir.iterdir():
                    if entry.is_dir():
                        entry_name = entry.name
                        if not name_part or entry_name.lower().startswith(name_part.lower()):
                            # Build the full path for the match
                            if text.startswith("~"):
                                match = "~/" + str(entry.relative_to(Path.home())) + "/"
                            else:
                                match = str(entry) + "/"
                            matches.append(match)
            matches.sort()
            if state < len(matches):
                return matches[state]
        except (OSError, ValueError):
            pass
        return None

    # Save old completer and delims
    old_completer = readline.get_completer()
    old_delims = readline.get_completer_delims()

    try:
        # Set up path completion
        readline.set_completer(path_completer)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")

        # Pre-fill with start path if provided
        if start_path:
            readline.set_startup_hook(lambda: readline.insert_text(start_path))

        console.print(f"[bold]{prompt}:[/bold] ", end="")
        result = input().strip()
        return result
    except (KeyboardInterrupt, EOFError):
        console.print()
        return ""
    finally:
        # Restore old settings
        readline.set_completer(old_completer)
        readline.set_completer_delims(old_delims)
        readline.set_startup_hook(None)


def resolve_typed_path(current_path: "Path") -> Optional["Path"]:
    """Get path input, validate it's a directory, return resolved Path or None.

    Shows error message and waits for keypress if path is invalid.
    """

    typed_path = get_path_input("Path", str(current_path) + "/")
    if not typed_path:
        return None

    resolved = Path(typed_path).expanduser().resolve()
    if resolved.is_dir():
        return resolved

    console.print(f"[red]Not a valid directory: {resolved}[/red]")
    get_input("Press any key")
    return None


def confirm_action(message: str) -> bool:
    """Ask for confirmation with single keypress. Returns True if 'y'."""
    console.print(f"[yellow]{message}[/yellow]")
    choice = get_input("Press 'y' to confirm")
    return choice == "y"


def get_system_status() -> Optional[dict]:
    """Fetch system status from the boxctld web API.

    Returns None if the service is not running or unreachable.
    """
    from boxctl.host_config import HostConfig

    try:
        host_config = HostConfig()
        web_config = host_config._config.get("web_server", {})
        port = web_config.get("port", 8080)

        url = f"http://localhost:{port}/api/status"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        with urllib.request.urlopen(req, timeout=2) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception):
        return None


def status_menu() -> Optional[str]:
    """Show detailed system status with per-container port info."""
    from boxctl.config import parse_port_spec

    clear_screen()
    console.print(Panel(Text("STATUS", style="bold cyan"), expand=False))
    console.print()

    console.print("[dim]Loading...[/dim]")
    status = get_system_status()

    # Clear the loading message
    clear_screen()
    console.print(Panel(Text("STATUS", style="bold cyan"), expand=False))
    console.print()

    if status is None:
        console.print("[red]● Service offline[/red]")
        console.print("[dim]Run 'boxctld' on the host to start the service[/dim]")
        console.print()
        console.print("[dim]─" * 30 + "[/dim]")
        console.print("  [bold green]0)[/bold green] Back")
        console.print()
        get_input()
        return "main"

    # Extract data
    service = status.get("service", {})
    containers = status.get("containers", [])

    # Service section
    console.print("[bold]SERVICE[/bold]")
    console.print(f"  [green]●[/green] boxctld running")
    console.print()

    # Per-container details
    console.print("[bold]CONTAINERS[/bold]")

    # Single-pass partitioning instead of two list comprehensions
    running = []
    stopped = []
    for c in containers:
        if c.get("status") == "running":
            running.append(c)
        else:
            stopped.append(c)

    if not running:
        console.print("  [dim]No running containers[/dim]")
    else:
        for c in running:
            name = c.get("project", c.get("name", "unknown"))
            project_path = c.get("project_path", "")
            tunnel_ok = c.get("tunnel_connected", False)

            # Header line with tunnel status
            tunnel_indicator = (
                "[green]●[/green] tunnel" if tunnel_ok else "[yellow]○[/yellow] no tunnel"
            )
            console.print(f"  [bold]{name}[/bold]  {tunnel_indicator}")

            # Get port config for this container
            ports = (
                get_configured_ports(project_path)
                if project_path
                else {"host": [], "container": []}
            )

            # Exposed ports (container → host)
            exposed = ports.get("host", [])
            if exposed:
                exposed_strs = []
                for spec in exposed[:4]:  # Max 4
                    try:
                        parsed = parse_port_spec(str(spec))
                        if parsed["container_port"] == parsed["host_port"]:
                            exposed_strs.append(f"{parsed['container_port']}")
                        else:
                            exposed_strs.append(f"{parsed['container_port']}→{parsed['host_port']}")
                    except Exception:
                        exposed_strs.append(str(spec))
                if len(exposed) > 4:
                    exposed_strs.append(f"+{len(exposed) - 4}")
                console.print(f"    [cyan]Exposed:[/cyan] {', '.join(exposed_strs)}")
            else:
                console.print(f"    [dim]Exposed: none[/dim]")

            # Forwarded ports (host → container)
            forwarded = ports.get("container", [])
            if forwarded:
                fwd_strs = []
                for entry in forwarded[:4]:  # Max 4
                    try:
                        if isinstance(entry, dict):
                            # Old dict format
                            port = entry.get("port", 0)
                        else:
                            # New string format: "9222" or "9222:9223"
                            port = int(str(entry).split(":")[0])
                        fwd_strs.append(f":{port}")
                    except (ValueError, TypeError):
                        fwd_strs.append("??")
                if len(forwarded) > 4:
                    fwd_strs.append(f"+{len(forwarded) - 4}")
                console.print(f"    [cyan]Forward:[/cyan] {', '.join(fwd_strs)}")
            else:
                console.print(f"    [dim]Forward: none[/dim]")

            console.print()

    # Stopped containers summary (already computed above)
    if stopped:
        console.print(f"  [dim]{len(stopped)} stopped[/dim]")
        console.print()

    # Actions
    console.print("[dim]─" * 30 + "[/dim]")
    console.print("  [bold green]0)[/bold green] Back")
    console.print()

    get_input()
    return "main"


# Agent types available for new sessions - (id, display_name, command_func)
AGENT_TYPES = [
    ("claude", "claude", claude),
    ("superclaude", "superclaude", superclaude),
    ("codex", "codex", codex),
    ("supercodex", "supercodex", supercodex),
    ("gemini", "gemini", gemini),
    ("supergemini", "supergemini", supergemini),
]


def get_all_sessions() -> list[dict]:
    """Get all sessions across all running containers, sorted by project/session name.

    Uses daemon cache for fast queries (~5ms), falls back to docker exec if unavailable.
    """
    # Try daemon first (fast path)
    daemon_sessions = get_sessions_from_daemon(timeout=1.0)
    if daemon_sessions is not None:
        # Sort by project name, then session name
        daemon_sessions.sort(
            key=lambda s: (s.get("project", "").lower(), s.get("session_name", "").lower())
        )
        return daemon_sessions

    # Fallback to docker exec (slow path)
    manager = ContainerManager()
    containers = manager.list_containers(all_containers=False)  # Only running

    all_sessions = []
    for container in containers:
        container_name = container["name"]
        project = container.get("project", ContainerDefaults.project_from_container(container_name))
        project_path = container.get("project_path", "")

        sessions = _get_tmux_sessions(manager, container_name)
        for session in sessions:
            all_sessions.append(
                {
                    "container_name": container_name,
                    "project": project,
                    "project_path": project_path,
                    "session_name": session["name"],
                    "attached": session["attached"],
                    "windows": session["windows"],
                }
            )

    # Sort by project name, then session name
    all_sessions.sort(key=lambda s: (s["project"].lower(), s["session_name"].lower()))
    return all_sessions


def get_running_containers() -> list[dict]:
    """Get all running containers with their session counts, sorted by project name.

    Uses daemon cache for session counts (~5ms), falls back to docker exec if unavailable.
    """
    manager = ContainerManager()
    containers = manager.list_containers(all_containers=False)  # Only running

    # Try to get session counts from daemon (fast path)
    session_counts = get_session_counts_from_daemon(timeout=1.0)

    result = []
    for container in containers:
        container_name = container["name"]
        project = container.get("project", ContainerDefaults.project_from_container(container_name))
        project_path = container.get("project_path", "")

        # Use daemon cache if available, otherwise fallback to docker exec
        if session_counts is not None:
            count = session_counts.get(container_name, 0)
        else:
            sessions = _get_tmux_sessions(manager, container_name)
            count = len(sessions)

        result.append(
            {
                "container_name": container_name,
                "project": project,
                "project_path": project_path,
                "session_count": count,
            }
        )

    # Sort by project name
    result.sort(key=lambda c: c["project"].lower())
    return result


def shorten_path(path: str, max_len: int = 30) -> str:
    """Shorten path for display, keeping end visible."""
    if not path or len(path) <= max_len:
        return path or ""
    return "..." + path[-(max_len - 3) :]


def new_session_menu(container_data: dict) -> Optional[str]:
    """Show agent selection for new session."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Set project dir env var at the start so all commands use correct project
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    path_short = shorten_path(project_path)

    items = []
    for agent_id, agent_name, agent_cmd in AGENT_TYPES:
        items.append((agent_name, "", agent_cmd))

    sections = [("AGENT TYPE", items)]
    actions = [("0", "Back")]

    render_menu(f"NEW SESSION: {project}", sections, actions)
    if path_short:
        console.print(f"[dim]Path: {path_short}[/dim]\n")

    choice = get_input()

    if choice == "0":
        return "main"

    # Handle agent selection
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(items):
            agent_cmd = items[idx][2]

            # Invoke agent command - BOXCTL_PROJECT_DIR is already set
            ctx = click.get_current_context()
            ctx.invoke(agent_cmd, prompt=())
            return None  # Exit after launching

    return "main"


def manage_select_menu() -> Optional[str]:
    """Show container selection for management."""
    containers = get_running_containers()

    items = []
    for c in containers:
        path_short = shorten_path(c.get("project_path", ""))
        sessions = f"{c['session_count']} sessions" if c["session_count"] > 0 else "no sessions"
        items.append((c["project"], f"{sessions} {path_short}".strip(), c))

    sections = [("SELECT CONTAINER", items)]
    actions = [("0", "Back")]

    render_menu("MANAGE", sections, actions)

    choice = get_input()

    if choice == "0":
        return "main"

    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(items):
            return ("manage_actions", items[idx][2])

    return "main"


def manage_actions_menu(container_data: dict) -> Optional[str]:
    """Show actions for a specific container."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Always set the project dir env var at the start
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    action_items = [
        ("New session...", "", "new_session"),
        ("Add MCP server...", "", "add_mcp"),
        ("Add workspace...", "", "add_workspace"),
        ("Add skill...", "", "add_skill"),
        ("Ports...", "", "ports"),
        ("Network connect...", "", "network"),
        ("Shell access", "", "shell"),
        ("View info", "", "info"),
    ]

    danger_items = [
        ("Stop container", "", "stop"),
        ("Rebase container", "", "rebase"),
        ("Remove container", "", "remove"),
    ]

    sections = [
        ("ACTIONS", action_items),
        ("DANGER", danger_items),
    ]

    all_items = action_items + danger_items
    actions = [("0", "Back")]

    render_menu(f"MANAGE: {project}", sections, actions)
    path_short = shorten_path(project_path)
    if path_short:
        console.print(f"[dim]Path: {path_short}[/dim]\n")

    choice = get_input()

    if choice == "0":
        return "manage_select"

    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(all_items):
            action = all_items[idx][2]
            ctx = click.get_current_context()

            if action == "new_session":
                return ("new_session", container_data)

            elif action == "add_mcp":
                return ("mcp_menu", container_data, 0)

            elif action == "add_workspace":
                return ("workspace_menu", container_data)

            elif action == "add_skill":
                return ("skill_menu", container_data, 0)

            elif action == "ports":
                return ("ports_menu", container_data)

            elif action == "network":
                return ("network_menu", container_data)

            elif action == "shell":
                ctx.invoke(shell, project_name=project)
                return None  # Exit after shell

            elif action == "info":
                clear_screen()
                ctx.invoke(info, project_name=project)
                get_input("Press any key")
                return ("manage_actions", container_data)

            elif action == "stop":
                if confirm_action(f"Stop container {project}?"):
                    ctx.invoke(stop, project_name=project)
                    get_input("Press any key")
                return "manage_select"

            elif action == "rebase":
                if confirm_action(f"Rebase container {project}? This will restart all sessions."):
                    ctx.invoke(rebase)
                    get_input("Press any key")
                return "manage_select"

            elif action == "remove":
                if confirm_action(f"Remove container {project}? This cannot be undone."):
                    ctx.invoke(remove, project_name=project, force_remove="force")
                    get_input("Press any key")
                return "manage_select"

    return ("manage_actions", container_data)


def get_added_mcps(project_path: str) -> set:
    """Get set of MCP names already added to the project."""
    from boxctl.cli.helpers import _get_project_context

    if not project_path:
        return set()

    try:
        # Temporarily set the project dir for the context
        old_dir = os.environ.get("BOXCTL_PROJECT_DIR")
        os.environ["BOXCTL_PROJECT_DIR"] = project_path
        pctx = _get_project_context()
        result = _get_installed_mcps(pctx)
        if old_dir:
            os.environ["BOXCTL_PROJECT_DIR"] = old_dir
        return result
    except Exception:
        return set()


def mcp_menu(container_data: dict, page: int = 0) -> Optional[str]:
    """Show MCP server selection menu."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Set project dir for mcp_add command
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    # Get available and added MCPs
    lib = LibraryManager()
    all_mcps = lib.list_mcp_servers()
    added_mcps = get_added_mcps(project_path)

    # Split into available and added
    available = [
        (m["name"], m["description"][:40], m) for m in all_mcps if m["name"] not in added_mcps
    ]
    added = [(m["name"], "✓ added", m) for m in all_mcps if m["name"] in added_mcps]

    # Paginate available items
    page_available, page, total_pages = paginate(available, page)

    sections = [
        ("AVAILABLE", page_available),
        ("ADDED", added),
    ]

    actions = []
    add_pagination_actions(actions, page, total_pages)
    actions.append(("0", "Back"))

    render_menu(f"ADD MCP: {project}", sections, actions)
    show_page_indicator(page, total_pages)

    choice = get_input()

    if choice == "0":
        return ("manage_actions", container_data)
    elif choice == "1" and page < total_pages - 1:
        return ("mcp_menu", container_data, page + 1)
    elif choice == "2" and page > 0:
        return ("mcp_menu", container_data, page - 1)

    # Handle MCP selection
    all_items = page_available + added
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(all_items):
            mcp_name = all_items[idx][0]

            if mcp_name in added_mcps:
                console.print(f"[yellow]'{mcp_name}' is already added[/yellow]")
                get_input("Press any key")
            else:
                # Add the MCP server using internal function
                console.print(f"\n[cyan]Adding {mcp_name}...[/cyan]\n")
                from boxctl.cli.helpers import _get_project_context, _rebuild_container

                try:
                    pctx = _get_project_context()
                    success, needs_rebuild = _add_mcp(mcp_name, lib, pctx)
                    if success:
                        console.print(f"[green]✓ Added '{mcp_name}' MCP server[/green]")
                        if needs_rebuild:
                            console.print("\n[blue]Rebuilding container...[/blue]")
                            _rebuild_container(
                                pctx.manager,
                                pctx.project_name,
                                pctx.project_dir,
                                pctx.container_name,
                            )
                            console.print("[green]✓ Container rebuilt[/green]")
                    else:
                        console.print(f"[red]Failed to add MCP server '{mcp_name}'[/red]")
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                get_input("Press any key")

            return ("mcp_menu", container_data, page)

    return ("mcp_menu", container_data, page)


def get_added_skills(project_path: str) -> set:
    """Get set of skill names already added to the project."""
    from boxctl.utils.project import get_boxctl_dir

    if not project_path:
        return set()

    boxctl_dir = get_boxctl_dir(Path(project_path))
    return _get_installed_skills(boxctl_dir)


def skill_menu(container_data: dict, page: int = 0) -> Optional[str]:
    """Show skill selection menu."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Set project dir for skill_add command
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    # Get available and added skills
    lib = LibraryManager()
    all_skills = lib.list_skills()
    added_skills = get_added_skills(project_path)

    # Extract skill name (remove .yaml/.json extension)
    def skill_name(skill):
        name = skill["name"]
        for ext in [".yaml", ".yml", ".json"]:
            if name.endswith(ext):
                name = name[: -len(ext)]
        return name

    # Split into available and added
    available = [
        (skill_name(s), s["description"][:40], s)
        for s in all_skills
        if skill_name(s) not in added_skills
    ]
    added = [(skill_name(s), "✓ added", s) for s in all_skills if skill_name(s) in added_skills]

    # Paginate available items
    page_available, page, total_pages = paginate(available, page)

    sections = [
        ("AVAILABLE", page_available),
        ("ADDED", added),
    ]

    actions = []
    add_pagination_actions(actions, page, total_pages)
    actions.append(("0", "Back"))

    render_menu(f"ADD SKILL: {project}", sections, actions)
    show_page_indicator(page, total_pages)

    choice = get_input()

    if choice == "0":
        return ("manage_actions", container_data)
    elif choice == "1" and page < total_pages - 1:
        return ("skill_menu", container_data, page + 1)
    elif choice == "2" and page > 0:
        return ("skill_menu", container_data, page - 1)

    # Handle skill selection
    all_items = page_available + added
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(all_items):
            sname = all_items[idx][0]

            if sname in added_skills:
                console.print(f"[yellow]'{sname}' is already added[/yellow]")
                get_input("Press any key")
            else:
                # Add the skill using internal function
                console.print(f"\n[cyan]Adding {sname}...[/cyan]\n")
                from boxctl.utils.project import get_boxctl_dir

                try:
                    boxctl_dir = get_boxctl_dir(Path(project_path))
                    if _add_skill(sname, lib, boxctl_dir):
                        console.print(f"[green]✓ Added '{sname}' skill[/green]")
                    else:
                        console.print(f"[red]Failed to add skill '{sname}'[/red]")
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                get_input("Press any key")

            return ("skill_menu", container_data, page)

    return ("skill_menu", container_data, page)


def get_connected_containers(project_path: str) -> set:
    """Get set of container names currently connected."""

    connected = set()
    if not project_path:
        return connected

    boxctl_dir = Path(project_path) / ".boxctl"
    if boxctl_dir.exists():
        connections = _load_containers_config(boxctl_dir)
        connected = {conn.get("name") for conn in connections if conn.get("name")}

    return connected


def network_menu(container_data: dict) -> Optional[str]:
    """Show network connection menu."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Set project dir for network commands
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    # Get available containers
    manager = ContainerManager()
    all_containers = manager.get_all_containers(include_boxctl=False)
    connected = get_connected_containers(project_path)

    # Split into available and connected
    available_items = []
    connected_items = []

    for c in sorted(all_containers, key=lambda x: x["name"].lower()):
        cname = c["name"]
        status = c["status"][:12]
        if cname in connected:
            connected_items.append((cname, f"✓ {status}", c))
        else:
            available_items.append((cname, status, c))

    sections = [
        ("AVAILABLE", available_items),
        ("CONNECTED", connected_items),
    ]

    actions = [("0", "Back")]

    render_menu(f"NETWORK: {project}", sections, actions)
    console.print("[dim]Select available to connect, connected to disconnect[/dim]\n")

    choice = get_input()

    if choice == "0":
        return ("manage_actions", container_data)

    # Handle container selection
    all_items = available_items + connected_items
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(all_items):
            cname = all_items[idx][0]
            ctx = click.get_current_context()

            if cname in connected:
                # Disconnect
                console.print(f"\n[cyan]Disconnecting from {cname}...[/cyan]\n")
                try:
                    ctx.invoke(network_disconnect, container_name=cname)
                except SystemExit:
                    pass
            else:
                # Connect
                console.print(f"\n[cyan]Connecting to {cname}...[/cyan]\n")
                try:
                    ctx.invoke(network_connect, container_name=cname)
                except SystemExit:
                    pass

            get_input("Press any key")
            return ("network_menu", container_data)

    return ("network_menu", container_data)


def get_configured_ports(project_path: str) -> dict:
    """Get configured ports from .boxctl/config.yml.

    Performance optimized: Uses TTL cache (5 seconds) to avoid repeated YAML reads.
    """
    import yaml

    result = {"host": [], "container": []}
    if not project_path:
        return result

    # Check cache first
    cache_key = project_path
    with _port_config_cache_lock:
        if cache_key in _port_config_cache:
            if time.time() - _port_config_cache_time.get(cache_key, 0) < _PORT_CONFIG_CACHE_TTL:
                return _port_config_cache[cache_key].copy()

    config_file = Path(project_path) / ".boxctl/config.yml"
    if not config_file.exists():
        return result

    try:
        data = yaml.safe_load(config_file.read_text()) or {}
        ports = data.get("ports", {})

        if isinstance(ports, dict):
            result["host"] = ports.get("host", [])
            result["container"] = ports.get("container", [])

        # Cache the result
        with _port_config_cache_lock:
            _port_config_cache[cache_key] = result
            _port_config_cache_time[cache_key] = time.time()
    except Exception:
        pass

    return result


def ports_menu(container_data: dict) -> Optional[str]:
    """Show port forwarding management menu."""
    from boxctl.config import parse_port_spec

    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Set project dir for port commands
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    # Get configured ports
    ports = get_configured_ports(project_path)

    # Build items for exposed ports (container → host)
    exposed_items = []
    for spec in ports.get("host", []):
        try:
            parsed = parse_port_spec(spec)
            desc = f"container:{parsed['container_port']} → host:{parsed['host_port']}"
            exposed_items.append(
                (f":{parsed['host_port']}", desc, ("exposed", spec, parsed["host_port"]))
            )
        except Exception:
            exposed_items.append((spec, "invalid", ("exposed", spec, 0)))

    # Build items for forwarded ports (host → container)
    # New format is string like "9222" or "9222:9223", old format was dict
    forwarded_items = []
    for entry in ports.get("container", []):
        try:
            if isinstance(entry, dict):
                # Old dict format: {"name": "...", "port": N}
                port = entry.get("port", 0)
                cport = entry.get("container_port", port)
            else:
                # New string format: "9222" or "9222:9223"
                parts = str(entry).split(":")
                if len(parts) == 2:
                    port, cport = int(parts[0]), int(parts[1])
                else:
                    port = cport = int(parts[0])
            desc = f"host:{port} → container:{cport}"
            forwarded_items.append((f":{port}", desc, ("forwarded", port, entry)))
        except (ValueError, TypeError):
            # Invalid port spec, skip
            forwarded_items.append((str(entry), "invalid", ("forwarded", 0, entry)))

    sections = [
        ("EXPOSED (container → host)", exposed_items),
        ("FORWARDED (host → container)", forwarded_items),
    ]

    all_items = exposed_items + forwarded_items
    actions = [
        ("1", "Expose port..."),
        ("2", "Forward port..."),
        ("0", "Back"),
    ]

    render_menu(f"PORTS: {project}", sections, actions)
    console.print("[dim]Select to remove, or add new[/dim]\n")

    choice = get_input()

    if choice == "0":
        return ("manage_actions", container_data)
    elif choice == "1":
        return ("ports_expose", container_data)
    elif choice == "2":
        return ("ports_forward", container_data)

    # Handle port selection (to remove)
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(all_items):
            port_type, port_id, port_data = all_items[idx][2]

            if port_type == "exposed":
                if confirm_action(f"Unexpose port {port_data}?"):
                    ctx = click.get_current_context()
                    try:
                        ctx.invoke(unexpose, port=port_data)
                    except SystemExit:
                        pass
                    get_input("Press any key")
            else:
                # port_id is now the host port (int)
                if confirm_action(f"Unforward port {port_id}?"):
                    ctx = click.get_current_context()
                    try:
                        ctx.invoke(unforward, port=port_id)
                    except SystemExit:
                        pass
                    get_input("Press any key")

            return ("ports_menu", container_data)

    return ("ports_menu", container_data)


def ports_expose_flow(container_data: dict) -> Optional[str]:
    """Flow to expose a container port."""
    project_path = container_data.get("project_path") or ""

    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    clear_screen()
    console.print(f"[bold]EXPOSE PORT: {container_data['project']}[/bold]\n")
    console.print("[dim]Format: 3000 or 3000:8080 (container:host)[/dim]\n")
    console.print("[dim]Service runs in container, accessible from host[/dim]\n")

    port_spec = get_text_input("Port (or empty to cancel)")

    if not port_spec:
        return ("ports_menu", container_data)

    console.print(f"\n[cyan]Exposing port {port_spec}...[/cyan]\n")
    ctx = click.get_current_context()
    try:
        ctx.invoke(expose, port_spec=port_spec)
    except SystemExit:
        pass

    get_input("Press any key")
    return ("ports_menu", container_data)


def ports_forward_flow(container_data: dict) -> Optional[str]:
    """Flow to forward a host port into container."""
    project_path = container_data.get("project_path") or ""

    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    clear_screen()
    console.print(f"[bold]FORWARD PORT: {container_data['project']}[/bold]\n")
    console.print("[dim]Format: 9222 or 9222:9223 (host:container)[/dim]\n")
    console.print("[dim]Service runs on host, accessible from container[/dim]\n")

    port_spec = get_text_input("Port (or empty to cancel)")

    if not port_spec:
        return ("ports_menu", container_data)

    console.print(f"\n[cyan]Forwarding port {port_spec}...[/cyan]\n")
    ctx = click.get_current_context()
    try:
        ctx.invoke(forward, port_spec=port_spec)
    except SystemExit:
        pass

    get_input("Press any key")
    return ("ports_menu", container_data)


def folder_browser(
    start_path: str = None, title: str = "SELECT DIRECTORY", show_mode_options: bool = False
) -> Optional[tuple]:
    """Browse and select a directory.

    Args:
        start_path: Starting directory (defaults to home)
        title: Title to show in menu
        show_mode_options: If True, offer ro/rw selection options

    Returns:
        If show_mode_options: (path, mode) where mode is "ro" or "rw"
        Otherwise: (path,) single-element tuple
        None if cancelled
    """

    if start_path is None:
        start_path = str(Path.home())

    current_path = Path(start_path).resolve()
    page = 0

    while True:
        # Get directories in current path
        try:
            entries = []
            for entry in current_path.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    entries.append(entry.name)
            entries.sort(key=str.lower)
        except PermissionError:
            entries = []

        # Add parent directory option
        dir_items = []
        if current_path.parent != current_path:
            dir_items.append(("..", "parent directory", "parent"))

        # Add directories
        for dirname in entries:
            dir_items.append((f"{dirname}/", "", dirname))

        # Paginate directory items (18 per page to leave room for parent)
        page_items, page, total_pages = paginate(dir_items, page, items_per_page=18)

        sections = [("DIRECTORIES", page_items)]

        actions = []
        add_pagination_actions(actions, page, total_pages)

        if show_mode_options:
            actions.append(("3", "Select here (read-only)"))
            actions.append(("4", "Select here (read-write)"))
            actions.append(("5", "Type path..."))
        else:
            actions.append(("3", "Select here"))
            actions.append(("4", "Type path..."))
        actions.append(("0", "Cancel"))

        render_menu(title, sections, actions)
        path_display = str(current_path)
        if len(path_display) > 50:
            path_display = "..." + path_display[-47:]
        console.print(f"[dim]Path: {path_display}[/dim]")
        show_page_indicator(page, total_pages)

        choice = get_input()

        if choice == "0":
            return None
        elif choice == "1" and page < total_pages - 1:
            page += 1
            continue
        elif choice == "2" and page > 0:
            page -= 1
            continue
        elif choice == "3":
            if show_mode_options:
                return (str(current_path), "ro")
            else:
                return (str(current_path),)
        elif choice == "4":
            if show_mode_options:
                return (str(current_path), "rw")
            else:
                # Type path option (when no mode options)
                new_path = resolve_typed_path(current_path)
                if new_path:
                    current_path = new_path
                    page = 0
                continue
        elif choice == "5" and show_mode_options:
            # Type path option (when mode options present)
            new_path = resolve_typed_path(current_path)
            if new_path:
                current_path = new_path
                page = 0
            continue

        # Handle directory selection
        if choice.isalpha() and len(choice) == 1:
            idx = ord(choice) - ord("a")
            if 0 <= idx < len(page_items):
                item_data = page_items[idx][2]
                if item_data == "parent":
                    current_path = current_path.parent
                    page = 0
                else:
                    new_path = current_path / item_data
                    if new_path.is_dir():
                        current_path = new_path
                        page = 0


def workspace_menu(container_data: dict) -> Optional[str]:
    """Show workspace management menu using folder browser."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""

    # Set project dir for workspace_add command
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    # Use folder browser with mode selection
    result = folder_browser(
        start_path=str(os.path.expanduser("~")),
        title=f"ADD WORKSPACE: {project}",
        show_mode_options=True,
    )

    if result is None:
        return ("manage_actions", container_data)

    selected_path, mode = result

    # Add workspace using existing command
    console.print(f"\n[cyan]Adding workspace {selected_path} ({mode})...[/cyan]\n")
    ctx = click.get_current_context()
    try:
        ctx.invoke(workspace_add, path=selected_path, mode=mode, name=None)
    except SystemExit:
        pass  # workspace_add uses sys.exit

    get_input("Press any key")
    return ("manage_actions", container_data)


def new_container_flow() -> Optional[str]:
    """Flow to create a new container from a selected directory."""

    # Use folder browser to select project directory
    result = folder_browser(
        start_path=str(Path.home()), title="NEW CONTAINER", show_mode_options=False
    )

    if result is None:
        return "main"

    selected_path = result[0]

    # Set project dir for init command
    os.environ["BOXCTL_PROJECT_DIR"] = selected_path

    # Check if already initialized
    boxctl_dir = Path(selected_path) / ".boxctl"
    already_initialized = boxctl_dir.exists()

    if not already_initialized:
        # Initialize the project
        console.print(f"\n[cyan]Initializing {selected_path}...[/cyan]\n")
        ctx = click.get_current_context()
        try:
            ctx.invoke(project_init)
        except SystemExit:
            pass

    # Ask if user wants to start a session
    clear_screen()
    console.print(f"[green]Project directory: {selected_path}[/green]\n")

    if already_initialized:
        console.print("[dim]Project was already initialized[/dim]\n")

    console.print("[bold]Start a session?[/bold]")
    console.print("  [bold yellow]a)[/bold yellow] Claude")
    console.print("  [bold yellow]b)[/bold yellow] SuperClaude (auto-approve)")
    console.print("  [bold yellow]c)[/bold yellow] Codex")
    console.print("  [bold yellow]d)[/bold yellow] SuperCodex (auto-approve)")
    console.print("  [bold yellow]e)[/bold yellow] Gemini")
    console.print("  [bold yellow]f)[/bold yellow] SuperGemini (auto-approve)")
    console.print()
    console.print("  [bold green]0)[/bold green] Back to main menu")
    console.print()

    choice = get_input()

    if choice == "0":
        return "main"

    # Get project name from the path
    project_name = Path(selected_path).name

    # Build container data for session
    container_data = {
        "project": project_name,
        "project_path": selected_path,
    }

    agent_map = {
        "a": claude,
        "b": superclaude,
        "c": codex,
        "d": supercodex,
        "e": gemini,
        "f": supergemini,
    }

    if choice in agent_map:
        ctx = click.get_current_context()
        # Don't pass project - BOXCTL_PROJECT_DIR is already set
        ctx.invoke(agent_map[choice], prompt=())
        return None  # Exit after launching

    return "main"


def get_worktrees(container_name: str) -> list[dict]:
    """Get list of worktrees from a specific container."""
    import json

    try:
        manager = ContainerManager()

        if not _ensure_container_running(manager, container_name):
            return []

        # Get worktrees as JSON
        from boxctl.container import get_abox_environment

        exit_code, output = manager.exec_command(
            container_name,
            ["agentctl", "worktree", "list", "--json"],
            environment=get_abox_environment(include_tmux=True, container_name=container_name),
            user=ContainerPaths.USER,
            workdir="/workspace",
        )

        if exit_code != 0 or not output:
            return []

        return json.loads(output)
    except Exception:
        return []


def worktree_select_menu() -> Optional[str]:
    """Show container selection for worktree management."""
    containers = get_running_containers()

    items = []
    for c in containers:
        path_short = shorten_path(c.get("project_path", ""))
        items.append((c["project"], path_short, c))

    sections = [("SELECT CONTAINER", items)]
    actions = [("0", "Back")]

    render_menu("WORKTREES", sections, actions)

    choice = get_input()

    if choice == "0":
        return "main"

    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(items):
            return ("worktree_menu", items[idx][2])

    return "worktree_select"


def worktree_menu(container_data: dict) -> Optional[str]:
    """Show worktree management menu for a container."""
    project = container_data["project"]
    project_path = container_data.get("project_path") or ""
    container_name = container_data["container_name"]

    # Set project dir for worktree commands
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    worktrees = get_worktrees(container_name)

    # Build items
    wt_items = []
    for wt in sorted(worktrees, key=lambda x: x.get("branch", "").lower()):
        branch = wt.get("branch", "")
        path = wt.get("path", "")
        is_main = path == "/workspace"
        if is_main:
            continue  # Skip main workspace
        path_short = path.split("/")[-1] if path else ""
        wt_items.append((branch, path_short, wt))

    sections = [("WORKTREES", wt_items)]
    actions = [
        ("1", "Add worktree..."),
        ("0", "Back"),
    ]

    render_menu(f"WORKTREES: {project}", sections, actions)

    choice = get_input()

    if choice == "0":
        return "worktree_select"
    elif choice == "1":
        return ("worktree_add", container_data)

    # Handle worktree selection
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(wt_items):
            wt_data = wt_items[idx][2]
            wt_data["_container_data"] = container_data  # Pass container info
            return ("worktree_actions", wt_data)

    return ("worktree_menu", container_data)


def worktree_add_flow(container_data: dict) -> Optional[str]:
    """Flow to add a new worktree."""
    project_path = container_data.get("project_path") or ""

    # Set project dir for worktree command
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    clear_screen()
    console.print(f"[bold]ADD WORKTREE: {container_data['project']}[/bold]\n")

    branch_name = get_text_input("Branch name (or empty to cancel)")

    if not branch_name:
        return ("worktree_menu", container_data)

    console.print(f"\n[cyan]Creating worktree for branch '{branch_name}'...[/cyan]\n")
    ctx = click.get_current_context()
    try:
        ctx.invoke(worktree_add, branch=branch_name)
    except SystemExit:
        pass

    get_input("Press any key")
    return ("worktree_menu", container_data)


def worktree_actions_menu(wt_data: dict) -> Optional[str]:
    """Show actions for a selected worktree."""
    branch = wt_data.get("branch", "")
    container_data = wt_data.get("_container_data", {})
    project_path = container_data.get("project_path") or ""

    # Set project dir for worktree commands
    if project_path:
        os.environ["BOXCTL_PROJECT_DIR"] = project_path

    action_items = [
        ("Claude", "Run Claude Code", "claude"),
        ("SuperClaude", "Run Claude auto-approve", "superclaude"),
        ("Shell", "Open shell in worktree", "shell"),
    ]

    sections = [("ACTIONS", action_items)]
    actions = [("0", "Back")]

    render_menu(f"WORKTREE: {branch}", sections, actions)

    choice = get_input()

    if choice == "0":
        return ("worktree_menu", container_data)

    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(action_items):
            action = action_items[idx][2]
            ctx = click.get_current_context()

            if action == "claude":
                _run_worktree_agent(branch, "claude", ())
                return None  # Exit after launching
            elif action == "superclaude":
                _run_worktree_agent(branch, "superclaude", ())
                return None  # Exit after launching
            elif action == "shell":
                _run_worktree_shell(branch)
                return None  # Exit after shell

    return ("worktree_actions", wt_data)


def main_menu() -> Optional[str]:
    """Show the main quick menu and return the next action."""
    sessions = get_all_sessions()
    containers = get_running_containers()

    # Build sections
    session_items = []
    for s in sessions:
        attached = "attached" if s["attached"] else ""
        path_short = shorten_path(s.get("project_path", ""))
        label = f"{s['project']}/{s['session_name']}"
        desc = f"{attached} {path_short}".strip() if path_short or attached else ""
        session_items.append((label, desc, ("attach", s)))

    # Containers without sessions (ready for new session)
    container_items = []
    for c in containers:
        if c["session_count"] == 0:
            path_short = shorten_path(c.get("project_path", ""))
            label = f"{c['project']}"
            container_items.append((label, path_short, ("new_session", c)))

    sections = [
        ("SESSIONS", session_items),
        ("CONTAINERS", container_items),
    ]

    # Flatten items for index lookup
    all_items = session_items + container_items

    actions = [
        ("1", "New container..."),
        ("2", "Manage..."),
        ("3", "Worktrees..."),
        ("4", "Status"),
        ("0", "Exit"),
    ]

    render_menu("BOXCTL QUICK", sections, actions)

    choice = get_input()

    # Handle number actions
    if choice == "0":
        return None
    elif choice == "1":
        return "new_container"
    elif choice == "2":
        return "manage_select"
    elif choice == "3":
        return "worktree_select"
    elif choice == "4":
        return "status"

    # Handle letter selections
    if choice.isalpha() and len(choice) == 1:
        idx = ord(choice) - ord("a")
        if 0 <= idx < len(all_items):
            action, data = all_items[idx][2]

            if action == "attach":
                # Attach to session
                manager = ContainerManager()
                console.print(
                    f"\n[cyan]Attaching to {data['project']}/{data['session_name']}...[/cyan]"
                )
                _attach_tmux_session(manager, data["container_name"], data["session_name"])
                return None  # Exit after attach

            elif action == "new_session":
                return ("new_session", data)

    # Invalid input
    return "main"


def quick_loop():
    """Main quick menu loop."""
    next_screen = "main"
    screen_data = None
    extra_data = None  # For pagination etc

    while next_screen:
        if next_screen == "main":
            result = main_menu()
        elif next_screen == "new_session" and screen_data:
            result = new_session_menu(screen_data)
        elif next_screen == "manage_select":
            result = manage_select_menu()
        elif next_screen == "manage_actions" and screen_data:
            result = manage_actions_menu(screen_data)
        elif next_screen == "mcp_menu" and screen_data:
            page = extra_data if extra_data is not None else 0
            result = mcp_menu(screen_data, page)
        elif next_screen == "skill_menu" and screen_data:
            page = extra_data if extra_data is not None else 0
            result = skill_menu(screen_data, page)
        elif next_screen == "network_menu" and screen_data:
            result = network_menu(screen_data)
        elif next_screen == "workspace_menu" and screen_data:
            result = workspace_menu(screen_data)
        elif next_screen == "ports_menu" and screen_data:
            result = ports_menu(screen_data)
        elif next_screen == "ports_expose" and screen_data:
            result = ports_expose_flow(screen_data)
        elif next_screen == "ports_forward" and screen_data:
            result = ports_forward_flow(screen_data)
        elif next_screen == "new_container":
            result = new_container_flow()
        elif next_screen == "worktree_select":
            result = worktree_select_menu()
        elif next_screen == "worktree_menu" and screen_data:
            result = worktree_menu(screen_data)
        elif next_screen == "worktree_add" and screen_data:
            result = worktree_add_flow(screen_data)
        elif next_screen == "worktree_actions" and screen_data:
            result = worktree_actions_menu(screen_data)
        elif next_screen == "status":
            result = status_menu()
        else:
            break

        # Handle result
        if isinstance(result, tuple):
            if len(result) == 3:
                next_screen, screen_data, extra_data = result
            else:
                next_screen, screen_data = result
                extra_data = None
        else:
            next_screen = result
            screen_data = None
            extra_data = None

    clear_screen()
    console.print("[dim]Goodbye![/dim]")


@cli.command("quick")
def quick():
    """Quick access menu - mobile-friendly TUI for boxctl.

    Navigate with numbers for actions, letters for items.
    """
    quick_loop()


@cli.command("q")
def quick_alias():
    """Quick access menu (alias for: quick)."""
    quick_loop()
