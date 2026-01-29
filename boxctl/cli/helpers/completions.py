# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Click shell completion functions.

These functions provide fast tab-completion by querying the boxctld service
when available. Falls back to direct Docker API calls when the service isn't running.

Performance optimized with TTL cache to avoid repeated Docker API calls during
rapid tab completion sequences.
"""

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List, Any

import click

from boxctl import container_naming
from boxctl.paths import ContainerPaths

# =============================================================================
# Completion cache for fallback functions (avoids repeated Docker API calls)
# =============================================================================
_completion_cache: Dict[str, List[str]] = {}
_completion_cache_time: Dict[str, float] = {}
_completion_cache_lock = threading.Lock()
_COMPLETION_CACHE_TTL = 5.0  # 5 seconds - short enough to stay fresh


def _get_cached_completion(cache_key: str) -> Optional[List[str]]:
    """Get completion results from cache if fresh."""
    with _completion_cache_lock:
        if cache_key in _completion_cache:
            if time.time() - _completion_cache_time.get(cache_key, 0) < _COMPLETION_CACHE_TTL:
                return _completion_cache[cache_key]
    return None


def _set_cached_completion(cache_key: str, results: List[str]) -> None:
    """Store completion results in cache."""
    with _completion_cache_lock:
        _completion_cache[cache_key] = results
        _completion_cache_time[cache_key] = time.time()


def _get_boxctld_socket() -> Path:
    """Get the boxctld socket path (platform-aware: macOS vs Linux)."""
    from boxctl.host_config import get_config

    return get_config().socket_path


def _query_boxctld(action: str, **params) -> Optional[dict]:
    """Query boxctld via socket. Returns None on failure.

    This is optimized for fast completions with a short timeout.
    """
    socket_path = _get_boxctld_socket()
    if not socket_path.exists():
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.1)  # Fast timeout for completions (socket IPC is <10ms)
        sock.connect(str(socket_path))
        request = json.dumps({"action": action, **params})
        sock.sendall(request.encode() + b"\n")
        response = sock.recv(8192).decode()
        sock.close()
        result = json.loads(response)
        if result.get("ok"):
            return result
        return None
    except Exception:
        return None


# =============================================================================
# Fallback functions (used when boxctld is not running)
# =============================================================================


def _complete_project_name_fallback(incomplete: str) -> list[str]:
    """Fallback: complete project names via Docker API (slow).

    Performance optimized: Uses TTL cache (5 seconds) to avoid repeated Docker calls.
    """
    cache_key = "project_names"

    # Check cache first (regardless of incomplete prefix)
    cached = _get_cached_completion(cache_key)
    if cached is not None:
        return [n for n in cached if n.startswith(incomplete)]

    try:
        from boxctl.container import ContainerManager

        manager = ContainerManager()
        containers = manager.list_containers(all_containers=False)
        project_names = []
        for container in containers:
            name = container.get("name", "")
            project_name = container_naming.extract_project_name(name)
            if project_name:
                project_names.append(project_name)

        # Cache full list
        _set_cached_completion(cache_key, project_names)
        return [n for n in project_names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_session_name_fallback(incomplete: str, project: str = None) -> list[str]:
    """Fallback: complete session names via Docker exec (slow).

    Performance optimized: Uses TTL cache (5 seconds) to avoid repeated docker exec calls.
    """
    try:
        from boxctl.container import ContainerManager
        from boxctl.cli.helpers.tmux_ops import _get_tmux_sessions

        manager = ContainerManager()
        if project:
            # Explicit project - use simple name generation
            project_name = container_naming.sanitize_name(project)
            container_name = f"{container_naming.CONTAINER_PREFIX}{project_name}"
        else:
            # No project - use collision-aware resolution based on current directory
            container_name = container_naming.resolve_container_name()

        if not manager.is_running(container_name):
            return []

        # Check cache first
        cache_key = f"sessions:{container_name}"
        cached = _get_cached_completion(cache_key)
        if cached is not None:
            return [n for n in cached if n.startswith(incomplete)]

        sessions = _get_tmux_sessions(manager, container_name)
        names = [session["name"] for session in sessions]

        # Cache full list
        _set_cached_completion(cache_key, names)
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_worktree_fallback(incomplete: str) -> list[str]:
    """Fallback: complete worktree branches via Docker exec (slow).

    Performance optimized: Uses TTL cache (5 seconds) to avoid repeated docker exec calls.
    """
    try:
        from boxctl.container import ContainerManager, get_abox_environment

        manager = ContainerManager()
        # Use collision-aware resolution based on current directory
        container_name = container_naming.resolve_container_name()
        if not manager.is_running(container_name):
            return []

        # Check cache first
        cache_key = f"worktrees:{container_name}"
        cached = _get_cached_completion(cache_key)
        if cached is not None:
            return [b for b in cached if b.startswith(incomplete)]

        exit_code, output = manager.exec_command(
            container_name,
            ["agentctl", "worktree", "list", "--json"],
            environment=get_abox_environment(include_tmux=True, container_name=container_name),
            user=ContainerPaths.USER,
            workdir="/workspace",
        )
        if exit_code != 0:
            return []

        data = json.loads(output)
        worktrees = data.get("worktrees", [])
        branches = []
        for wt in worktrees:
            path = wt.get("path", "")
            branch = wt.get("branch", "")
            if path != "/workspace" and branch:
                branches.append(branch)

        # Cache full list
        _set_cached_completion(cache_key, branches)
        return [b for b in branches if b.startswith(incomplete)]
    except Exception:
        return []


# =============================================================================
# Main completion functions (fast path via boxctld, fallback to slow path)
# =============================================================================


def _complete_session_name(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete session names for current project."""
    # Get current project name for context (used for boxctld query filtering)
    try:
        project_dir = container_naming.resolve_project_dir()
        project = container_naming.sanitize_name(project_dir.name)
    except Exception:
        project = None

    # Only use boxctld if we have a project context (otherwise it returns cross-project entries)
    if project:
        result = _query_boxctld("get_completions", type="sessions", project=project)
        if result:
            sessions = result.get("sessions", [])
            return [s for s in sessions if s.startswith(incomplete)]

    # Fallback to Docker API (slow)
    return _complete_session_name_fallback(incomplete, project=project)


