# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Agentbox host proxy daemon."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _default_socket_path() -> Path:
    return Path(f"/run/user/{os.getuid()}/agentbox-notify.sock")


def _config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "agentbox" / "proxy.json"


def _load_config() -> Dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


class AgentboxProxy:
    def __init__(self, socket_path: Path, config: Optional[Dict[str, Any]] = None) -> None:
        self.socket_path = socket_path
        self.config = config or {}
        self.handlers = {
            "notify": self._handle_notify,
        }

    def _notify_enabled(self) -> bool:
        cfg = self.config.get("notify", {})
        if isinstance(cfg, dict):
            return cfg.get("enabled", True)
        return True

    def _handle_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._notify_enabled():
            return {"ok": False, "error": "notify_disabled"}

        title = str(payload.get("title", "Agentbox"))
        message = str(payload.get("message", "Notification"))
        urgency = str(payload.get("urgency", "normal"))
        if urgency == "high":
            urgency = "critical"

        args = ["notify-send", "-u", urgency, title, message]
        result = subprocess.run(args, check=False, capture_output=True, text=True)

        if urgency == "critical":
            self._beep()

        if result.returncode != 0:
            print(result.stderr.strip() or "notify-send failed", file=sys.stderr)
            return {"ok": False, "error": result.stderr.strip() or "notify_failed"}
        return {"ok": True}

    def _beep(self) -> None:
        sound = Path("/usr/share/sounds/freedesktop/stereo/bell.oga")
        if sound.exists() and shutil.which("paplay"):
            subprocess.run(["paplay", str(sound)], check=False)
            return
        try:
            with open("/dev/tty", "w", encoding="utf-8") as tty:
                tty.write("\a")
                tty.flush()
        except Exception:
            pass

    def _handle_request(self, raw: bytes) -> Dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "invalid_json"}

        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_payload"}

        action = payload.get("action") or "notify"
        handler = self.handlers.get(action)
        if handler is None:
            return {"ok": False, "error": "unknown_action"}
        result = handler(payload)
        print(f"agentbox-proxy action={action} ok={result.get('ok')}", file=sys.stderr)
        return result

    def serve_forever(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            server.listen(5)

            while True:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(1.0)
                    data = b""
                    while True:
                        try:
                            chunk = conn.recv(4096)
                        except socket.timeout:
                            break
                        if not chunk:
                            break
                        data += chunk
                    responses = []
                    for line in data.splitlines():
                        if not line.strip():
                            continue
                        responses.append(self._handle_request(line))
                    if not responses:
                        responses = [{"ok": False, "error": "empty_request"}]
                    conn.sendall((json.dumps(responses[-1]) + "\n").encode("utf-8"))


def run_proxy(socket_path: Optional[str] = None) -> None:
    path = Path(socket_path) if socket_path else _default_socket_path()
    proxy = AgentboxProxy(path, _load_config())
    proxy.serve_forever()