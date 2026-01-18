# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Command-line interface for Agentbox."""

import json
import subprocess
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from agentbox.proxy import run_proxy
from rich.table import Table

from agentbox.container import ContainerManager
from agentbox.config import ProjectConfig
from agentbox.network import NetworkManager
from agentbox.library import LibraryManager

console = Console()

BANNER = (
    " ______   ______  ________ __    __ ________ __                         \n"
    " /      \\ /      \\|        \\  \\  |  \\        \\  \\                        \n"
    "|  ▓▓▓▓▓▓\\  ▓▓▓▓▓▓\\ ▓▓▓▓▓▓▓▓ ▓▓\\ | ▓▓\\▓▓▓▓▓▓▓▓ ▓▓____   ______  __    __ \n"
    "| ▓▓__| ▓▓ ▓▓ __\\▓▓ ▓▓__   | ▓▓▓\\| ▓▓  | ▓▓  | ▓▓    \\ /      \\|  \\  /  \\\n"
    "| ▓▓    ▓▓ ▓▓|    \\ ▓▓  \\  | ▓▓▓▓\\ ▓▓  | ▓▓  | ▓▓▓▓▓▓▓\\  ▓▓▓▓▓▓\\\\▓▓\\/  ▓▓\n"
    "| ▓▓▓▓▓▓▓▓ ▓▓ \\▓▓▓▓ ▓▓▓▓▓  | ▓▓\\▓▓ ▓▓  | ▓▓  | ▓▓  | ▓▓ ▓▓  | ▓▓ >▓▓  ▓▓ \n"
    "| ▓▓  | ▓▓ ▓▓__| ▓▓ ▓▓_____| ▓▓ \\▓▓▓▓  | ▓▓  | ▓▓__/ ▓▓ ▓▓__/ ▓▓/  ▓▓▓▓\\ \n"
    "| ▓▓  | ▓▓\\▓▓    ▓▓ ▓▓     \\ ▓▓  \\▓▓▓  | ▓▓  | ▓▓    ▓▓\\▓▓    ▓▓  ▓▓ \\▓▓\\\n"
    " \\▓▓   \\▓▓ \\▓▓▓▓▓▓ \\▓▓▓▓▓▓▓▓\\▓▓   \\▓▓   \\▓▓   \\▓▓▓▓▓▓▓  \\▓▓▓▓▓▓ \\▓▓   \\▓▓\n"
)
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[assignment]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None


VOLUMES_CONFIG_NAME = "volumes.json"
VOLUMES_MOUNT_ROOT = "/context"
CODEX_CONTEXT_TRUST = "trusted"
CLAUDE_DOC_NAME = "CLAUDE.md"
AGENT_DOC_NAME = "AGENTS.md"
LEGACY_AGENT_DOC_NAME = "AGENT.md"
LOG_DOC_NAME = "LOG.md"


def _sanitize_mount_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in name).strip("-")


def _sanitize_tmux_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in name)
    return cleaned.strip("-") or "agentbox"


def _resolve_tmux_prefix() -> Optional[str]:
    raw_prefix = os.getenv("AGENTBOX_TMUX_PREFIX", "").strip()
    if raw_prefix:
        lowered = raw_prefix.lower()
        if lowered in {"default", "none", "off"}:
            return None
        return raw_prefix
    if os.getenv("TMUX"):
        return "C-a"
    return None


def _resolve_container_and_args(
    manager: ContainerManager,
    project: Optional[str],
    args: tuple,
) -> tuple[str, tuple]:
    if project and not manager.container_exists(
        manager.get_container_name(manager.sanitize_project_name(project))
    ):
        args = (project,) + args
        project = None

    if project is None:
        project_name = manager.get_project_name()
    else:
        project_name = manager.sanitize_project_name(project)

    container_name = manager.get_container_name(project_name)
    return container_name, args


def _ensure_container_running(manager: ContainerManager, container_name: str) -> bool:
    """Ensure the container exists and is running, auto-starting if needed.

    Args:
        manager: ContainerManager instance
        container_name: Full container name

    Returns:
        True if container is running (or was started), False otherwise
    """
    if manager.is_running(container_name):
        return True

    # Container exists but not running - start it
    if manager.container_exists(container_name):
        console.print(f"[blue]Container {container_name} is not running. Starting...[/blue]")
        manager.start_container(container_name)
        return True

    # Container doesn't exist - create it
    console.print(f"[blue]Container {container_name} doesn't exist. Creating and starting...[/blue]")
    env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
    project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
    project_name = manager.get_project_name(project_dir)

    try:
        manager.create_container(
            project_name=project_name,
            project_dir=project_dir,
        )
        console.print(f"[green]Container {container_name} created and started[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Failed to create container: {e}[/red]")
        return False


def _run_agent_command(
    manager: ContainerManager,
    project: Optional[str],
    args: tuple,
    command: str,
    extra_args: Optional[list[str]] = None,
    label: Optional[str] = None,
    reuse_tmux_session: bool = False,
    session_key: Optional[str] = None,
) -> None:
    container_name, args = _resolve_container_and_args(manager, project, args)

    if not _ensure_container_running(manager, container_name):
        console.print(f"[red]Failed to start container {container_name}[/red]")
        sys.exit(1)

    cmd = [command]
    if extra_args:
        cmd.extend(extra_args)
    if args:
        cmd.extend(args)

    display = label or command
    escaped_cmd = " ".join(shlex.quote(part) for part in cmd)
    title = f"AGENTBOX {container_name} | {display}"
    title_cmd = f"printf '\\033]0;{title}\\007'"
    inner_cmd = f"{title_cmd}; exec {escaped_cmd}"
    session_suffix = "" if reuse_tmux_session else f"-{int(time.time())}"
    session_token = session_key or command
    session_raw = f"{session_token}{session_suffix}"
    session_name = _sanitize_tmux_name(session_raw)
    tmux_prefix = _resolve_tmux_prefix()

    tmux_prefix_option = ""
    if tmux_prefix:
        tmux_prefix_option = (
            f"tmux set-option -t {shlex.quote(session_name)} "
            f"prefix {shlex.quote(tmux_prefix)}; "
        )

    tmux_options = (
        f"{tmux_prefix_option}tmux set-option -t {shlex.quote(session_name)} status on; "
        f"tmux set-option -t {shlex.quote(session_name)} status-position top; "
        f"tmux set-option -t {shlex.quote(session_name)} status-style 'bg=colour226,fg=colour232'; "
        f"tmux set-option -t {shlex.quote(session_name)} mouse off; "
        f"tmux set-option -t {shlex.quote(session_name)} history-limit 50000; "
        f"tmux set-option -t {shlex.quote(session_name)} status-left "
        f"{shlex.quote(' AGENTBOX ' + container_name + ' | ' + display + ' ')}; "
        f"tmux set-option -t {shlex.quote(session_name)} status-right ''; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-status top; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-style 'fg=colour226'; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-format "
        f"{shlex.quote(' AGENTBOX ' + container_name + ' | ' + display + ' ')}; "
    )

    if reuse_tmux_session:
        tmux_setup = (
            f"if tmux has-session -t {shlex.quote(session_name)} 2>/dev/null; then "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(session_name)}; "
            f"else "
            f"tmux new-session -d -s {shlex.quote(session_name)} "
            f"/bin/bash -lc {shlex.quote(inner_cmd)}; "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(session_name)}; "
            f"fi"
        )
    else:
        tmux_setup = (
            f"tmux new-session -d -s {shlex.quote(session_name)} "
            f"/bin/bash -lc {shlex.quote(inner_cmd)}; "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(session_name)}"
        )

    agent_cmd = [
        "docker",
        "exec",
        "-it",
        "-u",
        "abox",
        "-e",
        "HOME=/home/abox",
        "-e",
        "USER=abox",
        container_name,
        "/bin/bash",
        "-lc",
        tmux_setup,
    ]
    banner_title = f"AGENTBOX CONTAINER: {container_name}"
    banner_action = f"RUNNING: {display}"
    width = max(len(banner_title), len(banner_action))
    line = "-" * width
    console.print("")
    console.print(f"+{line}+")
    console.print(f"|{banner_title.ljust(width)}|")
    console.print(f"|{banner_action.ljust(width)}|")
    console.print(f"+{line}+")
    os.execvp("docker", agent_cmd)


