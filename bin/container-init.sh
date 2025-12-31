#!/usr/bin/env bash
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

set -euo pipefail

# Agentbox Container Initialization Script
# Runs on container startup to set up SSH keys, Git config, and config watcher

echo "Initializing Agentbox container..."
echo "User: ${USER:-unknown}"

HOST_UID="${HOST_UID:-1000}"
HOST_GID="${HOST_GID:-1000}"

ensure_abox_user() {
    local user_name="abox"
    local group_name="abox"

    if ! getent group "${HOST_GID}" >/dev/null; then
        groupadd -g "${HOST_GID}" "${group_name}"
    else
        group_name="$(getent group "${HOST_GID}" | cut -d: -f1)"
    fi

    if id "${user_name}" >/dev/null 2>&1; then
        usermod -u "${HOST_UID}" -g "${HOST_GID}" "${user_name}" || true
    else
        existing_user="$(getent passwd "${HOST_UID}" | cut -d: -f1)"
        if [[ -n "${existing_user}" ]]; then
            if [[ "${existing_user}" != "${user_name}" ]]; then
                usermod -l "${user_name}" "${existing_user}" || true
            fi
            usermod -u "${HOST_UID}" -g "${HOST_GID}" "${user_name}" || true
        else
            useradd -m -u "${HOST_UID}" -g "${HOST_GID}" -s /bin/bash "${user_name}"
        fi
    fi

    if ! getent passwd "${user_name}" >/dev/null; then
        echo "Failed to create ${user_name} user" >&2
        exit 1
    fi

    mkdir -p "/home/${user_name}"
    chown -R "${HOST_UID}:${HOST_GID}" "/home/${user_name}"

    echo "${user_name} ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/abox
    chmod 0440 /etc/sudoers.d/abox
}

ensure_abox_user
ABOX_HOME="$(getent passwd abox | cut -d: -f6)"
if [[ -z "${ABOX_HOME}" ]]; then
    echo "Failed to resolve abox home directory" >&2
    exit 1
fi
if [[ "${ABOX_HOME}" != "/home/abox" ]]; then
    usermod -d /home/abox -m abox || true
    ABOX_HOME="/home/abox"
fi

ensure_abox_aliases() {
    local bashrc="${ABOX_HOME}/.bashrc"
    local marker="# Agentbox aliases"
    if ! grep -q "${marker}" "${bashrc}" 2>/dev/null; then
        {
            echo ""
            echo "${marker}"
            echo "alias ll='ls -alFh'"
            echo "alias la='ls -A'"
            echo "alias l='ls -CF'"
        } >>"${bashrc}"
    fi
    chown "${HOST_UID}:${HOST_GID}" "${bashrc}" 2>/dev/null || true
}

ensure_abox_aliases

ensure_abox_env() {
    local runtime_dir="/run/user/${HOST_UID}"
    if [[ ! -e "${runtime_dir}" ]]; then
        mkdir -p "${runtime_dir}"
    fi
    if [[ -w "${runtime_dir}" ]]; then
        chown "${HOST_UID}:${HOST_GID}" "${runtime_dir}" 2>/dev/null || true
    fi

    local env_line="export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${HOST_UID}/bus"
    local xdg_line="export XDG_RUNTIME_DIR=/run/user/${HOST_UID}"
    local bashrc="${ABOX_HOME}/.bashrc"
    if ! grep -q "DBUS_SESSION_BUS_ADDRESS" "${bashrc}" 2>/dev/null; then
        {
            echo ""
            echo "# Agentbox runtime environment"
            echo "${xdg_line}"
            echo "${env_line}"
        } >>"${bashrc}"
    fi

    local profile="/etc/profile.d/agentbox.sh"
    {
        echo "${xdg_line}"
        echo "${env_line}"
    } >"${profile}"
    chmod 0644 "${profile}"
}

ensure_abox_env

# Ensure agentbox runtime dir exists for socket mounts.
mkdir -p "${ABOX_HOME}/.agentbox"
chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.agentbox"

# Keep notify socket path stable even if the host service restarts.
NOTIFY_TARGET="/run/user/${HOST_UID}/agentbox-notify.sock"
NOTIFY_LINK="${ABOX_HOME}/.agentbox/notify.sock"
if [[ -e "${NOTIFY_LINK}" && ! -L "${NOTIFY_LINK}" ]]; then
    rm -f "${NOTIFY_LINK}" || true
fi
ln -sfn "${NOTIFY_TARGET}" "${NOTIFY_LINK}"
chown -h "${HOST_UID}:${HOST_GID}" "${NOTIFY_LINK}" 2>/dev/null || true

