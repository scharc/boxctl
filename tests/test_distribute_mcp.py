# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for distribute-mcp-config.py script."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestDistributeMcpConfig:
    """Tests for MCP config distribution.

    The script reads ~/.mcp.json and distributes to:
    - ~/.gemini/settings.json
    - ~/.qwen/settings.json
    - Codex uses host-mounted config (skipped)
    """

    @pytest.fixture
    def temp_home(self):
        """Create a temporary home directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)

    def run_script(self, home_dir):
        """Run the distribute script with HOME set to temp dir."""
        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        return subprocess.run(
            ["python3", "/workspace/bin/distribute-mcp-config.py"],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_empty_mcp_config(self, temp_home):
        """Script handles missing mcp.json gracefully."""
        result = self.run_script(temp_home)
        assert result.returncode == 0
        assert (
            "nothing to distribute" in result.stderr.lower()
            or "no mcp servers" in result.stderr.lower()
        )

    def test_distributes_servers_to_gemini(self, temp_home):
        """MCP servers are distributed to Gemini settings."""
        # Create ~/.mcp.json
        mcp_config = {
            "mcpServers": {
                "test-server": {
                    "command": "python3",
                    "args": ["/path/to/server.py"],
                }
            }
        }
        (temp_home / ".mcp.json").write_text(json.dumps(mcp_config))

        result = self.run_script(temp_home)
        assert result.returncode == 0

        # Check Gemini settings
        gemini_path = temp_home / ".gemini" / "settings.json"
        assert gemini_path.exists()
        gemini_config = json.loads(gemini_path.read_text())
        assert "test-server" in gemini_config["mcpServers"]

    def test_distributes_servers_to_qwen(self, temp_home):
        """MCP servers are distributed to Qwen settings."""
        # Create ~/.mcp.json
        mcp_config = {
            "mcpServers": {
                "test-server": {
                    "command": "python3",
                    "args": ["/path/to/server.py"],
                }
            }
        }
        (temp_home / ".mcp.json").write_text(json.dumps(mcp_config))

        result = self.run_script(temp_home)
        assert result.returncode == 0

        # Check Qwen settings
        qwen_path = temp_home / ".qwen" / "settings.json"
        assert qwen_path.exists()
        qwen_config = json.loads(qwen_path.read_text())
        assert "test-server" in qwen_config["mcpServers"]

    def test_preserves_existing_gemini_settings(self, temp_home):
        """Existing Gemini settings are preserved when merging MCP."""
        # Create existing Gemini settings
        gemini_dir = temp_home / ".gemini"
        gemini_dir.mkdir()
        existing_settings = {
            "theme": "dark",
            "fontSize": 14,
            "mcpServers": {"old-server": {"command": "old"}},
        }
        (gemini_dir / "settings.json").write_text(json.dumps(existing_settings))

        # Create ~/.mcp.json with new server
        mcp_config = {
            "mcpServers": {
                "new-server": {
                    "command": "python3",
                    "args": ["/path/to/server.py"],
                }
            }
        }
        (temp_home / ".mcp.json").write_text(json.dumps(mcp_config))

        result = self.run_script(temp_home)
        assert result.returncode == 0

        # Check settings are merged
        gemini_config = json.loads((gemini_dir / "settings.json").read_text())
        assert gemini_config["theme"] == "dark"  # Preserved
        assert gemini_config["fontSize"] == 14  # Preserved
        assert "new-server" in gemini_config["mcpServers"]  # Added
        # Note: old-server is replaced since we set the entire mcpServers dict

    def test_codex_not_modified(self, temp_home):
        """Codex config is not created/modified (uses host config)."""
        # Create ~/.mcp.json
        mcp_config = {
            "mcpServers": {
                "test-server": {
                    "command": "python3",
                    "args": ["/path/to/server.py"],
                }
            }
        }
        (temp_home / ".mcp.json").write_text(json.dumps(mcp_config))

        result = self.run_script(temp_home)
        assert result.returncode == 0

        # Codex config should NOT be created by this script
        codex_path = temp_home / ".codex" / "config.toml"
        assert not codex_path.exists()

    def test_handles_multiple_servers(self, temp_home):
        """Multiple MCP servers are all distributed."""
        mcp_config = {
            "mcpServers": {
                "server-1": {"command": "cmd1", "args": []},
                "server-2": {"command": "cmd2", "args": []},
                "server-3": {"command": "cmd3", "args": []},
            }
        }
        (temp_home / ".mcp.json").write_text(json.dumps(mcp_config))

        result = self.run_script(temp_home)
        assert result.returncode == 0

        gemini_config = json.loads((temp_home / ".gemini" / "settings.json").read_text())
        assert len(gemini_config["mcpServers"]) == 3
        assert "server-1" in gemini_config["mcpServers"]
        assert "server-2" in gemini_config["mcpServers"]
        assert "server-3" in gemini_config["mcpServers"]
