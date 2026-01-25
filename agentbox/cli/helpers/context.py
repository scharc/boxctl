# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Dynamic context building from native configs."""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agentbox.config import ProjectConfig

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[assignment]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None

# =============================================================================
# Module-level caches for performance optimization
# =============================================================================

# Cache for skill frontmatter (SKILL.md files) - keyed by file path
_skill_cache: Dict[str, Dict[str, Any]] = {}
_skill_cache_time: Dict[str, float] = {}
_skill_cache_lock = threading.Lock()
_SKILL_CACHE_TTL = float(os.environ.get("AGENTBOX_SKILL_CACHE_TTL", "300.0"))  # 5 min default

# Cache for config file reads (JSON/TOML) - keyed by file path
_config_cache: Dict[str, Any] = {}
_config_cache_time: Dict[str, float] = {}
_config_cache_lock = threading.Lock()
_CONFIG_CACHE_TTL = float(os.environ.get("AGENTBOX_CONFIG_CACHE_TTL", "5.0"))  # 5 sec default


def _get_cached_skill(skill_path: Path) -> Optional[Dict]:
    """Get skill frontmatter from cache if fresh."""
    key = str(skill_path)
    with _skill_cache_lock:
        if key in _skill_cache:
            if time.time() - _skill_cache_time.get(key, 0) < _SKILL_CACHE_TTL:
                return _skill_cache[key]
    return None


def _set_cached_skill(skill_path: Path, data: Dict) -> None:
    """Store skill frontmatter in cache."""
    key = str(skill_path)
    with _skill_cache_lock:
        _skill_cache[key] = data
        _skill_cache_time[key] = time.time()


def _get_cached_config(config_path: Path) -> Optional[Any]:
    """Get config file data from cache if fresh."""
    key = str(config_path)
    with _config_cache_lock:
        if key in _config_cache:
            if time.time() - _config_cache_time.get(key, 0) < _CONFIG_CACHE_TTL:
                return _config_cache[key]
    return None


def _set_cached_config(config_path: Path, data: Any) -> None:
    """Store config file data in cache."""
    key = str(config_path)
    with _config_cache_lock:
        _config_cache[key] = data
        _config_cache_time[key] = time.time()


def _read_json_cached(path: Path) -> Dict:
    """Read JSON file with caching."""
    cached = _get_cached_config(path)
    if cached is not None:
        return cached
    try:
        data = json.loads(path.read_text())
        _set_cached_config(path, data)
        return data
    except Exception:
        return {}


def _read_toml_cached(path: Path) -> Dict:
    """Read TOML file with caching."""
    if tomllib is None:
        return {}
    cached = _get_cached_config(path)
    if cached is not None:
        return cached
    try:
        data = tomllib.loads(path.read_text())
        _set_cached_config(path, data)
        return data
    except Exception:
        return {}