def _get_tmux_sessions(manager: ContainerManager, container_name: str) -> list[dict]:
    fmt = "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created_string}"
    socket_path = _get_tmux_socket(manager, container_name)
    tmux_cmd = ["/usr/bin/tmux", "list-sessions", "-F", fmt]
    if socket_path:
        tmux_cmd = ["/usr/bin/tmux", "-S", socket_path, "list-sessions", "-F", fmt]
    exit_code, output = manager.exec_command(
        container_name,
        tmux_cmd,
        environment={"HOME": "/home/abox", "USER": "abox", "TMUX_TMPDIR": "/tmp"},
        user="abox",
    )
    if exit_code != 0:
        lowered = output.lower()
        if (
            "no server running" in lowered
            or "failed to connect" in lowered
            or "error connecting" in lowered
        ):
            return []
        console.print(f"[red]Failed to list tmux sessions in {container_name}[/red]")
        if output.strip():
            console.print(output.strip())
        return []

    sessions = []
    for line in output.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 3:
            parts.append("")
        if len(parts) != 4:
            continue
        name, windows, attached, created = parts
        sessions.append(
            {
                "name": name,
                "windows": windows,
                "attached": attached == "1",
                "created": created,
            }
        )
    return sessions


def _complete_session_name(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    try:
        manager = ContainerManager()
        project_name = manager.get_project_name()
        container_name = manager.get_container_name(project_name)
        if not manager.is_running(container_name):
            return []
        sessions = _get_tmux_sessions(manager, container_name)
        names = [session["name"] for session in sessions]
        return [name for name in names if name.startswith(incomplete)]
    except Exception:
        return []


def _get_tmux_socket(manager: ContainerManager, container_name: str) -> Optional[str]:
    exit_code, output = manager.exec_command(
        container_name,
        ["/usr/bin/id", "-u"],
        environment={"HOME": "/home/abox", "USER": "abox"},
        user="abox",
    )
    if exit_code != 0:
        return None
    uid = output.strip()
    if not uid:
        return None
    return f"/tmp/tmux-{uid}/default"


def _attach_tmux_session(manager: ContainerManager, container_name: str, session_name: str) -> None:
    socket_path = _get_tmux_socket(manager, container_name)
    tmux_cmd = ["tmux", "attach", "-t", session_name]
    if socket_path:
        tmux_cmd = ["tmux", "-S", socket_path, "attach", "-t", session_name]
    cmd = [
        "docker",
        "exec",
        "-it",
        "-u",
        "abox",
        "-e",
        "HOME=/home/abox",
        "-e",
        "USER=abox",
        container_name,
        "/usr/bin/tmux",
        *tmux_cmd[1:],
    ]
    os.execvp("docker", cmd)


def _load_volumes_config(agentbox_dir: Path) -> list[dict]:
    config_path = agentbox_dir / VOLUMES_CONFIG_NAME
    if not config_path.exists():
        return []
    try:
        data = json.loads(config_path.read_text())
        volumes = data.get("volumes", [])
        return volumes if isinstance(volumes, list) else []
    except Exception:
        return []


def _save_volumes_config(agentbox_dir: Path, volumes: list[dict]) -> None:
    config_path = agentbox_dir / VOLUMES_CONFIG_NAME
    config_path.write_text(json.dumps({"volumes": volumes}, indent=2))


def _load_project_config(project_dir: Path) -> dict:
    config_path = project_dir / ".agentbox" / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
    except Exception:
        return {}


AGENT_MANAGED_START = "<!-- AGENTBOX:BEGIN -->"
AGENT_MANAGED_END = "<!-- AGENTBOX:END -->"


def _render_managed_section(volumes: list[dict], project_config: dict) -> str:
    mcp_servers = project_config.get("mcpServers", {})
    skills = project_config.get("skills", [])

    lines = [
        AGENT_MANAGED_START,
        "## Agentbox Managed Context",
        "",
        "### Workflow",
        "- Commit often.",
        "- Keep a log in `.agentbox/LOG.md`.",
        "",
        "### MCP",
    ]
    if isinstance(mcp_servers, dict) and mcp_servers:
        lines.append("- MCP servers: " + ", ".join(sorted(mcp_servers.keys())))
    else:
        lines.append("- MCP servers: _none_")
    if isinstance(skills, list) and skills:
        lines.append("- Skills: " + ", ".join(str(s) for s in skills))
    else:
        lines.append("- Skills: _none_")

    lines += [
        "",
        "### Human Interaction",
        "- You are allowed to use `/usr/local/bin/notify`.",
        "- Use it to request human input or confirmation instead of blocking on questions.",
        "- Always send a notification if you have a question for the human.",
        "- Include a concise title and a clear next action for the human.",
        "",
        "### Allowed Commands",
        "- `/usr/local/bin/notify`",
        "",
        "### Context Files",
        "- `PLAN.md` (if present).",
        "",
        "### Context Mounts",
        "Extra context paths are mounted under `/context/<name>`.",
        "",
    ]
    if not volumes:
        lines.append("_No extra context mounts configured._")
    else:
        for entry in volumes:
            mount = entry.get("mount", "")
            mode = entry.get("mode", "ro")
            lines.append(f"- `/context/{mount}` ({mode})")
    lines += [
        "",
        AGENT_MANAGED_END,
        "",
    ]
    return "\n".join(lines)


def _render_agent_doc(volumes: list[dict], project_config: dict) -> str:
    lines = [
        "# Agent Context",
        "",
        _render_managed_section(volumes, project_config),
        "## Notes",
        "- Add project-specific notes here.",
        "",
    ]
    return "\n".join(lines)


def _ensure_agent_doc(project_dir: Path, volumes: list[dict]) -> None:
    claude_path = project_dir / CLAUDE_DOC_NAME
    agent_path = project_dir / AGENT_DOC_NAME
    legacy_agent_path = project_dir / LEGACY_AGENT_DOC_NAME
    project_config = _load_project_config(project_dir)

    if not agent_path.exists():
        if legacy_agent_path.exists():
            try:
                agent_path.write_text(legacy_agent_path.read_text())
            except Exception:
                agent_path.write_text(_render_agent_doc(volumes, project_config))
        else:
            agent_path.write_text(_render_agent_doc(volumes, project_config))

    if not legacy_agent_path.exists():
        try:
            legacy_agent_path.symlink_to(agent_path.name)
        except Exception:
            legacy_agent_path.write_text(agent_path.read_text())

    if not claude_path.exists():
        try:
            claude_path.symlink_to(agent_path.name)
        except Exception:
            claude_path.write_text(agent_path.read_text())

def _cleanup_default_docs(project_dir: Path, agentbox_dir: Path) -> None:
    paths = [
        agentbox_dir / "README.md",
        agentbox_dir / "VOLUMES.md",
        project_dir / "CONTEXT.md",
        project_dir / "NOTES.md",
    ]
    for path in paths:
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass


def _update_agent_context(project_dir: Path, volumes: list[dict]) -> None:
    agent_path = project_dir / AGENT_DOC_NAME
    project_config = _load_project_config(project_dir)
    _ensure_agent_doc(project_dir, volumes)

    content = agent_path.read_text() if agent_path.exists() else ""
    managed = _render_managed_section(volumes, project_config)

    if AGENT_MANAGED_START in content and AGENT_MANAGED_END in content:
        pre, _, rest = content.partition(AGENT_MANAGED_START)
        _, _, tail = rest.partition(AGENT_MANAGED_END)
        new_content = pre.rstrip() + "\n\n" + managed + tail.lstrip()
    else:
        if content.strip():
            new_content = content.rstrip() + "\n\n" + managed
        else:
            new_content = _render_agent_doc(volumes, project_config)

    agent_path.write_text(new_content)


def _load_codex_config(path: Path) -> dict:
    if not path.exists():
        return {}
    if tomllib is None:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}


