#!/bin/bash
# Boxctl VM Test Runner
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
#
# This script orchestrates VM-based testing for boxctl.
# Tests run INSIDE the VM, just like in DinD, but with full VM isolation.
#
# Usage:
#   ./run-vm-tests.sh                     # Run all tests
#   ./run-vm-tests.sh --zero-to-hero      # Run only installation tests
#   ./run-vm-tests.sh -k "TestPhase1"     # Run tests matching pattern
#   ./run-vm-tests.sh --with-auth         # Run with Claude/Codex auth mounted

set -e

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_TESTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${VM_TESTS_DIR}/../.." && pwd)"
VM_CTL="${SCRIPT_DIR}/vm-ctl.py"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[====]${NC} $*"; }

# Generate unique run ID (can be overridden by CI)
generate_run_id() {
    # Use CI job ID if available, otherwise generate timestamp + random
    if [[ -n "${CI_JOB_ID:-}" ]]; then
        echo "${CI_JOB_ID}"
    elif [[ -n "${GITHUB_RUN_ID:-}" ]]; then
        # Include GITHUB_JOB to make unique across parallel jobs in same workflow
        local job="${GITHUB_JOB:-default}"
        echo "${GITHUB_RUN_ID}-${job}-${GITHUB_RUN_ATTEMPT:-1}"
    elif [[ -n "${BUILD_ID:-}" ]]; then
        echo "${BUILD_ID}"
    else
        echo "$(date +%Y%m%d-%H%M%S)-$$"
    fi
}

# Default options
DISTRO="${DISTRO:-ubuntu-24.04}"
IMAGE_TYPE="prepared"
RUN_ID="${RUN_ID:-$(generate_run_id)}"
VM_NAME=""
USE_SHARED_VM=false  # If true, use shared VM name (for local dev)
WITH_AUTH=false
REBUILD_IMAGE=false
INTERACTIVE=false
PRESERVE_VM=false
ZERO_TO_HERO=false
SYNC_REPO=false
NO_RESTORE=false  # Skip snapshot restore (for debugging)
TEST_ARGS=""
PYTEST_ARGS="-v --tb=short"
SSH_TIMEOUT=300
TEST_TIMEOUT=1800  # 30 min for full test suite

# Track if we created the VM (for cleanup)
CREATED_VM=""
CLEANUP_DONE=false

# ============================================================================
# Cleanup and Signal Handling
# ============================================================================

cleanup() {
    # Prevent double cleanup
    if [[ "$CLEANUP_DONE" == "true" ]]; then
        return
    fi
    CLEANUP_DONE=true

    local exit_code=${1:-$?}

    if [[ "$PRESERVE_VM" == "false" ]] && [[ -n "$CREATED_VM" ]]; then
        log_info "Cleaning up VM: $CREATED_VM"
        python3 "${VM_CTL}" destroy --name "$CREATED_VM" 2>/dev/null || true
    elif [[ -n "$CREATED_VM" ]]; then
        log_info "VM preserved: $CREATED_VM"
        log_info "To reconnect: python3 ${VM_CTL} ssh --name $CREATED_VM"
        log_info "To destroy:   python3 ${VM_CTL} destroy --name $CREATED_VM"
    fi

    # Clean up temp files
    rm -f "/tmp/boxctl-sync-$$.tar.gz" 2>/dev/null || true

    exit "$exit_code"
}

# Trap all termination signals for robust cleanup
trap 'cleanup $?' EXIT
trap 'log_warn "Received SIGINT, cleaning up..."; cleanup 130' INT
trap 'log_warn "Received SIGTERM, cleaning up..."; cleanup 143' TERM
trap 'log_warn "Received SIGHUP, cleaning up..."; cleanup 129' HUP

