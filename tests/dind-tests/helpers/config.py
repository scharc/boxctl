# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Project config helpers for DinD tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def _merge_dicts(base: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """Recursively merge updates into base."""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_dicts(base[key], value)
        else:
            base[key] = value


def update_project_config(project_dir: Path, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update .boxctl.yml with provided values.

    Returns the updated config dict.
    """
    config_path = project_dir / ".boxctl.yml"
    config: Dict[str, Any] = {}

    if config_path.exists():
        config = yaml.safe_load(config_path.read_text()) or {}

    _merge_dicts(config, updates)

    if "version" not in config:
        config["version"] = "1.0"

    config_path.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
    return config