def _update_codex_context_mount(agentbox_dir: Path, mount_name: str, present: bool) -> None:
    if tomllib is None:
        return
    codex_path = agentbox_dir / "codex.toml"
    codex_config = _load_codex_config(codex_path)
    projects = codex_config.get("projects")
    if not isinstance(projects, dict):
        projects = {}
        codex_config["projects"] = projects

    mount_path = f"{VOLUMES_MOUNT_ROOT}/{mount_name}"
    if present:
        projects[mount_path] = {"trust_level": CODEX_CONTEXT_TRUST}
    else:
        if mount_path in projects:
            del projects[mount_path]

    codex_path.write_text(_dump_codex_toml(codex_config))


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(value):
    if isinstance(value, str):
        return f'"{_toml_escape(value)}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        items = ", ".join(_toml_value(v) for v in value)
        return f"[{items}]"
    return str(value)


def _dump_codex_toml(data):
    lines = []

    projects = data.get("projects", {})
    if isinstance(projects, dict):
        for project_path in sorted(projects.keys()):
            entry = projects[project_path]
            if not isinstance(entry, dict):
                continue
            lines.append(f'[projects."{project_path}"]')
            for key in sorted(entry.keys()):
                lines.append(f"{key} = {_toml_value(entry[key])}")
            lines.append("")

    mcp_servers = data.get("mcp_servers", {})
    if isinstance(mcp_servers, dict):
        for server_name in sorted(mcp_servers.keys()):
            entry = mcp_servers[server_name]
            if not isinstance(entry, dict):
                continue
            lines.append(f'[mcp_servers."{server_name}"]')

            for key in sorted(entry.keys()):
                if key in ("env", "http_headers", "env_http_headers"):
                    continue
                lines.append(f"{key} = {_toml_value(entry[key])}")

            for nested_key in ("env", "http_headers", "env_http_headers"):
                nested = entry.get(nested_key)
                if isinstance(nested, dict) and nested:
                    lines.append(f'[mcp_servers."{server_name}".{nested_key}]')
                    for nk in sorted(nested.keys()):
                        lines.append(f"{nk} = {_toml_value(nested[nk])}")

            lines.append("")

    if not lines:
        return "# empty\n"
    return "\n".join(lines).rstrip() + "\n"


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.1")
def cli():
    """Agentbox - Secure, isolated Docker environment for Claude Code."""
    ctx = click.get_current_context()
    if ctx.invoked_subcommand is None:
        click.echo("Usage: agentbox [OPTIONS] COMMAND [ARGS]...\n")
        def _print_table(title: str, rows: list[tuple[str, str]], width: int) -> None:
            click.echo(f"{title}:")
            for name, desc in rows:
                click.echo(f"  {name.ljust(width)}  {desc}")
            click.echo("")

        groups = [
            ("Agents", [
                ("claude", "Run Claude Code"),
                ("superclaude", "Run Claude Code (auto-approve)"),
                ("codex", "Run Codex"),
                ("supercodex", "Run Codex (auto-approve)"),
                ("gemini", "Run Gemini"),
                ("supergemini", "Run Gemini (auto-approve)"),
            ]),
            ("Container Commands", [
                ("start", "Start container for current project"),
                ("stop", "Stop current or named container"),
                ("ps", "List containers"),
                ("shell", "Open shell in container"),
                ("sessions", "List tmux sessions in containers"),
                ("ip", "Show container IP"),
                ("remove", "Remove container"),
                ("cleanup", "Remove stopped containers"),
                ("rebuild", "Recreate container for current project"),
                ("init", "Initialize .agentbox/ in project"),
                ("update", "Update base image"),
            ]),
            ("Libraries", [
                ("mcp", "Manage MCP servers (list/show/add/remove)"),
                ("skill", "Manage skills (list/show/add/remove)"),
            ]),
            ("Other", [
            ("hosts", "Manage /etc/hosts (add/remove/list)"),
            ("proxy", "Host proxy daemon (install/serve)"),
            ("volume", "Manage extra mounts (list/add/remove)"),
        ]),
    ]

        width = max(len(name) for _, rows in groups for name, _ in rows)
        for title, rows in groups:
            _print_table(title, rows, width)
        click.echo("Use --help for full command details.")
        return


@cli.group()
def proxy():
    """Manage the Agentbox host proxy daemon."""


def _proxy_unit_contents(socket_path: str, display: str, runtime_dir: str, dbus_addr: str) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Agentbox Proxy",
            "After=graphical-session.target",
            "",
            "[Service]",
            "Type=simple",
            "Environment=PYTHONUNBUFFERED=1",
            f"Environment=DISPLAY={display}",
            f"Environment=XDG_RUNTIME_DIR={runtime_dir}",
            f"Environment=DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
            f"Environment=AGENTBOX_PROXY_SOCKET={socket_path}",
            "ExecStart=/usr/bin/env agentbox proxy serve --socket ${AGENTBOX_PROXY_SOCKET}",
            "Restart=on-failure",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


