#!/usr/bin/env python3
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Merge global and project configs into runtime config.

Reads:
  - /library/config/default/config.json (global baseline)
  - /workspace/.agentbox/config.json (project overrides)

Writes:
  - /root/.claude/config.json (merged runtime config)

Project config takes precedence for overlapping keys.
MCP servers are merged (project can add to global MCPs).
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any


def deep_merge(base: Dict[Any, Any], override: Dict[Any, Any]) -> Dict[Any, Any]:
    """Deep merge two dictionaries, override takes precedence."""
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def _env_path(var_name: str, default: Path) -> Path:
    value = os.getenv(var_name)
    return Path(value) if value else default


def merge_configs() -> bool:
    """Merge global and project configs into runtime config."""
    global_config_path = _env_path(
        "AGENTBOX_CLAUDE_GLOBAL_CONFIG",
        Path("/agentbox/library/config/default/config.json"),
    )
    project_config_path = _env_path(
        "AGENTBOX_CLAUDE_PROJECT_CONFIG",
        Path("/workspace/.agentbox/config.json"),
    )
    runtime_config_path = _env_path(
        "AGENTBOX_CLAUDE_RUNTIME_CONFIG",
        Path("/home/abox/.claude/config.json"),
    )

    # Read global config (baseline)
    global_config = {}
    if global_config_path.exists():
        try:
            with open(global_config_path, 'r') as f:
                data = json.load(f)
                global_config = data.get('settings', {}) if 'settings' in data else data
        except Exception as e:
            print(f"Warning: Failed to read global config: {e}", file=sys.stderr)

    # Read project config (overrides)
    project_config = {}
    if project_config_path.exists():
        try:
            with open(project_config_path, 'r') as f:
                project_config = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to read project config: {e}", file=sys.stderr)

    # Merge configs
    merged = deep_merge(global_config, project_config)

    # Ensure .claude directory exists
    runtime_config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write merged config
    try:
        with open(runtime_config_path, 'w') as f:
            json.dump(merged, f, indent=2)
        return True
    except Exception as e:
        print(f"Error: Failed to write runtime config: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    success = merge_configs()
    sys.exit(0 if success else 1)