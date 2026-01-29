#!/usr/bin/env bash
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

set -euo pipefail

# Boxctl Container Initialization Script
# Runs on container startup to set up SSH keys, Git config, and config watcher

# Project config directory name (used throughout this script)
readonly BOXCTL_PROJECT_DIR="/workspace/.boxctl"

echo "Initializing Boxctl container..."
echo "User: ${USER:-unknown}"

# Status file for host to monitor initialization progress
STATUS_FILE="/tmp/container-status"

# Write status update (phase and optional details)
# Format: PHASE|details
set_status() {
    local phase="$1"
    local details="${2:-}"
    echo "${phase}|${details}" > "${STATUS_FILE}"
    chmod 666 "${STATUS_FILE}" 2>/dev/null || true
}

set_status "starting" "Container initialization starting"

HOST_UID="${HOST_UID:-1000}"
HOST_GID="${HOST_GID:-1000}"

ensure_abox_user() {
    local user_name="abox"
    local group_name="abox"

    # Check if the target GID already exists as a group
    if getent group "${HOST_GID}" >/dev/null; then
        # GID exists - use that group name
        group_name="$(getent group "${HOST_GID}" | cut -d: -f1)"
    elif getent group "${group_name}" >/dev/null; then
        # Group 'abox' exists but with different GID - modify it
        groupmod -g "${HOST_GID}" "${group_name}"
    else
        # Neither GID nor group name exists - create new group
        groupadd -g "${HOST_GID}" "${group_name}"
    fi

    if id "${user_name}" >/dev/null 2>&1; then
        usermod -u "${HOST_UID}" -g "${HOST_GID}" "${user_name}" || true
    else
        existing_user="$(getent passwd "${HOST_UID}" | cut -d: -f1)" || true
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
    # chown may fail on read-only volume-mounted files (e.g., .ssh/config)
    chown -R "${HOST_UID}:${HOST_GID}" "/home/${user_name}" 2>/dev/null || true

    echo "${user_name} ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/abox
    chmod 0440 /etc/sudoers.d/abox
}

set_status "user" "Creating abox user"
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
    local marker="# Boxctl aliases"
    if ! grep -q "${marker}" "${bashrc}" 2>/dev/null; then
        {
            echo ""
            echo "${marker}"
            echo "alias ll='ls -alFh'"
            echo "alias la='ls -A'"
            echo "alias l='ls -CF'"
            echo "# agentctl shortcuts"
            echo "alias ctl='agentctl'"
            echo "alias acls='agentctl ls'"
            echo "alias ad='tmux detach-client 2>/dev/null || echo \"Not in tmux session\"'"
            echo "# claude alias with settings (superclaude uses /usr/local/bin/superclaude wrapper)"
            echo "alias claude='\${HOME}/.local/bin/claude --settings /home/abox/.claude/settings.json --mcp-config /home/abox/.mcp.json'"
            # Note: boxctl runs on the HOST, not in the container - no completion here
        } >>"${bashrc}"
    fi
    chown "${HOST_UID}:${HOST_GID}" "${bashrc}" 2>/dev/null || true

    # Note: boxctl completion is NOT set up here - boxctl runs on the HOST only
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
            echo "# Boxctl runtime environment"
            echo "${xdg_line}"
            echo "${env_line}"
        } >>"${bashrc}"
    fi

    local profile="/etc/profile.d/boxctl.sh"
    {
        echo "${xdg_line}"
        echo "${env_line}"
    } >"${profile}"
    chmod 0644 "${profile}"
}

ensure_abox_env

ensure_system_path() {
    local profile_file="/etc/profile.d/boxctl-path.sh"
    cat >"${profile_file}" <<'EOF'
# Boxctl PATH - include common package manager binary locations
# Order: user npm first, then local, then system
export PATH="${HOME}/.npm-global/bin:${HOME}/.local/bin:${HOME}/.cargo/bin:${HOME}/go/bin:/usr/local/sbin:/usr/local/bin:${PATH}"

# Include user's pip packages in Python path (for MCP servers installed via pip)
export PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages:${PYTHONPATH}"
EOF
    chmod 0644 "${profile_file}"
}