@proxy.command("serve")
@click.option("--socket", "socket_path", default=None, help="Unix socket path")
def proxy_serve(socket_path: Optional[str]):
    """Run the host proxy daemon in the foreground."""
    run_proxy(socket_path)


@proxy.command("install")
@click.option("--socket", "socket_path", default=None, help="Unix socket path")
@click.option("--enable/--no-enable", default=False, help="Enable and start the service")
def proxy_install(socket_path: Optional[str], enable: bool):
    """Install the user systemd service for the proxy."""
    socket_path = socket_path or f"/run/user/{os.getuid()}/agentbox-notify.sock"
    display = os.environ.get("DISPLAY", ":0")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    dbus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir}/bus")
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "agentbox-proxy.service"
    unit_path.write_text(_proxy_unit_contents(socket_path, display, runtime_dir, dbus_addr))
    console.print(f"[green]Installed user service at {unit_path}[/green]")
    if display == ":0" and "DISPLAY" not in os.environ:
        console.print("[yellow]DISPLAY not set in this shell; using :0[/yellow]")

    if enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", "agentbox-proxy.service"], check=False)
        console.print("[green]Service enabled and started[/green]")
    else:
        console.print("[yellow]Run: systemctl --user enable --now agentbox-proxy.service[/yellow]")


@proxy.command("uninstall")
def proxy_uninstall():
    """Remove the user systemd service for the proxy."""
    unit_path = Path.home() / ".config" / "systemd" / "user" / "agentbox-proxy.service"
    if unit_path.exists():
        subprocess.run(["systemctl", "--user", "disable", "--now", "agentbox-proxy.service"], check=False)
        unit_path.unlink()
        console.print(f"[green]Removed {unit_path}[/green]")
    else:
        console.print("[yellow]agentbox-proxy.service not installed[/yellow]")


@cli.command()
@click.option("--name", "-n", help="Custom container name (auto-generated from directory if not provided)")
@click.option("--rebuild", "-r", is_flag=True, help="Rebuild from .agentbox.yml if exists")
def start(name: Optional[str], rebuild: bool):
    """Start an Agentbox container for the current project."""
    try:
        manager = ContainerManager()
        # Get project directory from environment variable or current directory
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        project_name = manager.get_project_name(project_dir)

        # Create and start container
        container = manager.create_container(
            project_name=project_name,
            project_dir=project_dir,
            custom_name=name,
        )

        # Rebuild from config if requested or if .agentbox.yml exists
        config = ProjectConfig(project_dir)
        if rebuild or config.exists():
            container_name = container.name
            config.rebuild(manager, container_name)

        console.print(f"\n[green]Container started: {container.name}[/green]")
        console.print("\n[blue]Next steps:[/blue]")
        console.print(f"  agentbox shell    - Enter interactive shell")
        console.print(f"  agentbox claude   - Run Claude Code")
        console.print(f"  agentbox codex    - Run Codex")
        console.print(f"  agentbox ip       - Get container IP for accessing services")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
def stop(project: Optional[str]):
    """Stop an Agentbox container.

    If no project name is provided, stops the container for the current directory.
    """
    try:
        manager = ContainerManager()

        if project is None:
            # Stop current project
            project_name = manager.get_project_name()
        else:
            project_name = manager.sanitize_project_name(project)

        container_name = manager.get_container_name(project_name)
        manager.stop_container(container_name)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--all", "-a", is_flag=True, help="Show all containers including stopped ones")
def ps(all: bool):
    """List all Agentbox containers."""
    try:
        manager = ContainerManager()
        manager.print_containers_table(all_containers=all)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
def shell(project: Optional[str]):
    """Open an interactive shell in an Agentbox container.

    If no project name is provided, opens shell in the current project's container.
    """
    try:
        manager = ContainerManager()

        if project is None:
            # Use current project
            project_name = manager.get_project_name()
        else:
            project_name = manager.sanitize_project_name(project)

        container_name = manager.get_container_name(project_name)

        # Check if container is running
        if not manager.is_running(container_name):
            console.print(f"[red]Container {container_name} is not running[/red]")
            console.print(f"[blue]Start it with: agentbox start[/blue]")
            sys.exit(1)

        console.print(f"[green]Opening shell in {container_name}...[/green]")
        _run_agent_command(
            manager,
            project,
            tuple(),
            "/bin/bash",
            label="Shell",
            reuse_tmux_session=True,
            session_key="shell",
        )

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.group()
def session():
    """Manage tmux sessions in containers."""
    pass


@session.command(name="list")
def session_list():
    """List tmux sessions with attach commands."""
    try:
        manager = ContainerManager()
        container_name = manager.get_container_name(manager.get_project_name())

        if not manager.is_running(container_name):
            console.print(f"[red]Container {container_name} is not running[/red]")
            console.print(f"[blue]Start it with: agentbox start[/blue]")
            return

        table = Table(title="Agentbox Tmux Sessions")
        table.add_column("Session", style="magenta")
        table.add_column("Attached", style="green")
        table.add_column("Windows", style="blue")

        sessions = _get_tmux_sessions(manager, container_name)
        if not sessions:
            console.print("[yellow]No tmux sessions found[/yellow]")
            return

        for session in sessions:
            table.add_row(
                session["name"],
                "yes" if session["attached"] else "no",
                str(session["windows"]),
            )

        console.print(table)
        console.print("[blue]Reconnect:[/blue] agentbox <session> (or abox <session>)")
        console.print("[blue]Custom tmux:[/blue] agentbox shell, then: tmux attach -t <session>")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@session.command(name="remove")
