#!/usr/bin/env python3
"""AgentCtl MCP Server (FastMCP Implementation)

Expose agentctl functionality to AI agents using the FastMCP framework.
This provides worktree management, session switching, and autonomous agent operations.
"""

import os
import socket
import subprocess
import json
from typing import Optional, Literal
from fastmcp import FastMCP

try:
    import yaml
except ImportError:
    yaml = None

# Initialize FastMCP server
mcp = FastMCP(
    name="agentctl",
    instructions="""AgentCtl MCP server for git worktree and tmux session management.

IMPORTANT: At the start of every conversation (including after /clear),
you MUST call the `bootstrap_context` tool to load your working environment.
This ensures you always have the correct context about your session, branch, and workspace."""
)


# ============================================================================
# Helper Functions
# ============================================================================

def get_tmux_socket() -> Optional[str]:
    """Get the tmux socket path from TMUX environment variable.

    TMUX env var format: /path/to/socket,pid,session_index
    Returns the socket path or None if not in tmux.
    """
    tmux_env = os.environ.get("TMUX")
    if tmux_env:
        # Extract socket path (first comma-separated field)
        return tmux_env.split(",")[0]
    return None


def tmux_cmd(args: list[str]) -> list[str]:
    """Build tmux command with socket if available.

    Ensures all tmux commands use the same server as the current session.
    """
    socket = get_tmux_socket()
    if socket:
        return ["tmux", "-S", socket] + args
    return ["tmux"] + args


def get_current_session_info() -> dict:
    """Get current session information"""
    info = {
        "name": None,
        "agent_type": None,
        "working_dir": None,
        "super_mode": False
    }

    # Check for super mode via environment variable (set by super* wrapper scripts)
    info["super_mode"] = os.environ.get("BOXCTL_SUPER_MODE", "").lower() in ("true", "1", "yes")

    # Get session name
    if os.environ.get("TMUX"):
        try:
            result = subprocess.run(
                tmux_cmd(["display-message", "-p", "#S"]),
                capture_output=True,
                text=True,
                check=True
            )
            info["name"] = result.stdout.strip()
        except:
            pass

    # Infer agent type from session name
    # Check for super variants first (longer strings first for proper matching)
    if info["name"]:
        for agent in ["superclaude", "supercodex", "supergemini", "superqwen", "claude", "codex", "gemini", "qwen", "shell"]:
            if agent in info["name"]:
                info["agent_type"] = agent
                # Also infer super_mode from session name if not set via env
                if not info["super_mode"] and agent.startswith("super"):
                    info["super_mode"] = True
                break
        if not info["agent_type"]:
            info["agent_type"] = "claude"  # Default

    # Get current working directory
    info["working_dir"] = os.getcwd()

    return info


def branch_exists(branch: str) -> tuple[bool, bool]:
    """Check if branch exists locally or remotely

    Returns:
        (exists_locally, exists_remotely)
    """
    local = False
    remote = False

    # Check local
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
            check=False
        )
        local = result.returncode == 0
    except:
        pass

    # Check remote
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch],
            capture_output=True,
            text=True,
            check=False
        )
        remote = bool(result.stdout.strip())
    except:
        pass

    return local, remote


def get_worktree_for_branch(branch: str) -> Optional[str]:
    """Check if worktree exists for branch

    Returns:
        Worktree path if exists, None otherwise
    """
    try:
        result = subprocess.run(
            ["agentctl", "worktree", "list", "--json"],
            capture_output=True,
            text=True,
            check=True
        )

        data = json.loads(result.stdout)
        worktrees = data.get("worktrees", [])

        for wt in worktrees:
            if wt.get("branch") == branch:
                return wt.get("path")

    except:
        pass

    return None


def setup_worktree_configs(worktree_path: str) -> tuple[bool, str]:
    """Setup .boxctl for worktree with symlinks to shared project configs

    Creates symlinks to shared project files in /workspace/.boxctl.
    Agent configs are in home directories (shared across worktrees).

    Args:
        worktree_path: Path to the worktree

    Returns:
        (success, error_message)
    """
    try:
        # Source and destination paths
        source_boxctl = "/workspace/.boxctl"
        dest_boxctl = f"{worktree_path}/.boxctl"

        # Skip if already configured
        if os.path.exists(f"{dest_boxctl}/agents.md"):
            return True, ""

        # Create directory structure
        os.makedirs(dest_boxctl, exist_ok=True)

        # Symlink shared project files (not agent configs - those are in ~/.claude etc)
        symlinks = [
            ("agents.md", f"{dest_boxctl}/agents.md"),
            ("superagents.md", f"{dest_boxctl}/superagents.md"),
            ("skills", f"{dest_boxctl}/skills"),
            ("mcp", f"{dest_boxctl}/mcp"),
            ("mcp-meta.json", f"{dest_boxctl}/mcp-meta.json"),
            (".gitignore", f"{dest_boxctl}/.gitignore"),
        ]

        for source_rel, dest in symlinks:
            source = f"{source_boxctl}/{source_rel}"
            if os.path.exists(source) and not os.path.exists(dest):
                os.symlink(source, dest)

        return True, ""

    except Exception as e:
        return False, f"Failed to setup worktree configs: {str(e)}"


def create_worktree_helper(branch: str, create_new: bool) -> tuple[bool, str, str]:
    """Create worktree for branch

    Args:
        branch: Branch name
        create_new: Whether to create new branch if it doesn't exist

    Returns:
        (success, path, error_message)
    """
    try:
        cmd = ["agentctl", "worktree", "add", branch]
        if create_new:
            cmd.append("--create")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return False, "", result.stderr

        # Get the created worktree path
        worktree_path = get_worktree_for_branch(branch)
        if not worktree_path:
            return False, "", "Failed to find created worktree"

        # Setup configs for the worktree
        success, error = setup_worktree_configs(worktree_path)
        if not success:
            return False, worktree_path, error

        return True, worktree_path, ""

    except Exception as e:
        return False, "", str(e)