ensure_package_permissions() {
    # Set up npm user directory for runtime package installs
    # Base packages (claude, codex, gemini) are in /usr/local from the image
    # MCP and user packages go to ~/.npm-global
    local npm_dir="${ABOX_HOME}/.npm-global"
    mkdir -p "${npm_dir}"
    chown -R "${HOST_UID}:${HOST_GID}" "${npm_dir}"

    # Create user npmrc to use the user directory
    local user_npmrc="${ABOX_HOME}/.npmrc"
    if [[ ! -f "${user_npmrc}" ]]; then
        echo "prefix=${npm_dir}" > "${user_npmrc}"
        chown "${HOST_UID}:${HOST_GID}" "${user_npmrc}"
    fi

    # Configure pip to allow system package modification
    cat >/etc/pip.conf <<'EOF'
[global]
break-system-packages = true
EOF
}

ensure_system_path
ensure_package_permissions

# Ensure boxctl runtime dir exists for socket mounts.
mkdir -p "${ABOX_HOME}/.boxctl"
chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.boxctl"

# Set up SSH directory based on mode
setup_ssh() {
    local ssh_mode="${SSH_MODE:-keys}"
    local ssh_enabled="${SSH_ENABLED:-true}"

    # Map old mode names to new names for backwards compatibility
    case "${ssh_mode}" in
        disabled) ssh_mode="none" ;;
        copy) ssh_mode="keys" ;;
        shared) ssh_mode="mount" ;;
        agent) ssh_mode="config" ;;
    esac

    if [[ "${ssh_enabled}" != "true" ]] || [[ "${ssh_mode}" == "none" ]]; then
        echo "SSH disabled, skipping SSH setup"
        return
    fi

    mkdir -p "${ABOX_HOME}/.ssh"
    chmod 700 "${ABOX_HOME}/.ssh"

    case "${ssh_mode}" in
        keys)
            echo "Setting up SSH in keys mode (copy all SSH files)..."
            setup_ssh_keys
            ;;
        mount)
            echo "SSH in mount mode (bind mounted read-write, no setup needed)..."
            # Bind mounted directly to /home/abox/.ssh, just ensure permissions
            chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.ssh" 2>/dev/null || true
            ;;
        config)
            echo "Setting up SSH in config mode (config/known_hosts only, no keys)..."
            setup_ssh_config_only
            ;;
        *)
            echo "Unknown SSH mode: ${ssh_mode}"
            return 1
            ;;
    esac

    echo "SSH setup complete (mode: ${ssh_mode})."
}

