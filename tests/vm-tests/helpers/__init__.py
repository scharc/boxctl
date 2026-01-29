# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Test helpers for VM tests.

These helpers are imported from the DinD tests and work unchanged
because pytest runs INSIDE the VM where local Docker and boxctl
are available.
"""

# Re-export from dind-tests helpers
# This allows tests to import from helpers.* consistently
import sys
from pathlib import Path

# Add dind-tests helpers to path
dind_helpers = Path(__file__).parent.parent.parent / "dind-tests" / "helpers"
if dind_helpers.exists() and str(dind_helpers.parent) not in sys.path:
    sys.path.insert(0, str(dind_helpers.parent))

try:
    from helpers.cli import run_abox, run_agentctl
    from helpers.docker import (
        run_docker,
        container_exists,
        container_is_running,
        wait_for_container_ready,
        get_container_ip,
        exec_in_container,
        get_container_logs,
        remove_container,
        create_network,
        remove_network,
    )
    from helpers.config import update_project_config
    from helpers.git import (
        init_git_repo,
        get_current_branch,
        list_branches,
        list_worktrees,
        add_worktree,
        remove_worktree,
    )
except ImportError:
    # Helpers not available (e.g., running outside test context)
    pass
