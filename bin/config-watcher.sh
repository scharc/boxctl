#!/usr/bin/env bash
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

# Bidirectional config poller for Agentbox
# Polls both runtime and project configs for changes and syncs them

set -euo pipefail

CLAUDE_RUNTIME_CONFIG="/home/abox/.claude/config.json"
CLAUDE_PROJECT_CONFIG="/workspace/.agentbox/config.json"
CODEX_RUNTIME_CONFIG="/home/abox/.codex/config.toml"
CODEX_PROJECT_CONFIG="/workspace/.agentbox/codex.toml"

MERGE_CLAUDE_SCRIPT="/usr/local/bin/merge-config.py"
SPLIT_CLAUDE_SCRIPT="/usr/local/bin/split-config.py"
MERGE_CODEX_SCRIPT="/usr/local/bin/merge-codex-config.py"
SPLIT_CODEX_SCRIPT="/usr/local/bin/split-codex-config.py"

LOCK_FILE="/tmp/config-sync.lock"
POLL_INTERVAL="${AGENTBOX_CONFIG_POLL_INTERVAL:-5}"

get_mtime() {
    local path="$1"
    if [[ -f "$path" ]]; then
        stat -c %Y "$path" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

acquire_lock() {
    local timeout=5
    local elapsed=0
    while [[ -f "$LOCK_FILE" ]]; do
        sleep 0.1
        elapsed=$(echo "$elapsed + 0.1" | bc)
        if (( $(echo "$elapsed > $timeout" | bc -l) )); then
            echo "[Config Poller] Warning: lock timeout, forcing sync" >&2
            rm -f "$LOCK_FILE"
            break
        fi
    done
    touch "$LOCK_FILE"
}

release_lock() {
    rm -f "$LOCK_FILE"
}

sync_project_to_runtime() {
    echo "[Config Poller] Project config changed, merging to runtime..." >&2
    acquire_lock
    python3 "$MERGE_CLAUDE_SCRIPT" || true
    python3 "$MERGE_CODEX_SCRIPT" || true
    release_lock
}

sync_runtime_to_project() {
    echo "[Config Poller] Runtime config changed, splitting to project..." >&2
    acquire_lock
    python3 "$SPLIT_CLAUDE_SCRIPT" || true
    python3 "$SPLIT_CODEX_SCRIPT" || true
    release_lock
}

echo "[Config Poller] Starting config poller..." >&2

# Initial merge on startup
if [[ -f "$CLAUDE_PROJECT_CONFIG" || -f "$CODEX_PROJECT_CONFIG" ]]; then
    echo "[Config Poller] Performing initial merge..." >&2
    python3 "$MERGE_CLAUDE_SCRIPT" || true
    python3 "$MERGE_CODEX_SCRIPT" || true
fi

last_claude_project_mtime=$(get_mtime "$CLAUDE_PROJECT_CONFIG")
last_claude_runtime_mtime=$(get_mtime "$CLAUDE_RUNTIME_CONFIG")
last_codex_project_mtime=$(get_mtime "$CODEX_PROJECT_CONFIG")
last_codex_runtime_mtime=$(get_mtime "$CODEX_RUNTIME_CONFIG")

while true; do
    sleep "$POLL_INTERVAL"

    current_claude_project_mtime=$(get_mtime "$CLAUDE_PROJECT_CONFIG")
    current_claude_runtime_mtime=$(get_mtime "$CLAUDE_RUNTIME_CONFIG")
    current_codex_project_mtime=$(get_mtime "$CODEX_PROJECT_CONFIG")
    current_codex_runtime_mtime=$(get_mtime "$CODEX_RUNTIME_CONFIG")

    if [[ "$current_claude_project_mtime" -gt "$last_claude_project_mtime" || "$current_codex_project_mtime" -gt "$last_codex_project_mtime" ]]; then
        sync_project_to_runtime
        current_claude_runtime_mtime=$(get_mtime "$CLAUDE_RUNTIME_CONFIG")
        current_codex_runtime_mtime=$(get_mtime "$CODEX_RUNTIME_CONFIG")
    fi

    if [[ "$current_claude_runtime_mtime" -gt "$last_claude_runtime_mtime" || "$current_codex_runtime_mtime" -gt "$last_codex_runtime_mtime" ]]; then
        sync_runtime_to_project
        current_claude_project_mtime=$(get_mtime "$CLAUDE_PROJECT_CONFIG")
        current_codex_project_mtime=$(get_mtime "$CODEX_PROJECT_CONFIG")
    fi

    last_claude_project_mtime="$current_claude_project_mtime"
    last_claude_runtime_mtime="$current_claude_runtime_mtime"
    last_codex_project_mtime="$current_codex_project_mtime"
    last_codex_runtime_mtime="$current_codex_runtime_mtime"
done