def _configure_tmux_session(session_name: str, branch: str, agent_type: str) -> None:
    """Apply tmux configuration to match boxctl-created sessions.

    This ensures sessions created via agentctl have the same look and feel
    as sessions created via 'boxctl superclaude'.
    """
    # Get container name from hostname
    container_name = socket.gethostname().replace("boxctl-", "")

    # Display name for status bar
    display = f"{branch} | {agent_type}"

    # Apply all tmux options (matching agent_commands.py)
    tmux_options = [
        # Status bar
        ["set-option", "-t", session_name, "status", "on"],
        ["set-option", "-t", session_name, "status-position", "top"],
        ["set-option", "-t", session_name, "status-style", "bg=colour226,fg=colour232"],
        ["set-option", "-t", session_name, "status-left", f" BOXCTL {container_name} | {display} "],
        ["set-option", "-t", session_name, "status-right", ""],
        # Mouse and history
        ["set-option", "-t", session_name, "mouse", "off"],
        ["set-option", "-t", session_name, "history-limit", "50000"],
        # Pane border
        ["set-option", "-t", session_name, "pane-border-status", "top"],
        ["set-option", "-t", session_name, "pane-border-style", "fg=colour226"],
        ["set-option", "-t", session_name, "pane-border-format", f" BOXCTL {container_name} | {display} "],
    ]

    # Key bindings (global, not session-specific)
    tmux_bindings = [
        ["bind-key", "-n", "PPage", "copy-mode", "-eu"],
        ["bind-key", "-T", "copy-mode", "PPage", "send-keys", "-X", "page-up"],
        ["bind-key", "-T", "copy-mode", "NPage", "send-keys", "-X", "page-down"],
        ["bind-key", "-T", "copy-mode-vi", "PPage", "send-keys", "-X", "page-up"],
        ["bind-key", "-T", "copy-mode-vi", "NPage", "send-keys", "-X", "page-down"],
    ]

    # Apply session options
    for opt in tmux_options:
        subprocess.run(tmux_cmd(opt), capture_output=True, check=False)

    # Apply key bindings
    for binding in tmux_bindings:
        subprocess.run(tmux_cmd(binding), capture_output=True, check=False)