# ============================================================================
# Argument Parsing
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --distro)
            DISTRO="$2"
            shift 2
            ;;
        --image)
            IMAGE_TYPE="$2"
            shift 2
            ;;
        --run-id)
            RUN_ID="$2"
            shift 2
            ;;
        --vm)
            VM_NAME="$2"
            USE_SHARED_VM=true
            PRESERVE_VM=true  # Explicit VMs should not be destroyed
            shift 2
            ;;
        --shared)
            # Use shared VM name (for local development, not CI)
            USE_SHARED_VM=true
            PRESERVE_VM=true  # Shared VMs should not be destroyed
            shift
            ;;
        --with-auth)
            WITH_AUTH=true
            shift
            ;;
        --rebuild-image)
            REBUILD_IMAGE=true
            shift
            ;;
        --interactive|-i)
            INTERACTIVE=true
            PRESERVE_VM=true  # Interactive implies preserve
            shift
            ;;
        --preserve)
            PRESERVE_VM=true
            shift
            ;;
        --no-restore)
            NO_RESTORE=true
            shift
            ;;
        --zero-to-hero)
            ZERO_TO_HERO=true
            IMAGE_TYPE="minimal"
            shift
            ;;
        --sync-repo)
            SYNC_REPO=true
            shift
            ;;
        --all)
            TEST_ARGS=""
            shift
            ;;
        -k)
            PYTEST_ARGS="${PYTEST_ARGS} -k \"$2\""
            shift 2
            ;;
        -x)
            PYTEST_ARGS="${PYTEST_ARGS} -x"
            shift
            ;;
        --html)
            PYTEST_ARGS="${PYTEST_ARGS} --html=/test-results/report.html --self-contained-html"
            shift
            ;;
        --no-junit)
            # Skip default JUnit output (for local runs)
            NO_JUNIT=true
            shift
            ;;
        --help|-h)
            cat <<EOF
Boxctl VM Test Runner

Usage: $0 [OPTIONS] [TEST_FILE|TEST_PATTERN]

VM Options:
  --distro DISTRO     Distribution (default: ubuntu-24.04)
                      Options: ubuntu-24.04, ubuntu-22.04, fedora-41, fedora-40
  --image TYPE        Image type: minimal or prepared (default: prepared)
  --run-id ID         Unique run identifier (auto-generated if not set)
  --vm NAME           Use specific VM by name (implies --shared, --preserve)
  --shared            Use shared VM name instead of unique per-run
                      (implies --preserve, for local development)
  --rebuild-image     Force rebuild the base VM image
  --interactive       SSH into VM instead of running tests (implies --preserve)
  --preserve          Don't destroy VM after tests
  --no-restore        Skip snapshot restore (use current VM state)

Test Options:
  --with-auth         Copy Claude/Codex credentials for auth tests
  --zero-to-hero      Run zero-to-hero installation tests (uses minimal image)
  --sync-repo         Sync local repo to VM before tests
  --all               Run all tests
  -k PATTERN          Run tests matching pattern
  -x                  Stop on first failure
  --html              Generate HTML report
  --no-junit          Skip default JUnit XML output

Environment Variables:
  RUN_ID              Override run identifier
  DISTRO              Override distribution
  CI_JOB_ID           CI job ID (used for run-id if set)
  GITHUB_RUN_ID       GitHub Actions run ID (used for run-id if set)

Examples:
  $0                              # Run all tests (unique VM per run)
  $0 --shared                     # Run with shared VM (local dev)
  $0 --zero-to-hero               # Run installation tests from scratch
  $0 -k 'test_start'              # Run tests with 'test_start' in name
  $0 --with-auth                  # Run with auth for agent tests
  $0 --interactive                # SSH into VM for debugging
  $0 --distro fedora-41           # Test on Fedora

Image Types:
  minimal   - Base OS + Python + Git (NO Docker)
              Used for zero-to-hero installation testing
  prepared  - Above + Docker + boxctl + boxctl-base image
              Used for regression testing (fast)

