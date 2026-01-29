# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Conversation log commands.

View and export agent conversation logs from tracked sessions.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from click.shell_completion import CompletionItem
from rich.console import Console
from rich.table import Table

console = Console()


def _complete_session_name(ctx, param, incomplete):
    """Autocomplete session names from session-map.json."""
    map_file = Path.cwd() / ".boxctl" / "session-map.json"
    if not map_file.exists():
        return []

    try:
        data = json.loads(map_file.read_text())
        return [
            CompletionItem(name, help=f"{info.get('agent', '?')} - {info.get('started', '')[:19]}")
            for name, info in data.items()
            if name.startswith(incomplete)
        ]
    except:
        return []


def get_project_dir() -> Path:
    """Get current project directory."""
    return Path.cwd()


def get_boxctl_dir() -> Path:
    """Get .boxctl directory for current project."""
    return get_project_dir() / ".boxctl"


def load_session_map() -> dict:
    """Load session mapping."""
    map_file = get_boxctl_dir() / "session-map.json"
    if map_file.exists():
        try:
            return json.loads(map_file.read_text())
        except:
            pass
    return {}


def parse_timestamp(ts: str) -> str:
    """Format timestamp for display."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except:
        return ""


def extract_text(content) -> str:
    """Extract plain text from message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif "text" in item:
                    texts.append(item["text"])
        return "\n".join(texts)
    return ""


def parse_jsonl(path: Path, agent: str) -> list[dict]:
    """Parse JSONL file to messages."""
    messages = []

    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = parse_timestamp(entry.get("timestamp", ""))

                    # Claude format
                    if agent == "claude":
                        etype = entry.get("type", "")
                        if etype == "user":
                            text = extract_text(entry.get("message", {}).get("content", ""))
                            if text:
                                messages.append({"time": ts, "role": "USER", "text": text})
                        elif etype == "assistant":
                            content = entry.get("message", {}).get("content", "")
                            if isinstance(content, list):
                                texts = [
                                    i.get("text", "")
                                    for i in content
                                    if isinstance(i, dict) and i.get("type") == "text"
                                ]
                                text = "\n".join(t for t in texts if t)
                            else:
                                text = str(content) if content else ""
                            if text:
                                messages.append({"time": ts, "role": "ASSISTANT", "text": text})

                    # Codex/generic format
                    else:
                        role = entry.get("role", "")
                        if role in ("user", "assistant"):
                            text = extract_text(entry.get("content", ""))
                            if text:
                                messages.append({"time": ts, "role": role.upper(), "text": text})

                except json.JSONDecodeError:
                    continue
    except Exception as e:
        console.print(f"[red]Error reading {path}: {e}[/red]")

    return messages


def format_markdown(session: str, info: dict, messages: list) -> str:
    """Format messages as markdown."""
    lines = [
        f"# Session: {session}",
        f"",
        f"- **Agent**: {info.get('agent', 'unknown')}",
        f"- **Started**: {info.get('started', '')[:19]}",
        f"- **Messages**: {len(messages)}",
        f"",
        f"---",
        f"",
    ]

    for msg in messages:
        time_str = f"[{msg['time']}] " if msg["time"] else ""
        lines.append(f"## {time_str}{msg['role']}")
        lines.append("")
        lines.append(msg["text"])
        lines.append("")

    return "\n".join(lines)


@click.group()
def logs():
    """Conversation log commands."""
    pass


@logs.command("list")
def logs_list():
    """List tracked sessions."""
    data = load_session_map()

    if not data:
        console.print("[yellow]No sessions tracked[/yellow]")
        console.print("Sessions are tracked when agents start in tmux sessions.")
        return

    table = Table(title="Tracked Sessions")
    table.add_column("Session", style="cyan")
    table.add_column("Agent", style="green")
    table.add_column("Started", style="yellow")
    table.add_column("File")

    for session, info in sorted(data.items(), key=lambda x: x[1].get("started", ""), reverse=True):
        agent = info.get("agent", "?")
        started = info.get("started", "")[:19]
        file_path = info.get("file", "none")
        if file_path and len(file_path) > 40:
            file_path = "..." + file_path[-37:]
        table.add_row(session, agent, started, file_path or "none")

    console.print(table)


@logs.command("export")
@click.argument("session", required=False, shell_complete=_complete_session_name)
@click.option("--output", "-o", type=click.Path(), help="Output file path")
def logs_export(session: Optional[str], output: Optional[str]):
    """Export session to markdown.

    If SESSION is not specified, lists available sessions.
    """
    data = load_session_map()

    if not session:
        if not data:
            console.print("[yellow]No sessions tracked[/yellow]")
            return
        console.print("Available sessions:")
        for s in data.keys():
            console.print(f"  {s}")
        console.print("\nUsage: boxctl logs export <session>")
        return

    if session not in data:
        console.print(f"[red]Session not found: {session}[/red]")
        console.print("Use 'boxctl logs list' to see available sessions")
        return

    info = data[session]
    file_path = info.get("file")

    if not file_path:
        console.print(f"[red]No file mapped for session: {session}[/red]")
        return

    history_dir = get_boxctl_dir() / "history"
    full_path = history_dir / file_path

    if not full_path.exists():
        console.print(f"[red]File not found: {full_path}[/red]")
        return

    agent = info.get("agent", "unknown")
    messages = parse_jsonl(full_path, agent)
    markdown = format_markdown(session, info, messages)

    if output:
        out_file = Path(output)
    else:
        logs_dir = get_boxctl_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        started = info.get("started", "")[:19].replace(":", "").replace("-", "").replace("T", "-")
        out_file = logs_dir / f"{started}-{session}.md"

    out_file.write_text(markdown)
    console.print(f"[green]Exported {len(messages)} messages to {out_file}[/green]")


@logs.command("show")
@click.argument("session", required=False, shell_complete=_complete_session_name)
@click.option("--limit", "-n", type=int, default=20, help="Number of messages to show")
def logs_show(session: Optional[str], limit: int):
    """Show recent messages from session.

    If SESSION is not specified, lists available sessions.
    """
    data = load_session_map()

    if not session:
        if not data:
            console.print("[yellow]No sessions tracked[/yellow]")
            return
        console.print("Available sessions:")
        for s in data.keys():
            console.print(f"  {s}")
        console.print("\nUsage: boxctl logs show <session>")
        return

    if session not in data:
        console.print(f"[red]Session not found: {session}[/red]")
        return

    info = data[session]
    file_path = info.get("file")

    if not file_path:
        console.print(f"[red]No file mapped for session: {session}[/red]")
        return

    history_dir = get_boxctl_dir() / "history"
    full_path = history_dir / file_path

    if not full_path.exists():
        console.print(f"[red]File not found: {full_path}[/red]")
        return

    agent = info.get("agent", "unknown")
    messages = parse_jsonl(full_path, agent)

    # Show last N messages
    for msg in messages[-limit:]:
        time_str = f"[dim][{msg['time']}][/dim] " if msg["time"] else ""
        role_color = "cyan" if msg["role"] == "USER" else "green"
        text = msg["text"][:300] + "..." if len(msg["text"]) > 300 else msg["text"]
        text = text.replace("\n", " ")
        console.print(f"{time_str}[{role_color}]{msg['role']}[/{role_color}]: {text}")