@click.argument("session_name", shell_complete=_complete_session_name)
def session_remove(session_name: str):
    """Kill a tmux session inside a container."""
    try:
        manager = ContainerManager()
        target_container = manager.get_container_name(manager.get_project_name())

        if not manager.is_running(target_container):
            console.print(f"[red]Container {target_container} is not running[/red]")
            console.print(f"[blue]Start it with: agentbox start[/blue]")
            sys.exit(1)

        socket_path = _get_tmux_socket(manager, target_container)
        tmux_cmd = ["/usr/bin/tmux", "kill-session", "-t", session_name]
        if socket_path:
            tmux_cmd = ["/usr/bin/tmux", "-S", socket_path, "kill-session", "-t", session_name]
        exit_code, output = manager.exec_command(
            target_container,
            tmux_cmd,
            environment={"HOME": "/home/abox", "USER": "abox", "TMUX_TMPDIR": "/tmp"},
            user="abox",
        )
        if exit_code != 0:
            console.print(f"[red]Failed to remove tmux session {session_name}[/red]")
            if output.strip():
                console.print(output.strip())
            sys.exit(1)

        console.print(f"[green]Removed tmux session {session_name} from {target_container}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@session.command(name="attach")
@click.argument("session_name", shell_complete=_complete_session_name)
def session_attach(session_name: str):
    """Attach to a tmux session inside the project container."""
    try:
        manager = ContainerManager()
        container_name = manager.get_container_name(manager.get_project_name())

        if not manager.is_running(container_name):
            console.print(f"[red]Container {container_name} is not running[/red]")
            console.print(f"[blue]Start it with: agentbox start[/blue]")
            sys.exit(1)

        _attach_tmux_session(manager, container_name, session_name)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.argument("project", required=False)
@click.argument("args", nargs=-1)
def claude(project: Optional[str], args: tuple):
    """Run Claude Code in an Agentbox container.

    If no project name is provided, runs in the current project's container.

    Examples:
        agentbox claude
        agentbox claude "implement user authentication"
        agentbox claude my-project "fix the bug in login"
    """
    try:
        manager = ContainerManager()
        _run_agent_command(
            manager,
            project,
            args,
            "claude",
            label="Claude Code",
            reuse_tmux_session=True,
            session_key="claude",
        )

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.argument("project", required=False)
@click.argument("args", nargs=-1)
def superclaude(project: Optional[str], args: tuple):
    """Run Claude Code with auto-approve permissions enabled.

    If no project name is provided, runs in the current project's container.
    """
    try:
        manager = ContainerManager()
        _run_agent_command(
            manager,
            project,
            args,
            "claude",
            extra_args=["--dangerously-skip-permissions"],
            label="Claude Code (auto-approve)",
            reuse_tmux_session=True,
            session_key="superclaude",
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
@click.argument("args", nargs=-1)
def codex(project: Optional[str], args: tuple):
    """Run Codex in an Agentbox container.

    If no project name is provided, runs in the current project's container.
    """
    try:
        manager = ContainerManager()
        _run_agent_command(
            manager,
            project,
            args,
            "codex",
            label="Codex",
            reuse_tmux_session=True,
            session_key="codex",
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
@click.argument("args", nargs=-1)
def supercodex(project: Optional[str], args: tuple):
    """Run Codex with auto-approve permissions enabled.

    If no project name is provided, runs in the current project's container.
    """
    try:
        manager = ContainerManager()
        _run_agent_command(
            manager,
            project,
            args,
            "codex",
            extra_args=["-a", "never"],
            label="Codex (auto-approve)",
            reuse_tmux_session=True,
            session_key="supercodex",
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.argument("project", required=False)
@click.argument("args", nargs=-1)
def gemini(project: Optional[str], args: tuple):
    """Run Gemini in an Agentbox container.

    If no project name is provided, runs in the current project's container.
    """
    try:
        manager = ContainerManager()
        _run_agent_command(
            manager,
            project,
            args,
            "gemini",
            label="Gemini",
            reuse_tmux_session=True,
            session_key="gemini",
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
@click.argument("args", nargs=-1)
def supergemini(project: Optional[str], args: tuple):
    """Run Gemini with auto-approve permissions enabled."""
    try:
        manager = ContainerManager()
        _run_agent_command(
            manager,
            project,
            args,
            "gemini",
            extra_args=["--non-interactive"],
            label="Gemini (auto-approve)",
            reuse_tmux_session=True,
            session_key="supergemini",
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
def ip(project: Optional[str]):
    """Show container IP address for accessing services.

    If no project name is provided, shows IP for the current project's container.
    """
    try:
        manager = ContainerManager()

        if project is None:
            # Use current project
            project_name = manager.get_project_name()
        else:
            project_name = manager.sanitize_project_name(project)

        container_name = manager.get_container_name(project_name)

        # Check if container exists
        if not manager.container_exists(container_name):
            console.print(f"[red]Container {container_name} not found[/red]")
            sys.exit(1)

        net_manager = NetworkManager(container_name)
        net_manager.show_access_info()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.group()
def hosts():
    """Manage /etc/hosts entries for containers."""
    pass


@hosts.command(name="add")
@click.argument("project", required=False)
@click.option("--hostname", "-h", help="Custom hostname (auto-generated if not provided)")
def hosts_add(project: Optional[str], hostname: Optional[str]):
    """Add /etc/hosts entry for container.

    If no project name is provided, adds entry for the current project's container.
    """
    try:
        manager = ContainerManager()

        if project is None:
            # Use current project
            project_name = manager.get_project_name()
        else:
            project_name = manager.sanitize_project_name(project)

        container_name = manager.get_container_name(project_name)

        # Check if container exists
        if not manager.container_exists(container_name):
            console.print(f"[red]Container {container_name} not found[/red]")
            sys.exit(1)

        net_manager = NetworkManager(container_name)
        success = net_manager.add_hosts_entry(hostname)

        if not success:
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@hosts.command(name="remove")
@click.argument("hostname")
def hosts_remove(hostname: str):
    """Remove /etc/hosts entry."""
    try:
        # We don't need a container for this, just remove from /etc/hosts
        from agentbox.network import NetworkManager
        # Create a dummy manager just to use the remove method
        # This is a bit hacky, but works for now
        import subprocess
        result = subprocess.run(
            ["sudo", "sed", "-i", f"/{hostname}/d", "/etc/hosts"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            console.print(f"[green]Removed {hostname} from /etc/hosts[/green]")
        else:
            console.print(f"[red]Error removing entry: {result.stderr}[/red]")
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@hosts.command(name="list")
def hosts_list():
    """List all /etc/hosts entries with .local domains."""
    try:
        with open("/etc/hosts", "r") as f:
            lines = f.readlines()

        entries = [
            line.strip() for line in lines if ".local" in line and not line.strip().startswith("#")
        ]

        if not entries:
            console.print("[yellow]No .local entries found in /etc/hosts[/yellow]")
            return

        console.print("[blue]/etc/hosts entries:[/blue]")
        for entry in entries:
            console.print(f"  {entry}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.group()
def mcp():
    """Manage MCP servers (list, add, remove)."""
    pass


@mcp.command(name="list")
def mcp_list():
    """List available MCP servers from library."""
    try:
        lib_manager = LibraryManager()
        lib_manager.print_mcp_table()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@mcp.command(name="show")
@click.argument("name")
def mcp_show(name: str):
    """Show details of an MCP server."""
    try:
        if name == "notify":
            console.print("[yellow]MCP server 'notify' is managed by Agentbox and hidden from the library[/yellow]")
            return
        lib_manager = LibraryManager()
        lib_manager.show_mcp(name)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@mcp.command(name="add")
@click.argument("name")
def mcp_add(name: str):
    """Add an MCP server from library to current project."""
    try:
        if name == "notify":
            console.print("[yellow]MCP server 'notify' is managed by Agentbox and cannot be added or removed[/yellow]")
            return
        # Get project directory
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()

        # Check if .agentbox exists
        agentbox_dir = project_dir / ".agentbox"
        if not agentbox_dir.exists():
            console.print(f"[red].agentbox/ not found in {project_dir}[/red]")
            console.print(f"[blue]Run: agentbox init[/blue]")
            sys.exit(1)

        config_path = agentbox_dir / "config.json"
        codex_config_path = agentbox_dir / "codex.toml"

        # Load template from library
        lib_manager = LibraryManager()
        template_path = lib_manager.mcp_dir / name / "config.json"

        if not template_path.exists():
            console.print(f"[red]MCP server '{name}' not found in library[/red]")
            console.print(f"[blue]Run: agentbox mcp list[/blue]")
            sys.exit(1)

        # Read template
        with open(template_path, 'r') as f:
            template = json.load(f)

        # Read current project config
        with open(config_path, 'r') as f:
            project_config = json.load(f)

        # Ensure mcpServers exists
        if "mcpServers" not in project_config:
            project_config["mcpServers"] = {}

        # Check if already exists
        if name in project_config["mcpServers"]:
            console.print(f"[yellow]MCP server '{name}' already exists in project config[/yellow]")
            console.print(f"[blue]Edit {config_path} to modify it[/blue]")
            return

        # Add to config
        project_config["mcpServers"][name] = template["config"]

        # Update Codex config (if available)
        if tomllib is None:
            console.print("[yellow]tomllib not available, skipping Codex config update[/yellow]")
        else:
            codex_config = {}
            if codex_config_path.exists():
                try:
                    codex_config = tomllib.loads(codex_config_path.read_text())
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to read codex.toml: {e}[/yellow]")
                    codex_config = {}

            if "mcp_servers" not in codex_config or not isinstance(codex_config.get("mcp_servers"), dict):
                codex_config["mcp_servers"] = {}

            codex_config["mcp_servers"][name] = template["config"]
            codex_config_path.write_text(_dump_codex_toml(codex_config))

        # Write updated config
        with open(config_path, 'w') as f:
            json.dump(project_config, f, indent=2)

        console.print(f"[green]✓ Added '{name}' MCP server to project config[/green]")
        _update_agent_context(project_dir, _load_volumes_config(agentbox_dir))

        # Show environment variables if needed
        if "env_template" in template:
            console.print(f"\n[yellow]⚠ Configure environment variables:[/yellow]")
            for key, value in template["env_template"].items():
                console.print(f"  {key}={value}")
            console.print(f"\n[blue]Edit {config_path} or set in your shell environment[/blue]")

        # Show notes if present
        if "notes" in template:
            console.print(f"\n[blue]Notes:[/blue]")
            for line in template["notes"].split("\n"):
                console.print(f"  {line}")

        # Trigger config merge in running container
        manager = ContainerManager()
        project_name = manager.get_project_name(project_dir)
        container_name = manager.get_container_name(project_name)

        if name == "docker":
            if not Path("/var/run/docker.sock").exists():
                console.print("[yellow]Warning: /var/run/docker.sock not found on host[/yellow]")
            console.print(f"\n[blue]Rebuilding container to apply Docker socket mount...[/blue]")
            if manager.container_exists(container_name):
                manager.remove_container(container_name, force=True)
            manager.create_container(project_name=project_name, project_dir=project_dir)
            console.print(f"[green]✓ Container rebuilt[/green]")
            return

        if manager.is_running(container_name):
            console.print(f"\n[blue]Syncing config to running container...[/blue]")
            import subprocess
            claude_result = subprocess.run(
                ["docker", "exec", container_name, "python3", "/usr/local/bin/merge-config.py"],
                capture_output=True,
                text=True
            )
            codex_result = subprocess.run(
                ["docker", "exec", container_name, "python3", "/usr/local/bin/merge-codex-config.py"],
                capture_output=True,
                text=True
            )
            if claude_result.returncode == 0 and codex_result.returncode == 0:
                console.print(f"[green]✓ Configs synced to container[/green]")
            else:
                console.print(f"[yellow]Container not running or sync failed[/yellow]")
        else:
            console.print(f"\n[yellow]Container not running. Config will sync on next start.[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@mcp.command(name="remove")
@click.argument("name")
def mcp_remove(name: str):
    """Remove an MCP server from current project."""
    try:
        if name == "notify":
            console.print("[yellow]MCP server 'notify' is managed by Agentbox and cannot be added or removed[/yellow]")
            return
        # Get project directory
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()

        config_path = project_dir / ".agentbox" / "config.json"
        codex_config_path = project_dir / ".agentbox" / "codex.toml"

        if not config_path.exists():
            console.print(f"[red]No project config found[/red]")
            sys.exit(1)

        # Read current config
        with open(config_path, 'r') as f:
            project_config = json.load(f)

        # Check if exists
        if "mcpServers" not in project_config or name not in project_config["mcpServers"]:
            console.print(f"[yellow]MCP server '{name}' not found in project config[/yellow]")
            return

        # Remove
        del project_config["mcpServers"][name]

        # Update Codex config (if available)
        if tomllib is None:
            console.print("[yellow]tomllib not available, skipping Codex config update[/yellow]")
        else:
            if codex_config_path.exists():
                try:
                    codex_config = tomllib.loads(codex_config_path.read_text())
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to read codex.toml: {e}[/yellow]")
                    codex_config = {}

                mcp_servers = codex_config.get("mcp_servers")
                if isinstance(mcp_servers, dict) and name in mcp_servers:
                    del mcp_servers[name]
                    codex_config_path.write_text(_dump_codex_toml(codex_config))

        # Write updated config
        with open(config_path, 'w') as f:
            json.dump(project_config, f, indent=2)

        console.print(f"[green]✓ Removed '{name}' MCP server from project config[/green]")
        agentbox_dir = project_dir / ".agentbox"
        _update_agent_context(project_dir, _load_volumes_config(agentbox_dir))

        # Trigger config merge in running container
        manager = ContainerManager()
        project_name = manager.get_project_name(project_dir)
        container_name = manager.get_container_name(project_name)

        if name == "docker":
            console.print(f"\n[blue]Rebuilding container to remove Docker socket mount...[/blue]")
            if manager.container_exists(container_name):
                manager.remove_container(container_name, force=True)
                manager.create_container(project_name=project_name, project_dir=project_dir)
                console.print(f"[green]✓ Container rebuilt[/green]")
            return

        if manager.is_running(container_name):
            console.print(f"\n[blue]Syncing config to running container...[/blue]")
            import subprocess
            claude_result = subprocess.run(
                ["docker", "exec", container_name, "python3", "/usr/local/bin/merge-config.py"],
                capture_output=True,
                text=True
            )
            codex_result = subprocess.run(
                ["docker", "exec", container_name, "python3", "/usr/local/bin/merge-codex-config.py"],
                capture_output=True,
                text=True
            )
            if claude_result.returncode == 0 and codex_result.returncode == 0:
                console.print(f"[green]✓ Configs synced to container[/green]")
            else:
                console.print(f"[yellow]Container not running or sync failed[/yellow]")
        else:
            console.print(f"\n[yellow]Container not running. Config will sync on next start.[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.group()
def volume():
    """Manage extra volume mounts (list, add, remove)."""
    pass


@volume.command(name="list")
def volume_list():
    """List configured extra mounts for the current project."""
    try:
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        agentbox_dir = project_dir / ".agentbox"
        volumes = _load_volumes_config(agentbox_dir)

        if not volumes:
            console.print("[yellow]No extra mounts configured[/yellow]")
            return

        table = Table(title="Extra Mounts")
        table.add_column("Name", style="cyan")
        table.add_column("Host Path", style="white")
        table.add_column("Mode", style="magenta")
        table.add_column("Container Path", style="blue")

        for entry in volumes:
            mount = entry.get("mount", "")
            host_path = entry.get("path", "")
            mode = entry.get("mode", "ro")
            container_path = f"{VOLUMES_MOUNT_ROOT}/{mount}"
            table.add_row(mount, host_path, mode, container_path)

        console.print(table)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@volume.command(name="add")
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=True, file_okay=True, resolve_path=False),
)
@click.argument("mode", required=False, type=click.Choice(["ro", "rw"]))
@click.argument("name", required=False)
def volume_add(path: str, mode: Optional[str], name: Optional[str]):
    """Add an extra mount for the current project."""
    try:
        mode_final = mode or "ro"
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        agentbox_dir = project_dir / ".agentbox"
        if not agentbox_dir.exists():
            console.print(f"[red].agentbox/ not found in {project_dir}[/red]")
            console.print(f"[blue]Run: agentbox init[/blue]")
            sys.exit(1)

        host_path = Path(path).expanduser().resolve()
        if not host_path.exists():
            console.print(f"[red]Path not found: {host_path}[/red]")
            sys.exit(1)

        mount_name = name or host_path.name or "root"
        mount_name = _sanitize_mount_name(mount_name)
        if not mount_name:
            console.print(f"[red]Invalid mount name[/red]")
            sys.exit(1)

        volumes = _load_volumes_config(agentbox_dir)
        for entry in volumes:
            if entry.get("mount") == mount_name:
                console.print(f"[yellow]Mount name already exists: {mount_name}[/yellow]")
                return
            if entry.get("path") == str(host_path):
                console.print(f"[yellow]Path already mounted: {host_path}[/yellow]")
                return

        volumes.append({"path": str(host_path), "mode": mode_final, "mount": mount_name})
        _save_volumes_config(agentbox_dir, volumes)

        _update_agent_context(project_dir, volumes)
        _cleanup_default_docs(project_dir, agentbox_dir)
        _update_codex_context_mount(agentbox_dir, mount_name, True)

        container_path = f"{VOLUMES_MOUNT_ROOT}/{mount_name}"
        console.print(f"[green]✓ Added mount[/green]")
        console.print(f"  Host: {host_path}")
        console.print(f"  Container: {container_path} ({mode})")

        # Rebuild container to apply mounts
        manager = ContainerManager()
        project_name = manager.get_project_name(project_dir)
        container_name = manager.get_container_name(project_name)
        console.print(f"[blue]Rebuilding container to apply mounts...[/blue]")
        if manager.container_exists(container_name):
            manager.remove_container(container_name, force=True)
        manager.create_container(project_name=project_name, project_dir=project_dir)
        console.print(f"[green]✓ Container rebuilt[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@volume.command(name="remove")
@click.argument("path_or_name")
def volume_remove(path_or_name: str):
    """Remove an extra mount by name or path."""
    try:
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        agentbox_dir = project_dir / ".agentbox"
        if not agentbox_dir.exists():
            console.print(f"[red].agentbox/ not found in {project_dir}[/red]")
            console.print(f"[blue]Run: agentbox init[/blue]")
            sys.exit(1)

        volumes = _load_volumes_config(agentbox_dir)
        if not volumes:
            console.print("[yellow]No extra mounts configured[/yellow]")
            return

        target_path = str(Path(path_or_name).expanduser().resolve())
        removed = [
            entry
            for entry in volumes
            if entry.get("mount") == path_or_name or entry.get("path") == target_path
        ]
        remaining = [
            entry
            for entry in volumes
            if entry.get("mount") != path_or_name and entry.get("path") != target_path
        ]

        if len(remaining) == len(volumes):
            console.print(f"[yellow]No matching mount found for '{path_or_name}'[/yellow]")
            return

        _save_volumes_config(agentbox_dir, remaining)
        _update_agent_context(project_dir, remaining)
        _cleanup_default_docs(project_dir, agentbox_dir)
        for entry in removed:
            mount_name = entry.get("mount")
            if mount_name:
                _update_codex_context_mount(agentbox_dir, mount_name, False)

        console.print(f"[green]✓ Removed mount(s) matching '{path_or_name}'[/green]")

        # Rebuild container to apply mounts
        manager = ContainerManager()
        project_name = manager.get_project_name(project_dir)
        container_name = manager.get_container_name(project_name)
        console.print(f"[blue]Rebuilding container to apply mounts...[/blue]")
        if manager.container_exists(container_name):
            manager.remove_container(container_name, force=True)
        manager.create_container(project_name=project_name, project_dir=project_dir)
        console.print(f"[green]✓ Container rebuilt[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.group()
def skill():
    """Manage skills (list, add, remove)."""
    pass


@skill.command(name="list")
def skill_list():
    """List available skills from library."""
    try:
        lib_manager = LibraryManager()
        lib_manager.print_skills_table()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@skill.command(name="show")
@click.argument("name")
def skill_show(name: str):
    """Show details of a skill."""
    try:
        lib_manager = LibraryManager()
        lib_manager.show_skill(name)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@skill.command(name="add")
@click.argument("name")
def skill_add(name: str):
    """Add a skill from the library to the current project."""
    try:
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        agentbox_dir = project_dir / ".agentbox"
        if not agentbox_dir.exists():
            console.print(f"[red].agentbox/ not found in {project_dir}[/red]")
            console.print(f"[blue]Run: agentbox init[/blue]")
            sys.exit(1)

        lib_manager = LibraryManager()
        candidate_paths = []
        if Path(name).suffix:
            candidate_paths.append(lib_manager.skills_dir / name)
        else:
            for ext in (".yaml", ".yml", ".json"):
                candidate_paths.append(lib_manager.skills_dir / f"{name}{ext}")

        source_path = next((p for p in candidate_paths if p.exists()), None)
        if source_path is None:
            console.print(f"[red]Skill '{name}' not found in library[/red]")
            console.print(f"[blue]Run: agentbox skill list[/blue]")
            sys.exit(1)

        skills_dir = agentbox_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        target_path = skills_dir / source_path.name
        if target_path.exists():
            console.print(f"[yellow]Skill '{source_path.name}' already exists in project[/yellow]")
            console.print(f"[blue]Edit {target_path} to modify it[/blue]")
            return

        shutil.copy2(source_path, target_path)
        readme_source = source_path.parent / f"{source_path.stem}.md"
        if readme_source.exists():
            shutil.copy2(readme_source, skills_dir / readme_source.name)

        config_path = agentbox_dir / "config.json"
        project_config = {}
        if config_path.exists():
            try:
                project_config = json.loads(config_path.read_text())
            except Exception:
                project_config = {}
        skills_list = project_config.get("skills")
        if not isinstance(skills_list, list):
            skills_list = []
        if source_path.name not in skills_list:
            skills_list.append(source_path.name)
        project_config["skills"] = skills_list
        config_path.write_text(json.dumps(project_config, indent=2))
        _update_agent_context(project_dir, _load_volumes_config(agentbox_dir))

        console.print(f"[green]✓ Added '{source_path.name}' skill to project[/green]")
        console.print(f"[blue]Path: {target_path}[/blue]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@skill.command(name="remove")
@click.argument("name")
def skill_remove(name: str):
    """Remove a skill from the current project."""
    try:
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        agentbox_dir = project_dir / ".agentbox"
        config_path = agentbox_dir / "config.json"
        skills_dir = agentbox_dir / "skills"

        if not config_path.exists():
            console.print(f"[red]No project config found[/red]")
            sys.exit(1)

        project_config = {}
        try:
            project_config = json.loads(config_path.read_text())
        except Exception:
            project_config = {}

        skills_list = project_config.get("skills")
        if not isinstance(skills_list, list):
            skills_list = []

        removed = False
        if name in skills_list:
            skills_list.remove(name)
            removed = True
        if skills_list:
            project_config["skills"] = skills_list
        elif "skills" in project_config:
            del project_config["skills"]

        target_path = skills_dir / name
        if target_path.exists():
            target_path.unlink()
            removed = True
            readme_path = skills_dir / f"{target_path.stem}.md"
            if readme_path.exists():
                readme_path.unlink()

        if not removed:
            console.print(f"[yellow]Skill '{name}' not found in project[/yellow]")
            return

        config_path.write_text(json.dumps(project_config, indent=2))
        _update_agent_context(project_dir, _load_volumes_config(agentbox_dir))
        console.print(f"[green]✓ Removed '{name}' skill from project[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("project", required=False)
@click.option("--force", "-f", is_flag=True, help="Force remove running container")
def remove(project: Optional[str], force: bool):
    """Remove an Agentbox container.

    If no project name is provided, removes the current project's container.
    """
    try:
        manager = ContainerManager()

        if project is None:
            # Use current project
            project_name = manager.get_project_name()
        else:
            project_name = manager.sanitize_project_name(project)

        container_name = manager.get_container_name(project_name)
        manager.remove_container(container_name, force=force)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
def cleanup():
    """Remove all stopped Agentbox containers."""
    try:
        manager = ContainerManager()
        manager.cleanup_stopped()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
def rebuild():
    """Rebuild container from scratch (useful to fix broken states)."""
    try:
        manager = ContainerManager()
        # Get project directory from environment variable or current directory
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()
        project_name = manager.get_project_name(project_dir)
        container_name = manager.get_container_name(project_name)

        # Check if container exists
        if manager.container_exists(container_name):
            console.print(f"[yellow]Removing existing container {container_name}...[/yellow]")
            manager.remove_container(container_name, force=True)
            console.print(f"[green]Container removed[/green]")
        else:
            console.print(f"[blue]No existing container found[/blue]")

        # Recreate container
        console.print(f"[green]Creating fresh container...[/green]")
        container = manager.create_container(
            project_name=project_name,
            project_dir=project_dir,
        )

        console.print(f"\n[green]✓ Container rebuilt: {container.name}[/green]")
        console.print("\n[blue]Next steps:[/blue]")
        console.print(f"  agentbox shell    - Enter interactive shell")
        console.print(f"  agentbox claude   - Run Claude Code")
        console.print(f"  agentbox codex    - Run Codex")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
def init():
    """Initialize .agentbox/ directory structure for the project."""
    try:
        console.print(BANNER, highlight=False, markup=False)
        # Get project directory
        env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
        project_dir = Path(env_project_dir) if env_project_dir else Path.cwd()

        agentbox_dir = project_dir / ".agentbox"

        # Check if already initialized
        config_path = agentbox_dir / "config.json"
        codex_config_path = agentbox_dir / "codex.toml"
        if agentbox_dir.exists():
            console.print(f"[yellow].agentbox/ already initialized in {project_dir}[/yellow]")

        console.print(f"[green]Initializing .agentbox/ in {project_dir}...[/green]")

        # Create directory structure
        agentbox_dir.mkdir(parents=True, exist_ok=True)
        (agentbox_dir / "state").mkdir(exist_ok=True)
        (agentbox_dir / "skills").mkdir(exist_ok=True)

        # Create config.json with defaults
        if not config_path.exists():
            default_config = {
                "mcpServers": {
                    "notify": {
                        "command": "python3",
                        "args": ["/agentbox/library/mcp/notify/server.py"]
                    }
                }
            }
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=2)

        # Create codex.toml with defaults
        if not codex_config_path.exists():
            codex_config_content = """[projects."/workspace"]
trust_level = "trusted"

[mcp_servers."notify"]
command = "python3"
args = ["/agentbox/library/mcp/notify/server.py"]
"""
            with open(codex_config_path, 'w') as f:
                f.write(codex_config_content)

        # Create volumes.json with defaults
        volumes_path = agentbox_dir / VOLUMES_CONFIG_NAME
        if not volumes_path.exists():
            volumes_path.write_text(json.dumps({"volumes": []}, indent=2))

        _ensure_agent_doc(project_dir, [])
        _update_agent_context(project_dir, [])
        _cleanup_default_docs(project_dir, agentbox_dir)

        # Create .gitignore
        gitignore_path = agentbox_dir / ".gitignore"
        gitignore_content = """# Claude runtime state (auto-generated)
state/

# Environment secrets (if used)
.env
.env.local
"""
        with open(gitignore_path, 'w') as f:
            f.write(gitignore_content)

        # Create LOG.md
        log_path = agentbox_dir / LOG_DOC_NAME
        if not log_path.exists():
            log_path.write_text("# Agentbox Log\n\n- ")

        console.print(f"\n[green]✓ Initialized .agentbox/[/green]")
        console.print(f"\n[blue]Created:[/blue]")
        console.print(f"  .agentbox/config.json")
        console.print(f"  .agentbox/.gitignore")
        console.print(f"  .agentbox/LOG.md")
        console.print(f"  .agentbox/skills/")
        console.print(f"\n[yellow]Create PLAN.md in project root for planning context[/yellow]")
        console.print(f"\n[blue]Next: agentbox start[/blue]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.command()
def update():
    """Update the Agentbox base image."""
    try:
        repo_root = None
        for candidate in [Path.cwd(), *Path.cwd().parents]:
            if (candidate / "Dockerfile.base").is_file():
                repo_root = candidate
                break

        if repo_root is None:
            console.print("[red]Dockerfile.base not found in current or parent directories.[/red]")
            console.print("[yellow]Run this from the Agentbox repo or build manually:[/yellow]")
            console.print("  docker build -f Dockerfile.base -t agentbox-base:latest .")
            sys.exit(1)

        console.print(f"[blue]Rebuilding base image from {repo_root}...[/blue]")
        result = subprocess.run(
            [
                "docker",
                "build",
                "-f",
                str(repo_root / "Dockerfile.base"),
                "-t",
                "agentbox-base:latest",
                str(repo_root),
            ],
            check=False,
        )
        if result.returncode != 0:
            console.print("[red]Docker build failed.[/red]")
            sys.exit(result.returncode)
        console.print("[green]✓ Base image rebuilt[/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
