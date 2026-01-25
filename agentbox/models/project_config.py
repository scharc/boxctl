# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Pydantic models for project configuration (.agentbox/config.yml)."""

import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Valid package name pattern for apt/npm/pip/cargo packages
# Allows version specifiers like ==, >=, @version, and extras like [dev]
# Examples: requests, requests==2.31.0, @scope/pkg, @scope/pkg@1.2.3, pkg[extra]
VALID_PACKAGE_PATTERN = re.compile(
    r'^(?:@[a-zA-Z0-9_-]+/)?'          # Optional npm scope like @scope/
    r'[a-zA-Z0-9][a-zA-Z0-9._+-]*'     # Package name
    r'(?:\[[a-zA-Z0-9,_-]+\])?'        # Optional extras like [dev,test]
    r'(?:[@=<>~!][a-zA-Z0-9._,<>=~!*+-]+)?$'  # Optional version specifier (requires chars after operator)
)


class SSHConfig(BaseModel):
    """SSH configuration for git operations.

    Modes:
        - none: No SSH setup
        - keys: Copy all SSH files including private keys (default)
        - mount: Direct bind mount of ~/.ssh (read-write)
        - config: Copy only config/known_hosts (use with forward_agent=True)

    forward_agent: Forward host's SSH agent socket into container.
                   Required when mode=config since no keys are copied.
    """

    enabled: bool = True
    mode: Literal["none", "keys", "mount", "config"] = "keys"
    forward_agent: bool = False


class WorkspaceMount(BaseModel):
    """Additional workspace mount configuration."""

    path: str
    mount: Optional[str] = None  # Mount point name under /context/
    mode: Literal["ro", "rw"] = "ro"


class ContainerConnection(BaseModel):
    """Docker container connection configuration."""

    name: str
    auto_reconnect: bool = True


class PortsConfig(BaseModel):
    """Port configuration for container."""

    host: List[str] = Field(default_factory=list)
    container: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    mode: Literal["tunnel", "docker", "auto"] = "tunnel"


class ResourcesConfig(BaseModel):
    """Container resource limits."""

    memory: Optional[str] = None  # e.g., "4g"
    cpus: Optional[float] = None  # e.g., 2.0


class SecurityConfig(BaseModel):
    """Container security settings."""

    seccomp: Optional[str] = "unconfined"
    capabilities: List[str] = Field(default_factory=list)


class TaskAgentsConfig(BaseModel):
    """Task agent configuration for notification enhancement.

    Model aliases (work with any agent):
        - fast: Quick responses (claude: haiku, codex: gpt-4o-mini)
        - balanced: Good quality (claude: sonnet, codex: gpt-4o)
        - powerful: Best quality (claude: opus, codex: o3)

    You can also use agent-specific model names directly.
    """

    enabled: bool = False
    agent: str = "claude"
    model: str = "fast"  # Use alias for cross-agent compatibility
    timeout: int = 30
    buffer_lines: int = 50
    enhance_hooks: bool = True
    enhance_stall: bool = True
    prompt_template: str = (
        "Analyze this terminal session output and provide a brief 1-2 sentence summary "
        "of what task was being worked on.\n\n"
        "Session: {session}\n"
        "Project: {project}\n\n"
        "Last {buffer_lines} lines of output:\n"
        "```\n{buffer}\n```\n\n"
        "Provide ONLY the summary, no preamble or explanation."
    )


class StallDetectionConfig(BaseModel):
    """Stall detection configuration."""

    enabled: bool = True
    threshold_seconds: float = 30.0


class DockerConfigModel(BaseModel):
    """Docker socket access configuration."""

    enabled: bool = False


class CredentialsConfig(BaseModel):
    """CLI credentials auto-mount configuration.

    Controls whether gh (GitHub CLI) and glab (GitLab CLI) credentials
    from the host are mounted into the container.

    Both default to False for security - users must opt-in to share credentials.
    """

    gh: bool = False  # Mount ~/.config/gh (GitHub CLI)
    glab: bool = False  # Mount ~/.config/glab-cli (GitLab CLI)


class PackagesConfig(BaseModel):
    """Package installation configuration."""

    npm: List[str] = Field(default_factory=list)
    pip: List[str] = Field(default_factory=list)
    apt: List[str] = Field(default_factory=list)
    cargo: List[str] = Field(default_factory=list)
    post: List[str] = Field(default_factory=list)

    @field_validator("npm", "pip", "apt", "cargo", mode="after")
    @classmethod
    def validate_package_names(cls, packages: List[str]) -> List[str]:
        """Validate package names are safe for shell execution."""
        for pkg in packages:
            if not pkg or len(pkg) > 200:
                raise ValueError(f"Invalid package name: {pkg}")
            if not VALID_PACKAGE_PATTERN.match(pkg):
                raise ValueError(
                    f"Invalid package name '{pkg}'. "
                    "Must be alphanumeric with ._+- allowed."
                )
        return packages


class ProjectConfigModel(BaseModel):
    """Main project configuration model for .agentbox.yml."""

    version: str = "1.0"
    agentbox_version: Optional[str] = None

    # SSH
    ssh: SSHConfig = Field(default_factory=SSHConfig)

    # Workspaces and containers
    workspaces: List[WorkspaceMount] = Field(default_factory=list)
    containers: List[ContainerConnection] = Field(default_factory=list)

    # Packages
    system_packages: List[str] = Field(default_factory=list)
    packages: PackagesConfig = Field(default_factory=PackagesConfig)

    # Environment
    env: Dict[str, str] = Field(default_factory=dict)
    hostname: Optional[str] = None

    # Resources and security
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    devices: List[str] = Field(default_factory=list)

    # Ports
    ports: Union[PortsConfig, List[str]] = Field(default_factory=PortsConfig)

    # Features
    task_agents: TaskAgentsConfig = Field(default_factory=TaskAgentsConfig)
    stall_detection: StallDetectionConfig = Field(default_factory=StallDetectionConfig)
    docker: Optional[DockerConfigModel] = None
    credentials: CredentialsConfig = Field(default_factory=CredentialsConfig)

    # MCP and skills
    mcp_servers: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)

    @field_validator("system_packages", mode="after")
    @classmethod
    def validate_system_packages(cls, packages: List[str]) -> List[str]:
        """Validate system package names."""
        for pkg in packages:
            if not pkg or len(pkg) > 200:
                raise ValueError(f"Invalid package name: {pkg}")
            if not VALID_PACKAGE_PATTERN.match(pkg):
                raise ValueError(
                    f"Invalid package name '{pkg}'. "
                    "Must be alphanumeric with ._+- allowed."
                )
        return packages

    @model_validator(mode="before")
    @classmethod
    def normalize_ports(cls, data: Any) -> Any:
        """Convert old list-style ports to new PortsConfig format."""
        if isinstance(data, dict):
            ports = data.get("ports")
            if isinstance(ports, list):
                # Old format: list of strings -> convert to new format
                data["ports"] = {"host": ports, "container": [], "mode": "tunnel"}
        return data

    model_config = ConfigDict(extra="allow")  # Allow extra fields for forward compatibility
