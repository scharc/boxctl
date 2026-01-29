#!/bin/bash
# Wait for VM to be ready (SSH accessible and cloud-init complete)
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_CTL="${SCRIPT_DIR}/vm-ctl.py"

# Default values
VM_NAME=""
SSH_TIMEOUT=300
CLOUD_INIT_TIMEOUT=600
WAIT_CLOUD_INIT=true

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat <<EOF
Wait for VM to be ready.

Usage: $0 --name VM_NAME [OPTIONS]

Options:
    --name NAME              VM name (required)
    --ssh-timeout SECONDS    Timeout for SSH (default: 300)
    --ci-timeout SECONDS     Timeout for cloud-init (default: 600)
    --no-cloud-init          Don't wait for cloud-init completion
    --help                   Show this help

Example:
    $0 --name boxctl-test-vm
    $0 --name test-vm --ssh-timeout 60 --no-cloud-init
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)
            VM_NAME="$2"
            shift 2
            ;;
        --ssh-timeout)
            SSH_TIMEOUT="$2"
            shift 2
            ;;
        --ci-timeout)
            CLOUD_INIT_TIMEOUT="$2"
            shift 2
            ;;
        --no-cloud-init)
            WAIT_CLOUD_INIT=false
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ -z "$VM_NAME" ]]; then
    log_error "VM name is required"
    usage
    exit 1
fi

# Step 1: Wait for SSH
log_info "Waiting for SSH on VM: $VM_NAME (timeout: ${SSH_TIMEOUT}s)"

VM_IP=$(python3 "${VM_CTL}" wait-ssh --name "$VM_NAME" --timeout "$SSH_TIMEOUT") || {
    log_error "SSH timeout for VM: $VM_NAME"
    exit 1
}

log_info "SSH ready. VM IP: $VM_IP"

# Step 2: Wait for cloud-init (optional)
if [[ "$WAIT_CLOUD_INIT" == "true" ]]; then
    log_info "Waiting for cloud-init to complete (timeout: ${CLOUD_INIT_TIMEOUT}s)"

    start_time=$(date +%s)
    while true; do
        elapsed=$(($(date +%s) - start_time))
        if [[ $elapsed -gt $CLOUD_INIT_TIMEOUT ]]; then
            log_error "Cloud-init timeout"
            exit 1
        fi

        status=$(python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
            cat /tmp/cloud-init-status 2>/dev/null || echo "pending")

        if [[ "$status" == "cloud-init-complete" ]]; then
            log_info "Cloud-init completed"
            break
        fi

        # Show progress
        ci_status=$(python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
            "cloud-init status 2>/dev/null | head -1" 2>/dev/null || echo "unknown")
        echo -ne "\rCloud-init: ${ci_status} (${elapsed}s)    "
        sleep 5
    done
    echo ""
fi

# Output VM IP for scripting
echo "$VM_IP"
