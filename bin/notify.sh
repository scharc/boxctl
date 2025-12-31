#!/usr/bin/env bash
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.


# Agentbox Notification Bridge
# Sends notifications from container to host via D-Bus

# Usage: notify.sh [title] [message] [urgency]
# Example: notify.sh "Claude Code" "Human input needed" "critical"

TITLE="${1:-Agentbox}"
MESSAGE="${2:-Notification}"
URGENCY="${3:-normal}"
SOCKET_PATH="/home/abox/.agentbox/notify.sock"

if [[ ! -S "${SOCKET_PATH}" ]]; then
    echo "Notify socket not found at ${SOCKET_PATH}" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for notify" >&2
    exit 1
fi

TITLE_ENV="$TITLE" MESSAGE_ENV="$MESSAGE" URGENCY_ENV="$URGENCY" SOCKET_PATH_ENV="$SOCKET_PATH" python3 - <<'PY'
import json
import os
import socket
import sys

sock_path = os.environ.get("SOCKET_PATH_ENV", "")
payload = json.dumps({
    "action": "notify",
    "title": os.environ.get("TITLE_ENV", "Agentbox"),
    "message": os.environ.get("MESSAGE_ENV", "Notification"),
    "urgency": os.environ.get("URGENCY_ENV", "normal"),
})

try:
    data = payload.encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(sock_path)
        s.sendall(data + b"\n")
        s.shutdown(socket.SHUT_WR)
        resp = s.recv(4096).decode()
    if '"ok": true' not in resp:
        sys.exit(1)
except Exception:
    sys.exit(1)
PY
if [[ $? -ne 0 ]]; then
    echo "Failed to send notification via proxy socket" >&2
    exit 1
fi

echo "[NOTIFY] $TITLE: $MESSAGE (urgency: $URGENCY)"

# Append to project log if available.
LOG_PATH="/workspace/.agentbox/LOG.md"
if [[ -d "/workspace/.agentbox" ]]; then
    {
        echo "- [$(date '+%Y-%m-%d %H:%M:%S')] $TITLE: $MESSAGE (urgency: $URGENCY)"
    } >> "${LOG_PATH}"
fi