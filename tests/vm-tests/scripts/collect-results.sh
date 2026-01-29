#!/bin/bash
# Collect test results from VM
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_CTL="${SCRIPT_DIR}/vm-ctl.py"
VM_TESTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default values
VM_NAME=""
REMOTE_RESULTS="/test-results"
LOCAL_RESULTS="${VM_TESTS_DIR}/results"

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
Collect test results from VM.

Usage: $0 --name VM_NAME [OPTIONS]

Options:
    --name NAME           VM name (required)
    --remote PATH         Remote results path (default: /test-results)
    --local PATH          Local results path (default: tests/vm-tests/results)
    --help                Show this help

Example:
    $0 --name boxctl-test-vm
    $0 --name test-vm --local ./my-results
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)
            VM_NAME="$2"
            shift 2
            ;;
        --remote)
            REMOTE_RESULTS="$2"
            shift 2
            ;;
        --local)
            LOCAL_RESULTS="$2"
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

if [[ -z "$VM_NAME" ]]; then
    log_error "VM name is required"
    usage
    exit 1
fi

# Create local results directory
mkdir -p "$LOCAL_RESULTS"

# Add timestamp subdirectory
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RESULT_DIR="${LOCAL_RESULTS}/${VM_NAME}-${TIMESTAMP}"
mkdir -p "$RESULT_DIR"

log_info "Collecting results from VM: $VM_NAME"
log_info "Remote path: $REMOTE_RESULTS"
log_info "Local path: $RESULT_DIR"

# Check if remote results exist
if ! python3 "${VM_CTL}" ssh --name "$VM_NAME" -- "ls -la ${REMOTE_RESULTS}" &>/dev/null; then
    log_warn "No results found at ${REMOTE_RESULTS}"
    exit 0
fi

# List files to collect
log_info "Files to collect:"
python3 "${VM_CTL}" ssh --name "$VM_NAME" -- "ls -la ${REMOTE_RESULTS}"
echo ""

# Copy results
log_info "Copying results..."

# Create tarball on VM to handle multiple files
python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
    "tar -czf /tmp/test-results.tar.gz -C ${REMOTE_RESULTS} ." || {
    log_warn "Failed to create tarball"
    exit 1
}

# Copy tarball
python3 "${VM_CTL}" scp --name "$VM_NAME" --direction from \
    --remote "/tmp/test-results.tar.gz" --local "${RESULT_DIR}/results.tar.gz"

# Extract locally
cd "$RESULT_DIR"
tar -xzf results.tar.gz
rm -f results.tar.gz

# Cleanup tarball on VM
python3 "${VM_CTL}" ssh --name "$VM_NAME" -- "rm -f /tmp/test-results.tar.gz"

log_info "Results collected to: $RESULT_DIR"

# List collected files
echo ""
echo "Collected files:"
ls -la "$RESULT_DIR"

# If HTML report exists, show path
if [[ -f "${RESULT_DIR}/report.html" ]]; then
    echo ""
    log_info "HTML report: ${RESULT_DIR}/report.html"
fi
