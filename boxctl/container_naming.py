# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Container naming resolution - single source of truth.

This module handles all container name resolution for boxctl:
- Finding existing containers by workspace path
- Generating names with collision handling
- Sanitizing project names for Docker

All other modules should import from here instead of implementing their own logic.
"""

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from boxctl.paths import ContainerDefaults
from boxctl.utils.logging import get_logger

logger = get_logger(__name__)

# Re-export for backwards compatibility - source of truth is ContainerDefaults
CONTAINER_PREFIX = ContainerDefaults.CONTAINER_PREFIX
LEGACY_CONTAINER_PREFIX = "agentbox-"  # For migration warnings


def sanitize_name(name: str) -> str:
    """Sanitize a name for use in Docker container names.

    Args:
        name: Raw name (e.g., directory name)

    Returns:
        Sanitized name safe for Docker (lowercase, alphanumeric + hyphens)
    """
    # Convert to lowercase, replace invalid chars with hyphens
    sanitized = re.sub(r"[^a-z0-9_-]", "-", name.lower())
    # Remove leading/trailing hyphens
    sanitized = sanitized.strip("-")
    return sanitized


def resolve_project_dir(project_dir: Optional[Path] = None) -> Path:
    """Resolve the project directory.

    Resolution order:
    1. Explicit project_dir argument (if provided)
    2. BOXCTL_PROJECT_DIR environment variable
    3. Current working directory

    Args:
        project_dir: Optional explicit project directory

    Returns:
        Resolved project directory as absolute Path
    """
    if project_dir is not None:
        return project_dir.resolve()

    env_project_dir = os.getenv("BOXCTL_PROJECT_DIR")
    if env_project_dir:
        return Path(env_project_dir).resolve()

    return Path.cwd().resolve()


def get_container_workspace(container_name: str) -> Optional[Path]:
    """Get the workspace path mounted in a container.

    Args:
        container_name: Full container name

    Returns:
        Path to workspace on host, or None if not found
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                container_name,
                "--format",
                '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def find_container_by_workspace(project_dir: Path) -> Optional[str]:
    """Find an existing container by its workspace mount path.

    Searches all boxctl containers and returns the one whose
    /workspace mount matches the given project path.

    Args:
        project_dir: Project directory path (will be resolved to absolute)

    Returns:
        Container name if found, None otherwise
    """
    project_path = project_dir.resolve()

    try:
        # List all boxctl containers
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name={CONTAINER_PREFIX}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        for name in result.stdout.strip().split("\n"):
            if not name:
                continue
            workspace = get_container_workspace(name)
            if workspace and workspace.resolve() == project_path:
                return name

    except Exception as e:
        logger.debug(f"Error finding container by workspace: {e}")

    return None


def generate_default_name(project_dir: Path) -> str:
    """Generate the default container name from project directory.

    Args:
        project_dir: Project directory path

    Returns:
        Default container name (boxctl-<sanitized_name>)
    """
    sanitized = sanitize_name(project_dir.name)
    return f"{CONTAINER_PREFIX}{sanitized}"


def generate_hashed_name(project_dir: Path) -> str:
    """Generate a container name with hash suffix for collision handling.

    Args:
        project_dir: Project directory path (absolute)

    Returns:
        Container name with hash suffix (boxctl-<name>-<hash>)
    """
    base_name = generate_default_name(project_dir)
    path_hash = hashlib.md5(str(project_dir.resolve()).encode()).hexdigest()[:4]
    return f"{base_name}-{path_hash}"


def resolve_container_name(project_dir: Optional[Path] = None) -> str:
    """Resolve the container name for a project directory.

    This is the main entry point for container name resolution.
    It handles:
    1. Finding existing containers by workspace path
    2. Generating default names
    3. Handling collisions with hash suffixes

    Args:
        project_dir: Project directory (resolved via resolve_project_dir if None)

    Returns:
        Container name to use
    """
    resolved_dir = resolve_project_dir(project_dir)

    # First, check if a container already exists for this path
    existing = find_container_by_workspace(resolved_dir)
    if existing:
        logger.debug(f"Found existing container {existing} for {resolved_dir}")
        return existing

    # Generate default name
    container_name = generate_default_name(resolved_dir)

    # Check for collision with a different project
    existing_workspace = get_container_workspace(container_name)
    if existing_workspace and existing_workspace.resolve() != resolved_dir:
        # Collision detected - use hashed name
        hashed_name = generate_hashed_name(resolved_dir)
        logger.debug(f"Name collision for {container_name}, using {hashed_name}")
        return hashed_name

    return container_name


def extract_project_name(container_name: str) -> Optional[str]:
    """Extract the project name from a container name.

    Handles both regular names (boxctl-myapp) and hashed names (boxctl-myapp-a1b2).

    Args:
        container_name: Full container name

    Returns:
        Project name portion, or None if not a boxctl container
    """
    if not container_name.startswith(CONTAINER_PREFIX):
        return None

    name = container_name[len(CONTAINER_PREFIX) :]

    # Check if it has a hash suffix (4 hex chars at end after hyphen)
    if re.match(r".+-[a-f0-9]{4}$", name):
        # Remove the hash suffix
        name = name.rsplit("-", 1)[0]

    return name