setup_ssh_keys() {
    if [[ ! -d "/host-ssh" ]]; then
        echo "Warning: /host-ssh not mounted for keys mode"
        return
    fi

    # Copy all SSH files from host mount
    local file_basename
    for file in /host-ssh/*; do
        if [[ -e "${file}" ]]; then
            file_basename="$(basename "${file}")"
            cp -L "${file}" "${ABOX_HOME}/.ssh/${file_basename}" 2>/dev/null || true
        fi
    done

    # Set permissions
    setup_ssh_permissions
}

setup_ssh_config_only() {
    if [[ ! -d "/host-ssh" ]]; then
        echo "Warning: /host-ssh not mounted for config mode"
        return
    fi

    # Copy only config and known_hosts (no private keys)
    for file in config known_hosts; do
        if [[ -f "/host-ssh/${file}" ]]; then
            cp -L "/host-ssh/${file}" "${ABOX_HOME}/.ssh/${file}" 2>/dev/null || true
        fi
    done

    # Set permissions for config files only
    chmod 644 "${ABOX_HOME}/.ssh"/config 2>/dev/null || true
    chmod 644 "${ABOX_HOME}/.ssh"/known_hosts 2>/dev/null || true

    # Create known_hosts if missing
    if [[ ! -f "${ABOX_HOME}/.ssh/known_hosts" ]]; then
        touch "${ABOX_HOME}/.ssh/known_hosts"
        chmod 644 "${ABOX_HOME}/.ssh/known_hosts"
    fi

    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.ssh"
}

setup_ssh_permissions() {
    # Private keys: read-only for owner
    chmod 600 "${ABOX_HOME}/.ssh"/id_* 2>/dev/null || true
    chmod 600 "${ABOX_HOME}/.ssh"/*_rsa 2>/dev/null || true
    chmod 600 "${ABOX_HOME}/.ssh"/*_ed25519 2>/dev/null || true
    chmod 600 "${ABOX_HOME}/.ssh"/*_ecdsa 2>/dev/null || true

    # Public keys and config: readable
    chmod 644 "${ABOX_HOME}/.ssh"/*.pub 2>/dev/null || true
    chmod 644 "${ABOX_HOME}/.ssh"/config 2>/dev/null || true
    chmod 644 "${ABOX_HOME}/.ssh"/known_hosts 2>/dev/null || true

    # Create known_hosts if missing
    if [[ ! -f "${ABOX_HOME}/.ssh/known_hosts" ]]; then
        touch "${ABOX_HOME}/.ssh/known_hosts"
        chmod 644 "${ABOX_HOME}/.ssh/known_hosts"
    fi

    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.ssh"
}

set_status "ssh" "Configuring SSH"
setup_ssh

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

# === AGENT HOME DIRECTORY SETUP ===
# Sets up agent configurations in home directories (~/.claude, ~/.codex, etc.)
# Configs come from library templates, auth from host mounts
# Must run before credential bootstrapping so credentials go into the right place

setup_agent_home_dirs() {
    local boxctl_dir="${BOXCTL_PROJECT_DIR}"
    local library_config="/boxctl/library/config/default"

    echo "Setting up agent home directories..."

    # Create real directories for ALL agents in home
    for agent in claude codex gemini qwen; do
        mkdir -p "${ABOX_HOME}/.${agent}"
        chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.${agent}" 2>/dev/null || true
    done

    # Copy config templates to home dirs
    # Priority: project config (.boxctl/config/) > library defaults
    local project_config="${boxctl_dir}/config"

    # Claude: settings.json (used with --settings flag)
    if [[ -f "${project_config}/claude/settings.json" ]]; then
        cp "${project_config}/claude/settings.json" "${ABOX_HOME}/.claude/settings.json"
    elif [[ -f "${library_config}/claude/settings.json" ]]; then
        cp "${library_config}/claude/settings.json" "${ABOX_HOME}/.claude/settings.json"
    fi
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/settings.json" 2>/dev/null || true

    if [[ -f "${project_config}/claude/settings-super.json" ]]; then
        cp "${project_config}/claude/settings-super.json" "${ABOX_HOME}/.claude/settings-super.json"
    elif [[ -f "${library_config}/claude/settings-super.json" ]]; then
        cp "${library_config}/claude/settings-super.json" "${ABOX_HOME}/.claude/settings-super.json"
    fi
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/settings-super.json" 2>/dev/null || true

    # Gemini: base settings (MCP injected later by distribute script)
    if [[ -f "${project_config}/gemini/settings.json" ]]; then
        cp "${project_config}/gemini/settings.json" "${ABOX_HOME}/.gemini/settings.json"
    elif [[ -f "${library_config}/gemini/settings.json" ]]; then
        cp "${library_config}/gemini/settings.json" "${ABOX_HOME}/.gemini/settings.json"
    fi
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.gemini/settings.json" 2>/dev/null || true

    # Qwen: base settings (MCP injected later by distribute script)
    if [[ -f "${project_config}/qwen/settings.json" ]]; then
        cp "${project_config}/qwen/settings.json" "${ABOX_HOME}/.qwen/settings.json"
    elif [[ -f "${library_config}/qwen/settings.json" ]]; then
        cp "${library_config}/qwen/settings.json" "${ABOX_HOME}/.qwen/settings.json"
    fi
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.qwen/settings.json" 2>/dev/null || true

    # Symlink project instructions (agents.md) into agent home dirs
    if [[ -f "${boxctl_dir}/agents.md" ]]; then
        ln -sf "${boxctl_dir}/agents.md" "${ABOX_HOME}/.claude/CLAUDE.md" 2>/dev/null || true
        ln -sf "${boxctl_dir}/agents.md" "${ABOX_HOME}/.codex/AGENTS.md" 2>/dev/null || true
        ln -sf "${boxctl_dir}/agents.md" "${ABOX_HOME}/.gemini/GEMINI.md" 2>/dev/null || true
        ln -sf "${boxctl_dir}/agents.md" "${ABOX_HOME}/.qwen/QWEN.md" 2>/dev/null || true
        # Also create convenience symlink in home
        ln -sf "${boxctl_dir}/agents.md" "${ABOX_HOME}/agents.md" 2>/dev/null || true
    fi

    # Set up skills directory - Claude looks for ~/.claude/skills/
    # Priority: library < user home < project (later overrides earlier)
    mkdir -p "${ABOX_HOME}/.claude/skills"
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/skills" 2>/dev/null || true

    # 1. Library skills (lowest priority)
    local skill_name
    if [[ -d "/boxctl/library/skills" ]]; then
        for skill_dir in /boxctl/library/skills/*/; do
            if [[ -d "${skill_dir}" ]]; then
                skill_name=$(basename "${skill_dir}")
                ln -sf "${skill_dir}" "${ABOX_HOME}/.claude/skills/${skill_name}" 2>/dev/null || true
            fi
        done
    fi

    # 2. User home skills (~/.config/boxctl/skills/)
    if [[ -d "${ABOX_HOME}/.config/boxctl/skills" ]]; then
        for skill_dir in "${ABOX_HOME}/.config/boxctl/skills/"*/; do
            if [[ -d "${skill_dir}" ]]; then
                skill_name=$(basename "${skill_dir}")
                ln -sf "${skill_dir}" "${ABOX_HOME}/.claude/skills/${skill_name}" 2>/dev/null || true
            fi
        done
    fi

    # 3. Project skills (highest priority, overrides others)
    if [[ -d "${boxctl_dir}/skills" ]]; then
        for skill_dir in "${boxctl_dir}/skills/"*/; do
            if [[ -d "${skill_dir}" ]]; then
                skill_name=$(basename "${skill_dir}")
                ln -sf "${skill_dir}" "${ABOX_HOME}/.claude/skills/${skill_name}" 2>/dev/null || true
            fi
        done
    fi

    # Set up commands directory - Claude looks for ~/.claude/commands/
    # These are "personal commands" available across all projects in this container
    # Priority: library < user home < project (later overrides earlier)
    mkdir -p "${ABOX_HOME}/.claude/commands"
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/commands" 2>/dev/null || true

    # 1. Library MCP commands (lowest priority)
    local cmd_name
    if [[ -d "/boxctl/library/mcp" ]]; then
        for mcp_dir in /boxctl/library/mcp/*/; do
            if [[ -d "${mcp_dir}commands" ]]; then
                for cmd_file in "${mcp_dir}commands/"*.md; do
                    if [[ -f "${cmd_file}" ]]; then
                        cmd_name=$(basename "${cmd_file}")
                        ln -sf "${cmd_file}" "${ABOX_HOME}/.claude/commands/ab-${cmd_name}" 2>/dev/null || true
                    fi
                done
            fi
        done
    fi

    # 2. User home MCP commands (~/.config/boxctl/mcp/*/commands/)
    if [[ -d "${ABOX_HOME}/.config/boxctl/mcp" ]]; then
        for mcp_dir in "${ABOX_HOME}/.config/boxctl/mcp/"*/; do
            if [[ -d "${mcp_dir}commands" ]]; then
                for cmd_file in "${mcp_dir}commands/"*.md; do
                    if [[ -f "${cmd_file}" ]]; then
                        cmd_name=$(basename "${cmd_file}")
                        ln -sf "${cmd_file}" "${ABOX_HOME}/.claude/commands/ab-${cmd_name}" 2>/dev/null || true
                    fi
                done
            fi
        done
    fi

    # 3. Project MCP commands (highest priority, overrides others)
    if [[ -d "${boxctl_dir}/mcp" ]]; then
        for mcp_dir in "${boxctl_dir}/mcp/"*/; do
            if [[ -d "${mcp_dir}commands" ]]; then
                for cmd_file in "${mcp_dir}commands/"*.md; do
                    if [[ -f "${cmd_file}" ]]; then
                        cmd_name=$(basename "${cmd_file}")
                        ln -sf "${cmd_file}" "${ABOX_HOME}/.claude/commands/ab-${cmd_name}" 2>/dev/null || true
                    fi
                done
            fi
        done
    fi

    # Symlink agent history directories to workspace for persistence across rebases
    # This allows session resume and preserves conversation history
    local history_dir="${boxctl_dir}/history"
    mkdir -p "${history_dir}/claude" "${history_dir}/codex" "${history_dir}/gemini" "${history_dir}/qwen"
    chown -R "${HOST_UID}:${HOST_GID}" "${history_dir}"

    # Claude: projects/ contains conversation JSONL files
    ln -sfn "${history_dir}/claude" "${ABOX_HOME}/.claude/projects"

    # Codex: sessions/ contains conversation JSONL files
    ln -sfn "${history_dir}/codex" "${ABOX_HOME}/.codex/sessions"

    # Gemini: tmp/ contains chat JSON files
    ln -sfn "${history_dir}/gemini" "${ABOX_HOME}/.gemini/tmp"

    # Qwen: tmp/ contains chat JSON files
    ln -sfn "${history_dir}/qwen" "${ABOX_HOME}/.qwen/tmp"
}

