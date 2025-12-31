#!/usr/bin/env python3
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Split runtime Codex config into project overrides.

Reads:
  - /agentbox/library/config/default/codex.toml (global baseline)
  - /root/.codex/config.toml (runtime config)

Writes:
  - /workspace/.agentbox/codex.toml (project overrides)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None
    try:
        import tomli as tomllib  # type: ignore[assignment]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None


def read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is None:
        print("Error: tomllib not available", file=sys.stderr)
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception as e:
        print(f"Warning: Failed to read {path}: {e}", file=sys.stderr)
        return {}


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return f'"{_toml_escape(value)}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        items = ", ".join(_toml_value(v) for v in value)
        return f"[{items}]"
    return str(value)


def dump_toml(data: Dict[str, Any]) -> str:
    lines: list[str] = []

    projects = data.get("projects", {})
    if isinstance(projects, dict):
        for project_path in sorted(projects.keys()):
            entry = projects[project_path]
            if not isinstance(entry, dict):
                continue
            lines.append(f'[projects."{project_path}"]')
            for key in sorted(entry.keys()):
                lines.append(f"{key} = {_toml_value(entry[key])}")
            lines.append("")

    mcp_servers = data.get("mcp_servers", {})
    if isinstance(mcp_servers, dict):
        for server_name in sorted(mcp_servers.keys()):
            entry = mcp_servers[server_name]
            if not isinstance(entry, dict):
                continue
            lines.append(f'[mcp_servers."{server_name}"]')

            for key in sorted(entry.keys()):
                if key in ("env", "http_headers", "env_http_headers"):
                    continue
                lines.append(f"{key} = {_toml_value(entry[key])}")

            for nested_key in ("env", "http_headers", "env_http_headers"):
                nested = entry.get(nested_key)
                if isinstance(nested, dict) and nested:
                    lines.append(f'[mcp_servers."{server_name}".{nested_key}]')
                    for nk in sorted(nested.keys()):
                        lines.append(f"{nk} = {_toml_value(nested[nk])}")

            lines.append("")

    if not lines:
        return "# empty\n"
    return "\n".join(lines).rstrip() + "\n"


def diff_overrides(base: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}

    base_projects = base.get("projects", {}) if isinstance(base.get("projects"), dict) else {}
    runtime_projects = (
        runtime.get("projects", {}) if isinstance(runtime.get("projects"), dict) else {}
    )

    project_overrides: Dict[str, Any] = {}
    for project_path, runtime_entry in runtime_projects.items():
        base_entry = base_projects.get(project_path)
        if runtime_entry != base_entry:
            project_overrides[project_path] = runtime_entry

    if project_overrides:
        overrides["projects"] = project_overrides

    base_mcp = base.get("mcp_servers", {}) if isinstance(base.get("mcp_servers"), dict) else {}
    runtime_mcp = (
        runtime.get("mcp_servers", {}) if isinstance(runtime.get("mcp_servers"), dict) else {}
    )
    mcp_overrides: Dict[str, Any] = {}
    for server_name, runtime_entry in runtime_mcp.items():
        base_entry = base_mcp.get(server_name)
        if runtime_entry != base_entry:
            mcp_overrides[server_name] = runtime_entry

    if mcp_overrides:
        overrides["mcp_servers"] = mcp_overrides

    return overrides


def _env_path(var_name: str, default: Path) -> Path:
    value = os.getenv(var_name)
    return Path(value) if value else default


def split_config() -> bool:
    global_config_path = _env_path(
        "AGENTBOX_CODEX_GLOBAL_CONFIG",
        Path("/agentbox/library/config/default/codex.toml"),
    )
    runtime_config_path = _env_path(
        "AGENTBOX_CODEX_RUNTIME_CONFIG",
        Path("/home/abox/.codex/config.toml"),
    )
    project_config_path = _env_path(
        "AGENTBOX_CODEX_PROJECT_CONFIG",
        Path("/workspace/.agentbox/codex.toml"),
    )

    base_config = read_toml(global_config_path)
    runtime_config = read_toml(runtime_config_path)

    overrides = diff_overrides(base_config, runtime_config)

    project_config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        project_config_path.write_text(dump_toml(overrides))
        return True
    except Exception as e:
        print(f"Error: Failed to write project config: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    success = split_config()
    sys.exit(0 if success else 1)