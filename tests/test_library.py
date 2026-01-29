# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for LibraryManager."""

import json
import pytest
from pathlib import Path
from boxctl.library import LibraryManager


@pytest.fixture
def mock_library(tmp_path):
    """Create a mock library structure for testing.

    Returns:
        Path to the mock library root
    """
    library_root = tmp_path / "library"
    library_root.mkdir()

    # Create MCP directory structure
    mcp_dir = library_root / "mcp"
    mcp_dir.mkdir()

    # Create test MCP with README
    test_mcp = mcp_dir / "test-server"
    test_mcp.mkdir()
    (test_mcp / "README.md").write_text("# Test Server\nA test MCP server for testing.")
    (test_mcp / "config.json").write_text('{"command": "node", "args": ["index.js"]}')

    # Create test MCP with package.json
    npm_mcp = mcp_dir / "npm-server"
    npm_mcp.mkdir()
    (npm_mcp / "package.json").write_text('{"name": "npm-server", "description": "NPM MCP server"}')

    # Create skills directory structure
    skills_dir = library_root / "skills"
    skills_dir.mkdir()

    # Create test skill (SKILL.md format)
    test_skill = skills_dir / "test-skill"
    test_skill.mkdir()
    (test_skill / "SKILL.md").write_text(
        """---
name: test-skill
description: A test skill for testing.
---

# Test Skill

A test skill.
"""
    )

    # Create config directory structure
    config_dir = library_root / "config"
    config_dir.mkdir()

    # Create test config preset
    test_config = config_dir / "default"
    test_config.mkdir()
    (test_config / "README.md").write_text("# Default Config\nDefault configuration preset.")
    (test_config / "config.json").write_text('{"version": "1.0"}')

    return library_root


def test_library_manager_autodiscovery():
    """Test that LibraryManager discovers library path automatically."""
    lm = LibraryManager()

    # Should discover library as sibling to boxctl package
    assert lm.library_root.exists()
    assert lm.library_root.name == "library"
    assert lm.mcp_dir == lm.library_root / "mcp"
    assert lm.skills_dir == lm.library_root / "skills"
    assert lm.config_dir == lm.library_root / "config"


def test_library_manager_custom_path(mock_library):
    """Test that LibraryManager accepts custom library path."""
    lm = LibraryManager(library_root=mock_library)

    assert lm.library_root == mock_library
    assert lm.mcp_dir == mock_library / "mcp"
    assert lm.skills_dir == mock_library / "skills"
    assert lm.config_dir == mock_library / "config"


def test_list_mcp_servers_empty():
    """Test listing MCP servers when directory doesn't exist."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        empty_lib = Path(tmpdir) / "empty_library"
        empty_user = Path(tmpdir) / "empty_user"
        # Patch user directories to avoid picking up real user config
        with patch("boxctl.library.HostPaths.user_mcp_dir", return_value=empty_user / "mcp"):
            with patch(
                "boxctl.library.HostPaths.user_skills_dir", return_value=empty_user / "skills"
            ):
                lm = LibraryManager(library_root=empty_lib)
                servers = lm.list_mcp_servers()
                assert servers == []


def test_list_mcp_servers(mock_library):
    """Test listing MCP servers."""
    from unittest.mock import patch
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        empty_user = Path(tmpdir) / "empty_user"
        # Patch user directories to isolate test
        with patch("boxctl.library.HostPaths.user_mcp_dir", return_value=empty_user / "mcp"):
            with patch(
                "boxctl.library.HostPaths.user_skills_dir", return_value=empty_user / "skills"
            ):
                lm = LibraryManager(library_root=mock_library)
                servers = lm.list_mcp_servers()
                assert len(servers) == 2

    # Check test-server (has README)
    test_server = next(s for s in servers if s["name"] == "test-server")
    assert test_server["description"] == "Test Server"
    assert "test-server" in test_server["path"]

    # Check npm-server (has package.json)
    npm_server = next(s for s in servers if s["name"] == "npm-server")
    assert npm_server["description"] == "NPM MCP server"
    assert "npm-server" in npm_server["path"]


def test_list_mcp_servers_malformed_json(mock_library):
    """Test that malformed JSON doesn't crash listing."""
    lm = LibraryManager(library_root=mock_library)

    # Create MCP with malformed package.json
    bad_mcp = mock_library / "mcp" / "bad-server"
    bad_mcp.mkdir()
    (bad_mcp / "package.json").write_text("{ invalid json }")

    servers = lm.list_mcp_servers()

    # Should still return servers, with "No description" for bad one
    bad_server = next((s for s in servers if s["name"] == "bad-server"), None)
    assert bad_server is not None
    assert bad_server["description"] == "No description"


