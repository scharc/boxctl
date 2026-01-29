#!/bin/bash
# Build minimal VM image for zero-to-hero testing
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
#
# This script creates a minimal VM image with:
# - Base OS (Ubuntu/Fedora)
# - testuser with sudo
# - Git, Python 3, pip
# - NO Docker (tests install it)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_CTL="${SCRIPT_DIR}/../scripts/vm-ctl.py"

# Default values
DISTRO="${DISTRO:-ubuntu-24.04}"
VM_NAME="boxctl-minimal-${DISTRO}"
TIMEOUT=600  # 10 minutes for cloud-init

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[====]${NC} $*"; }

usage() {
    cat <<EOF
Build minimal VM image for zero-to-hero testing.

Usage: $0 [OPTIONS]

Options:
    --distro DISTRO    Distribution (default: ubuntu-24.04)
                       Options: ubuntu-24.04, ubuntu-22.04, fedora-41, fedora-40
    --name NAME        VM name (default: boxctl-minimal-DISTRO)
    --help             Show this help

Example:
    $0 --distro ubuntu-24.04
    DISTRO=fedora-41 $0
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --distro)
            DISTRO="$2"
            shift 2
            ;;
        --name)
            VM_NAME="$2"
            shift 2
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

# Update VM name if using default
if [[ "$VM_NAME" == "boxctl-minimal-"* ]]; then
    VM_NAME="boxctl-minimal-${DISTRO}"
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Build Minimal VM Image                             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Distro: ${DISTRO}"
echo "VM Name: ${VM_NAME}"
echo ""

# Step 1: Check if VM already exists
log_step "Checking for existing VM..."
if python3 "${VM_CTL}" info --name "${VM_NAME}" &>/dev/null; then
    log_warn "VM already exists: ${VM_NAME}"
    read -p "Destroy and rebuild? [y/N] " answer
    if [[ "${answer}" =~ ^[Yy]$ ]]; then
        python3 "${VM_CTL}" destroy --name "${VM_NAME}"
    else
        log_info "Exiting"
        exit 0
    fi
fi

# Step 2: Create VM
log_step "Creating minimal VM..."
python3 "${VM_CTL}" create \
    --name "${VM_NAME}" \
    --distro "${DISTRO}" \
    --image minimal \
    --wait-ssh

# Step 3: Wait for cloud-init to complete
log_step "Waiting for cloud-init to complete..."
start_time=$(date +%s)
while true; do
    elapsed=$(($(date +%s) - start_time))
    if [[ $elapsed -gt $TIMEOUT ]]; then
        log_error "Timeout waiting for cloud-init"
        python3 "${VM_CTL}" destroy --name "${VM_NAME}"
        exit 1
    fi

    status=$(python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- cat /tmp/cloud-init-status 2>/dev/null || echo "pending")
    if [[ "$status" == "cloud-init-complete" ]]; then
        log_info "Cloud-init completed"
        break
    fi

    echo -n "."
    sleep 10
done
echo ""

# Step 4: Verify the image
log_step "Verifying minimal image..."

# Check Python
python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- python3 --version || {
    log_error "Python not available"
    exit 1
}

# Check Git
python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- git --version || {
    log_error "Git not available"
    exit 1
}

# Verify Docker is NOT installed (this is minimal image)
if python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- which docker &>/dev/null; then
    log_warn "Docker is installed - this should be a minimal image!"
fi

# Step 5: Create snapshot for fast restore
log_step "Creating clean snapshot..."
python3 "${VM_CTL}" snapshot --name "${VM_NAME}" --snapshot "clean-minimal"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Minimal Image Built Successfully                   ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "VM Name: ${VM_NAME}"
echo "Snapshot: clean-minimal"
echo ""
echo "To use:"
echo "  python3 ${VM_CTL} restore --name ${VM_NAME} --snapshot clean-minimal"
echo "  python3 ${VM_CTL} ssh --name ${VM_NAME}"
echo ""
