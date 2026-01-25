# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Container lifecycle management for Agentbox."""

import json
import os
import pwd
import re
import time
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

import docker
from docker.models.containers import Container
from rich.console import Console
from rich.table import Table

from agentbox.config import ProjectConfig
from agentbox.utils.terminal import reset_terminal
from agentbox.utils.exceptions import ConfigError
from agentbox import container_naming
from agentbox.paths import ContainerPaths, HostPaths, ProjectPaths
import threading

console = Console()

# Module-level container cache (shared across all ContainerManager instances)
# Uses explicit string keys to avoid ambiguity with boolean parameters
_CACHE_KEY_ALL = "containers_all"      # all_containers=True
_CACHE_KEY_RUNNING = "containers_running"  # all_containers=False

_container_cache: Dict[str, List[Dict]] = {}
_container_cache_time: Dict[str, float] = {}
_container_cache_lock = threading.Lock()
_CONTAINER_CACHE_TTL = float(os.environ.get("AGENTBOX_CONTAINER_CACHE_TTL", "2.0"))


def invalidate_container_cache() -> None:
    """Clear ALL container cache variants. Call after create/remove/stop/start."""
    with _container_cache_lock:
        _container_cache.clear()
        _container_cache_time.clear()


def get_abox_environment(include_tmux: bool = False, container_name: str = None) -> dict:
    """Get standard environment dict for abox user container operations.

    Args:
        include_tmux: If True, includes TMUX_TMPDIR for tmux operations
        container_name: If provided, includes AGENTBOX_CONTAINER_NAME for MCP servers

    Returns:
        Dict with standard environment variables
    """
    env = {"HOME": ContainerPaths.HOME, "USER": "abox"}
    if include_tmux:
        env["TMUX_TMPDIR"] = "/tmp"
    if container_name:
        env["AGENTBOX_CONTAINER_NAME"] = container_name
    return env


