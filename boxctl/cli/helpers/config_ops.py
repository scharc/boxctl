# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Configuration loading and saving operations."""

import json
from pathlib import Path

from boxctl.container import ContainerManager


def _load_workspaces_config(boxctl_dir: Path) -> list[dict]:
    """Load workspaces from .boxctl/config.yml."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(boxctl_dir.parent)
    return config.workspaces


def _save_workspaces_config(boxctl_dir: Path, workspaces: list[dict]) -> None:
    """Save workspaces to .boxctl/config.yml."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(boxctl_dir.parent)
    config.workspaces = workspaces
    config.save()


def _load_containers_config(boxctl_dir: Path) -> list[dict]:
    """Load container connections from .boxctl/config.yml."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(boxctl_dir.parent)
    return config.containers


def _save_containers_config(boxctl_dir: Path, connections: list[dict]) -> None:
    """Save container connections to .boxctl/config.yml."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(boxctl_dir.parent)
    config.containers = connections
    config.save()


def _validate_connection(manager: ContainerManager, connection: dict) -> bool:
    """Validate that a connected container still exists and is running."""
    # Support both old and new format
    container_name = connection.get("name") or connection.get("container_name")

    if not container_name:
        return False

    try:
        container = manager.client.containers.get(container_name)
        return container.status == "running"
    except Exception:
        return False


def _load_packages_config(boxctl_dir: Path) -> dict:
    """Load packages from .boxctl/config.yml."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(boxctl_dir.parent)
    return config.packages


def _save_packages_config(boxctl_dir: Path, packages: dict) -> None:
    """Save packages to .boxctl/config.yml."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(boxctl_dir.parent)
    config.packages = packages
    config.save()


def _load_mcp_meta(boxctl_dir: Path) -> dict:
    """Load MCP metadata from project.

    MCP metadata tracks install requirements and mounts for each MCP server.
    """
    meta_path = boxctl_dir / "mcp-meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except Exception:
            pass
    return {"servers": {}}


def _save_mcp_meta(boxctl_dir: Path, meta: dict) -> None:
    """Save MCP metadata to project."""
    meta_path = boxctl_dir / "mcp-meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
