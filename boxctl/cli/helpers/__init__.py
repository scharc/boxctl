# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Shared helpers for the boxctl CLI.

This package has been split into modular files for better organization:
- tmux_ops.py: Tmux session management
- agent_commands.py: Agent command building and execution
- completions.py: Click shell completions
- config_ops.py: Configuration loading/saving
- context.py: Dynamic context building
- utils.py: Utility functions

All functions are re-exported here for convenience.
"""

from rich.console import Console

# Constants
BANNER = (
    " ███████████     ███████    █████ █████           █████    ████\n"
    "░░███░░░░░███  ███░░░░░███ ░░███ ░░███           ░░███    ░░███\n"
    " ░███    ░███ ███     ░░███ ░░███ ███    ██████  ███████   ░███\n"
    " ░██████████ ░███      ░███  ░░█████    ███░░███░░░███░    ░███\n"
    " ░███░░░░░███░███      ░███   ███░███  ░███ ░░░   ░███     ░███\n"
    " ░███    ░███░░███     ███   ███ ░░███ ░███  ███  ░███ ███ ░███\n"
    " ███████████  ░░░███████░   █████ █████░░██████   ░░█████  █████\n"
    "░░░░░░░░░░░     ░░░░░░░    ░░░░░ ░░░░░  ░░░░░░     ░░░░░  ░░░░░\n"
)

WORKSPACES_CONFIG_NAME = "workspaces.json"
WORKSPACES_MOUNT_ROOT = "/context"
CONTAINERS_CONFIG_NAME = "containers.json"
LOG_DOC_NAME = "LOG.md"

console = Console()

# Import all functions from modules
from boxctl.cli.helpers.tmux_ops import (
    _sanitize_tmux_name,
    _resolve_tmux_prefix,
    _get_tmux_sessions,
    _session_exists,
    _get_agent_sessions,
    _generate_session_name,
    _warn_if_agents_running,
    _warn_if_base_outdated,
    _warn_if_devices_missing,
    _get_tmux_socket,
    _attach_tmux_session,
)

from boxctl.cli.helpers.agent_commands import (
    _resolve_container_and_args,
    _build_agent_command,
    _ensure_container_running,
    _run_agent_command,
)

from boxctl.cli.helpers.completions import (
    _complete_session_name,
    _complete_project_name,
    _complete_connect_session,
    _complete_mcp_names,
    _complete_worktree_branch,
)

from boxctl.cli.helpers.config_ops import (
    _load_workspaces_config,
    _save_workspaces_config,
    _load_containers_config,
    _save_containers_config,
    _validate_connection,
    _load_packages_config,
    _save_packages_config,
    _load_mcp_meta,
    _save_mcp_meta,
)

from boxctl.cli.helpers.context import (
    _build_dynamic_context,
    _load_codex_config,
)

from boxctl.cli.helpers.command_ops import (
    _copy_commands,
    _remove_commands,
    _list_installed_commands,
    _sync_mcp_commands,
    _sync_skill_commands,
    _remove_stale_commands,
)

from boxctl.cli.helpers.utils import (
    ProjectContext,
    _get_project_context,
    _require_container_running,
    _require_boxctl_dir,
    _sanitize_mount_name,
    _sync_library_mcps,
    _sync_library_skills,
    _rebuild_container,
    handle_errors,
    safe_rmtree,
    wait_for_container_ready,
    parse_env_file,
    # Error handling helpers
    show_error_panel,
    require_initialized,
    ContainerError,
    NotInitializedError,
)

from boxctl.cli.helpers.daemon_client import (
    query_daemon,
    get_sessions_from_daemon,
    get_session_counts_from_daemon,
)

from boxctl.cli.helpers.port_utils import (
    PortConflict,
    check_port_available,
    check_configured_ports,
    format_conflict_message,
    release_port_from_container,
)

__all__ = [
    # Constants
    "BANNER",
    "WORKSPACES_CONFIG_NAME",
    "WORKSPACES_MOUNT_ROOT",
    "CONTAINERS_CONFIG_NAME",
    "LOG_DOC_NAME",
    "console",
    # Tmux operations
    "_sanitize_tmux_name",
    "_resolve_tmux_prefix",
    "_get_tmux_sessions",
    "_session_exists",
    "_get_agent_sessions",
    "_generate_session_name",
    "_warn_if_agents_running",
    "_warn_if_base_outdated",
    "_warn_if_devices_missing",
    "_get_tmux_socket",
    "_attach_tmux_session",
    # Agent commands
    "_resolve_container_and_args",
    "_build_agent_command",
    "_ensure_container_running",
    "_run_agent_command",
    # Completions
    "_complete_session_name",
    "_complete_project_name",
    "_complete_connect_session",
    "_complete_mcp_names",
    "_complete_worktree_branch",
    # Config operations
    "_load_workspaces_config",
    "_save_workspaces_config",
    "_load_containers_config",
    "_save_containers_config",
    "_validate_connection",
    "_load_packages_config",
    "_save_packages_config",
    "_load_mcp_meta",
    "_save_mcp_meta",
    # Context building
    "_build_dynamic_context",
    "_load_codex_config",
    # Command operations
    "_copy_commands",
    "_remove_commands",
    "_list_installed_commands",
    "_sync_mcp_commands",
    "_sync_skill_commands",
    "_remove_stale_commands",
    # Utilities
    "ProjectContext",
    "_get_project_context",
    "_require_container_running",
    "_require_boxctl_dir",
    "_sanitize_mount_name",
    "_sync_library_mcps",
    "_sync_library_skills",
    "_rebuild_container",
    "handle_errors",
    "safe_rmtree",
    "wait_for_container_ready",
    "parse_env_file",
    # Error handling helpers
    "show_error_panel",
    "require_initialized",
    "ContainerError",
    "NotInitializedError",
    # Daemon client
    "query_daemon",
    "get_sessions_from_daemon",
    "get_session_counts_from_daemon",
    # Port utilities
    "PortConflict",
    "check_port_available",
    "check_configured_ports",
    "format_conflict_message",
    "release_port_from_container",
]