class ContainerManager:
    """Manages Agentbox Docker containers."""

    BASE_IMAGE = "agentbox-base:latest"
    CONTAINER_PREFIX = "agentbox-"

    def __init__(self):
        """Initialize Docker client."""
        try:
            self.client = docker.from_env()
            from agentbox.host_config import get_config

            self.config = get_config()
        except docker.errors.DockerException as e:
            console.print(f"[red]Error: Could not connect to Docker: {e}[/red]")
            raise

    @property
    def AGENTBOX_DIR(self) -> Path:
        """Get agentbox installation directory (auto-detected)."""
        return self.config.agentbox_dir

    def sanitize_project_name(self, name: str) -> str:
        """Sanitize project name for Docker container naming.

        Args:
            name: Project directory name

        Returns:
            Sanitized name safe for Docker
        """
        return container_naming.sanitize_name(name)

    def get_project_name(self, project_dir: Optional[Path] = None) -> str:
        """Get sanitized project name from directory.

        Args:
            project_dir: Project directory path (defaults to current dir)

        Returns:
            Sanitized project name
        """
        resolved = container_naming.resolve_project_dir(project_dir)
        return container_naming.sanitize_name(resolved.name)

    def resolve_container_name(self, project_dir: Optional[Path] = None) -> str:
        """Resolve container name for a project directory.

        This is the preferred method - handles existing containers
        and name collisions properly.

        Args:
            project_dir: Project directory (defaults to current dir)

        Returns:
            Container name to use
        """
        return container_naming.resolve_container_name(project_dir)

    def _get_mcp_mounts(self, project_dir: Path) -> list:
        """Get extra mounts from MCP metadata."""
        meta_path = ProjectPaths.mcp_meta_file(project_dir)
        if not meta_path.exists():
            return []

        try:
            data = json.loads(meta_path.read_text())
        except Exception:
            return []

        mounts = []
        for server_name, server_meta in data.get("servers", {}).items():
            for mount in server_meta.get("mounts", []):
                host = mount.get("host")
                container = mount.get("container")
                mode = mount.get("mode", "ro")
                if host and container:
                    # Resolve relative paths against project_dir
                    host_path = Path(host)
                    if not host_path.is_absolute():
                        host_path = project_dir / host_path
                    if host_path.exists():
                        mounts.append({"host": str(host_path), "container": container, "mode": mode})
        return mounts

    def get_runtime_dir(self, project_name: str) -> Path:
        """Get runtime directory for project.

        Args:
            project_name: Sanitized project name

        Returns:
            Path to runtime directory
        """
        return self.AGENTBOX_DIR / "runtime" / project_name

    def container_exists(self, container_name: str) -> bool:
        """Check if container exists.

        Args:
            container_name: Full container name

        Returns:
            True if container exists
        """
        try:
            self.client.containers.get(container_name)
            return True
        except docker.errors.NotFound:
            return False

    def get_container(self, container_name: str) -> Optional[Container]:
        """Get container by name.

        Args:
            container_name: Full container name

        Returns:
            Container object or None if not found
        """
        try:
            return self.client.containers.get(container_name)
        except docker.errors.NotFound:
            return None

    def get_container_workspace(self, container_name: str) -> Optional[Path]:
        """Get the workspace path mounted in a container.

        Args:
            container_name: Full container name

        Returns:
            Path to workspace on host, or None if not found
        """
        return container_naming.get_container_workspace(container_name)

    def find_container_for_project(self, project_dir: Path) -> Optional[str]:
        """Find the container name for a project directory.

        Searches all agentbox containers and returns the one whose
        /workspace mount matches the given project path.

        Args:
            project_dir: Project directory path

        Returns:
            Container name, or None if not found
        """
        return container_naming.find_container_by_workspace(project_dir)

    def is_running(self, container_name: str) -> bool:
        """Check if container is running.

        Args:
            container_name: Full container name

        Returns:
            True if container is running
        """
        container = self.get_container(container_name)
        return container is not None and container.status == "running"

    def is_base_image_outdated(self, container_name: str) -> bool:
        """Check if container was created from an older base image.

        Compares the container's image ID with the current agentbox-base:latest image.

        Args:
            container_name: Full container name

        Returns:
            True if container's base image differs from current base image
        """
        try:
            container = self.client.containers.get(container_name)
        except docker.errors.NotFound:
            return False

        # Get container's image ID from attrs (works even if image was deleted)
        container_image_id = container.attrs.get("Image", "")

        try:
            # Get current base image ID
            base_image = self.client.images.get(self.BASE_IMAGE)
            base_image_id = base_image.id
        except docker.errors.ImageNotFound:
            # Base image doesn't exist yet - can't compare
            return False
        except Exception:
            return False

        return container_image_id != base_image_id

    def create_container(
        self,
        project_name: str,
        project_dir: Path,
        custom_name: Optional[str] = None,
    ) -> Container:
        """Create a new Agentbox container.

        Args:
            project_name: Sanitized project name
            project_dir: Absolute path to project directory
            custom_name: Optional custom container name (will be sanitized)

        Returns:
            Created container object
        """
        if custom_name:
            project_name = self.sanitize_project_name(custom_name)

        # Resolve container name (handles existing containers and collisions)
        container_name = container_naming.resolve_container_name(project_dir)

        # Check if this is a new collision-generated name
        default_name = container_naming.generate_default_name(project_dir)
        if container_name != default_name and not self.container_exists(container_name):
            console.print(f"[yellow]Name collision detected, using: {container_name}[/yellow]")

        # Return existing container if found
        if self.container_exists(container_name):
            # Lazy import to avoid circular dependency
            from agentbox.cli.helpers.tmux_ops import _show_warning_panel
            _show_warning_panel(
                "Config changes won't apply to existing container.\n"
                "Run 'agentbox rebase' to recreate with new settings.",
                "Existing Container"
            )
            container = self.get_container(container_name)
            if not self.is_running(container_name):
                console.print(f"[blue]Starting existing container...[/blue]")
                container.start()
            return container

        # Ensure .agentbox/state directory exists in project
        # Note: state is no longer mounted when host ~/.claude is mounted directly.
        agentbox_dir = ProjectPaths.agentbox_dir(project_dir)
        state_dir = agentbox_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        # Load project configuration
        config = ProjectConfig(project_dir)

        # Get user environment variables
        username = os.getenv("USER", "user")
        host_uid = os.getuid()
        # Use primary GID from passwd, not effective GID (which may be docker group)
        host_gid = pwd.getpwuid(host_uid).pw_gid
        # Git author defaults to username if not set (avoid hardcoded personal info)
        git_author_name = os.getenv("GIT_AUTHOR_NAME", username)
        git_author_email = os.getenv("GIT_AUTHOR_EMAIL", "")
        display = os.getenv("DISPLAY", ":0")
        runtime_dir = str(HostPaths.runtime_dir())
        agentboxd_dir = str(HostPaths.agentboxd_dir())
        dbus_address = HostPaths.dbus_socket()

        # Prepare volume mounts
        # Mount host config dirs for optional auth/state bootstrap
        host_claude_dir = HostPaths.claude_dir()
        host_openai_config_dir = HostPaths.openai_config_dir()
        host_codex_dir = HostPaths.codex_dir()
        host_gemini_dir = HostPaths.gemini_dir()
        host_qwen_dir = HostPaths.qwen_dir()
        host_gh_config_dir = HostPaths.gh_config_dir()
        host_glab_config_dir = HostPaths.glab_config_dir()
        mcp_mounts = self._get_mcp_mounts(project_dir)

        # Use project-local Claude state for session isolation
        # Each container gets its own history, cache, etc.
        project_claude_dir = ProjectPaths.claude_dir(project_dir)
        project_claude_dir.mkdir(parents=True, exist_ok=True)

        # Use project-local Codex state for session isolation (like Claude)
        project_codex_dir = ProjectPaths.codex_dir(project_dir)
        project_codex_dir.mkdir(parents=True, exist_ok=True)

        # Mount host config directories for credential access
        # We mount directories (not individual files) to avoid stale inode issues
        # when credential files are replaced during OAuth token refresh.
        # Individual file mounts capture the inode at mount time; directory mounts
        # allow seeing updated files even after replacement.

        volumes = {
            # Project workspace (read/write)
            str(project_dir.absolute()): {"bind": ContainerPaths.WORKSPACE, "mode": "rw"},
            # Project-local Claude state for session isolation
            str(project_claude_dir): {"bind": f"/{username}/claude", "mode": "rw"},
            # Project-local Codex state for session isolation
            str(project_codex_dir): {"bind": f"/{username}/codex", "mode": "rw"},
            # Agentbox global library (read-only)
            str(self.AGENTBOX_DIR / "library" / "config"): {"bind": ContainerPaths.LIBRARY_CONFIG, "mode": "ro"},
            str(self.AGENTBOX_DIR / "library" / "mcp"): {"bind": ContainerPaths.LIBRARY_MCP, "mode": "ro"},
            str(self.AGENTBOX_DIR / "library" / "skills"): {"bind": ContainerPaths.LIBRARY_SKILLS, "mode": "ro"},
        }

        # Mount user's custom MCP/skills directories if they exist
        # These are at ~/.config/agentbox/{mcp,skills}/ on host, mounted to /home/abox/.config/agentbox/
        user_mcp_dir = HostPaths.user_mcp_dir()
        user_skills_dir = HostPaths.user_skills_dir()
        if user_mcp_dir.exists():
            volumes[str(user_mcp_dir)] = {"bind": ContainerPaths.user_mcp_dir(), "mode": "ro"}
        if user_skills_dir.exists():
            volumes[str(user_skills_dir)] = {"bind": ContainerPaths.user_skills_dir(), "mode": "ro"}

        # Mount agentboxd socket directory (for streaming/notifications)
        # Create dir if needed - socket will appear when service starts
        Path(agentboxd_dir).mkdir(parents=True, exist_ok=True)
        volumes[agentboxd_dir] = {"bind": agentboxd_dir, "mode": "ro"}

        # Mount container-init.sh from workspace to override baked-in version
        # Note: File mounts have stale inode issues, but container-init.sh rarely changes
        # after container creation, so this is acceptable. Rebuild image for production.
        local_init_script = self.AGENTBOX_DIR / "bin" / "container-init.sh"
        if local_init_script.exists():
            volumes[str(local_init_script)] = {"bind": "/usr/local/bin/container-init.sh", "mode": "ro"}

        # Mount install-packages.py for development (same caveat as container-init.sh)
        local_install_script = self.AGENTBOX_DIR / "bin" / "install-packages.py"
        if local_install_script.exists():
            volumes[str(local_install_script)] = {"bind": "/usr/local/bin/install-packages.py", "mode": "ro"}

        # Mount generate-mcp-config.py for development
        local_mcp_config_script = self.AGENTBOX_DIR / "bin" / "generate-mcp-config.py"
        if local_mcp_config_script.exists():
            volumes[str(local_mcp_config_script)] = {"bind": "/usr/local/bin/generate-mcp-config.py", "mode": "ro"}

        # Mount host credential directories (not individual files) to avoid stale inode issues
        # When OAuth tokens refresh, the credential file is replaced (new inode).
        # File mounts would still show the old content; directory mounts see updates.
        # Must be read-write so container can update credentials during OAuth token refresh.
        if host_claude_dir.exists():
            volumes[str(host_claude_dir)] = {"bind": ContainerPaths.host_claude_mount(username), "mode": "rw"}
        if host_codex_dir.exists():
            volumes[str(host_codex_dir)] = {"bind": ContainerPaths.host_codex_mount(username), "mode": "rw"}

        # SSH configuration based on mode
        ssh_home = HostPaths.ssh_dir()
        ssh_mode = config.ssh_mode

        if config.ssh_enabled and ssh_mode != "none":
            if ssh_mode == "keys":
                # Keys mode: Mount to /host-ssh for copying during init
                if ssh_home.exists():
                    volumes[str(ssh_home)] = {"bind": ContainerPaths.HOST_SSH_MOUNT, "mode": "ro"}

            elif ssh_mode == "mount":
                # Mount mode: Bind mount read-write directly to .ssh
                if ssh_home.exists():
                    volumes[str(ssh_home)] = {"bind": ContainerPaths.ssh_dir(), "mode": "rw"}

            elif ssh_mode == "config":
                # Config mode: Mount only config/known_hosts for copying (no keys)
                if ssh_home.exists():
                    volumes[str(ssh_home)] = {"bind": ContainerPaths.HOST_SSH_MOUNT, "mode": "ro"}

        # SSH agent socket forwarding (works with all modes when enabled)
        ssh_sock_name = None
        if config.ssh_enabled and config.ssh_forward_agent:
            # Forward SSH agent socket (for passphrase-protected keys)
            # Mount the parent directory instead of the socket file directly to handle
            # socket file replacement when the SSH agent restarts.
            ssh_auth_sock = os.getenv("SSH_AUTH_SOCK")
            if ssh_auth_sock and Path(ssh_auth_sock).exists():
                ssh_sock_path = Path(ssh_auth_sock)
                ssh_sock_dir = ssh_sock_path.parent
                ssh_sock_name = ssh_sock_path.name
                # Mount the directory containing the socket
                volumes[str(ssh_sock_dir)] = {"bind": "/ssh-agent-dir", "mode": "ro"}
            else:
                console.print("[yellow]Warning: SSH agent forwarding enabled but SSH_AUTH_SOCK not found[/yellow]")

        # Add MCP-specific mounts from mcp-meta.json
        for mount in mcp_mounts:
            volumes[mount["host"]] = {"bind": mount["container"], "mode": mount["mode"]}

        # Clean up any stale symlink in project dir (legacy from previous approach)
        project_credentials_link = project_claude_dir / ".credentials.json"
        if project_credentials_link.is_symlink():
            project_credentials_link.unlink()

        # Host Claude client state file (.claude.json in home dir)
        # This file is in the home directory root. Unlike credentials, it changes infrequently
        # (mainly settings and telemetry), so a file mount is acceptable here despite the
        # stale inode limitation. The critical OAuth tokens are in .credentials.json which
        # is accessed via the directory mount above.
        # Note: Must be read-write as Claude updates this file with session state.
        host_claude_state = Path.home() / ".claude.json"
        if host_claude_state.exists():
            volumes[str(host_claude_state)] = {"bind": f"/{username}/claude.json", "mode": "rw"}

        # Notify socket is exposed via the runtime dir mount; container-init links it.

        # Optional OpenAI/Gemini configs for CLI auth (already directories)
        if host_openai_config_dir.exists():
            volumes[str(host_openai_config_dir)] = {"bind": ContainerPaths.host_openai_mount(username), "mode": "rw"}
        if host_gemini_dir.exists():
            volumes[str(host_gemini_dir)] = {"bind": ContainerPaths.host_gemini_mount(username), "mode": "rw"}
        if host_qwen_dir.exists():
            volumes[str(host_qwen_dir)] = {"bind": ContainerPaths.host_qwen_mount(username), "mode": "rw"}

        # GitHub CLI config (gh) - mount if enabled in config and exists
        if config.gh_enabled and host_gh_config_dir.exists():
            volumes[str(host_gh_config_dir)] = {"bind": ContainerPaths.host_gh_mount(username), "mode": "ro"}

        # GitLab CLI config (glab) - mount if enabled in config and exists
        if config.glab_enabled and host_glab_config_dir.exists():
            volumes[str(host_glab_config_dir)] = {"bind": ContainerPaths.host_glab_mount(username), "mode": "ro"}

        # Extra user-defined workspace mounts from .agentbox/config.yml
        for entry in config.workspaces:
            if not isinstance(entry, dict):
                continue
            host_path = entry.get("path")
            mount_name = entry.get("mount")
            mode = entry.get("mode", "ro")
            if not host_path or not mount_name:
                continue
            if mode not in ("ro", "rw"):
                mode = "ro"
            # Expand ~ in path
            abs_path = Path(host_path).expanduser().absolute()
            # Skip if this is the project directory (already mounted at /workspace)
            if abs_path == project_dir.absolute():
                console.print(f"[yellow]Warning: skipping workspace mount for project directory[/yellow]")
                continue
            if not abs_path.exists():
                console.print(f"[yellow]Warning: mount path not found: {host_path}[/yellow]")
                continue
            mount_point = f"/context/{mount_name}"
            volumes[str(abs_path)] = {"bind": mount_point, "mode": mode}

        # Docker socket mount (if enabled)
        if config.docker_enabled and Path(HostPaths.DOCKER_SOCKET).exists():
            volumes[HostPaths.DOCKER_SOCKET] = {"bind": HostPaths.DOCKER_SOCKET, "mode": "rw"}

        # Environment variables
        environment = {
            "USER": username,  # Pass username for container scripts
            "HOST_UID": str(host_uid),
            "HOST_GID": str(host_gid),
            "GIT_AUTHOR_NAME": git_author_name,
            "GIT_AUTHOR_EMAIL": git_author_email,
            "GIT_COMMITTER_NAME": git_author_name,
            "GIT_COMMITTER_EMAIL": git_author_email,
            "DBUS_SESSION_BUS_ADDRESS": dbus_address,
            "DISPLAY": display,
            "SSH_MODE": ssh_mode,
            "SSH_ENABLED": str(config.ssh_enabled).lower(),
        }

        # Set SSH_AUTH_SOCK if agent forwarding is enabled
        # Point to the socket file inside the mounted directory
        if config.ssh_enabled and config.ssh_forward_agent and ssh_sock_name:
            environment["SSH_AUTH_SOCK"] = f"/ssh-agent-dir/{ssh_sock_name}"

        console.print(f"[green]Creating container {container_name}...[/green]")

        # Build security options from config
        security_opt = []
        security_config = config.security
        seccomp = security_config.get("seccomp", "unconfined")
        if seccomp:
            security_opt.append(f"seccomp={seccomp}")

        # Build additional container options
        container_kwargs = {
            "image": self.BASE_IMAGE,
            "name": container_name,
            "hostname": container_name,
            "volumes": volumes,
            "environment": environment,
            "detach": True,
            "tty": True,
            "stdin_open": True,
            "working_dir": ContainerPaths.WORKSPACE,
            "init": True,  # Enable init process to handle zombie processes (needed for Chrome/Playwright)
        }

        if security_opt:
            container_kwargs["security_opt"] = security_opt

        # Add resource limits if configured
        resources_config = config.resources
        if resources_config.get("memory"):
            container_kwargs["mem_limit"] = resources_config["memory"]
        if resources_config.get("cpus"):
            container_kwargs["nano_cpus"] = int(float(resources_config["cpus"]) * 1e9)

        # Add capabilities if configured
        capabilities = security_config.get("capabilities", [])
        if capabilities:
            container_kwargs["cap_add"] = capabilities

        # Add device mappings if configured (validate devices exist)
        devices = config.devices
        if devices:
            valid_devices = []
            for device in devices:
                device_path = Path(device.split(":")[0])  # Handle host:container format
                if device_path.exists():
                    valid_devices.append(device)
                else:
                    console.print(f"[yellow]Warning: Device not found, skipping: {device}[/yellow]")
            if valid_devices:
                container_kwargs["devices"] = valid_devices

        # Add port mappings if configured and mode is docker/auto
        # In tunnel mode, ports are exposed dynamically via agentboxd
        if config.ports_host and config.ports_mode in ("docker", "auto"):
            ports = {}
            for port_mapping in config.ports_host:
                # Support formats:
                # - "8080" -> bind 8080 to all interfaces
                # - "3000:8080" -> bind container 8080 to host 3000 on all interfaces
                # - "127.0.0.1:8080:8080" -> bind container 8080 to 127.0.0.1:8080 on host
                try:
                    parts = port_mapping.split(":")

                    if len(parts) == 3:
                        # Format: host_ip:host_port:container_port
                        host_ip, host_port, container_port = parts
                        ports[f"{container_port}/tcp"] = (host_ip, int(host_port))
                    elif len(parts) == 2:
                        # Format: host_port:container_port
                        host_port, container_port = parts
                        ports[f"{container_port}/tcp"] = int(host_port)
                    else:
                        # Format: port (same on host and container)
                        ports[f"{port_mapping}/tcp"] = int(port_mapping)
                except ValueError:
                    console.print(f"[red]Error: Invalid port mapping '{port_mapping}'[/red]")
                    raise ConfigError(f"Invalid port mapping: {port_mapping}")

            container_kwargs["ports"] = ports

        try:
            container = self.client.containers.run(**container_kwargs)

            console.print(f"[green]Container {container_name} created successfully[/green]")

            # Restore container network connections from .agentbox/config.yml
            for conn in config.containers:
                if not conn.get("auto_reconnect", True):
                    continue

                target_name = conn.get("name")
                if not target_name:
                    continue

                # Get networks from target container
                try:
                    target = self.client.containers.get(target_name)
                    if target.status == "running":
                        networks = list(target.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
                        for network in networks:
                            try:
                                net = self.client.networks.get(network)
                                # Check if already connected
                                current_networks = self.get_container_networks(container_name)
                                if network not in current_networks:
                                    net.connect(container)
                                    console.print(f"[blue]Connected to {target_name} network: {network}[/blue]")
                            except Exception as e:
                                console.print(f"[yellow]Warning: Could not connect to network {network}: {e}[/yellow]")
                except Exception:
                    console.print(f"[yellow]Warning: Container {target_name} not found or not running[/yellow]")

            invalidate_container_cache()
            return container

        except docker.errors.ImageNotFound:
            console.print(f"[red]Error: Base image {self.BASE_IMAGE} not found[/red]")
            console.print("[yellow]Please build the base image first:[/yellow]")
            console.print(f"  docker build -f Dockerfile.base -t {self.BASE_IMAGE} .")
            raise
        except docker.errors.APIError as e:
            console.print(f"[red]Error creating container: {e}[/red]")
            raise

    def start_container(self, container_name: str) -> None:
        """Start a stopped container.

        Args:
            container_name: Full container name
        """
        container = self.get_container(container_name)
        if container is None:
            console.print(f"[red]Container {container_name} not found[/red]")
            return

        if container.status == "running":
            console.print(f"[yellow]Container {container_name} is already running[/yellow]")
            return

        console.print(f"[blue]Starting container {container_name}...[/blue]")
        container.start()
        invalidate_container_cache()
        console.print(f"[green]Container {container_name} started[/green]")

    def stop_container(self, container_name: str) -> None:
        """Stop a running container.

        Args:
            container_name: Full container name
        """
        container = self.get_container(container_name)
        if container is None:
            console.print(f"[red]Container {container_name} not found[/red]")
            return

        if container.status != "running":
            console.print(f"[yellow]Container {container_name} is not running[/yellow]")
            return

        # Reset terminal before stopping to disable mouse mode
        reset_terminal()

        console.print(f"[blue]Stopping container {container_name}...[/blue]")
        container.stop()
        invalidate_container_cache()
        console.print(f"[green]Container {container_name} stopped[/green]")

    def remove_container(self, container_name: str, force: bool = False) -> None:
        """Remove a container.

        Args:
            container_name: Full container name
            force: Force remove running container (kills immediately without graceful stop)
        """
        container = self.get_container(container_name)
        if container is None:
            console.print(f"[red]Container {container_name} not found[/red]")
            return

        # Reset terminal before removing to disable mouse mode
        reset_terminal()

        # Stop container gracefully if it's running (unless force is specified)
        if container.status == "running" and not force:
            console.print(f"[blue]Stopping container {container_name}...[/blue]")
            container.stop()

        console.print(f"[blue]Removing container {container_name}...[/blue]")
        container.remove(force=force)
        invalidate_container_cache()
        console.print(f"[green]Container {container_name} removed[/green]")

    def list_containers(self, all_containers: bool = False) -> List[Dict[str, str]]:
        """List Agentbox containers.

        Args:
            all_containers: Include stopped containers

        Returns:
            List of container info dicts
        """
        cache_key = _CACHE_KEY_ALL if all_containers else _CACHE_KEY_RUNNING

        # Lock covers both check AND fetch to prevent race conditions
        with _container_cache_lock:
            # Check cache first
            if cache_key in _container_cache:
                if time.time() - _container_cache_time.get(cache_key, 0) < _CONTAINER_CACHE_TTL:
                    # Deep copy to prevent caller mutation of cached data
                    return [d.copy() for d in _container_cache[cache_key]]

            # Fetch fresh data
            result = self._list_containers_impl(all_containers)
            _container_cache[cache_key] = result
            _container_cache_time[cache_key] = time.time()
            # Deep copy to prevent caller mutation of cached data
            return [d.copy() for d in result]

    def _list_containers_impl(self, all_containers: bool = False) -> List[Dict[str, str]]:
        """Internal implementation of list_containers (uncached)."""
        filters = {"name": self.CONTAINER_PREFIX}
        containers = self.client.containers.list(all=all_containers, filters=filters)

        result = []
        for container in containers:
            # Extract project name from container name
            project_name = container.name.replace(self.CONTAINER_PREFIX, "")

            # Get runtime directory to find original project path
            runtime_dir = self.get_runtime_dir(project_name)

            # Get project path from /workspace mount
            project_path = None
            mounts = container.attrs.get("Mounts", [])
            for mount in mounts:
                if mount.get("Destination") == ContainerPaths.WORKSPACE:
                    project_path = mount.get("Source")
                    break

            result.append({
                "name": container.name,
                "project": project_name,
                "status": container.status,
                "runtime_dir": str(runtime_dir),
                "project_path": project_path,
            })

        return result

    def print_containers_table(self, all_containers: bool = False) -> None:
        """Print a formatted table of containers.

        Args:
            all_containers: Include stopped containers
        """
        containers = self.list_containers(all_containers=all_containers)

        if not containers:
            console.print("[yellow]No Agentbox containers found[/yellow]")
            return

        table = Table(title="Agentbox Containers")
        table.add_column("Container", style="cyan")
        table.add_column("Project", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Runtime Dir", style="blue")

        for container in containers:
            status_color = "green" if container["status"] == "running" else "yellow"
            table.add_row(
                container["name"],
                container["project"],
                f"[{status_color}]{container['status']}[/{status_color}]",
                container["runtime_dir"],
            )

        console.print(table)

    def exec_command(
        self,
        container_name: str,
        command: List[str],
        workdir: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
    ) -> tuple[int, str]:
        """Execute a command in container.

        Args:
            container_name: Full container name
            command: Command and arguments as list
            workdir: Working directory for command
            environment: Environment variables

        Returns:
            Tuple of (exit_code, output)
        """
        container = self.get_container(container_name)
        if container is None:
            console.print(f"[red]Container {container_name} not found[/red]")
            return 1, ""

        if container.status != "running":
            console.print(f"[red]Container {container_name} is not running[/red]")
            return 1, ""

        exec_result = container.exec_run(
            command,
            workdir=workdir,
            environment=environment,
            user=user,
            stream=False,
            demux=False,
        )

        output = exec_result.output or b""
        return exec_result.exit_code, output.decode("utf-8", errors="replace")

    def wait_for_user(
        self,
        container_name: str,
        username: str,
        timeout_s: float = 6.0,
        interval_s: float = 0.25,
    ) -> bool:
        """Wait for a user to exist in the container."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            container = self.get_container(container_name)
            if container is None or container.status != "running":
                return False
            try:
                exec_result = container.exec_run(
                    ["getent", "passwd", username],
                    user="root",
                    stream=False,
                    demux=False,
                )
            except docker.errors.APIError:
                exec_result = None

            if exec_result and exec_result.exit_code == 0 and exec_result.output:
                return True

            time.sleep(interval_s)
        return False

    def get_container_init_status(self, container_name: str) -> tuple[str, str]:
        """Read the container's initialization status file.

        Returns:
            Tuple of (phase, details). Returns ("unknown", "") if status unavailable.
        """
        try:
            container = self.get_container(container_name)
            if container is None:
                return ("unknown", "")

            result = container.exec_run(
                ["cat", ContainerPaths.STATUS_FILE],
                user="root",
            )
            if result.exit_code == 0:
                output = result.output.decode("utf-8").strip()
                if "|" in output:
                    phase, details = output.split("|", 1)
                    return (phase, details)
                return (output, "")
        except Exception:
            pass
        return ("unknown", "")

    def wait_for_ready(
        self,
        container_name: str,
        timeout_s: float = 90.0,
        interval_s: float = 1.0,
        status_callback: Callable[[str, str], None] | None = None,
    ) -> bool:
        """Wait for container to pass health check (initialization complete).

        Uses Docker's native HEALTHCHECK status to determine when the container
        has completed initialization including MCP package installation.

        Args:
            container_name: Full container name
            timeout_s: Maximum time to wait (default 90s for MCP installs)
            interval_s: Polling interval in seconds
            status_callback: Optional callback called with (phase, details) on status changes

        Returns:
            True if container is healthy, False if timeout/error/unhealthy
        """
        deadline = time.time() + timeout_s
        last_health_status = None
        last_init_phase = None

        while time.time() < deadline:
            container = self.get_container(container_name)

            # Container must be running
            if container is None or container.status != "running":
                return False

            # Refresh container state to get latest health status
            container.reload()

            # Get health status from Docker
            health = container.attrs.get("State", {}).get("Health", {})
            health_status = health.get("Status", "none")

            # Read init status from container
            init_phase, init_details = self.get_container_init_status(container_name)

            # Call status callback if phase changed
            if status_callback and init_phase != last_init_phase:
                last_init_phase = init_phase
                status_callback(init_phase, init_details)

            # Track health status changes
            if health_status != last_health_status:
                last_health_status = health_status

            # Check health status
            if health_status == "healthy":
                return True
            elif health_status == "unhealthy":
                # Container failed health check permanently
                return False
            # "starting" or "none" - continue waiting

            time.sleep(interval_s)

        # Timeout reached
        return False

    def cleanup_stopped(self) -> None:
        """Remove all stopped Agentbox containers."""
        containers = self.list_containers(all_containers=True)
        stopped = [c for c in containers if c["status"] != "running"]

        if not stopped:
            console.print("[yellow]No stopped containers to clean up[/yellow]")
            return

        console.print(f"[blue]Found {len(stopped)} stopped container(s)[/blue]")
        for container in stopped:
            self.remove_container(container["name"])

    def get_all_containers(self, include_agentbox: bool = False) -> List[Dict[str, Any]]:
        """List all running Docker containers.

        Args:
            include_agentbox: Include Agentbox containers in results

        Returns:
            List of dicts with container info: name, id, image, networks, ports, status
        """
        containers = self.client.containers.list(all=False)

        result = []
        for container in containers:
            # Skip Agentbox containers unless requested
            if not include_agentbox and container.name.startswith(self.CONTAINER_PREFIX):
                continue

            # Get network info
            networks = list(container.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())

            # Get port info
            ports = []
            port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            if port_bindings:
                for port_key in port_bindings.keys():
                    # Extract just the port number (e.g., "5432/tcp" -> "5432")
                    port_num = port_key.split("/")[0] if "/" in port_key else port_key
                    ports.append(port_num)

            result.append({
                "name": container.name,
                "id": container.id[:12],
                "image": container.image.tags[0] if container.image.tags else container.image.id[:12],
                "networks": networks,
                "ports": ports,
                "status": container.status,
            })

        return result

    def get_container_networks(self, container_name: str) -> List[str]:
        """Get list of network names a container is connected to.

        Args:
            container_name: Target container name

        Returns:
            List of network names
        """
        try:
            container = self.client.containers.get(container_name)
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            return list(networks.keys())
        except docker.errors.NotFound:
            return []

    def connect_to_networks(self, container_name: str, networks: List[str]) -> None:
        """Connect a container to one or more Docker networks.

        Args:
            container_name: Container to connect
            networks: List of network names to join

        Raises:
            docker.errors.NotFound: If container or network doesn't exist
            docker.errors.APIError: If connection fails
        """
        container = self.client.containers.get(container_name)
        # Fetch current networks once before the loop
        current_networks = set(self.get_container_networks(container_name))

        for network_name in networks:
            try:
                network = self.client.networks.get(network_name)
                # Check if already connected
                if network_name not in current_networks:
                    network.connect(container)
                    current_networks.add(network_name)
            except docker.errors.APIError as e:
                # If already connected, that's fine
                if "already exists" not in str(e).lower():
                    raise

    def disconnect_from_networks(self, container_name: str, networks: List[str]) -> None:
        """Disconnect a container from networks.

        Args:
            container_name: Container to disconnect
            networks: Networks to leave
        """
        container = self.client.containers.get(container_name)

        for network_name in networks:
            try:
                network = self.client.networks.get(network_name)
                network.disconnect(container)
            except docker.errors.APIError:
                # If not connected or other error, continue
                pass