def _complete_project_name(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete project names from running boxctl containers."""
    # Try boxctld first (fast)
    result = _query_boxctld("get_completions", type="projects")
    if result:
        projects = result.get("projects", [])
        return [p for p in projects if p.startswith(incomplete)]

    # Fallback to Docker API (slow)
    return _complete_project_name_fallback(incomplete)


def _complete_connect_session(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete session names for connect command, using project from first arg if provided."""
    # Support both "project" and "project_name" parameter names
    project = ctx.params.get("project_name") or ctx.params.get("project")

    # If no project specified, try to get from current directory
    if not project:
        try:
            project_dir = container_naming.resolve_project_dir()
            project = container_naming.sanitize_name(project_dir.name)
        except Exception:
            pass

    # Only use boxctld if we have a project context (otherwise it returns cross-project entries)
    if project:
        result = _query_boxctld("get_completions", type="sessions", project=project)
        if result:
            sessions = result.get("sessions", [])
            return [s for s in sessions if s.startswith(incomplete)]

    # Fallback to Docker API (slow)
    return _complete_session_name_fallback(incomplete, project=project)


def _complete_mcp_names(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    """Complete MCP server names from the library."""
    # Try boxctld first (fast, but MCP is already fast: ~1ms)
    result = _query_boxctld("get_completions", type="mcp")
    if result:
        names = result.get("mcp_servers", [])
        return [n for n in names if n.startswith(incomplete)]

    # Direct fallback (also fast)
    try:
        from boxctl.library import LibraryManager

        lib = LibraryManager()
        servers = lib.list_mcp_servers()
        names = [s["name"] for s in servers]
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_worktree_branch(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete worktree branch names from existing worktrees."""
    # Get current project name for context (used for boxctld query filtering)
    try:
        project_dir = container_naming.resolve_project_dir()
        project = container_naming.sanitize_name(project_dir.name)
    except Exception:
        project = None

    # Only use boxctld if we have a project context (otherwise it returns cross-project entries)
    if project:
        result = _query_boxctld("get_completions", type="worktrees", project=project)
        if result:
            worktrees = result.get("worktrees", [])
            return [w for w in worktrees if w.startswith(incomplete)]

    # Fallback to Docker exec (slow)
    return _complete_worktree_fallback(incomplete)


def _complete_skill_names(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    """Complete skill names from the library."""
    # Try boxctld first (fast, but skills is already fast: ~23ms)
    result = _query_boxctld("get_completions", type="skills")
    if result:
        names = result.get("skills", [])
        return [n for n in names if n.startswith(incomplete)]

    # Direct fallback (also fast)
    try:
        from boxctl.library import LibraryManager

        lib = LibraryManager()
        skills = lib.list_skills()
        names = [s["name"] for s in skills]
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_workspace_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete workspace mount names for current project."""
    try:
        from boxctl.cli.helpers import _load_workspaces_config
        from boxctl.utils.project import resolve_project_dir, get_boxctl_dir

        project_dir = resolve_project_dir()
        boxctl_dir = get_boxctl_dir(project_dir)
        workspaces = _load_workspaces_config(boxctl_dir)
        names = [w.get("mount", "") for w in workspaces if w.get("mount")]
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_config_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete config names from the library."""
    try:
        from boxctl.library import LibraryManager

        lib = LibraryManager()
        configs = lib.list_configs()
        names = [c["name"] for c in configs]
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_docker_containers(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete docker container names (non-boxctl containers)."""
    # Try boxctld first (queries Docker API but via persistent daemon)
    result = _query_boxctld("get_completions", type="docker_containers", include_boxctl=False)
    if result:
        names = result.get("docker_containers", [])
        return [n for n in names if n.startswith(incomplete)]

    # Fallback to Docker API directly
    try:
        from boxctl.container import ContainerManager

        manager = ContainerManager()
        containers = manager.get_all_containers(include_boxctl=False)
        names = [c["name"] for c in containers]
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []


def _complete_connected_containers(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[str]:
    """Complete connected container names for current project."""
    try:
        from boxctl.cli.helpers import _load_containers_config
        from boxctl.utils.project import resolve_project_dir, get_boxctl_dir

        project_dir = resolve_project_dir()
        boxctl_dir = get_boxctl_dir(project_dir)
        connections = _load_containers_config(boxctl_dir)
        names = [c.get("name", "") for c in connections if c.get("name")]
        return [n for n in names if n.startswith(incomplete)]
    except Exception:
        return []
