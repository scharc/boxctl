# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Usage tracking and fallback CLI commands."""

import click
from rich.table import Table

from boxctl.cli import cli
from boxctl.cli.helpers import console, handle_errors
from boxctl.cli.helpers.daemon_client import get_usage_status_from_daemon


def _format_timedelta(seconds: int) -> str:
    """Format seconds as human-readable string."""
    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        return f"{hours}h {remaining_minutes}m"

    days = hours // 24
    remaining_hours = hours % 24
    return f"{days}d {remaining_hours}h"


@cli.group()
def usage():
    """Agent usage tracking and fallback management.

    Track rate limit status across agents and configure automatic fallback
    when an agent is rate-limited.
    """
    pass


@usage.command("status")
@handle_errors
def status():
    """Show current rate limit status for all agents.

    Displays which agents are available and which are rate-limited,
    including when limits are expected to reset.
    """
    # Try daemon first
    daemon_status = get_usage_status_from_daemon()

    if daemon_status:
        source = "service"
        agents_data = daemon_status
    else:
        # Fallback to local state
        source = "local"
        try:
            from boxctl.usage.client import get_usage_status

            agents_data = get_usage_status()
        except ImportError:
            console.print("[red]Usage module not available[/red]")
            return

    table = Table(title=f"Agent Rate Limit Status (source: {source})")
    table.add_column("Agent", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Resets In", style="dim")

    # Show only super agents for cleaner output
    super_agents = ["superclaude", "supercodex", "supergemini", "superqwen"]

    for agent in super_agents:
        data = agents_data.get(agent, {})
        available = data.get("available", True)
        status_style = "green" if available else "red"
        status_text = f"[{status_style}]{'OK' if available else 'Limited'}[/{status_style}]"

        resets_in = "-"
        if not available and data.get("resets_in_seconds"):
            resets_in = _format_timedelta(data["resets_in_seconds"])

        table.add_row(agent, status_text, resets_in)

    console.print(table)


@usage.command("probe")
@click.argument("agent")
@handle_errors
def probe(agent: str):
    """Probe an agent to check if it's rate-limited.

    Sends a minimal test request to the agent and updates the state
    based on the response.

    AGENT: Agent to probe (superclaude, supercodex, supergemini, etc.)
    """
    from boxctl.usage.parser import probe_agent
    from boxctl.usage.client import report_rate_limit, clear_rate_limit

    console.print(f"[blue]Probing {agent}...[/blue]")

    result = probe_agent(agent)

    if result.get("error_type") == "not_installed":
        console.print(f"[yellow]{agent} is not installed[/yellow]")
        return

    if result.get("error_type") == "timeout":
        console.print(f"[yellow]{agent} timed out (may be slow or unavailable)[/yellow]")
        return

    if result.get("is_limited"):
        resets_at = result.get("resets_at")
        resets_in = result.get("resets_in_seconds")
        report_rate_limit(agent, resets_in, result.get("error_type"))
        resets_info = ""
        if resets_at:
            resets_info = f" (resets at {resets_at.isoformat()})"
        console.print(f"[red]{agent} is rate-limited{resets_info}[/red]")
    else:
        clear_rate_limit(agent)
        console.print(f"[green]{agent} is available[/green]")


@usage.command("reset")
@click.argument("agent")
@handle_errors
def reset(agent: str):
    """Clear rate limit state for an agent.

    Use this when you know a limit has reset or to clear stale state.

    AGENT: Agent to reset (superclaude, supercodex, supergemini, etc.)
    """
    from boxctl.usage.client import clear_rate_limit

    clear_rate_limit(agent)
    console.print(f"[green]Cleared rate limit state for {agent}[/green]")


@usage.command("reset-all")
@handle_errors
def reset_all():
    """Clear rate limit state for all agents."""
    from boxctl.usage.client import clear_rate_limit, FALLBACK_CHAINS

    for agent in FALLBACK_CHAINS.keys():
        clear_rate_limit(agent)

    console.print("[green]Cleared all agent rate limit state[/green]")


@usage.command("fallback")
@handle_errors
def fallback():
    """Show fallback configuration.

    Displays the fallback chain for each agent - which agents will be
    tried when the primary is rate-limited.
    """
    from boxctl.usage.client import FALLBACK_CHAINS

    table = Table(title="Agent Fallback Chains")
    table.add_column("Agent", style="cyan")
    table.add_column("Fallback Chain", style="dim")

    # Show only super agents
    super_agents = ["superclaude", "supercodex", "supergemini", "superqwen"]

    for agent in super_agents:
        chain = FALLBACK_CHAINS.get(agent, [])
        chain_str = " -> ".join(chain)
        table.add_row(agent, chain_str)

    console.print(table)
    console.print("\n[dim]When an agent is rate-limited, fallbacks are tried in order.[/dim]")


@usage.command("check")
@click.argument("agent")
@handle_errors
def check(agent: str):
    """Check if an agent is available and show fallback if needed.

    AGENT: Agent to check (superclaude, supercodex, supergemini, etc.)
    """
    from boxctl.usage.client import is_agent_available, get_fallback_agent

    if is_agent_available(agent):
        console.print(f"[green]{agent} is available[/green]")
    else:
        fallback_agent, reason = get_fallback_agent(agent)
        console.print(f"[yellow]{agent} is rate-limited[/yellow]")
        if fallback_agent != agent:
            console.print(f"[blue]Would use fallback: {fallback_agent}[/blue]")
        else:
            console.print(f"[yellow]No fallback available, would try {agent} anyway[/yellow]")