set_status "agent_configs" "Setting up agent home directories"
setup_agent_home_dirs

# Bootstrap Claude auth/state from host
# Host directories are mounted as directories (not individual files) to avoid stale
# inode issues when credential files are replaced during OAuth token refresh.
# The mount is read-write so container can update credentials (OAuth token refresh).
# Find the host-claude mount (it's at /{host_username}/host-claude, not /${USER})
HOST_CLAUDE_DIR=""
for dir in /*/host-claude; do
    if [[ -d "${dir}" ]]; then
        HOST_CLAUDE_DIR="${dir}"
        break
    fi
done

# Set up credentials from host-mounted directory
if [[ -f "${HOST_CLAUDE_DIR}/.credentials.json" ]]; then
    echo "Setting up Claude credentials from host directory..."
    mkdir -p "${ABOX_HOME}/.claude"
    rm -f "${ABOX_HOME}/.claude/.credentials.json"
    ln -s "${HOST_CLAUDE_DIR}/.credentials.json" "${ABOX_HOME}/.claude/.credentials.json"
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/.credentials.json" 2>/dev/null || true
fi

if [[ -d "${HOST_CLAUDE_DIR}" ]]; then
    echo "Bootstrapping Claude state from host..."
    mkdir -p "${ABOX_HOME}/.claude"
    # Only chown directories we own, not read-only mounted content
    chown "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude" 2>/dev/null || true

    # Global Claude client state (mounted at /{host_username}/claude.json)
    HOST_USER_DIR="$(dirname "${HOST_CLAUDE_DIR}")"
    if [[ -f "${HOST_USER_DIR}/claude.json" ]]; then
        rm -f "${ABOX_HOME}/.claude.json"
        ln -s "${HOST_USER_DIR}/claude.json" "${ABOX_HOME}/.claude.json"
        chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude.json" 2>/dev/null || true
    fi

    # Statsig identity - copy from host if not already present
    if [[ -d "${HOST_CLAUDE_DIR}/statsig" && ! -d "${ABOX_HOME}/.claude/statsig" ]]; then
        cp -a "${HOST_CLAUDE_DIR}/statsig" "${ABOX_HOME}/.claude/"
        chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/statsig" 2>/dev/null || true
    fi

    # Session environment - copy from host if not already present
    if [[ -d "${HOST_CLAUDE_DIR}/session-env" && ! -d "${ABOX_HOME}/.claude/session-env" ]]; then
        cp -a "${HOST_CLAUDE_DIR}/session-env" "${ABOX_HOME}/.claude/"
        chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.claude/session-env" 2>/dev/null || true
    fi
fi

# Bootstrap Codex auth from host (like Claude credentials)
# Uses directory mount to avoid stale inode issues
# Find the host-codex mount (it's at /{host_username}/host-codex)
HOST_CODEX_DIR=""
for dir in /*/host-codex; do
    if [[ -d "${dir}" ]]; then
        HOST_CODEX_DIR="${dir}"
        break
    fi
