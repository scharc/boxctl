#!/usr/bin/env python3
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Split runtime config changes back to project config.

Reads:
  - /root/.claude/config.json (runtime config, edited by Claude)
  - /library/config/default/config.json (global baseline)

Writes:
  - /workspace/.agentbox/config.json (project-specific changes)

Extracts only what differs from global baseline.
Always preserves mcpServers (project-specific).
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Set


def get_differences(runtime: Dict[Any, Any], baseline: Dict[Any, Any],
                    preserve_keys: Set[str]) -> Dict[Any, Any]:
    """Extract differences between runtime and baseline configs.

    Args:
        runtime: Current runtime config (edited)
        baseline: Global baseline config
        preserve_keys: Keys to always include (e.g., mcpServers)

    Returns:
        Dictionary with only the differences
    """
    result = {}

    # Always preserve certain keys (like mcpServers)
    for key in preserve_keys:
        if key in runtime:
            result[key] = runtime[key]

    # Find differences for other keys
    for key, value in runtime.items():
        if key in preserve_keys:
            continue  # Already handled

        if key not in baseline:
            # New key added by user/Claude
            result[key] = value
        elif isinstance(value, dict) and isinstance(baseline[key], dict):
            # Recursively check nested dicts
            nested_diff = get_differences(value, baseline[key], set())
            if nested_diff:
                result[key] = nested_diff
        elif value != baseline[key]:
            # Value changed from baseline
            result[key] = value

    return result


def _env_path(var_name: str, default: Path) -> Path:
    value = os.getenv(var_name)
    return Path(value) if value else default


def split_config() -> bool:
    """Split runtime config changes back to project config."""
    global_config_path = _env_path(
        "AGENTBOX_CLAUDE_GLOBAL_CONFIG",
        Path("/agentbox/library/config/default/config.json"),
    )
    runtime_config_path = _env_path(
        "AGENTBOX_CLAUDE_RUNTIME_CONFIG",
        Path("/home/abox/.claude/config.json"),
    )
    project_config_path = _env_path(
        "AGENTBOX_CLAUDE_PROJECT_CONFIG",
        Path("/workspace/.agentbox/config.json"),
    )

    # Read runtime config (edited)
    if not runtime_config_path.exists():
        print("Warning: Runtime config doesn't exist yet", file=sys.stderr)
        return False

    try:
        with open(runtime_config_path, 'r') as f:
            runtime_config = json.load(f)
    except Exception as e:
        print(f"Error: Failed to read runtime config: {e}", file=sys.stderr)
        return False

    # Read global baseline
    global_config = {}
    if global_config_path.exists():
        try:
            with open(global_config_path, 'r') as f:
                data = json.load(f)
                global_config = data.get('settings', {}) if 'settings' in data else data
        except Exception as e:
            print(f"Warning: Failed to read global config: {e}", file=sys.stderr)

    # Extract differences (preserve mcpServers and other project-specific keys)
    preserve_keys = {'mcpServers', 'skills'}
    project_config = get_differences(runtime_config, global_config, preserve_keys)

    # Ensure .agentbox directory exists
    project_config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write project config
    try:
        with open(project_config_path, 'w') as f:
            json.dump(project_config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error: Failed to write project config: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    success = split_config()
    sys.exit(0 if success else 1)