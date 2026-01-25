# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Configuration management for Agentbox projects."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml
from pydantic import ValidationError
from rich.console import Console

from agentbox import __version__ as AGENTBOX_VERSION
from agentbox.paths import ProjectPaths
from agentbox.models.project_config import (
    ProjectConfigModel,
    ContainerConnection,
    CredentialsConfig,
    DockerConfigModel,
    PackagesConfig,
    PortsConfig,
    SSHConfig,
    StallDetectionConfig,
    TaskAgentsConfig,
    WorkspaceMount,
    VALID_PACKAGE_PATTERN,
)

console = Console()


def validate_package_name(name: str) -> bool:
    """Validate a package name is safe for shell execution.

    Args:
        name: Package name to validate

    Returns:
        True if valid, False if potentially dangerous
    """
    if not name or len(name) > 200:
        return False
    return VALID_PACKAGE_PATTERN.match(name) is not None


def validate_host_port(port: int) -> None:
    """Validate a host port number.

    Args:
        port: Port number to validate

    Raises:
        ValueError: If port is invalid or privileged
    """
    if port < 1024:
        raise ValueError(f"Port {port} requires root privileges. Use ports >= 1024.")
    if port > 65535:
        raise ValueError(f"Port {port} is invalid. Must be between 1024 and 65535.")


def parse_port_spec(spec: str) -> Dict[str, Any]:
    """Parse a port specification string.

    Formats:
    - "3000" -> host:3000, container:3000
    - "8080:3000" -> host:8080, container:3000

    Args:
        spec: Port specification string

    Returns:
        Dict with host_port and container_port

    Raises:
        ValueError: If format is invalid
    """
    parts = spec.split(":")
    if len(parts) == 1:
        port = int(parts[0])
        return {"host_port": port, "container_port": port}
    elif len(parts) == 2:
        host_port = int(parts[0])
        container_port = int(parts[1])
        return {"host_port": host_port, "container_port": container_port}
    else:
        raise ValueError(f"Invalid port format: {spec}. Use 'port' or 'host:container'")


class ConfigValidationError(Exception):
    """Raised when config validation fails."""
    pass