done

# Codex CLI auth files from host (AGENTS.md symlink handled in setup_unified_agent_configs)
# Symlink all files except .md (instruction files come from project agents.md)
if [[ -d "${HOST_CODEX_DIR}" ]]; then
    echo "Linking Codex auth files from host..."
    for f in "${HOST_CODEX_DIR}"/*; do
        [[ ! -f "$f" ]] && continue
        [[ "$f" == *.md ]] && continue
        ln -sf "$f" "${ABOX_HOME}/.codex/"
    done
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.codex"/* 2>/dev/null || true
fi

# Bootstrap OpenAI/Gemini CLI configs if mounted
if [[ -d "/${USER}/openai-config" ]]; then
    mkdir -p "${ABOX_HOME}/.config"
    chown -R "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.config"
    echo "Linking OpenAI CLI config from host..."
    rm -rf "${ABOX_HOME}/.config/openai"
    ln -s "/${USER}/openai-config" "${ABOX_HOME}/.config/openai"
fi
# Gemini CLI auth files from host (GEMINI.md symlink handled in setup_unified_agent_configs)
# Symlink all files except .md (instruction files come from project agents.md)
if [[ -d "/${USER}/gemini" ]]; then
    echo "Linking Gemini auth files from host..."
    for f in "/${USER}/gemini"/*; do
        [[ ! -f "$f" ]] && continue
        [[ "$f" == *.md ]] && continue
        ln -sf "$f" "${ABOX_HOME}/.gemini/"
    done
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.gemini"/* 2>/dev/null || true
fi
# Qwen CLI auth files from host (QWEN.md symlink handled in setup_unified_agent_configs)
# Symlink all files except .md (instruction files come from project agents.md)
if [[ -d "/${USER}/qwen-config" ]]; then
    echo "Linking Qwen auth files from host..."
    # Link regular files
    for f in "/${USER}/qwen-config"/*; do
        [[ ! -f "$f" ]] && continue
        [[ "$f" == *.md ]] && continue
        ln -sf "$f" "${ABOX_HOME}/.qwen/"
    done
    # Also link dotfiles (like .env)
    for f in "/${USER}/qwen-config"/.*; do
        [[ ! -f "$f" ]] && continue
        [[ "$(basename "$f")" == "." || "$(basename "$f")" == ".." ]] && continue
        ln -sf "$f" "${ABOX_HOME}/.qwen/"
    done
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.qwen"/* 2>/dev/null || true
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.qwen"/.* 2>/dev/null || true
fi

# GitHub CLI (gh) config from host - auto-symlink for gh auth
if [[ -d "/${USER}/gh-config" ]]; then
    echo "Linking GitHub CLI (gh) config from host..."
    mkdir -p "${ABOX_HOME}/.config"
    rm -rf "${ABOX_HOME}/.config/gh"
    ln -s "/${USER}/gh-config" "${ABOX_HOME}/.config/gh"
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.config/gh" 2>/dev/null || true
fi

# GitLab CLI (glab) config from host - auto-symlink for glab auth
if [[ -d "/${USER}/glab-config" ]]; then
    echo "Linking GitLab CLI (glab) config from host..."
    mkdir -p "${ABOX_HOME}/.config"
    rm -rf "${ABOX_HOME}/.config/glab-cli"
    ln -s "/${USER}/glab-config" "${ABOX_HOME}/.config/glab-cli"
    chown -h "${HOST_UID}:${HOST_GID}" "${ABOX_HOME}/.config/glab-cli" 2>/dev/null || true
fi

# Load project environment variables (optional).
load_env_file() {
    local env_file="$1"
    if [[ -f "$env_file" ]]; then
        echo "Loading environment from $env_file"
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    fi
}

load_env_file /workspace/.boxctl/.env
load_env_file /workspace/.boxctl/.env.local
# Load agent-specific env files (API keys, etc.)
load_env_file "${ABOX_HOME}/.qwen/.env"

# Load env files from user's custom MCP directories
# These provide credentials for MCPs in ~/.config/boxctl/mcp/
if [[ -d "/home/abox/.config/boxctl/mcp" ]]; then
    for mcp_env in /home/abox/.config/boxctl/mcp/*/.env; do
        if [[ -f "$mcp_env" ]]; then
            load_env_file "$mcp_env"
        fi
    done
