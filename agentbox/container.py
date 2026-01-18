# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Container lifecycle management for Agentbox."""

import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, List

import docker
from docker.models.containers import Container
from rich.console import Console
from rich.table import Table

console = Console()


class ContainerManager:
    """Manages Agentbox Docker containers."""

    BASE_IMAGE = "agentbox-base:latest"
    CONTAINER_PREFIX = "agentbox-"
    AGENTBOX_DIR = Path("/x/coding/agentbox")

    def __init__(self):
        """Initialize Docker client."""
        try:
            self.client = docker.from_env()
        except docker.errors.DockerException as e:
            console.print(f"[red]Error: Could not connect to Docker: {e}[/red]")
            raise

    def sanitize_project_name(self, name: str) -> str:
        """Sanitize project name for Docker container naming.

        Args:
            name: Project directory name

        Returns:
            Sanitized name safe for Docker
        """
        # Convert to lowercase, replace invalid chars with hyphens
        sanitized = re.sub(r'[^a-z0-9_-]', '-', name.lower())
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip('-')
        return sanitized

    def get_project_name(self, project_dir: Optional[Path] = None) -> str:
        """Get sanitized project name from directory.

        Args:
            project_dir: Project directory path (defaults to current dir)

        Returns:
            Sanitized project name
        """
        if project_dir is None:
            # Check for environment variable set by wrapper script
            env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
            if env_project_dir:
                project_dir = Path(env_project_dir)
            else:
                project_dir = Path.cwd()
        return self.sanitize_project_name(project_dir.name)

    def get_container_name(self, project_name: str) -> str:
        """Get container name from project name.

        Args:
            project_name: Sanitized project name

        Returns:
            Full container name with prefix
        """
        return f"{self.CONTAINER_PREFIX}{project_name}"

    def _project_uses_docker_mcp(self, project_dir: Path) -> bool:
        config_path = project_dir / ".agentbox" / "config.json"
        if not config_path.exists():
            return False
        try:
            data = json.loads(config_path.read_text())
        except Exception:
            return False
        mcp_servers = data.get("mcpServers", {})
        return isinstance(mcp_servers, dict) and "docker" in mcp_servers

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

    def is_running(self, container_name: str) -> bool:
        """Check if container is running.

        Args:
            container_name: Full container name

        Returns:
            True if container is running
        """
        container = self.get_container(container_name)
        return container is not None and container.status == "running"

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

        container_name = self.get_container_name(project_name)

        # Check if container already exists
        if self.container_exists(container_name):
            console.print(f"[yellow]Container {container_name} already exists[/yellow]")
            container = self.get_container(container_name)
            if not self.is_running(container_name):
                console.print(f"[blue]Starting existing container...[/blue]")
                container.start()
            return container

        # Ensure .agentbox/state directory exists in project
        # Note: state is no longer mounted when host ~/.claude is mounted directly.
        agentbox_dir = project_dir / ".agentbox"
        state_dir = agentbox_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        # Get user environment variables
        username = os.getenv("USER", "user")
        host_uid = os.getuid()
        host_gid = os.getgid()
        git_author_name = os.getenv("GIT_AUTHOR_NAME", "Marc")
        git_author_email = os.getenv("GIT_AUTHOR_EMAIL", "marc@schuetze.io")
        display = os.getenv("DISPLAY", ":0")
        runtime_dir = f"/run/user/{os.getuid()}"
        dbus_address = f"unix:path={runtime_dir}/bus"

        # Prepare volume mounts
        # Mount host config dirs for optional auth/state bootstrap
        host_claude_dir = Path.home() / ".claude"
        host_openai_config_dir = Path.home() / ".config" / "openai"
        host_codex_dir = Path.home() / ".codex"
        host_gemini_config_dir = Path.home() / ".config" / "gemini"
        docker_enabled = self._project_uses_docker_mcp(project_dir)

        volumes = {
            # Project workspace (read/write)
            str(project_dir.absolute()): {"bind": "/workspace", "mode": "rw"},
            # User's SSH keys for git operations (read-only)
            str(Path.home() / ".ssh"): {"bind": f"/{username}/ssh", "mode": "ro"},
            # Host Claude directory for bootstrap (read-only)
            str(host_claude_dir): {"bind": f"/{username}/claude", "mode": "ro"},
            # Agentbox global library (templates, read-only)
            str(self.AGENTBOX_DIR / "library" / "config"): {"bind": "/agentbox/library/config", "mode": "ro"},
            str(self.AGENTBOX_DIR / "library" / "mcp"): {"bind": "/agentbox/library/mcp", "mode": "ro"},
            str(self.AGENTBOX_DIR / "library" / "skills"): {"bind": "/agentbox/library/skills", "mode": "ro"},
            # Runtime directory for notifications (read-only)
            runtime_dir: {"bind": runtime_dir, "mode": "ro"},
        }
        if docker_enabled and Path("/var/run/docker.sock").exists():
            volumes["/var/run/docker.sock"] = {"bind": "/var/run/docker.sock", "mode": "rw"}
        # Optional host Claude client state file
        host_claude_state = Path.home() / ".claude.json"
        if host_claude_state.exists():
            volumes[str(host_claude_state)] = {"bind": f"/{username}/claude.json", "mode": "ro"}

        # Notify socket is exposed via the runtime dir mount; container-init links it.

        # Optional OpenAI/Gemini configs for CLI auth
        if host_openai_config_dir.exists():
            volumes[str(host_openai_config_dir)] = {"bind": f"/{username}/openai-config", "mode": "ro"}
        if host_gemini_config_dir.exists():
            volumes[str(host_gemini_config_dir)] = {"bind": f"/{username}/gemini-config", "mode": "ro"}
        if host_codex_dir.exists():
            volumes[str(host_codex_dir)] = {"bind": f"/{username}/codex", "mode": "ro"}

        # Extra user-defined mounts from project config
        volumes_config = project_dir / ".agentbox" / "volumes.json"
        if volumes_config.exists():
            try:
                import json

                data = json.loads(volumes_config.read_text())
                extra = data.get("volumes", [])
                for entry in extra:
                    if not isinstance(entry, dict):
                        continue
                    host_path = entry.get("path")
                    mount_name = entry.get("mount")
                    mode = entry.get("mode", "ro")
                    if not host_path or not mount_name:
                        continue
                    if mode not in ("ro", "rw"):
                        mode = "ro"
                    if not Path(host_path).exists():
                        console.print(f"[yellow]Warning: mount path not found: {host_path}[/yellow]")
                        continue
                    mount_point = f"/context/{mount_name}"
                    volumes[str(Path(host_path).absolute())] = {"bind": mount_point, "mode": mode}
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to load volumes.json: {e}[/yellow]")

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
        }

        console.print(f"[green]Creating container {container_name}...[/green]")

        try:
            container = self.client.containers.run(
                self.BASE_IMAGE,
                name=container_name,
                hostname=container_name,
                volumes=volumes,
                environment=environment,
                detach=True,
                tty=True,
                stdin_open=True,
                working_dir="/workspace",
                security_opt=["seccomp=unconfined"],
            )

            console.print(f"[green]Container {container_name} created successfully[/green]")
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

        console.print(f"[blue]Stopping container {container_name}...[/blue]")
        container.stop()
        console.print(f"[green]Container {container_name} stopped[/green]")

    def remove_container(self, container_name: str, force: bool = False) -> None:
        """Remove a container.

        Args:
            container_name: Full container name
            force: Force remove running container
        """
        container = self.get_container(container_name)
        if container is None:
            console.print(f"[red]Container {container_name} not found[/red]")
            return

        console.print(f"[blue]Removing container {container_name}...[/blue]")
        container.remove(force=force)
        console.print(f"[green]Container {container_name} removed[/green]")

    def list_containers(self, all_containers: bool = False) -> List[Dict[str, str]]:
        """List Agentbox containers.

        Args:
            all_containers: Include stopped containers

        Returns:
            List of container info dicts
        """
        filters = {"name": self.CONTAINER_PREFIX}
        containers = self.client.containers.list(all=all_containers, filters=filters)

        result = []
        for container in containers:
            # Extract project name from container name
            project_name = container.name.replace(self.CONTAINER_PREFIX, "")

            # Get runtime directory to find original project path
            runtime_dir = self.get_runtime_dir(project_name)

            result.append({
                "name": container.name,
                "project": project_name,
                "status": container.status,
                "runtime_dir": str(runtime_dir),
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

        return exec_result.exit_code, exec_result.output.decode("utf-8")

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