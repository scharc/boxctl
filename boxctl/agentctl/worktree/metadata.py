"""Worktree metadata management"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class WorktreeMetadata:
    """Manages worktree metadata stored in .boxctl/worktrees.json"""

    def __init__(self, boxctl_dir: str = "/workspace/.boxctl"):
        self.boxctl_dir = boxctl_dir
        self.metadata_file = os.path.join(boxctl_dir, "worktrees.json")

    def _ensure_boxctl_dir(self):
        """Ensure .boxctl directory exists"""
        Path(self.boxctl_dir).mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict:
        """Load metadata from file"""
        if not os.path.exists(self.metadata_file):
            return {"worktrees": []}

        try:
            with open(self.metadata_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"worktrees": []}

    def _save(self, data: Dict):
        """Save metadata to file"""
        self._ensure_boxctl_dir()

        try:
            with open(self.metadata_file, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            raise Exception(f"Failed to save worktree metadata: {e}")

    def list_all(self) -> List[Dict]:
        """List all tracked worktrees

        Returns:
            List of worktree metadata dictionaries
        """
        data = self._load()
        return data.get("worktrees", [])

    def get(self, path: str) -> Optional[Dict]:
        """Get metadata for a specific worktree

        Args:
            path: Worktree path

        Returns:
            Worktree metadata dict or None
        """
        worktrees = self.list_all()
        return next((wt for wt in worktrees if wt.get("path") == path), None)

    def add(self, path: str, branch: str, commit: Optional[str] = None):
        """Add or update worktree metadata

        Args:
            path: Worktree path
            branch: Branch name
            commit: Commit hash (optional)
        """
        data = self._load()
        worktrees = data.get("worktrees", [])

        # Check if worktree already exists
        existing = next((wt for wt in worktrees if wt.get("path") == path), None)

        if existing:
            # Update existing
            existing["branch"] = branch
            existing["updated"] = datetime.now().isoformat()
            if commit:
                existing["commit"] = commit
        else:
            # Add new
            worktrees.append(
                {
                    "path": path,
                    "branch": branch,
                    "commit": commit,
                    "created": datetime.now().isoformat(),
                    "sessions": [],
                }
            )

        data["worktrees"] = worktrees
        self._save(data)

    def remove(self, path: str):
        """Remove worktree from metadata

        Args:
            path: Worktree path
        """
        data = self._load()
        worktrees = data.get("worktrees", [])

        # Filter out the worktree
        worktrees = [wt for wt in worktrees if wt.get("path") != path]

        data["worktrees"] = worktrees
        self._save(data)

    def add_session(self, path: str, session_name: str):
        """Associate a session with a worktree

        Args:
            path: Worktree path
            session_name: Tmux session name
        """
        data = self._load()
        worktrees = data.get("worktrees", [])

        for wt in worktrees:
            if wt.get("path") == path:
                sessions = wt.get("sessions", [])
                if session_name not in sessions:
                    sessions.append(session_name)
                    wt["sessions"] = sessions
                break

        data["worktrees"] = worktrees
        self._save(data)

    def remove_session(self, path: str, session_name: str):
        """Remove session association from worktree

        Args:
            path: Worktree path
            session_name: Tmux session name
        """
        data = self._load()
        worktrees = data.get("worktrees", [])

        for wt in worktrees:
            if wt.get("path") == path:
                sessions = wt.get("sessions", [])
                if session_name in sessions:
                    sessions.remove(session_name)
                    wt["sessions"] = sessions
                break

        data["worktrees"] = worktrees
        self._save(data)

    def clear_all_sessions(self):
        """Clear all session associations (useful after container restart)"""
        data = self._load()
        worktrees = data.get("worktrees", [])

        for wt in worktrees:
            wt["sessions"] = []

        data["worktrees"] = worktrees
        self._save(data)