CI Integration:
  By default, each run gets a unique VM name based on RUN_ID.
  This prevents parallel run collisions. VMs are destroyed after tests
  unless --preserve is used.

  For regression tests (prepared image), the VM is always restored to
  a clean snapshot before running tests, ensuring isolation.
EOF
            exit 0
            ;;
        *)
            # Treat as pytest args
            if [[ $1 == *.py ]] || [[ $1 == Test* ]] || [[ $1 == test_* ]]; then
                TEST_ARGS="$1"
            else
                PYTEST_ARGS="${PYTEST_ARGS} $1"
            fi
            shift
            ;;
    esac
done

# ============================================================================
# VM Name Generation
# ============================================================================

if [[ -z "$VM_NAME" ]]; then
    if [[ "$USE_SHARED_VM" == "true" ]]; then
        # Shared VM name (for local development)
        VM_NAME="boxctl-${IMAGE_TYPE}-${DISTRO}"
    else
        # Unique VM name per run (for CI and isolation)
        VM_NAME="boxctl-${IMAGE_TYPE}-${DISTRO}-${RUN_ID}"
    fi
fi

# Add default JUnit output for CI (unless disabled)
if [[ "${NO_JUNIT:-false}" != "true" ]]; then
    PYTEST_ARGS="${PYTEST_ARGS} --junitxml=/test-results/junit.xml"
fi

# ============================================================================
# Banner
# ============================================================================

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║         Boxctl VM Test Runner                              ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Run ID:${NC}     ${RUN_ID}"
echo -e "${BLUE}Distro:${NC}     ${DISTRO}"
echo -e "${BLUE}Image:${NC}      ${IMAGE_TYPE}"
echo -e "${BLUE}VM:${NC}         ${VM_NAME}"
echo -e "${BLUE}Shared VM:${NC}  ${USE_SHARED_VM}"
echo -e "${BLUE}Zero-Hero:${NC}  ${ZERO_TO_HERO}"
echo -e "${BLUE}With Auth:${NC}  ${WITH_AUTH}"
echo ""

# ============================================================================
# Step 1: VM Setup
# ============================================================================

log_step "Setting up VM..."

VM_EXISTS=false
if python3 "${VM_CTL}" info --name "$VM_NAME" &>/dev/null; then
    VM_EXISTS=true
    log_info "Found existing VM: $VM_NAME"
fi

# Handle rebuild-image flag
if [[ "$REBUILD_IMAGE" == "true" ]] && [[ "$VM_EXISTS" == "true" ]]; then
    log_info "Rebuilding image, destroying existing VM..."
    python3 "${VM_CTL}" destroy --name "$VM_NAME"
    VM_EXISTS=false
fi

if [[ "$VM_EXISTS" == "false" ]]; then
    # Create new VM
    log_info "Creating new VM: $VM_NAME"
    python3 "${VM_CTL}" create \
        --name "$VM_NAME" \
        --distro "$DISTRO" \
        --image "$IMAGE_TYPE" \
        --wait-ssh
    CREATED_VM="$VM_NAME"

    # Wait for cloud-init (with proper failure handling)
    log_info "Waiting for cloud-init..."
    CLOUD_INIT_SUCCESS=false
    for i in {1..60}; do
        status=$(python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
            cat /tmp/cloud-init-status 2>/dev/null || echo "pending")
        if [[ "$status" == "cloud-init-complete" ]]; then
            log_info "Cloud-init completed"
            CLOUD_INIT_SUCCESS=true
            break
        elif [[ "$status" == cloud-init-error* ]]; then
            log_error "Cloud-init failed: $status"
            python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
                "tail -50 /var/log/cloud-init-output.log" 2>/dev/null || true
            exit 1
        fi
        echo -ne "\rWaiting for cloud-init... (${i}/60)    "
        sleep 10
    done
    echo ""
    if [[ "$CLOUD_INIT_SUCCESS" == "false" ]]; then
        log_error "Cloud-init timeout after 10 minutes"
        log_info "Fetching cloud-init logs..."
        python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
            "tail -100 /var/log/cloud-init-output.log" 2>/dev/null || true
        exit 1
    fi

    # Create initial snapshot for prepared images
    if [[ "$IMAGE_TYPE" == "prepared" ]]; then
        log_info "Creating clean snapshot..."
        python3 "${VM_CTL}" snapshot --name "$VM_NAME" --snapshot "clean-prepared" || true
    fi