fi

# Install packages from MCP metadata
install_mcp_packages() {
    local meta_file="/workspace/.boxctl/mcp-meta.json"
    if [[ ! -f "${meta_file}" ]]; then
        return
    fi

    set_status "mcp_packages" "Checking MCP dependencies"
    echo "Installing MCP server dependencies..."
    su -s /bin/bash abox -c "python3 /usr/local/bin/install-packages.py \
        --meta ${meta_file} \
        --manifest /workspace/.boxctl/install-manifest.json \
        --log /tmp/mcp-install.log" || {
        echo "ERROR: MCP package installation failed!"
        echo "Check /tmp/mcp-install.log for details"
        exit 1
    }
}

install_mcp_packages

# Install packages from project .boxctl/config.yml
install_project_packages() {
    local config_file="/workspace/.boxctl/config.yml"

    # Wait for volume mount to be fully available (up to 5 seconds)
    local attempts=0
    while [[ ! -f "${config_file}" ]] && [[ $attempts -lt 10 ]]; do
        sleep 0.5
        attempts=$((attempts + 1))
    done

    if [[ ! -f "${config_file}" ]]; then
        return
    fi

    set_status "project_packages" "Installing project packages"
    echo "Installing project packages from .boxctl/config.yml..."

    # Install apt packages (kept in bash - no quoting issues)
    local apt_packages
    apt_packages=$(python3 -c "
import yaml, sys
try:
    with open('${config_file}') as f:
        data = yaml.safe_load(f)
    packages = data.get('packages', {}).get('apt', [])
    if packages:
        print(' '.join(packages))
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
" 2>/dev/null || true)

    if [[ -n "${apt_packages}" ]]; then
        echo "Installing apt packages: ${apt_packages}"
        apt-get update -qq
        # Word splitting intentional for package list
        # shellcheck disable=SC2086
        apt-get install -y ${apt_packages} || {
            echo "Warning: Failed to install some apt packages"
        }
        rm -rf /var/lib/apt/lists/*
    fi

    # Install cargo packages (kept in bash for now)
    local cargo_packages
    cargo_packages=$(python3 -c "
import yaml, sys
try:
    with open('${config_file}') as f:
        data = yaml.safe_load(f)
    packages = data.get('packages', {}).get('cargo', [])
    for pkg in packages:
        print(pkg)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
" 2>/dev/null || true)

    if [[ -n "${cargo_packages}" ]]; then
        # Build array of quoted package arguments
        local -a pkg_args=()
        while IFS= read -r pkg; do
            [[ -n "${pkg}" ]] && pkg_args+=("${pkg@Q}")
        done <<< "${cargo_packages}"

        if [[ ${#pkg_args[@]} -gt 0 ]]; then
            echo "Installing cargo packages: ${pkg_args[*]//\'/}"
            su -s /bin/bash abox -c "cargo install ${pkg_args[*]}" || {
                echo "Warning: Failed to install some cargo packages"
            }
        fi
    fi

    # Install pip, npm, and run post-install commands using Python installer
    su -s /bin/bash abox -c "python3 /usr/local/bin/install-packages.py \
        --config ${config_file} \
        --manifest /workspace/.boxctl/install-manifest.json \
        --log /tmp/project-install.log" || {
        echo "ERROR: Project package installation failed!"
        echo "Check /tmp/project-install.log for details"
        exit 1
    }
}

install_project_packages

# Ensure /context directory exists for workspace mounts
mkdir -p /context
chown "${HOST_UID}:${HOST_GID}" /context

# Create /git-worktrees directory for git worktree isolation
mkdir -p /git-worktrees
chown "${HOST_UID}:${HOST_GID}" /git-worktrees

# Start MCP servers with SSE transport for instant connections
start_mcp_servers() {
    local meta_file="/workspace/.boxctl/mcp-meta.json"
    if [[ ! -f "${meta_file}" ]]; then
        echo "No mcp-meta.json found, skipping MCP server startup"
        return
    fi

    # Check if start-mcp-servers.py exists
    local mcp_manager=""
    if [[ -f "/workspace/boxctl/bin/start-mcp-servers.py" ]]; then
        mcp_manager="/workspace/boxctl/bin/start-mcp-servers.py"
    elif [[ -f "/usr/local/bin/start-mcp-servers.py" ]]; then
        mcp_manager="/usr/local/bin/start-mcp-servers.py"
    fi

    if [[ -z "${mcp_manager}" ]]; then
        echo "MCP server manager not found, skipping SSE startup"
        return
    fi

    echo "Starting MCP servers with SSE transport..."
    su -s /bin/bash abox -c "python3 ${mcp_manager} --no-monitor" || {
        echo "Warning: Some MCP servers failed to start"
    }
}

# Generate MCP config (always run to clean up stale configs)
generate_mcp_config() {
    local config_generator=""
    if [[ -f "/workspace/bin/generate-mcp-config.py" ]]; then
        config_generator="/workspace/bin/generate-mcp-config.py"
    elif [[ -f "/usr/local/bin/generate-mcp-config.py" ]]; then
        config_generator="/usr/local/bin/generate-mcp-config.py"
    fi

    if [[ -n "${config_generator}" ]]; then
        echo "Generating MCP config (~/.mcp.json)..."
        su -s /bin/bash abox -c "python3 ${config_generator}" || {
            echo "Warning: Failed to generate MCP config"
        }
    fi

    # Distribute MCP config to Gemini/Qwen settings.json
    local distributor=""
    if [[ -f "/workspace/bin/distribute-mcp-config.py" ]]; then
        distributor="/workspace/bin/distribute-mcp-config.py"
    elif [[ -f "/usr/local/bin/distribute-mcp-config.py" ]]; then
        distributor="/usr/local/bin/distribute-mcp-config.py"
    fi

    if [[ -n "${distributor}" ]]; then
        echo "Distributing MCP config to agents..."
        su -s /bin/bash abox -c "python3 ${distributor}" || {
            echo "Warning: Failed to distribute MCP config"
        }
    fi
}

set_status "mcp_servers" "Starting MCP servers"
start_mcp_servers
generate_mcp_config

# Start LiteLLM proxy if enabled in host config
start_litellm() {
    # Look for host config in multiple locations
    local config_file=""
    for path in "/host-config/boxctl/config.yml" "${ABOX_HOME}/.config/boxctl/config.yml"; do
        if [[ -f "${path}" ]]; then
            config_file="${path}"
            break
        fi
    done

    if [[ -z "${config_file}" ]]; then
        return
    fi

    # Check if LiteLLM is enabled
    local enabled
    enabled=$(python3 -c "
import yaml
try:
    with open('${config_file}') as f:
        cfg = yaml.safe_load(f) or {}
    print(cfg.get('litellm', {}).get('enabled', False))
except:
    print('False')
" 2>/dev/null)

    if [[ "${enabled}" == "True" ]]; then
        echo "Starting LiteLLM proxy..."
        local litellm_script=""
        if [[ -f "/workspace/bin/start-litellm.py" ]]; then
            litellm_script="/workspace/bin/start-litellm.py"
        elif [[ -f "/usr/local/bin/start-litellm.py" ]]; then
            litellm_script="/usr/local/bin/start-litellm.py"
        fi

        if [[ -n "${litellm_script}" ]]; then
            su -s /bin/bash abox -c "nohup python3 ${litellm_script} >> /tmp/litellm.log 2>&1 &"
            echo "LiteLLM proxy starting (logs: /tmp/litellm.log)"
        fi
    fi
}

set_status "litellm" "Starting LiteLLM proxy"
start_litellm

set_status "container_client" "Starting container client"
echo "Container initialization complete!"

# Start unified container client (streaming + port forwarding via SSH)
# Prefer workspace for development, then installed package
start_container_client() {
    local container_client=""
    if [[ -f "/workspace/boxctl/container_client.py" ]]; then
        container_client="/workspace/boxctl/container_client.py"
    elif [[ -f "/usr/local/lib/python3.12/dist-packages/boxctl/container_client.py" ]]; then
        container_client="/usr/local/lib/python3.12/dist-packages/boxctl/container_client.py"
    fi

    if [[ -z "${container_client}" ]]; then
        echo "Warning: Container client not found, streaming and port forwarding unavailable"
        return
    fi

    echo "Starting container client from ${container_client}..."
    CONTAINER_NAME="${BOXCTL_CONTAINER:-$(cat /etc/hostname 2>/dev/null || echo unknown)}"
    su -s /bin/bash abox -c "BOXCTL_CONTAINER=${CONTAINER_NAME} nohup python3 ${container_client} >> /tmp/container-client.log 2>&1 &"
    echo "Container client started (logs: /tmp/container-client.log)"
}

start_container_client


set_status "ready" "Container ready"

# Keep container running
exec sleep infinity