class ProjectConfig:
    """Manages agentbox configuration for projects.

    Config location: .agentbox/config.yml
    Uses Pydantic model as single source of truth. No fallback to raw dict.
    """

    # Config path inside .agentbox directory
    CONFIG_PATH = f"{ProjectPaths.AGENTBOX_DIR_NAME}/{ProjectPaths.CONFIG_NAME}"
    SUPPORTED_VERSION = "1.0"

    def __init__(self, project_dir: Optional[Path] = None):
        """Initialize config manager.

        Args:
            project_dir: Project directory (defaults to current dir)
        """
        if project_dir is None:
            env_project_dir = os.getenv("AGENTBOX_PROJECT_DIR")
            if env_project_dir:
                project_dir = Path(env_project_dir)
            else:
                project_dir = Path.cwd()
        self.project_dir = project_dir
        self.config_path = ProjectPaths.config_file(project_dir)
        self._model: Optional[ProjectConfigModel] = None
        self._load()

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_path.exists()

    def _load(self) -> None:
        """Load configuration from file.

        Raises:
            ConfigValidationError: If config is invalid
        """
        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, "r") as f:
                raw_config = yaml.safe_load(f) or {}

            # Validate version
            version = raw_config.get("version")
            if version != self.SUPPORTED_VERSION:
                console.print(
                    f"[yellow]Warning: Config version {version}, expected {self.SUPPORTED_VERSION}[/yellow]"
                )

            # Parse with Pydantic - fail on validation errors
            self._model = ProjectConfigModel.model_validate(raw_config)

        except ValidationError as e:
            error_details = []
            for error in e.errors():
                loc = ".".join(str(x) for x in error["loc"])
                error_details.append(f"  {loc}: {error['msg']}")
            error_msg = "\n".join(error_details)
            raise ConfigValidationError(
                f"Invalid config in {self.config_path}:\n{error_msg}\n\n"
                "Fix the errors above or delete the file to start fresh."
            )
        except yaml.YAMLError as e:
            raise ConfigValidationError(f"YAML parse error in {self.config_path}: {e}")

    def save(self, quiet: bool = False) -> None:
        """Save configuration to file."""
        if self._model is None:
            raise ConfigValidationError("No config model to save")

        try:
            # Ensure parent directory exists (for new .agentbox/ location)
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Use model as source of truth
            data = self._model.model_dump(exclude_none=True)
            with open(self.config_path, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
            if not quiet:
                console.print(f"[green]Config saved to {self.config_path}[/green]")
        except Exception as e:
            console.print(f"[red]Error saving config: {e}[/red]")
            raise

    def _ensure_model(self) -> ProjectConfigModel:
        """Ensure model exists, create default if needed."""
        if self._model is None:
            self._model = ProjectConfigModel()
        return self._model

    @property
    def config(self) -> Dict[str, Any]:
        """Get config as dict (for compatibility with code that reads config.config).

        Returns model data as dict. For writes, use the property setters instead.
        """
        if self._model is None:
            return {}
        return self._model.model_dump(exclude_none=True)

    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        """Set config from dict (for compatibility).

        Validates and loads the dict into the model.
        """
        self._model = ProjectConfigModel.model_validate(value)

    # -------------------------------------------------------------------------
    # Properties - all read from _model directly
    # -------------------------------------------------------------------------

    @property
    def agentbox_version(self) -> Optional[str]:
        """Get the agentbox version that created/last updated this config."""
        return self._model.agentbox_version if self._model else None

    @agentbox_version.setter
    def agentbox_version(self, value: str) -> None:
        """Set the agentbox version."""
        self._ensure_model().agentbox_version = value

    def is_version_outdated(self) -> bool:
        """Check if the config was created with an older agentbox version."""
        stored_version = self.agentbox_version
        if stored_version is None:
            return False
        return stored_version != AGENTBOX_VERSION

    @property
    def system_packages(self) -> List[str]:
        """Get list of system packages to install."""
        return self._model.system_packages if self._model else []

    @property
    def mcp_servers(self) -> List[str]:
        """Get list of MCP servers to enable."""
        return self._model.mcp_servers if self._model else []

    @property
    def skills(self) -> List[str]:
        """Get list of skills to enable."""
        return self._model.skills if self._model else []

    @property
    def hostname(self) -> Optional[str]:
        """Get hostname alias for /etc/hosts."""
        return self._model.hostname if self._model else None

    @property
    def environment(self) -> Dict[str, str]:
        """Get environment variables."""
        return self._model.env if self._model else {}

    @property
    def ports(self) -> Dict[str, Any]:
        """Get unified port configuration."""
        if not self._model:
            return {"host": [], "container": [], "mode": "tunnel"}

        ports = self._model.ports
        if isinstance(ports, PortsConfig):
            return {
                "host": ports.host,
                "container": ports.container,
                "mode": ports.mode,
            }
        # Old format (list) - shouldn't happen with model validation
        return {"host": ports, "container": [], "mode": "tunnel"}

    @ports.setter
    def ports(self, value: Dict[str, Any]) -> None:
        """Set port configuration."""
        model = self._ensure_model()
        model.ports = PortsConfig.model_validate(value)

    @property
    def ports_host(self) -> List[str]:
        """Get host-exposed ports (container -> host)."""
        return self.ports.get("host", [])

    @property
    def ports_container(self) -> List[Dict[str, Any]]:
        """Get container-forwarded ports (host -> container)."""
        return self.ports.get("container", [])

    @property
    def ports_mode(self) -> str:
        """Get port forwarding mode."""
        if not self._model:
            return "tunnel"
        ports = self._model.ports
        if isinstance(ports, PortsConfig):
            return ports.mode
        return "tunnel"

    @property
    def ssh_enabled(self) -> bool:
        """Get SSH enabled setting."""
        return self._model.ssh.enabled if self._model else True

    @property
    def ssh_mode(self) -> str:
        """Get SSH mode: none, keys, mount, config."""
        return self._model.ssh.mode if self._model else "keys"

    @ssh_mode.setter
    def ssh_mode(self, value: str) -> None:
        """Set SSH mode."""
        self._ensure_model().ssh.mode = value

    @property
    def ssh_forward_agent(self) -> bool:
        """Get SSH agent forwarding setting."""
        return self._model.ssh.forward_agent if self._model else False

    @ssh_forward_agent.setter
    def ssh_forward_agent(self, value: bool) -> None:
        """Set SSH agent forwarding."""
        self._ensure_model().ssh.forward_agent = value

    @property
    def workspaces(self) -> List[Dict[str, str]]:
        """Get workspace mounts."""
        if not self._model:
            return []
        return [w.model_dump() for w in self._model.workspaces]

    @workspaces.setter
    def workspaces(self, value: List[Dict[str, str]]) -> None:
        """Set workspace mounts."""
        model = self._ensure_model()
        model.workspaces = [WorkspaceMount.model_validate(w) for w in value]

    @property
    def containers(self) -> List[Dict[str, Any]]:
        """Get container connections."""
        if not self._model:
            return []
        return [c.model_dump() for c in self._model.containers]

    @containers.setter
    def containers(self, value: List[Dict[str, Any]]) -> None:
        """Set container connections."""
        model = self._ensure_model()
        model.containers = [ContainerConnection.model_validate(c) for c in value]

    @property
    def resources(self) -> Dict[str, str]:
        """Get container resource limits."""
        if not self._model:
            return {}
        return self._model.resources.model_dump(exclude_none=True)

    @property
    def security(self) -> Dict[str, Any]:
        """Get container security settings."""
        if not self._model:
            return {}
        return self._model.security.model_dump()

    @property
    def devices(self) -> List[str]:
        """Get device mappings for container."""
        return self._model.devices if self._model else []

    @devices.setter
    def devices(self, value: List[str]) -> None:
        """Set device mappings."""
        self._ensure_model().devices = value

    @property
    def task_agents(self) -> Dict[str, Any]:
        """Get task agent configuration for notification enhancement."""
        if not self._model:
            return TaskAgentsConfig().model_dump()
        return self._model.task_agents.model_dump()

    @task_agents.setter
    def task_agents(self, value: Dict[str, Any]) -> None:
        """Set task agent configuration."""
        model = self._ensure_model()
        model.task_agents = TaskAgentsConfig.model_validate(value)

    @property
    def stall_detection(self) -> Dict[str, Any]:
        """Get stall detection configuration."""
        if not self._model:
            return StallDetectionConfig().model_dump()
        return self._model.stall_detection.model_dump()

    @stall_detection.setter
    def stall_detection(self, value: Dict[str, Any]) -> None:
        """Set stall detection configuration."""
        model = self._ensure_model()
        model.stall_detection = StallDetectionConfig.model_validate(value)

    @property
    def packages(self) -> dict:
        """Get package installation configuration."""
        if not self._model:
            return PackagesConfig().model_dump()
        return self._model.packages.model_dump()

    @packages.setter
    def packages(self, value: dict) -> None:
        """Set package installation configuration."""
        model = self._ensure_model()
        model.packages = PackagesConfig.model_validate(value)

    @property
    def docker_enabled(self) -> bool:
        """Get docker socket enabled setting."""
        if not self._model or not self._model.docker:
            return False
        return self._model.docker.enabled

    @docker_enabled.setter
    def docker_enabled(self, value: bool) -> None:
        """Set docker socket enabled."""
        model = self._ensure_model()
        if model.docker is None:
            model.docker = DockerConfigModel(enabled=value)
        else:
            model.docker.enabled = value

    @property
    def gh_enabled(self) -> bool:
        """Get GitHub CLI (gh) credentials mount setting."""
        if not self._model:
            return False
        return self._model.credentials.gh

    @gh_enabled.setter
    def gh_enabled(self, value: bool) -> None:
        """Set GitHub CLI (gh) credentials mount."""
        self._ensure_model().credentials.gh = value

    @property
    def glab_enabled(self) -> bool:
        """Get GitLab CLI (glab) credentials mount setting."""
        if not self._model:
            return False
        return self._model.credentials.glab

    @glab_enabled.setter
    def glab_enabled(self, value: bool) -> None:
        """Set GitLab CLI (glab) credentials mount."""
        self._ensure_model().credentials.glab = value

    # -------------------------------------------------------------------------
    # Methods
    # -------------------------------------------------------------------------

    def rebuild(self, container_manager, container_name: str) -> None:
        """Rebuild container environment from config.

        Args:
            container_manager: ContainerManager instance
            container_name: Name of container to configure
        """
        if not self.exists():
            console.print(
                f"[yellow]No config found in {self.project_dir}[/yellow]"
            )
            return

        console.print(f"[blue]Rebuilding from {self.config_path}...[/blue]")

        # Install system packages
        if self.system_packages:
            # Validate all package names before execution
            invalid_packages = [p for p in self.system_packages if not validate_package_name(p)]
            if invalid_packages:
                console.print(f"[red]Invalid package names (skipping): {', '.join(invalid_packages)}[/red]")
                console.print("[yellow]Package names must be alphanumeric with ._+- allowed[/yellow]")

            valid_packages = [p for p in self.system_packages if validate_package_name(p)]
            if valid_packages:
                console.print(f"[blue]Installing system packages: {', '.join(valid_packages)}[/blue]")
                packages = " ".join(valid_packages)
                exit_code, output = container_manager.exec_command(
                    container_name,
                    ["sh", "-c", f"apt-get update && apt-get install -y {packages}"],
                )
                if exit_code != 0:
                    console.print(f"[red]Error installing packages: {output}[/red]")
                else:
                    console.print("[green]System packages installed[/green]")

        # Enable MCP servers
        if self.mcp_servers:
            console.print(f"[blue]Enabling MCP servers: {', '.join(self.mcp_servers)}[/blue]")
            console.print("[yellow]MCP server installation not yet implemented[/yellow]")

        # Enable skills
        if self.skills:
            console.print(f"[blue]Enabling skills: {', '.join(self.skills)}[/blue]")
            console.print("[yellow]Skill installation not yet implemented[/yellow]")

        # Set environment variables
        if self.environment:
            console.print(f"[blue]Setting environment variables[/blue]")
            console.print("[yellow]Environment variable persistence not yet implemented[/yellow]")

        # Set up hostname
        if self.hostname:
            console.print(f"[blue]Setting up hostname: {self.hostname}[/blue]")
            console.print("[yellow]Hostname configuration not yet implemented[/yellow]")

        console.print("[green]Rebuild complete[/green]")

    def create_template(self) -> None:
        """Create a template config.yml file in .agentbox/ directory."""
        if self.exists():
            console.print(f"[yellow]Config already exists at {self.config_path}[/yellow]")
            return

        # Ensure .agentbox directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy template from library
        from agentbox.library import LibraryManager
        lib = LibraryManager()
        template_path = lib.config_dir / "agentbox.yml.template"

        if template_path.exists():
            import shutil
            shutil.copy(template_path, self.config_path)
        else:
            # Fallback if template not found - use Pydantic model defaults
            self._model = ProjectConfigModel()
            self.save(quiet=True)

        # Reload to parse
        self._load()
        console.print(f"[green]Created template {self.CONFIG_PATH}[/green]")
        console.print("[blue]Edit the file and run 'abox rebuild' to apply changes[/blue]")