else
    # VM exists - handle restore for isolation
    # Note: We don't set CREATED_VM here because we didn't create it
    # This prevents destroying shared/explicit VMs

    # Check if VM is running, start if needed
    VM_STATE=$(python3 "${VM_CTL}" info --name "$VM_NAME" --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('state','unknown'))" 2>/dev/null || echo "unknown")
    if [[ "$VM_STATE" == "shut off" ]]; then
        log_info "Starting stopped VM: $VM_NAME"
        python3 "${VM_CTL}" start --name "$VM_NAME"
    fi

    if [[ "$IMAGE_TYPE" == "prepared" ]] && [[ "$NO_RESTORE" != "true" ]]; then
        # Always restore snapshot for prepared images to ensure isolation
        SNAPSHOT="clean-prepared"
        log_info "Restoring VM to clean state: $SNAPSHOT"
        if python3 "${VM_CTL}" restore --name "$VM_NAME" --snapshot "$SNAPSHOT" 2>/dev/null; then
            log_info "Restored from snapshot"
        else
            log_warn "Snapshot not found, using current state (tests may not be isolated!)"
        fi
    elif [[ "$NO_RESTORE" == "true" ]]; then
        log_warn "Snapshot restore skipped (--no-restore), using current VM state"
    fi
fi

# ============================================================================
# Step 2: Wait for SSH
# ============================================================================

log_step "Waiting for SSH..."
VM_IP=$(python3 "${VM_CTL}" wait-ssh --name "$VM_NAME" --timeout "$SSH_TIMEOUT")
log_info "VM IP: $VM_IP"

# ============================================================================
# Step 3: Sync Repo (if requested)
# ============================================================================

if [[ "$SYNC_REPO" == "true" ]]; then
    log_step "Syncing local repository..."

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

    python3 "${VM_CTL}" scp --name "$VM_NAME" --direction to \
        --local "${TARBALL}" --remote "/tmp/boxctl.tar.gz"
    python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
        "rm -rf /opt/boxctl/* && tar -xzf /tmp/boxctl.tar.gz -C /opt/boxctl"
    rm -f "${TARBALL}"

    python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
        "cd /opt/boxctl && ~/.local/bin/poetry install"
fi

# ============================================================================
# Step 4: Copy Auth Files (if requested)
# ============================================================================

if [[ "$WITH_AUTH" == "true" ]]; then
    log_step "Copying auth credentials..."

    if [[ -d "$HOME/.claude" ]]; then
        log_info "Copying Claude credentials..."
        python3 "${VM_CTL}" scp --name "$VM_NAME" --direction to \
            --local "$HOME/.claude" --remote "/home/testuser/.claude"
    else
        log_warn "~/.claude not found, auth tests will be skipped"
    fi

    if [[ -d "$HOME/.codex" ]]; then
        log_info "Copying Codex credentials..."
        python3 "${VM_CTL}" scp --name "$VM_NAME" --direction to \
            --local "$HOME/.codex" --remote "/home/testuser/.codex"
    fi

    if [[ -d "$HOME/.gemini" ]]; then
        log_info "Copying Gemini credentials..."
        python3 "${VM_CTL}" scp --name "$VM_NAME" --direction to \
            --local "$HOME/.gemini" --remote "/home/testuser/.gemini"
    fi
fi

# ============================================================================
# Step 5: Prepare Results Directory
# ============================================================================