def spawn_session_in_worktree(worktree_path: str, agent_type: str, branch: str) -> tuple[bool, str, str]:
    """Spawn a new tmux session in the worktree

    Args:
        worktree_path: Path to worktree
        agent_type: Type of agent (claude, codex, etc.)
        branch: Branch name (for session naming)

    Returns:
        (success, session_name, error_message)
    """
    try:
        # Sanitize branch name for session name
        sanitized_branch = branch.replace("/", "-").replace(".", "-")
        session_name = f"{sanitized_branch}-{agent_type}"

        # Check if session already exists
        result = subprocess.run(
            tmux_cmd(["has-session", "-t", session_name]),
            capture_output=True,
            check=False
        )

        if result.returncode == 0:
            # Session already exists, just return it
            return True, session_name, ""

        # Get agent command with proper configuration flags
        # MCP config is user-scoped at ~/.mcp.json
        agent_commands = {
            "claude": "/usr/local/bin/claude --settings /home/abox/.claude/settings.json --mcp-config /home/abox/.mcp.json",
            "superclaude": "/usr/local/bin/claude --settings /home/abox/.claude/settings-super.json --mcp-config /home/abox/.mcp.json --dangerously-skip-permissions",
            "codex": "/usr/local/bin/codex",
            "supercodex": "/usr/local/bin/codex --dangerously-bypass-approvals-and-sandbox",
            "gemini": "/usr/local/bin/gemini",
            "supergemini": "/usr/local/bin/gemini --non-interactive",
            "shell": "/bin/bash"
        }
        command = agent_commands.get(agent_type, "/usr/local/bin/claude")

        # Preserve SSH_AUTH_SOCK for SSH agent forwarding in new sessions
        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK")
        if ssh_auth_sock:
            # Set SSH_AUTH_SOCK in tmux global environment
            subprocess.run(
                tmux_cmd(["set-environment", "-g", "SSH_AUTH_SOCK", ssh_auth_sock]),
                capture_output=True,
                check=False
            )

        # Create new session in worktree directory
        # Use /bin/bash -lc to ensure shell configuration and environment are sourced
        result = subprocess.run(
            tmux_cmd(["new-session", "-d", "-s", session_name, "-c", worktree_path, "/bin/bash", "-lc", command]),
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return False, "", f"Failed to create session: {result.stderr}"

        # Apply tmux configuration to match boxctl-created sessions
        _configure_tmux_session(session_name, sanitized_branch, agent_type)

        return True, session_name, ""

    except Exception as e:
        return False, "", str(e)


def get_git_status(worktree_path: str) -> dict:
    """Get git status for worktree

    Returns:
        Dict with commit, uncommitted_changes, ahead, behind
    """
    status = {
        "commit": None,
        "uncommitted_changes": False,
        "ahead_remote": 0,
        "behind_remote": 0
    }

    try:
        # Get current commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        status["commit"] = result.stdout.strip()[:8]

        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        status["uncommitted_changes"] = bool(result.stdout.strip())

        # Check ahead/behind (this might fail if no upstream)
        try:
            result = subprocess.run(
                ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True
            )
            parts = result.stdout.strip().split()
            if len(parts) == 2:
                status["ahead_remote"] = int(parts[0])
                status["behind_remote"] = int(parts[1])
        except:
            pass

    except:
        pass

    return status


def get_git_info(cwd: str) -> dict:
    """Get git repository information

    Args:
        cwd: Working directory to check

    Returns:
        Dict with branch, commit, uncommitted_changes, recent_commits
    """
    info = {
        "branch": None,
        "commit": None,
        "uncommitted_changes": False,
        "recent_commits": []
    }

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        info["branch"] = result.stdout.strip()

        # Get current commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        info["commit"] = result.stdout.strip()[:8]

        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        info["uncommitted_changes"] = bool(result.stdout.strip())

        # Get recent commits (last 5)
        result = subprocess.run(
            ["git", "log", "-5", "--oneline"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        info["recent_commits"] = result.stdout.strip().splitlines()

    except subprocess.CalledProcessError:
        pass

    return info


# ============================================================================
# MCP Tools
# ============================================================================

@mcp.tool()
def switch_branch(
    branch: str,
    create_if_missing: bool = True,
    agent: Optional[str] = None
) -> dict:
    """Switch to work on a different git branch in an isolated environment.

    This tool creates a new git worktree for the branch (if needed) and spawns a new
    tmux session there. This allows working on multiple branches in parallel without
    conflicts. The new session will have the same agent type as the current session
    unless explicitly overridden.

    IMPORTANT: This tool CREATES the session but does NOT switch to it. You MUST call
    switch_session() afterwards to actually move into the new environment.

    Natural language triggers - use this tool when the user says:
    - "send me to <branch/feature>" or "go to <branch>"
    - "switch to <branch>" or "work on <feature>"
    - "create a session for <branch/agent>"
    - "open <agent> on <branch>" or "start <agent> session"
    - "I want to work on <feature>" or "let's work on <branch>"

    When to use: When you need to work on a different branch or feature in parallel.

    Args:
        branch: Name of the git branch to switch to (e.g., "feature/new-api")
        create_if_missing: If true, creates a new branch if it doesn't exist locally
                          or remotely (default: true)
        agent: Override the agent type for the new session. Options:
               - "claude": Standard Claude agent (requires approvals)
               - "superclaude": Auto-approve Claude agent (autonomous)
               - "codex", "supercodex": Alternative agents
               - "gemini", "supergemini": Alternative agents
               - "shell": Plain bash shell
               If not specified, uses the same agent type as current session.

    Returns:
        Dict with worktree_path, new_session name, branch, agent_type, and git status.
        Contains detailed message about next steps (calling switch_session).
    """
    try:
        # Step 1: Get current session info
        current = get_current_session_info()

        # Step 2: Determine which agent to use
        # Priority: explicit agent parameter > current agent type > default to claude
        if agent:
            agent_type = agent
        elif current["agent_type"]:
            agent_type = current["agent_type"]
        else:
            agent_type = "claude"

        # Validate agent type
        valid_agents = ["claude", "superclaude", "codex", "supercodex",
                       "gemini", "supergemini", "shell"]
        if agent_type not in valid_agents:
            return {
                "success": False,
                "error": f"Invalid agent type '{agent_type}'. Valid options: {', '.join(valid_agents)}"
            }

        # Step 3: Check if branch exists
        local_exists, remote_exists = branch_exists(branch)

        if not local_exists and not remote_exists and not create_if_missing:
            return {
                "success": False,
                "error": f"Branch '{branch}' not found. Set create_if_missing=true to create it."
            }

        # Step 4: Check if worktree exists for branch
        worktree_path = get_worktree_for_branch(branch)

        # Step 5: Create worktree if needed
        if not worktree_path:
            should_create_branch = not local_exists and not remote_exists
            success, worktree_path, error = create_worktree_helper(branch, should_create_branch)

            if not success:
                return {
                    "success": False,
                    "error": f"Failed to create worktree: {error}"
                }
        else:
            # Worktree exists, ensure it has proper configs
            success, error = setup_worktree_configs(worktree_path)
            if not success:
                # Non-fatal, log but continue
                pass

        # Step 6: Spawn new session in worktree
        success, new_session, error = spawn_session_in_worktree(
            worktree_path,
            agent_type,
            branch
        )

        if not success:
            return {
                "success": False,
                "error": f"Failed to spawn session: {error}"
            }

        # Step 7: Get git status
        git_status = get_git_status(worktree_path)

        # Step 8: Return rich context
        return {
            "success": True,
            "worktree_path": worktree_path,
            "branch": branch,
            "agent_type": agent_type,
            "old_session": current["name"],
            "new_session": new_session,
            **git_status,
            "message": f"✓ Created new '{agent_type}' session '{new_session}' for branch '{branch}' at {worktree_path}. "
                      f"\n\n"
                      f"⚠️  IMPORTANT: You are STILL in the OLD session '{current['name']}' at {current['working_dir']}. "
                      f"The new session has been CREATED but you have NOT switched to it yet. "
                      f"\n\n"
                      f"DO NOT work on files yet! You must call switch_session('{new_session}') first to move to the new environment. "
                      f"After switching, you will be in the new worktree with the correct branch checked out."
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def switch_session(session_name: str) -> dict:
    """Actually switch the agent into a different tmux session and working directory.

    This is the second step after switch_branch(). Calling this tool moves the agent's
    execution context into the new session, changing the working directory and environment.
    After calling this, all file operations will happen in the new worktree.

    Natural language triggers - use this tool when the user says:
    - "send me to <session>" or "go to <session>"
    - "switch to <session>" or "move to <session>"
    - "take me to <session>" or "jump to <session>"
    - "attach to <session>" or "connect to <session>"

    When to use: Immediately after switch_branch() to complete the branch switch, or
    anytime you need to move between existing sessions.

    Args:
        session_name: Name of the tmux session to switch to (get this from switch_branch
                      response or list_sessions)

    Returns:
        Dict with old_session, new_session, working_directory, and success status.
    """
    try:
        old_session = None

        # Try TMUX env var first (if running inside tmux)
        if os.environ.get("TMUX"):
            result = subprocess.run(
                tmux_cmd(["display-message", "-p", "#S"]),
                capture_output=True,
                text=True,
                check=True
            )
            old_session = result.stdout.strip()
        else:
            # MCP server runs as daemon, query tmux directly for attached session
            old_session, _ = _get_active_tmux_session()

        if not old_session:
            return {
                "success": False,
                "error": "Not in a tmux session. This tool only works from within tmux."
            }

        # Check if target session exists
        result = subprocess.run(
            tmux_cmd(["has-session", "-t", session_name]),
            capture_output=True,
            check=False
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Session '{session_name}' does not exist. Use list_sessions to see available sessions."
            }

        # Get working directory of target session
        result = subprocess.run(
            tmux_cmd(["display-message", "-p", "-t", session_name, "#{pane_current_path}"]),
            capture_output=True,
            text=True,
            check=True
        )
        working_directory = result.stdout.strip()

        # Switch to target session
        subprocess.run(
            tmux_cmd(["switch-client", "-t", session_name]),
            check=True
        )

        return {
            "success": True,
            "old_session": old_session,
            "new_session": session_name,
            "working_directory": working_directory,
            "message": f"✓ Switched to session '{session_name}'. You are now in {working_directory}."
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def detach_and_continue(task_description: str, branch: Optional[str] = None, notify_on_complete: bool = True) -> dict:
    """Detach from the current session so the agent continues working in the background.

    This disconnects the user's terminal from the tmux session while the agent keeps
    running autonomously. Perfect for long-running tasks or mobile use - the user can
    close their app and the agent will continue working and notify when complete.

    When to use: When starting a long task that should continue even if the user
    disconnects, or when working on mobile and need to close the app.

    IMPORTANT: If you want to switch branches first, call switch_branch and switch_session
    BEFORE calling this tool. Do not use the branch parameter.

    Args:
        task_description: Brief description of what you'll work on (used for logging/notifications)
        branch: DEPRECATED - do not use. Call switch_branch separately instead.
        notify_on_complete: If true, sends desktop notification when task completes (default: true)

    Returns:
        Dict with session name, worktree_path, branch, task description, and reconnect command.
    """
    try:
        session_name = None
        cwd = None

        # Try TMUX env var first (if running inside tmux)
        if os.environ.get("TMUX"):
            result = subprocess.run(
                tmux_cmd(["display-message", "-p", "#S"]),
                capture_output=True,
                text=True,
                check=True
            )
            session_name = result.stdout.strip()

            # Get working directory from tmux pane
            result = subprocess.run(
                tmux_cmd(["display-message", "-p", "#{pane_current_path}"]),
                capture_output=True,
                text=True,
                check=True
            )
            cwd = result.stdout.strip()
        else:
            # MCP server runs as daemon, query tmux directly for attached session
            session_name, cwd = _get_active_tmux_session()

        if not session_name:
            return {
                "success": False,
                "error": "Not in a tmux session. This tool only works from within tmux."
            }

        # Fallback for working directory
        if not cwd:
            cwd = os.getcwd()

        # If branch parameter provided, suggest switching first
        if branch:
            return {
                "success": False,
                "error": f"Please call switch_branch('{branch}') first, then call detach_and_continue again without the branch parameter.",
                "suggestion": f"Use switch_branch tool with branch='{branch}', then call detach_and_continue"
            }

        # Get current git info
        git_branch = None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True
            )
            git_branch = result.stdout.strip()
        except:
            pass

        # Determine worktree path
        is_worktree = cwd.startswith("/git-worktrees/")
        worktree_path = cwd if is_worktree else "/workspace"

        # Detach from tmux session
        subprocess.run(
            tmux_cmd(["detach-client"]),
            check=True
        )

        reconnect_command = f"abox shell {session_name}" if session_name != "claude" else "abox shell"

        return {
            "success": True,
            "session": session_name,
            "worktree_path": worktree_path,
            "branch": git_branch,
            "task": task_description,
            "notify_on_complete": notify_on_complete,
            "message": f"✓ Detached. Agent will continue working autonomously on '{task_description}'. "
                      f"You'll receive a notification when complete. "
                      f"Reconnect anytime with: {reconnect_command}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_worktrees() -> dict:
    """List all git worktrees (separate checkouts of different branches).

    Each worktree is an independent checkout of a specific branch, allowing you to
    work on multiple branches simultaneously without switching. This shows all existing
    worktrees with their paths, branches, commits, and creation times.

    When to use: To see what branches already have worktrees before calling switch_branch,
    or to find the path of an existing worktree.

    Returns:
        Dict with "worktrees" list, where each worktree has path, branch, commit,
        sessions (list of tmux sessions in that worktree), and created timestamp.
    """
    try:
        # Call agentctl worktree list --json
        result = subprocess.run(
            ["agentctl", "worktree", "list", "--json"],
            capture_output=True,
            text=True,
            check=True
        )

        # Parse JSON output
        data = json.loads(result.stdout)

        return {
            "success": True,
            **data  # Includes "worktrees" key
        }

    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Failed to list worktrees: {e.stderr}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_worktree(branch: str, create_branch: bool = False) -> dict:
    """Create a git worktree for a branch without switching to it.

    Creates an isolated checkout of the specified branch in a separate directory.
    This is useful for preparing a worktree in advance or for background operations.
    Unlike switch_branch, this does NOT create a tmux session or switch context.

    When to use: When you want to prepare a worktree for later use, or when another
    agent/process will work in that worktree.

    Args:
        branch: Name of the git branch to create a worktree for
        create_branch: If true, creates a new branch if it doesn't exist (default: false)

    Returns:
        Dict with worktree_path, branch, commit, and success status.
    """
    try:
        # Check if worktree already exists for this branch
        existing_path = get_worktree_for_branch(branch)
        if existing_path:
            # Ensure configs are set up (may have been created without them)
            setup_worktree_configs(existing_path)
            # Get git status for existing worktree
            git_status = get_git_status(existing_path)
            return {
                "success": True,
                "worktree_path": existing_path,
                "branch": branch,
                "already_existed": True,
                **git_status,
                "message": f"Worktree for branch '{branch}' already exists at {existing_path}"
            }

        # Check if branch exists
        local_exists, remote_exists = branch_exists(branch)

        if not local_exists and not remote_exists and not create_branch:
            return {
                "success": False,
                "error": f"Branch '{branch}' not found locally or remotely. Set create_branch=true to create it."
            }

        # Create the worktree
        should_create_branch = not local_exists and not remote_exists
        success, worktree_path, error = create_worktree_helper(branch, should_create_branch)

        if not success:
            return {
                "success": False,
                "error": f"Failed to create worktree: {error}"
            }

        # Get git status
        git_status = get_git_status(worktree_path)

        return {
            "success": True,
            "worktree_path": worktree_path,
            "branch": branch,
            "already_existed": False,
            **git_status,
            "message": f"Created worktree for branch '{branch}' at {worktree_path}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_sessions() -> dict:
    """List all tmux sessions (running agent instances).

    Each tmux session represents a running agent instance. This shows all active
    sessions with their names, window counts, and attachment status. Session names
    typically follow the pattern: {branch}-{agent-type} (e.g., "main-superclaude").

    When to use: To see what sessions exist before calling switch_session, or to
    find which sessions are currently running.

    Returns:
        Dict with "sessions" list, where each session has name, windows (count),
        attached (boolean), and created timestamp.
    """
    try:
        # Call agentctl list --json
        result = subprocess.run(
            ["agentctl", "list", "--json"],
            capture_output=True,
            text=True,
            check=True
        )

        # Parse JSON output
        data = json.loads(result.stdout)

        return {
            "success": True,
            **data  # Includes "sessions" key
        }

    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Failed to list sessions: {e.stderr}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _get_active_tmux_session() -> tuple:
    """Get the active tmux session and its working directory.

    Since the MCP server runs as a daemon, it doesn't have TMUX env var.
    Instead, we find the attached session by querying tmux directly.

    Returns:
        Tuple of (session_name, working_directory) or (None, None) if not found.
    """
    try:
        # List all sessions and find one that's attached
        result = subprocess.run(
            tmux_cmd(["list-sessions", "-F", "#{session_name}:#{session_attached}"]),
            capture_output=True,
            text=True,
            check=True
        )

        session = None
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] == "1":
                    session = parts[0]
                    break

        if not session:
            return None, None

        # Get the working directory from the active pane
        result = subprocess.run(
            tmux_cmd(["display-message", "-t", session, "-p", "#{pane_current_path}"]),
            capture_output=True,
            text=True,
            check=True
        )
        working_directory = result.stdout.strip()

        return session, working_directory

    except Exception:
        return None, None


@mcp.tool()
def set_session_task(task: str) -> dict:
    """Set a task label on the current tmux session name.

    Appends a task description to the session name to help identify what the agent
    is working on. The base session name (branch-agent) is preserved, with the task
    appended after @_ delimiter.

    Example: "main-superclaude" -> "main-superclaude@_auth-feature"

    Natural language triggers - use this tool when the user says:
    - "work on <task>" or "I'm working on <task>"
    - "start <task>" or "begin <task>"
    - "focus on <task>" or "let's do <task>"
    - "label this <task>" or "tag this session"

    When to use: When starting work on a specific task, to help users identify
    what each session is doing at a glance.

    Args:
        task: Short task description (will be sanitized - spaces become dashes,
              max 30 chars). Use descriptive names like "auth-feature", "fix-bug-123",
              "refactor-api".

    Returns:
        Dict with old_name, new_name, and success status.
    """
    try:
        # Get current session info
        session = None

        if os.environ.get("TMUX"):
            result = subprocess.run(
                tmux_cmd(["display-message", "-p", "#S"]),
                capture_output=True,
                text=True,
                check=True
            )
            session = result.stdout.strip()
        else:
            # MCP server runs as daemon, find attached session
            session, _ = _get_active_tmux_session()

        if not session:
            return {
                "success": False,
                "error": "Could not determine current tmux session"
            }

        # Extract base name (remove any existing task suffix)
        base_name = session.split("@_")[0]

        # Sanitize task label
        sanitized_task = task.strip()
        sanitized_task = sanitized_task.replace(" ", "-")
        sanitized_task = sanitized_task.replace("/", "-")
        sanitized_task = sanitized_task.replace(".", "-")
        sanitized_task = sanitized_task.replace(":", "-")
        sanitized_task = sanitized_task.replace("@", "-")
        sanitized_task = sanitized_task[:30]  # Max 30 chars

        # Build new session name
        new_name = f"{base_name}@_{sanitized_task}" if sanitized_task else base_name

        # Rename the session
        result = subprocess.run(
            tmux_cmd(["rename-session", "-t", session, new_name]),
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to rename session: {result.stderr}"
            }

        return {
            "success": True,
            "old_name": session,
            "new_name": new_name,
            "base_name": base_name,
            "task": sanitized_task,
            "message": f"Session renamed: {session} -> {new_name}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def clear_session_task() -> dict:
    """Remove the task label from the current session name.

    Reverts the session name back to its base form (branch-agent).

    Example: "main-superclaude@_auth-feature" -> "main-superclaude"

    Natural language triggers - use this tool when the user says:
    - "done with this task" or "finished with <task>"
    - "clear the task" or "clear session label"
    - "move on" or "next task"
    - "reset session name" or "remove task label"

    When to use: When finishing a task and moving to something else, or to
    clean up the session name.

    Returns:
        Dict with old_name, new_name, and success status.
    """
    try:
        # Get current session info
        session = None

        if os.environ.get("TMUX"):
            result = subprocess.run(
                tmux_cmd(["display-message", "-p", "#S"]),
                capture_output=True,
                text=True,
                check=True
            )
            session = result.stdout.strip()
        else:
            # MCP server runs as daemon, find attached session
            session, _ = _get_active_tmux_session()

        if not session:
            return {
                "success": False,
                "error": "Could not determine current tmux session"
            }

        # Extract base name (remove any existing task suffix)
        base_name = session.split("@_")[0]

        # If no task suffix, nothing to do
        if "@_" not in session:
            return {
                "success": True,
                "old_name": session,
                "new_name": session,
                "message": "Session has no task label to clear"
            }

        # Rename the session back to base
        result = subprocess.run(
            tmux_cmd(["rename-session", "-t", session, base_name]),
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to rename session: {result.stderr}"
            }

        return {
            "success": True,
            "old_name": session,
            "new_name": base_name,
            "message": f"Task label cleared: {session} -> {base_name}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_current_context() -> dict:
    """Get complete information about where the agent is currently working.

    Returns the current tmux session name, working directory, git branch, commit hash,
    whether you're in a worktree, and if there are uncommitted changes. Use this to
    understand your current environment before making changes.

    When to use: At the start of a task, after switching sessions, or when you need
    to verify which branch/worktree you're in.

    Returns:
        Dict with session, working_directory, worktree_path, is_worktree, branch,
        commit, uncommitted_changes, and recent_commits.
    """
    try:
        session = None
        working_directory = None

        # Get current session and working directory from tmux
        # Try TMUX env var first (if running inside tmux), then query tmux directly
        if os.environ.get("TMUX"):
            try:
                # Get session name
                result = subprocess.run(
                    tmux_cmd(["display-message", "-p", "#S"]),
                    capture_output=True,
                    text=True,
                    check=True
                )
                session = result.stdout.strip()

                # Get actual working directory from tmux pane
                # This returns the real cwd of the agent's shell, not the MCP server's cwd
                result = subprocess.run(
                    tmux_cmd(["display-message", "-p", "#{pane_current_path}"]),
                    capture_output=True,
                    text=True,
                    check=True
                )
                working_directory = result.stdout.strip()
            except:
                pass
        else:
            # MCP server runs as daemon, query tmux directly for attached session
            session, working_directory = _get_active_tmux_session()

        # Fallback to /workspace if not in tmux or tmux query failed
        if not working_directory:
            # Try /workspace first (standard boxctl location), then fall back to process cwd
            if os.path.isdir("/workspace") and os.path.isdir("/workspace/.git"):
                working_directory = "/workspace"
            else:
                working_directory = os.getcwd()

        # Determine if we're in a worktree
        is_worktree = working_directory.startswith("/git-worktrees/")
        worktree_path = working_directory if is_worktree else "/workspace"

        # Get git information from the actual working directory
        git_info = get_git_info(working_directory)

        # Check for super mode
        session_info = get_current_session_info()

        return {
            "success": True,
            "session": session,
            "super_mode": session_info.get("super_mode", False),
            "working_directory": working_directory,
            "worktree_path": worktree_path,
            "is_worktree": is_worktree,
            **git_info
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def bootstrap_context() -> dict:
    """Load essential context at conversation start.

    THIS IS A TEST TOOL to verify if agents follow MCP instructions.
    The MCP instructions tell agents to call this at every conversation start.

    If you're seeing this, it means:
    1. The agent read the MCP instructions
    2. The agent followed the instruction to call this tool
    3. MCP instructions CAN be used for bootstrap behavior

    Returns:
        Dict with test confirmation and basic context.
    """
    import datetime

    session_info = get_current_session_info()
    cwd = os.getcwd()

    return {
        "success": True,
        "test_confirmation": "✓ BOOTSTRAP TEST PASSED - Agent followed MCP instructions!",
        "timestamp": datetime.datetime.now().isoformat(),
        "session": session_info.get("name"),
        "agent_type": session_info.get("agent_type"),
        "super_mode": session_info.get("super_mode", False),
        "working_directory": cwd,
        "message": "If you see this, the agent proactively called bootstrap_context based on MCP instructions."
    }


# ============================================================================
# Usage / Rate Limit Tools
# ============================================================================

def _send_usage_request(action: str, payload: dict) -> Optional[dict]:
    """Send a usage request to the container client's local IPC socket.

    Returns:
        Response dict if successful, None if unavailable.
    """
    from pathlib import Path
    import socket as sock

    ipc_socket = Path("/tmp/boxctl-local.sock")
    if not ipc_socket.exists():
        return None

    try:
        with sock.socket(sock.AF_UNIX, sock.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect(str(ipc_socket))

            request = {"action": action, **payload}
            s.sendall((json.dumps(request) + "\n").encode())

            # Read response
            data = b""
            while b"\n" not in data and len(data) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk

            if data:
                return json.loads(data.decode().strip())
            return None
    except (OSError, sock.timeout):
        return None


@mcp.tool()
def check_agent_available(agent: str) -> dict:
    """Check if an agent is available (not rate-limited).

    Use this before launching an agent to see if it's available or rate-limited.
    If the agent is limited, consider using an alternative.

    Args:
        agent: Agent name (e.g., "superclaude", "supercodex", "supergemini")

    Returns:
        Dict with available (bool), resets_at (if limited), and fallback suggestion.
    """
    # Try service first
    response = _send_usage_request("check_agent", {"agent": agent})

    if response and response.get("ok"):
        available = response.get("available", True)
        result = {
            "agent": agent,
            "available": available,
            "resets_at": response.get("resets_at"),
        }

        # Suggest fallback if not available
        if not available:
            fallback_chains = {
                "superclaude": ["supercodex", "supergemini", "superqwen"],
                "supercodex": ["superclaude", "supergemini", "superqwen"],
                "supergemini": ["superclaude", "supercodex", "superqwen"],
                "superqwen": ["superclaude", "supercodex", "supergemini"],
            }
            chain = fallback_chains.get(agent, [])
            for fb in chain:
                fb_response = _send_usage_request("check_agent", {"agent": fb})
                if fb_response and fb_response.get("available"):
                    result["suggested_fallback"] = fb
                    break

        return result

    # Fallback to local state check
    try:
        from boxctl.usage.client import is_agent_available, get_fallback_agent
        available = is_agent_available(agent)
        result = {"agent": agent, "available": available}
        if not available:
            fallback, _ = get_fallback_agent(agent)
            if fallback != agent:
                result["suggested_fallback"] = fallback
        return result
    except ImportError:
        return {"agent": agent, "available": True, "note": "usage module not available"}


@mcp.tool()
def get_agent_status() -> dict:
    """Get rate limit status of all agents.

    Shows which agents are available and which are rate-limited,
    including when limits are expected to reset.

    Returns:
        Dict with status for each agent (available, limited, resets_at, resets_in).
    """
    # Try service first
    response = _send_usage_request("get_usage_status", {})

    if response and response.get("ok"):
        return {
            "source": "service",
            "agents": response.get("status", {}),
        }

    # Fallback to local state
    try:
        from boxctl.usage.client import get_usage_status
        return {
            "source": "local",
            "agents": get_usage_status(),
        }
    except ImportError:
        return {
            "source": "none",
            "agents": {},
            "note": "usage module not available",
        }


@mcp.tool()
def report_agent_limit(
    agent: str,
    resets_in_seconds: Optional[int] = None,
    error_type: Optional[str] = None,
) -> dict:
    """Report that an agent hit a rate limit.

    Call this when you detect a rate limit error from an agent.
    The information will be stored and used for fallback decisions.

    Args:
        agent: Agent name (e.g., "superclaude", "supercodex")
        resets_in_seconds: Seconds until limit resets (if known from error)
        error_type: Type of error (e.g., "rate_limit", "usage_limit_reached")

    Returns:
        Dict with ok status.
    """
    # Calculate resets_at from resets_in_seconds
    resets_at = None
    if resets_in_seconds:
        from datetime import datetime, timezone, timedelta
        resets_at = (datetime.now(timezone.utc) + timedelta(seconds=resets_in_seconds)).isoformat()

    # Try service first
    response = _send_usage_request("report_rate_limit", {
        "agent": agent,
        "limited": True,
        "resets_at": resets_at,
        "resets_in_seconds": resets_in_seconds,
        "error_type": error_type,
    })

    if response and response.get("ok"):
        return {"ok": True, "reported_to": "service"}

    # Fallback to local state
    try:
        from boxctl.usage.client import report_rate_limit
        report_rate_limit(agent, resets_in_seconds, error_type)
        return {"ok": True, "reported_to": "local"}
    except ImportError:
        return {"ok": False, "error": "usage module not available"}


@mcp.tool()
def clear_agent_limit(agent: str) -> dict:
    """Clear rate limit state for an agent.

    Use this when you know a limit has reset or to clear stale state.

    Args:
        agent: Agent name to clear

    Returns:
        Dict with ok status.
    """
    # Try service first
    response = _send_usage_request("clear_rate_limit", {"agent": agent})

    if response and response.get("ok"):
        return {"ok": True, "cleared_from": "service"}

    # Fallback to local state
    try:
        from boxctl.usage.client import clear_rate_limit
        clear_rate_limit(agent)
        return {"ok": True, "cleared_from": "local"}
    except ImportError:
        return {"ok": False, "error": "usage module not available"}


# ============================================================================
# Dependency Management Tools
# ============================================================================

# Type alias for package managers
PackageManager = Literal["npm", "pip", "apt", "cargo", "post"]

# Config file path - use workspace config for project dependencies
CONFIG_PATH = "/workspace/.boxctl/config.yml"


def _load_config() -> tuple[Optional[dict], Optional[str]]:
    """Load the boxctl config file.

    Returns:
        (config_dict, error_message) - config is None on error
    """
    if yaml is None:
        return None, "PyYAML not installed. Cannot manage dependencies."

    if not os.path.exists(CONFIG_PATH):
        return None, f"Config file not found at {CONFIG_PATH}"

    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
        return config, None
    except Exception as e:
        return None, f"Failed to read config: {str(e)}"


def _save_config(config: dict) -> Optional[str]:
    """Save the boxctl config file.

    Returns:
        Error message on failure, None on success
    """
    if yaml is None:
        return "PyYAML not installed. Cannot manage dependencies."

    try:
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        return None
    except Exception as e:
        return f"Failed to write config: {str(e)}"


def _ensure_packages_section(config: dict) -> None:
    """Ensure the packages section exists with all managers."""
    if "packages" not in config:
        config["packages"] = {}

    managers = ["npm", "pip", "apt", "cargo", "post"]
    for manager in managers:
        if manager not in config["packages"]:
            config["packages"][manager] = []


@mcp.tool()
def add_dependency(
    package: str,
    manager: PackageManager,
) -> dict:
    """Add a project dependency to the boxctl config file.

    Adds a package to the specified package manager's list in the project config.
    These dependencies will be installed when the container is built or rebased.

    Syntax examples for each manager:
    - npm: "lodash", "typescript@^5.0.0", "express@latest"
    - pip: "requests", "django>=4.0", "flask[async]"
    - apt: "curl", "build-essential", "libssl-dev"
    - cargo: "ripgrep", "fd-find", "tokei"
    - post: Shell commands to run after other packages install, e.g., "npm install -g pnpm"

    Natural language triggers:
    - "add <package> dependency" or "install <package>"
    - "I need <package>" or "add <package> to the project"
    - "configure <package> for this project"

    Args:
        package: Package name with optional version specifier (syntax depends on manager)
        manager: Package manager - one of: npm, pip, apt, cargo, post

    Returns:
        Dict with success status and updated dependency list.
    """
    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    _ensure_packages_section(config)

    packages_list = config["packages"][manager]

    # Check if already present
    if package in packages_list:
        return {
            "success": True,
            "already_present": True,
            "manager": manager,
            "package": package,
            "packages": packages_list,
            "message": f"Package '{package}' already in {manager} dependencies"
        }

    # Add the package
    packages_list.append(package)

    # Save config
    error = _save_config(config)
    if error:
        return {"success": False, "error": error}

    return {
        "success": True,
        "added": True,
        "manager": manager,
        "package": package,
        "packages": packages_list,
        "message": f"Added '{package}' to {manager} dependencies. "
                  f"Run 'abox rebase' on the host to install."
    }


@mcp.tool()
def remove_dependency(
    package: str,
    manager: PackageManager,
) -> dict:
    """Remove a project dependency from the boxctl config file.

    Removes a package from the specified package manager's list in the project config.

    Natural language triggers:
    - "remove <package>" or "uninstall <package>"
    - "I don't need <package> anymore"
    - "delete <package> dependency"

    Args:
        package: Package name to remove (must match exactly as it was added)
        manager: Package manager - one of: npm, pip, apt, cargo, post

    Returns:
        Dict with success status and updated dependency list.
    """
    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    _ensure_packages_section(config)

    packages_list = config["packages"][manager]

    # Check if present
    if package not in packages_list:
        return {
            "success": True,
            "not_found": True,
            "manager": manager,
            "package": package,
            "packages": packages_list,
            "message": f"Package '{package}' not found in {manager} dependencies"
        }

    # Remove the package
    packages_list.remove(package)

    # Save config
    error = _save_config(config)
    if error:
        return {"success": False, "error": error}

    return {
        "success": True,
        "removed": True,
        "manager": manager,
        "package": package,
        "packages": packages_list,
        "message": f"Removed '{package}' from {manager} dependencies. "
                  f"Note: Already-installed packages remain until container rebuild."
    }


@mcp.tool()
def list_dependencies() -> dict:
    """List all project dependencies from the boxctl config file.

    Shows all packages configured for each package manager (npm, pip, apt, cargo, post).

    Natural language triggers:
    - "what dependencies are configured?"
    - "show project packages" or "list dependencies"
    - "what packages does this project need?"

    Returns:
        Dict with all configured dependencies by manager.
    """
    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    _ensure_packages_section(config)

    packages = config.get("packages", {})

    # Count total
    total = sum(len(pkgs) for pkgs in packages.values() if isinstance(pkgs, list))

    return {
        "success": True,
        "packages": packages,
        "total_count": total,
        "config_path": CONFIG_PATH,
        "message": f"Found {total} configured dependencies across all managers"
    }


@mcp.tool()
def set_dependencies(
    packages: list[str],
    manager: PackageManager,
) -> dict:
    """Replace all dependencies for a package manager.

    Completely replaces the dependency list for the specified manager.
    Use this when you want to set an exact list rather than add/remove individually.

    Args:
        packages: List of packages (replaces existing list entirely)
        manager: Package manager - one of: npm, pip, apt, cargo, post

    Returns:
        Dict with success status and new dependency list.
    """
    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    _ensure_packages_section(config)

    old_packages = config["packages"][manager].copy()
    config["packages"][manager] = packages

    # Save config
    error = _save_config(config)
    if error:
        return {"success": False, "error": error}

    return {
        "success": True,
        "manager": manager,
        "old_packages": old_packages,
        "new_packages": packages,
        "message": f"Replaced {manager} dependencies: {len(old_packages)} -> {len(packages)} packages. "
                  f"Run 'abox rebase' on the host to apply changes."
    }


# ============================================================================
# Environment Variable Tools
# ============================================================================

# Blocklist of env vars that should not be modified by agents (security/stability)
ENV_BLOCKLIST = {
    # System paths and identity
    "PATH", "HOME", "USER", "SHELL", "PWD", "OLDPWD", "TERM", "LANG", "LC_ALL",
    # Boxctl internal
    "BOXCTL_PROJECT_DIR", "BOXCTL_SUPER_MODE", "BOXCTL_CONTAINER",
    # SSH/credentials
    "SSH_AUTH_SOCK", "SSH_AGENT_PID", "GPG_AGENT_INFO",
    # Docker
    "DOCKER_HOST", "DOCKER_CONFIG",
    # Potentially dangerous
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_PATH",
}


def _validate_env_key(key: str) -> tuple[bool, Optional[str]]:
    """Validate an environment variable key.

    Returns:
        (is_valid, error_message)
    """
    if not key:
        return False, "Key cannot be empty"

    if key in ENV_BLOCKLIST:
        return False, f"Cannot modify protected variable '{key}'"

    # Key must be valid env var name (letters, digits, underscore, not starting with digit)
    if not key.replace("_", "").isalnum():
        return False, f"Invalid key '{key}': must contain only letters, digits, and underscores"

    if key[0].isdigit():
        return False, f"Invalid key '{key}': cannot start with a digit"

    return True, None


@mcp.tool()
def set_env(key: str, value: str) -> dict:
    """Set a project environment variable in the boxctl config.

    Sets an environment variable that will be available in the container.
    Changes take effect after 'abox rebase' on the host.

    Common use cases:
    - NODE_ENV=development, NODE_ENV=production
    - DEBUG=true, DEBUG=1
    - API_URL=https://api.example.com
    - LOG_LEVEL=debug

    Note: Some system variables are protected and cannot be modified (PATH, HOME, etc.)

    Natural language triggers:
    - "set NODE_ENV to production"
    - "add environment variable DEBUG=true"
    - "configure API_URL"

    Args:
        key: Environment variable name (e.g., "NODE_ENV")
        value: Value to set (e.g., "production")

    Returns:
        Dict with success status and current env vars.
    """
    # Validate key
    valid, error = _validate_env_key(key)
    if not valid:
        return {"success": False, "error": error}

    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    # Ensure env section exists
    if "env" not in config:
        config["env"] = {}

    old_value = config["env"].get(key)
    config["env"][key] = value

    # Save config
    error = _save_config(config)
    if error:
        return {"success": False, "error": error}

    action = "Updated" if old_value is not None else "Set"
    return {
        "success": True,
        "key": key,
        "value": value,
        "old_value": old_value,
        "env": config["env"],
        "message": f"{action} {key}={value}. Run 'abox rebase' on the host to apply."
    }


@mcp.tool()
def remove_env(key: str) -> dict:
    """Remove a project environment variable from the boxctl config.

    Removes an environment variable from the project configuration.
    The variable will no longer be set in new container sessions after rebase.

    Natural language triggers:
    - "remove DEBUG env var"
    - "unset NODE_ENV"
    - "delete environment variable API_URL"

    Args:
        key: Environment variable name to remove

    Returns:
        Dict with success status and current env vars.
    """
    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    env = config.get("env", {})

    if key not in env:
        return {
            "success": True,
            "not_found": True,
            "key": key,
            "env": env,
            "message": f"Environment variable '{key}' not found in config"
        }

    old_value = env.pop(key)
    config["env"] = env

    # Save config
    error = _save_config(config)
    if error:
        return {"success": False, "error": error}

    return {
        "success": True,
        "removed": True,
        "key": key,
        "old_value": old_value,
        "env": env,
        "message": f"Removed {key}. Run 'abox rebase' on the host to apply."
    }


@mcp.tool()
def list_env() -> dict:
    """List all project environment variables from the boxctl config.

    Shows all environment variables configured for this project.

    Natural language triggers:
    - "what env vars are set?"
    - "show environment variables"
    - "list project environment"

    Returns:
        Dict with all configured environment variables.
    """
    config, error = _load_config()
    if error:
        return {"success": False, "error": error}

    env = config.get("env", {})

    return {
        "success": True,
        "env": env,
        "count": len(env),
        "config_path": CONFIG_PATH,
        "message": f"Found {len(env)} configured environment variables"
    }


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AgentCtl MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport mode: stdio (default) or sse"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "9100")),
        help="Port for SSE transport (default: 9100)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="Host for SSE transport (default: 127.0.0.1)"
    )

    args = parser.parse_args()

    if args.transport == "sse":
        # Run with SSE transport for pre-started server mode
        mcp.run(transport="sse", host=args.host, port=args.port, show_banner=False)
    else:
        # Default stdio transport (spawned by client)
        mcp.run()