def _parse_skill_frontmatter(skill_path: Path) -> dict:
    """Parse YAML frontmatter from a SKILL.md file.

    Handles common edge cases:
    - BOM markers
    - CRLF line endings
    - Colons in values
    - Quoted strings
    - Multiline values (YAML block scalars with |)

    Results are cached for performance (TTL: 5 minutes).
    """
    # Check cache first
    cached = _get_cached_skill(skill_path)
    if cached is not None:
        return cached

    try:
        content = skill_path.read_text(encoding="utf-8-sig")  # Handle BOM
        content = content.replace("\r\n", "\n")  # Normalize line endings

        # Match YAML frontmatter between --- markers (can start with optional whitespace)
        match = re.match(r"^\s*---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}

        frontmatter = match.group(1)

        # Try PyYAML if available (most robust)
        try:
            import yaml
            parsed = yaml.safe_load(frontmatter)
            # Ensure we return a dict (YAML could be a list or scalar)
            return parsed if isinstance(parsed, dict) else {}
        except ImportError:
            pass

        # Fallback: simple parser for common cases
        result = {}
        lines = frontmatter.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip empty lines and comments
            if not line.strip() or line.strip().startswith("#"):
                i += 1
                continue

            # Must have a colon for key-value
            if ":" not in line:
                i += 1
                continue

            # Split on first colon only (handles colons in values)
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Handle multiline block scalar (|)
            if value == "|":
                multiline_parts = []
                i += 1
                # Collect indented lines
                while i < len(lines):
                    next_line = lines[i]
                    # Check if line is indented (part of block) or empty
                    if next_line and not next_line[0].isspace() and next_line.strip():
                        break
                    multiline_parts.append(next_line.strip())
                    i += 1
                value = " ".join(p for p in multiline_parts if p)
            else:
                i += 1

            # Handle quoted strings
            if value.startswith('"') and value.endswith('"') and len(value) > 1:
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'") and len(value) > 1:
                value = value[1:-1]

            if key:
                result[key] = value

        _set_cached_skill(skill_path, result)
        return result
    except Exception:
        _set_cached_skill(skill_path, {})
        return {}


def _get_slash_commands(project_dir: Path) -> list[tuple[str, str]]:
    """Get list of available slash commands with descriptions.

    Returns:
        List of tuples: (command_name, description)
    """
    commands_dir = project_dir / ".claude" / "commands"
    if not commands_dir.exists():
        return []

    commands = []
    seen = set()

    for cmd_file in sorted(commands_dir.glob("*.md")):
        # Get the command name (use symlink target name if it's a symlink)
        if cmd_file.is_symlink():
            # This is the user-facing name
            cmd_name = cmd_file.stem
            if cmd_name in seen:
                continue
            seen.add(cmd_name)

            # Read description from the target file
            try:
                content = cmd_file.read_text()
                desc = ""
                if content.startswith("---"):
                    # Parse frontmatter for description
                    end = content.find("---", 3)
                    if end > 0:
                        frontmatter = content[3:end]
                        for line in frontmatter.split("\n"):
                            if line.startswith("description:"):
                                desc = line.split(":", 1)[1].strip().strip('"\'')
                                break
                commands.append((cmd_name, desc))
            except Exception:
                commands.append((cmd_name, ""))

    return commands


def _get_ssh_context(project_dir: Path, config: Optional["ProjectConfig"] = None) -> list[str]:
    """Get SSH configuration context lines for agents.

    Args:
        project_dir: Project directory path
        config: Optional cached ProjectConfig instance

    Returns:
        List of markdown lines describing SSH setup.
    """
    lines = []

    # Load project config to get SSH settings
    try:
        if config is None:
            from agentbox.config import ProjectConfig
            config = ProjectConfig(project_dir)

        if not config.ssh_enabled:
            lines.append("### SSH")
            lines.append("SSH is **disabled** for this project.")
            lines.append("")
            return lines

        ssh_mode = config.ssh_mode
        forward_agent = config.ssh_forward_agent

        lines.append("### SSH Configuration")

        # Describe the mode
        mode_descriptions = {
            "none": "No SSH keys available in container.",
            "keys": "SSH keys from host `~/.ssh` are copied to `/home/abox/.ssh`.",
            "mount": "Host `~/.ssh` is bind-mounted to `/home/abox/.ssh` (read-write).",
            "config": "Only SSH config/known_hosts copied (no private keys).",
        }
        mode_desc = mode_descriptions.get(ssh_mode, f"Unknown mode: {ssh_mode}")
        lines.append(f"- **Mode:** `{ssh_mode}` - {mode_desc}")

        # Describe agent forwarding
        if forward_agent:
            # Check if SSH_AUTH_SOCK exists on host (this runs on host during launch)
            host_sock = os.getenv("SSH_AUTH_SOCK")
            if host_sock and Path(host_sock).exists():
                lines.append("- **Agent Forwarding:** Enabled")
                lines.append("  - `SSH_AUTH_SOCK` is set in the container environment")
                lines.append("  - Git operations using SSH will use the forwarded agent")
                lines.append("  - This works with passphrase-protected keys")
            else:
                lines.append("- **Agent Forwarding:** Configured but `SSH_AUTH_SOCK` not found on host")
        else:
            if ssh_mode == "config":
                lines.append("- **Agent Forwarding:** Disabled (WARNING: mode=config without forwarding means no key access)")
            elif ssh_mode != "none":
                lines.append("- **Agent Forwarding:** Disabled (using keys directly from container)")

        lines.append("")

    except Exception:
        # If we can't load config, just skip SSH section
        pass

    return lines


def _get_docker_context(project_dir: Path, config: Optional["ProjectConfig"] = None) -> list[str]:
    """Get Docker access context lines for agents.

    Args:
        project_dir: Project directory path
        config: Optional cached ProjectConfig instance

    Returns:
        List of markdown lines describing Docker setup.
    """
    lines = []

    try:
        if config is None:
            from agentbox.config import ProjectConfig
            config = ProjectConfig(project_dir)

        docker_enabled = config.docker_enabled

        if docker_enabled:
            lines.append("### Docker Access")
            lines.append("- Docker socket is **enabled** and mounted at `/var/run/docker.sock`")
            lines.append("- You can run `docker` commands directly (e.g., `docker ps`, `docker build`)")
            lines.append("- The container has access to the host's Docker daemon")
            lines.append("")

    except Exception:
        pass

    return lines


def _get_credentials_context(project_dir: Path, config: Optional["ProjectConfig"] = None) -> list[str]:
    """Get CLI credentials context lines for agents.

    Args:
        project_dir: Project directory path
        config: Optional cached ProjectConfig instance

    Returns:
        List of markdown lines describing mounted CLI credentials.
    """
    lines = []

    try:
        if config is None:
            from agentbox.config import ProjectConfig
            config = ProjectConfig(project_dir)

        gh_enabled = config.gh_enabled
        glab_enabled = config.glab_enabled

        if gh_enabled or glab_enabled:
            lines.append("### CLI Credentials")
            if gh_enabled:
                lines.append("- **GitHub CLI (gh):** Credentials from `~/.config/gh` are mounted")
                lines.append("  - `gh` commands can use your GitHub authentication")
            if glab_enabled:
                lines.append("- **GitLab CLI (glab):** Credentials from `~/.config/glab-cli` are mounted")
                lines.append("  - `glab` commands can use your GitLab authentication")
            lines.append("")

    except Exception:
        pass

    return lines


def _get_ports_context(project_dir: Path, config: Optional["ProjectConfig"] = None) -> list[str]:
    """Get ports/networking context lines for agents.

    Args:
        project_dir: Project directory path
        config: Optional cached ProjectConfig instance

    Returns:
        List of markdown lines describing port forwarding setup.
    """
    lines = []

    try:
        if config is None:
            from agentbox.config import ProjectConfig
            config = ProjectConfig(project_dir)

        host_ports = config.ports_host
        container_ports = config.ports_container

        if host_ports or container_ports:
            lines.append("### Port Forwarding")

            if host_ports:
                lines.append("**Exposed ports** (container → host):")
                for port in host_ports:
                    lines.append(f"  - `{port}`")

            if container_ports:
                lines.append("**Forwarded ports** (host → container):")
                for port_config in container_ports:
                    if isinstance(port_config, dict):
                        host_port = port_config.get("host", "?")
                        container_port = port_config.get("container", "?")
                        lines.append(f"  - `localhost:{host_port}` → container `:{container_port}`")
                    else:
                        lines.append(f"  - `{port_config}`")

            lines.append("")

    except Exception:
        pass

    return lines


def _get_containers_context(project_dir: Path, config: Optional["ProjectConfig"] = None) -> list[str]:
    """Get connected containers context lines for agents.

    Args:
        project_dir: Project directory path
        config: Optional cached ProjectConfig instance

    Returns:
        List of markdown lines describing connected containers.
    """
    lines = []

    try:
        if config is None:
            from agentbox.config import ProjectConfig
            config = ProjectConfig(project_dir)

        containers = config.containers

        if containers:
            lines.append("### Connected Containers")
            lines.append("This project is connected to other Docker containers:")
            for c in containers:
                name = c.get("name", "unknown")
                auto_reconnect = c.get("auto_reconnect", True)
                reconnect_status = "auto-reconnect" if auto_reconnect else "manual"
                lines.append(f"  - `{name}` ({reconnect_status})")
            lines.append("Use `docker exec` to run commands in connected containers.")
            lines.append("")

    except Exception:
        pass

    return lines


def _get_devices_context(project_dir: Path, config: Optional["ProjectConfig"] = None) -> list[str]:
    """Get devices context lines for agents (GPU, etc.).

    Args:
        project_dir: Project directory path
        config: Optional cached ProjectConfig instance

    Returns:
        List of markdown lines describing mounted devices.
    """
    lines = []

    try:
        if config is None:
            from agentbox.config import ProjectConfig
            config = ProjectConfig(project_dir)

        devices = config.devices

        if devices:
            lines.append("### Devices")
            lines.append("Special devices are mounted in the container:")
            for device in devices:
                if "nvidia" in device.lower() or "gpu" in device.lower():
                    lines.append(f"  - `{device}` (GPU access)")
                else:
                    lines.append(f"  - `{device}`")
            lines.append("")

    except Exception:
        pass

    return lines


def _build_dynamic_context(agentbox_dir: Path) -> str:
    """Build dynamic context string from native configs (MCPs, workspaces, skills).

    Performance optimized:
    - Single ProjectConfig instance shared across all helper functions
    - Cached JSON/TOML file reads
    - Cached skill frontmatter parsing
    """
    lines = ["## Dynamic Context", ""]

    # Load ProjectConfig once and reuse for all helper functions
    project_dir = agentbox_dir.parent
    try:
        from agentbox.config import ProjectConfig
        project_config = ProjectConfig(project_dir)
    except Exception:
        project_config = None

    # MCP Servers from mcp-meta.json (source of truth for what's installed)
    all_mcps = set()

    # Read from mcp-meta.json (project-level MCP tracking)
    mcp_meta_path = agentbox_dir / "mcp-meta.json"
    if mcp_meta_path.exists():
        mcp_meta_data = _read_json_cached(mcp_meta_path)
        mcp_servers = mcp_meta_data.get("servers", {})
        all_mcps.update(mcp_servers.keys())

    if all_mcps:
        lines.append("### MCP Servers Available")
        for mcp_name in sorted(all_mcps):
            lines.append(f"- `{mcp_name}`")
        lines.append("")

    # Project Configuration File
    config_path = project_dir / ".agentbox/config.yml"
    if config_path.exists():
        lines.append("### Project Configuration")
        lines.append(f"- **Config file:** `/workspace/.agentbox/config.yml`")
        lines.append("- Read this file to check current settings (ports, SSH, docker, etc.)")
        lines.append("- Settings may change during the session via CLI commands")
        lines.append("")

    # Environment Configuration from .agentbox/config.yml
    # Pass cached project_config to all helpers to avoid repeated YAML parsing

    # SSH Configuration
    ssh_lines = _get_ssh_context(project_dir, project_config)
    if ssh_lines:
        lines.extend(ssh_lines)

    # Docker Access
    docker_lines = _get_docker_context(project_dir, project_config)
    if docker_lines:
        lines.extend(docker_lines)

    # CLI Credentials (gh, glab)
    credentials_lines = _get_credentials_context(project_dir, project_config)
    if credentials_lines:
        lines.extend(credentials_lines)

    # Port Forwarding
    ports_lines = _get_ports_context(project_dir, project_config)
    if ports_lines:
        lines.extend(ports_lines)

    # Connected Containers
    containers_lines = _get_containers_context(project_dir, project_config)
    if containers_lines:
        lines.extend(containers_lines)

    # Devices (GPU, etc.)
    devices_lines = _get_devices_context(project_dir, project_config)
    if devices_lines:
        lines.extend(devices_lines)

    # Workspace Mounts from .agentbox/workspaces.json (with caching)
    workspaces_path = agentbox_dir / "workspaces.json"
    if workspaces_path.exists():
        workspaces_data = _read_json_cached(workspaces_path)
        workspaces = workspaces_data.get("workspaces", [])
        if workspaces:
            lines.append("### Workspace Mounts")
            lines.append("Extra directories mounted in the container:")
            for entry in workspaces:
                mount = entry.get("mount", "")
                path = entry.get("path", "")
                mode = entry.get("mode", "ro")
                lines.append(f"- `/context/{mount}` → `{path}` ({mode})")
            lines.append("")

    # Skills from directory listings with descriptions
    skills_dir = agentbox_dir / "skills"
    all_skills: dict[str, dict] = {}  # name -> {description, path}

    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            # Skip system skills (hidden directories)
            if skill_dir.name.startswith("."):
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                frontmatter = _parse_skill_frontmatter(skill_file)
                skill_name = frontmatter.get("name", skill_dir.name)
                description = frontmatter.get("description", "")
                # Don't overwrite if we already have this skill with a description
                if skill_name not in all_skills or not all_skills[skill_name].get("description"):
                    all_skills[skill_name] = {"description": description}

    if all_skills:
        lines.append("### Skills")
        lines.append("Available skills. Use the Skill tool to invoke them when relevant:")
        lines.append("")
        for skill_name in sorted(all_skills.keys()):
            info = all_skills[skill_name]
            desc = info.get("description", "")
            if desc:
                lines.append(f"- **{skill_name}**: {desc}")
            else:
                lines.append(f"- **{skill_name}**")
        lines.append("")

    # Slash commands from .claude/commands/
    slash_commands = _get_slash_commands(project_dir)
    if slash_commands:
        lines.append("### Slash Commands")
        lines.append("Use these commands when relevant to the task:")
        lines.append("")
        for cmd_name, desc in slash_commands:
            if desc:
                lines.append(f"- `/{cmd_name}`: {desc}")
            else:
                lines.append(f"- `/{cmd_name}`")
        lines.append("")

    # Add skill/command usage instruction if any are available
    if all_skills or slash_commands:
        lines.append("### Using Skills and Commands")
        lines.append("")
        lines.append("**IMPORTANT:** Proactively use available skills and slash commands when they match the task at hand.")
        lines.append("- Skills provide specialized capabilities - invoke them with the Skill tool")
        lines.append("- Slash commands are quick actions - they appear in autocomplete with `/`")
        lines.append("- Don't wait to be asked - if a skill/command fits the situation, use it")
        lines.append("- Example: Use `/improve` periodically to optimize agent configuration")
        lines.append("- Example: Use `/analyze` when debugging unexpected behavior")
        lines.append("")

    return "\n".join(lines)


def _load_codex_config(path: Path) -> dict:
    if not path.exists():
        return {}
    if tomllib is None:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}