# Ensure /test-results exists and is writable by testuser
python3 "${VM_CTL}" ssh --name "$VM_NAME" -- "sudo mkdir -p /test-results && sudo chown testuser:testuser /test-results"

# ============================================================================
# Step 6: Run Tests or Interactive Mode
# ============================================================================

if [[ "$INTERACTIVE" == "true" ]]; then
    log_info "Starting interactive SSH session..."
    echo ""
    echo "Test workspace: /test-workspace"
    echo "boxctl root: /opt/boxctl"
    echo "Results dir: /test-results"
    echo ""
    echo "Run tests manually:"
    echo "  cd /opt/boxctl && poetry run pytest tests/dind-tests/ -v"
    echo ""
    python3 "${VM_CTL}" ssh --name "$VM_NAME"
else
    log_step "Running tests..."
    echo ""
    echo -e "${BLUE}Test args:${NC}   $TEST_ARGS"
    echo -e "${BLUE}Pytest args:${NC} $PYTEST_ARGS"
    echo ""

    # Determine test path
    if [[ "$ZERO_TO_HERO" == "true" ]]; then
        TEST_PATH="/opt/boxctl/tests/vm-tests/zero-to-hero/"
    elif [[ -n "$TEST_ARGS" ]]; then
        TEST_PATH="/opt/boxctl/tests/dind-tests/${TEST_ARGS}"
    else
        TEST_PATH="/opt/boxctl/tests/dind-tests/"
    fi

    # Run pytest inside VM
    PYTEST_CMD="cd /opt/boxctl && ~/.local/bin/poetry run pytest ${TEST_PATH} ${PYTEST_ARGS}"

    set +e
    python3 "${VM_CTL}" ssh --name "$VM_NAME" -- bash -c "$PYTEST_CMD"
    EXIT_CODE=$?
    set -e

    # ========================================================================
    # Step 7: Collect Results
    # ========================================================================

    log_step "Collecting results..."
    RESULTS_DIR="${REPO_ROOT}/tests/vm-tests/results"
    RUN_RESULTS_DIR="${RESULTS_DIR}/${RUN_ID}"
    mkdir -p "$RUN_RESULTS_DIR"

    # Copy results from VM
    python3 "${VM_CTL}" scp --name "$VM_NAME" --direction from \
        --remote "/test-results/*" --local "$RUN_RESULTS_DIR/" 2>/dev/null || true

    # Also collect logs on failure
    if [[ $EXIT_CODE -ne 0 ]]; then
        log_info "Collecting debug logs..."
        python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
            "cat /var/log/cloud-init-output.log" > "$RUN_RESULTS_DIR/cloud-init.log" 2>/dev/null || true
        python3 "${VM_CTL}" ssh --name "$VM_NAME" -- \
            "docker logs \$(docker ps -aq) 2>&1 | head -500" > "$RUN_RESULTS_DIR/docker.log" 2>/dev/null || true
    fi

    # ========================================================================
    # Step 8: Report Results
    # ========================================================================

    echo ""
    if [[ $EXIT_CODE -eq 0 ]]; then
        echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                    ALL TESTS PASSED                        ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║                    TESTS FAILED                            ║${NC}"
        echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    fi

    echo ""
    log_info "Results directory: $RUN_RESULTS_DIR"

    # Show specific result files
    if [[ -f "${RUN_RESULTS_DIR}/junit.xml" ]]; then
        log_info "JUnit report: ${RUN_RESULTS_DIR}/junit.xml"
    fi
    if [[ -f "${RUN_RESULTS_DIR}/report.html" ]]; then
        log_info "HTML report: ${RUN_RESULTS_DIR}/report.html"
    fi

    # Note: cleanup happens via EXIT trap
    # Set exit code for trap
    TRAP_EXIT_CODE=$EXIT_CODE
    exit $EXIT_CODE
fi