def test_list_skills_empty():
    """Test listing skills when directory doesn't exist."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        empty_lib = Path(tmpdir) / "empty_library"
        empty_user = Path(tmpdir) / "empty_user"
        # Patch user directories to avoid picking up real user config
        with patch("boxctl.library.HostPaths.user_mcp_dir", return_value=empty_user / "mcp"):
            with patch(
                "boxctl.library.HostPaths.user_skills_dir", return_value=empty_user / "skills"
            ):
                lm = LibraryManager(library_root=empty_lib)
                skills = lm.list_skills()
                assert skills == []


def test_list_skills(mock_library):
    """Test listing skills."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        empty_user = Path(tmpdir) / "empty_user"
        # Patch user directories to isolate test
        with patch("boxctl.library.HostPaths.user_mcp_dir", return_value=empty_user / "mcp"):
            with patch(
                "boxctl.library.HostPaths.user_skills_dir", return_value=empty_user / "skills"
            ):
                lm = LibraryManager(library_root=mock_library)
                skills = lm.list_skills()
                assert len(skills) == 1
    skill = skills[0]
    assert skill["name"] == "test-skill"
    assert skill["description"] == "A test skill for testing."
    assert "SKILL.md" in skill["path"]


def test_list_skills_without_description(mock_library):
    """Test listing skills that don't have description in frontmatter."""
    lm = LibraryManager(library_root=mock_library)

    # Create skill without description
    no_desc = mock_library / "skills" / "no-desc"
    no_desc.mkdir()
    (no_desc / "SKILL.md").write_text(
        """---
name: no-desc
---

# No Description Skill
"""
    )

    skills = lm.list_skills()

    no_desc_skill = next((s for s in skills if s["name"] == "no-desc"), None)
    assert no_desc_skill is not None
    assert no_desc_skill["description"] == "No description"


def test_list_configs_empty():
    """Test listing configs when directory doesn't exist."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        empty_lib = Path(tmpdir) / "empty_library"
        lm = LibraryManager(library_root=empty_lib)

        configs = lm.list_configs()
        assert configs == []


def test_list_configs(mock_library):
    """Test listing config presets."""
    lm = LibraryManager(library_root=mock_library)

    configs = lm.list_configs()

    assert len(configs) == 1
    config = configs[0]
    assert config["name"] == "default"
    assert config["description"] == "Default Config"
    assert "default" in config["path"]
    assert config["has_config"] is True


def test_list_configs_without_config_file(mock_library):
    """Test listing config preset without config.json."""
    lm = LibraryManager(library_root=mock_library)

    # Create config without config.json
    incomplete_config = mock_library / "config" / "incomplete"
    incomplete_config.mkdir()
    (incomplete_config / "README.md").write_text("# Incomplete\nNo config file.")

    configs = lm.list_configs()

    incomplete = next((c for c in configs if c["name"] == "incomplete"), None)
    assert incomplete is not None
    assert incomplete["has_config"] is False


def test_print_mcp_table_no_servers(mock_library, capsys):
    """Test printing MCP table when no servers exist."""
    from unittest.mock import patch

    # Create empty library
    empty_lib = mock_library.parent / "empty"
    empty_lib.mkdir()

    empty_user = mock_library.parent / "empty_user"
    # Patch user directories to avoid picking up real user config
    with patch("boxctl.library.HostPaths.user_mcp_dir", return_value=empty_user / "mcp"):
        with patch("boxctl.library.HostPaths.user_skills_dir", return_value=empty_user / "skills"):
            lm = LibraryManager(library_root=empty_lib)
            lm.print_mcp_table()

    captured = capsys.readouterr()
    assert "No MCP servers found" in captured.out


def test_print_mcp_table_with_servers(mock_library, capsys):
    """Test printing MCP table with servers."""
    lm = LibraryManager(library_root=mock_library)
    lm.print_mcp_table()

    captured = capsys.readouterr()
    assert "MCP Servers" in captured.out
    assert "test-server" in captured.out
    assert "npm-server" in captured.out


def test_print_skills_table_no_skills(mock_library, capsys):
    """Test printing skills table when no skills exist."""
    from unittest.mock import patch

    # Create empty library
    empty_lib = mock_library.parent / "empty_skills"
    empty_lib.mkdir()

    empty_user = mock_library.parent / "empty_user_skills"
    # Patch user directories to avoid picking up real user config
    with patch("boxctl.library.HostPaths.user_mcp_dir", return_value=empty_user / "mcp"):
        with patch("boxctl.library.HostPaths.user_skills_dir", return_value=empty_user / "skills"):
            lm = LibraryManager(library_root=empty_lib)
            lm.print_skills_table()

    captured = capsys.readouterr()
    assert "No skills found" in captured.out


def test_print_skills_table_with_skills(mock_library, capsys):
    """Test printing skills table with skills."""
    lm = LibraryManager(library_root=mock_library)
    lm.print_skills_table()

    captured = capsys.readouterr()
    assert "Skills" in captured.out
    assert "test-skill" in captured.out


def test_print_configs_table_no_configs(mock_library, capsys):
    """Test printing configs table when no configs exist."""
    # Create empty library
    empty_lib = mock_library.parent / "empty"
    empty_lib.mkdir()

    lm = LibraryManager(library_root=empty_lib)
    lm.print_configs_table()

    captured = capsys.readouterr()
    assert "No config presets found" in captured.out


def test_print_configs_table_with_configs(mock_library, capsys):
    """Test printing configs table with configs."""
    lm = LibraryManager(library_root=mock_library)
    lm.print_configs_table()

    captured = capsys.readouterr()
    assert "Config Presets" in captured.out
    assert "default" in captured.out


def test_show_mcp_exists(mock_library, capsys):
    """Test showing details of an MCP server that exists."""
    lm = LibraryManager(library_root=mock_library)
    lm.show_mcp("test-server")

    captured = capsys.readouterr()
    assert "MCP Server: test-server" in captured.out
    assert "Test Server" in captured.out
    # show_mcp displays README, not config.json
    assert "README:" in captured.out


def test_show_mcp_not_found(mock_library, capsys):
    """Test showing details of an MCP server that doesn't exist."""
    lm = LibraryManager(library_root=mock_library)
    lm.show_mcp("nonexistent")

    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_show_skill_exists(mock_library, capsys):
    """Test showing details of a skill that exists."""
    lm = LibraryManager(library_root=mock_library)
    lm.show_skill("test-skill")

    captured = capsys.readouterr()
    assert "Skill: test-skill" in captured.out
    assert "A test skill for testing." in captured.out