# Copy SSH keys with correct permissions
if [[ -d "/${USER}/ssh" ]]; then
    echo "Setting up SSH keys from /${USER}/ssh..."
    mkdir -p "${ABOX_HOME}/.ssh"
    cp -r "/${USER}/ssh"/* "${ABOX_HOME}/.ssh/" 2>/dev/null || true
    chmod 700 "${ABOX_HOME}/.ssh"
    chmod 600 "${ABOX_HOME}/.ssh"/id_* 2>/dev/null || true
    chmod 644 "${ABOX_HOME}/.ssh"/*.pub 2>/dev/null || true
    chmod 644 "${ABOX_HOME}/.ssh"/known_hosts 2>/dev/null || true
    chmod 644 "${ABOX_HOME}/.ssh"/config 2>/dev/null || true
    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.ssh"
fi

# Set up Git configuration from environment variables
if [[ -n "${GIT_AUTHOR_NAME:-}" ]]; then
    su -s /bin/bash abox -c "git config --global user.name \"$GIT_AUTHOR_NAME\""
fi

if [[ -n "${GIT_AUTHOR_EMAIL:-}" ]]; then
    su -s /bin/bash abox -c "git config --global user.email \"$GIT_AUTHOR_EMAIL\""
fi

# Set up Docker group for socket access (only when mounted).
if [[ -e /var/run/docker.sock ]]; then
    echo "Configuring Docker socket access..."
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
    if ! getent group "${DOCKER_GID}" >/dev/null; then
        groupadd -g "${DOCKER_GID}" docker 2>/dev/null || true
    fi
    DOCKER_GROUP="$(getent group "${DOCKER_GID}" | cut -d: -f1)"
    usermod -aG "${DOCKER_GROUP}" root 2>/dev/null || true
    usermod -aG "${DOCKER_GROUP}" abox 2>/dev/null || true
fi

# Bootstrap Claude auth/state from host ~/.claude if mounted
HOST_CLAUDE_DIR="/${USER}/claude"
if [[ -d "${HOST_CLAUDE_DIR}" ]]; then
    echo "Bootstrapping Claude auth/state from host..."
    mkdir -p "${ABOX_HOME}/.claude"
    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude"

    # Credentials
    if [[ -f "${HOST_CLAUDE_DIR}/.credentials.json" ]]; then
        if [[ ! -f "${ABOX_HOME}/.claude/.credentials.json" ]]; then
            cp "${HOST_CLAUDE_DIR}/.credentials.json" "${ABOX_HOME}/.claude/.credentials.json"
        fi
        chmod 600 "${ABOX_HOME}/.claude/.credentials.json"
    elif [[ -f "${HOST_CLAUDE_DIR}/credentials.json" ]]; then
        if [[ ! -f "${ABOX_HOME}/.claude/credentials.json" ]]; then
            cp "${HOST_CLAUDE_DIR}/credentials.json" "${ABOX_HOME}/.claude/credentials.json"
        fi
        chmod 600 "${ABOX_HOME}/.claude/credentials.json"
    fi

    # Global Claude client state
    if [[ -f "/${USER}/claude.json" ]]; then
        if [[ ! -f "${ABOX_HOME}/.claude.json" ]]; then
            cp "/${USER}/claude.json" "${ABOX_HOME}/.claude.json"
        fi
    fi

    # Statsig identity
    if [[ -d "${HOST_CLAUDE_DIR}/statsig" && ! -d "${ABOX_HOME}/.claude/statsig" ]]; then
        cp -a "${HOST_CLAUDE_DIR}/statsig" "${ABOX_HOME}/.claude/"
    fi

    # Session environment
    if [[ -d "${HOST_CLAUDE_DIR}/session-env" && ! -d "${ABOX_HOME}/.claude/session-env" ]]; then
        cp -a "${HOST_CLAUDE_DIR}/session-env" "${ABOX_HOME}/.claude/"
    fi

    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude" "${ABOX_HOME}/.claude.json" 2>/dev/null || true
fi

# Bootstrap OpenAI/Gemini CLI configs if mounted
if [[ -d "/${USER}/openai-config" || -d "/${USER}/gemini-config" || -d "/${USER}/codex" ]]; then
    mkdir -p "${ABOX_HOME}/.config"
    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.config"
fi
if [[ -d "/${USER}/openai-config" && ! -d "${ABOX_HOME}/.config/openai" ]]; then
    echo "Bootstrapping OpenAI CLI config from host..."
    cp -a "/${USER}/openai-config" "${ABOX_HOME}/.config/openai"
fi
if [[ -d "/${USER}/gemini-config" && ! -d "${ABOX_HOME}/.config/gemini" ]]; then
    echo "Bootstrapping Gemini CLI config from host..."
    cp -a "/${USER}/gemini-config" "${ABOX_HOME}/.config/gemini"
fi

# Codex config (if present)
if [[ -d "/${USER}/codex" && ! -d "${ABOX_HOME}/.codex" ]]; then
    echo "Bootstrapping Codex config from host..."
    cp -a "/${USER}/codex" "${ABOX_HOME}/.codex"
fi

# Start config watcher in background (bidirectional sync)
if [[ -f /workspace/.agentbox/config.json ]]; then
    echo "Starting config watcher for live sync..."
    su -s /bin/bash abox -c "nohup /usr/local/bin/config-watcher.sh >/tmp/agentbox-config-watcher.log 2>&1 &"
else
    echo "No project config found at /workspace/.agentbox/config.json"
    echo "Run 'agentbox init' to create project structure"
fi

echo "Container initialization complete!"

# Ensure a tmux session exists for convenience when attaching later.
if [[ -t 0 ]]; then
    SESSION_NAME="shell"
    TMUX_CMD="if ! tmux has-session -t ${SESSION_NAME} 2>/dev/null; then \
tmux new-session -d -s ${SESSION_NAME} /bin/bash; \
tmux set-option -t ${SESSION_NAME} status on; \
tmux set-option -t ${SESSION_NAME} status-position top; \
tmux set-option -t ${SESSION_NAME} status-style 'bg=colour226,fg=colour232'; \
tmux set-option -t ${SESSION_NAME} mouse off; \
tmux set-option -t ${SESSION_NAME} history-limit 50000; \
tmux set-option -t ${SESSION_NAME} status-left ' AGENTBOX SHELL '; \
tmux set-option -t ${SESSION_NAME} status-right ''; \
tmux set-option -t ${SESSION_NAME} pane-border-status top; \
tmux set-option -t ${SESSION_NAME} pane-border-style 'fg=colour226'; \
tmux set-option -t ${SESSION_NAME} pane-border-format ' AGENTBOX SHELL '; \
fi"
    su -s /bin/bash abox -c "${TMUX_CMD}"
fi

exec /bin/bash -lc "sleep infinity"