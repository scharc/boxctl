"""Worktree utilities for git operations and path management"""

import os
import re
import subprocess
from typing import List, Dict, Optional


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for use as worktree directory name.

    Args:
        branch: Branch name (may include refs/heads/ prefix)

    Returns:
        Sanitized name suitable for directory name

    Examples:
        feature/auth-fix -> feature-auth-fix
        refs/heads/main -> main
        my.branch -> my-branch
    """
    # Remove refs/heads/ prefix if present
    if branch.startswith("refs/heads/"):
        branch = branch[len("refs/heads/") :]

    # Replace special characters with hyphens
    sanitized = re.sub(r"[/\.]", "-", branch)

    # Remove any characters that aren't alphanumeric, hyphens, or underscores
    sanitized = re.sub(r"[^a-zA-Z0-9\-_]", "", sanitized)

    return sanitized


def get_worktree_path(branch: str, base_dir: str = "/git-worktrees") -> str:
    """Get the full path for a worktree.

    Args:
        branch: Branch name
        base_dir: Base directory for worktrees (default: /git-worktrees)

    Returns:
        Full path to worktree directory
    """
    sanitized = sanitize_branch_name(branch)
    return os.path.join(base_dir, f"worktree-{sanitized}")


def run_git_command(args: List[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Run a git command and return exit code, stdout, stderr.

    Args:
        args: Git command arguments (e.g., ['worktree', 'list'])
        cwd: Working directory (default: /workspace)

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    if cwd is None:
        cwd = "/workspace"

    try:
        result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Git command timed out"
    except Exception as e:
        return 1, "", str(e)


def list_git_worktrees() -> List[Dict[str, str]]:
    """List all git worktrees.

    Returns:
        List of worktree dictionaries with 'path', 'branch', 'commit' keys
    """
    exit_code, stdout, stderr = run_git_command(["worktree", "list", "--porcelain"])

    if exit_code != 0:
        return []

    worktrees = []
    current = {}

    for line in stdout.strip().split("\n"):
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue

        if line.startswith("worktree "):
            current["path"] = line[9:]  # Remove "worktree " prefix
        elif line.startswith("HEAD "):
            current["commit"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]  # Remove "branch " prefix
            # Remove refs/heads/ prefix if present
            if current["branch"].startswith("refs/heads/"):
                current["branch"] = current["branch"][11:]
        elif line.startswith("detached"):
            current["branch"] = "(detached)"

    # Add last worktree if exists
    if current:
        worktrees.append(current)

    return worktrees


def worktree_exists(path: str) -> bool:
    """Check if a worktree exists at the given path.

    Args:
        path: Path to check

    Returns:
        True if worktree exists
    """
    worktrees = list_git_worktrees()
    return any(wt.get("path") == path for wt in worktrees)


def branch_exists(branch: str) -> bool:
    """Check if a git branch exists.

    Args:
        branch: Branch name to check

    Returns:
        True if branch exists locally or remotely
    """
    # Check local branches
    exit_code, stdout, _ = run_git_command(["branch", "--list", branch])
    if exit_code == 0 and stdout.strip():
        return True

    # Check remote branches
    exit_code, stdout, _ = run_git_command(["branch", "-r", "--list", f"origin/{branch}"])
    if exit_code == 0 and stdout.strip():
        return True

    return False


def get_current_branch() -> Optional[str]:
    """Get the current git branch name.

    Returns:
        Branch name or None if not on a branch
    """
    exit_code, stdout, _ = run_git_command(["branch", "--show-current"])
    if exit_code == 0 and stdout.strip():
        return stdout.strip()
    return None


def is_git_repo(path: str = "/workspace") -> bool:
    """Check if the given path is inside a git repository.

    Args:
        path: Path to check (default: /workspace)

    Returns:
        True if inside a git repo
    """
    exit_code, _, _ = run_git_command(["rev-parse", "--git-dir"], cwd=path)
    return exit_code == 0
