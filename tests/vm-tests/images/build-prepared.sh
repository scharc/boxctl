#!/bin/bash
# Build prepared VM image for regression testing
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
#
# This script creates a prepared VM image with:
# - Base OS (Ubuntu/Fedora)
# - Docker installed and running
# - boxctl cloned and installed via Poetry
# - boxctl-base image built
# - Snapshot for fast restore between tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_CTL="${SCRIPT_DIR}/../scripts/vm-ctl.py"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Default values
DISTRO="${DISTRO:-ubuntu-24.04}"
VM_NAME="boxctl-prepared-${DISTRO}"
TIMEOUT=1800  # 30 minutes for full setup (Docker + boxctl + base image)

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
Build prepared VM image for regression testing.

Usage: $0 [OPTIONS]

Options:
    --distro DISTRO    Distribution (default: ubuntu-24.04)
                       Options: ubuntu-24.04, ubuntu-22.04, fedora-41, fedora-40
    --name NAME        VM name (default: boxctl-prepared-DISTRO)
    --sync-repo        Sync local repo to VM (instead of using clone from cloud-init)
    --help             Show this help

Example:
    $0 --distro ubuntu-24.04
    $0 --sync-repo  # Use local repo changes
    DISTRO=fedora-41 $0
EOF
}

SYNC_REPO=false

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
        --sync-repo)
            SYNC_REPO=true
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

# Update VM name if using default
if [[ "$VM_NAME" == "boxctl-prepared-"* ]]; then
    VM_NAME="boxctl-prepared-${DISTRO}"
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Build Prepared VM Image                            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Distro: ${DISTRO}"
echo "VM Name: ${VM_NAME}"
echo "Sync Repo: ${SYNC_REPO}"
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
log_step "Creating prepared VM..."
python3 "${VM_CTL}" create \
    --name "${VM_NAME}" \
    --distro "${DISTRO}" \
    --image prepared \
    --ram 8192 \
    --vcpus 4 \
    --disk 60 \
    --wait-ssh

# Step 3: If sync-repo, copy local repo to VM
if [[ "${SYNC_REPO}" == "true" ]]; then
    log_step "Syncing local repository to VM..."

    # Create temp tarball (exclude .git, __pycache__, etc.)
    TARBALL="/tmp/boxctl-sync-$$.tar.gz"
    tar -czf "${TARBALL}" \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache' \
        --exclude='*.egg-info' \
        --exclude='.venv' \
        --exclude='node_modules' \
        -C "${REPO_ROOT}" .

    # Copy to VM
    python3 "${VM_CTL}" scp --name "${VM_NAME}" --direction to \
        --local "${TARBALL}" --remote "/tmp/boxctl.tar.gz"

    # Extract on VM
    python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- \
        "rm -rf /opt/boxctl/* && tar -xzf /tmp/boxctl.tar.gz -C /opt/boxctl"

    rm -f "${TARBALL}"

    # Reinstall Poetry dependencies
    log_info "Reinstalling Poetry dependencies..."
    python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- \
        "cd /opt/boxctl && ~/.local/bin/poetry install"
fi

# Step 4: Wait for cloud-init to complete
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

    # Show progress
    cloud_init_stage=$(python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- \
        "cloud-init status 2>/dev/null | grep -oP 'status: \K.*' || echo 'unknown'")
    echo -ne "\rCloud-init status: ${cloud_init_stage} (${elapsed}s)    "
    sleep 10
done
echo ""

# Step 5: Verify Docker is working
log_step "Verifying Docker..."
python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- docker info >/dev/null || {
    log_error "Docker not working"
    exit 1
}
log_info "Docker is working"

# Step 6: Verify boxctl is installed
log_step "Verifying boxctl..."
python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- boxctl --version || {
    log_error "boxctl not available"
    exit 1
}
log_info "boxctl is installed"

# Step 7: Verify boxctl-base image exists
log_step "Verifying boxctl-base image..."
if ! python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- \
    "docker images boxctl-base:latest --format '{{.Repository}}'" | grep -q "boxctl-base"; then
    log_warn "boxctl-base image not found, building..."
    python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- \
        "cd /opt/boxctl && docker build -f Dockerfile.base -t boxctl-base:latest ."
fi
log_info "boxctl-base image exists"

# Step 8: Run a quick sanity check
log_step "Running sanity check..."
python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- bash -c '
    cd /test-workspace
    rm -rf sanity-test
    mkdir sanity-test && cd sanity-test
    git init
    boxctl init
    if [ -d .boxctl ]; then
        echo "Sanity check passed"
        exit 0
    else
        echo "Sanity check failed"
        exit 1
    fi
' || {
    log_error "Sanity check failed"
    exit 1
}
log_info "Sanity check passed"

# Step 9: Clean up test artifacts before snapshot
log_step "Cleaning up before snapshot..."
python3 "${VM_CTL}" ssh --name "${VM_NAME}" -- bash -c '
    # Clean test workspace
    rm -rf /test-workspace/*
    # Clean Docker
    docker system prune -f
    # Clear history
    > ~/.bash_history
    history -c
'

# Step 10: Create snapshot for fast restore
log_step "Creating clean snapshot..."
python3 "${VM_CTL}" snapshot --name "${VM_NAME}" --snapshot "clean-prepared"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Prepared Image Built Successfully                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "VM Name: ${VM_NAME}"
echo "Snapshot: clean-prepared"
echo ""
echo "To use:"
echo "  python3 ${VM_CTL} restore --name ${VM_NAME} --snapshot clean-prepared"
echo "  python3 ${VM_CTL} ssh --name ${VM_NAME}"
echo ""
echo "To run tests:"
echo "  ./tests/vm-tests/scripts/run-vm-tests.sh --vm ${VM_NAME}"
echo ""