def test_show_skill_not_found(mock_library, capsys):
    """Test showing details of a skill that doesn't exist."""
    lm = LibraryManager(library_root=mock_library)
    lm.show_skill("nonexistent")

    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_show_config_exists(mock_library, capsys):
    """Test showing details of a config preset that exists."""
    lm = LibraryManager(library_root=mock_library)
    lm.show_config("default")

    captured = capsys.readouterr()
    assert "Config Preset: default" in captured.out
    assert "Default Config" in captured.out


def test_show_config_not_found(mock_library, capsys):
    """Test showing details of a config preset that doesn't exist."""
    lm = LibraryManager(library_root=mock_library)
    lm.show_config("nonexistent")

    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_mcp_table_shows_added_status(mock_library, tmp_path, capsys):
    """Test that MCP table shows which servers are added to current project."""
    # Create a mock project with MCP added
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    agentbox_dir = project_dir / ".boxctl"
    agentbox_dir.mkdir()
    claude_dir = agentbox_dir / "claude"
    claude_dir.mkdir()

    # Add test-server to project
    mcp_config = {"mcpServers": {"test-server": {"command": "node", "args": ["index.js"]}}}
    (claude_dir / "mcp.json").write_text(json.dumps(mcp_config))

    # Set environment variable to point to test project
    import os

    old_env = os.environ.get("BOXCTL_PROJECT_DIR")
    os.environ["BOXCTL_PROJECT_DIR"] = str(project_dir)

    try:
        lm = LibraryManager(library_root=mock_library)
        lm.print_mcp_table()

        captured = capsys.readouterr()
        # Should show that test-server is added
        assert "test-server" in captured.out
        # Should show added MCPs summary
        assert "Added MCPs:" in captured.out or "✓" in captured.out
    finally:
        # Restore environment
        if old_env is None:
            os.environ.pop("BOXCTL_PROJECT_DIR", None)
        else:
            os.environ["BOXCTL_PROJECT_DIR"] = old_env


def test_list_skills_recursive(mock_library):
    """Test that skills in nested directories are discovered."""
    lm = LibraryManager(library_root=mock_library)

    # Create a nested skill (simulating a cloned repo)
    cloned_repo = mock_library / "skills" / "awesome-skills-repo"
    cloned_repo.mkdir()
    (cloned_repo / "README.md").write_text("# Awesome Skills Repo")

    nested_skill = cloned_repo / "my-skill"
    nested_skill.mkdir()
    (nested_skill / "SKILL.md").write_text(
        """---
name: my-skill
description: A skill in a cloned repo.
---

# My Skill

A nested skill.
"""
    )

    skills = lm.list_skills()

    # Should find both the original test-skill and the nested my-skill
    skill_names = [s["name"] for s in skills]
    assert "test-skill" in skill_names
    assert "my-skill" in skill_names

    # Check nested skill details
    nested = next(s for s in skills if s["name"] == "my-skill")
    assert nested["description"] == "A skill in a cloned repo."


def test_list_skills_skips_hidden_dirs(mock_library):
    """Test that skills in hidden directories (like .git) are skipped."""
    lm = LibraryManager(library_root=mock_library)

    # Create a skill in a hidden directory (should be skipped)
    hidden_dir = mock_library / "skills" / ".hidden"
    hidden_dir.mkdir()
    hidden_skill = hidden_dir / "hidden-skill"
    hidden_skill.mkdir()
    (hidden_skill / "SKILL.md").write_text(
        """---
name: hidden-skill
description: Should not be found.
---

Hidden skill.
"""
    )

    skills = lm.list_skills()

    skill_names = [s["name"] for s in skills]
    assert "hidden-skill" not in skill_names
