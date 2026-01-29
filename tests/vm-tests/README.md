# VM-Based Tests for boxctl

This directory contains VM-based testing infrastructure for boxctl. Unlike Docker-in-Docker (DinD) tests, these tests run in isolated libvirt VMs, providing:

- **True isolation**: Full VM isolation vs. privileged container
- **0-to-hero testing**: Test the complete installation flow from a fresh OS
- **Native Docker performance**: VMs use overlay2 vs. DinD's slow vfs driver
- **Multi-distro support**: Test on Ubuntu, Fedora, and other distributions
- **Observability**: Console access, VNC, full system logs

## Architecture

```
Host → libvirt VM → Docker → boxctl containers
        └─ pytest runs here (INSIDE VM)
        └─ native dockerd (fast overlay2)
Host observes via virsh console, collects results via SCP
```

Key insight: **pytest runs INSIDE the VM**, not on the host. This preserves all existing test assumptions about local paths, Docker CLI, and filesystem access. The existing DinD test helpers work unchanged.

## Directory Structure

```
vm-tests/
├── README.md               # This file
├── scripts/
│   ├── vm-ctl.py          # VM lifecycle controller
│   ├── run-vm-tests.sh    # Main test orchestrator
│   ├── wait-for-vm.sh     # Wait for VM readiness
│   └── collect-results.sh # Collect test results from VM
├── images/
│   ├── Makefile           # Build orchestration
│   ├── build-minimal.sh   # Build minimal image (no Docker)
│   ├── build-prepared.sh  # Build prepared image (with boxctl)
│   ├── cloud-init/
│   │   ├── meta-data.yaml
│   │   ├── minimal-user-data.yaml
│   │   └── prepared-user-data.yaml
│   └── distros/
│       ├── ubuntu-24.04.yml
│       └── fedora-41.yml
├── zero-to-hero/          # Installation tests
│   ├── conftest.py
│   └── test_installation.py
├── helpers/               # Reuses dind-tests/helpers/
└── results/               # Test results (gitignored)
```

## Image Types

### Minimal Image

For "0-to-hero" installation testing:

- Base OS (Ubuntu/Fedora cloud image)
- testuser with sudo
- Git, Python 3.12, pip
- **NO Docker pre-installed**

Tests install Docker and boxctl from scratch, exercising the real installation flow.

### Prepared Image

For regression testing:

- Everything in minimal, plus:
- Docker installed and running
- boxctl cloned and installed via Poetry
- boxctl-base image built
- Clean snapshot for fast restore

## Prerequisites

### On Host (where tests are launched)

```bash
# Ubuntu/Debian
sudo apt install libvirt-daemon-system virtinst qemu-kvm \
    genisoimage wget python3

# Fedora
sudo dnf install libvirt virt-install qemu-kvm \
    genisoimage wget python3

# Add user to libvirt group
sudo usermod -aG libvirt $USER
newgrp libvirt
```

### KVM Support

For best performance, ensure KVM is available:

```bash
# Check for KVM
ls -la /dev/kvm

# If not available, vm-ctl.py will fall back to TCG (software emulation)
```

## Quick Start

### Build Images

```bash
# Build both minimal and prepared images for Ubuntu 24.04
cd tests/vm-tests/images
make all

# Or build specific images
make minimal DISTRO=ubuntu-24.04
make prepared DISTRO=fedora-41
```

### Run Tests

```bash
# Run all regression tests (unique VM per run, auto-cleanup)
./tests/vm-tests/scripts/run-vm-tests.sh

# Run with shared VM (for local development, faster iteration)
./tests/vm-tests/scripts/run-vm-tests.sh --shared

# Run zero-to-hero installation tests (uses minimal image)
./tests/vm-tests/scripts/run-vm-tests.sh --zero-to-hero

# Run specific tests
./tests/vm-tests/scripts/run-vm-tests.sh -k "test_start"

# Run on Fedora
./tests/vm-tests/scripts/run-vm-tests.sh --distro fedora-41

# Interactive mode (SSH into VM)
./tests/vm-tests/scripts/run-vm-tests.sh --interactive

# Preserve VM after tests for debugging
./tests/vm-tests/scripts/run-vm-tests.sh --preserve

# Skip JUnit output (for local runs)
./tests/vm-tests/scripts/run-vm-tests.sh --no-junit

# Skip snapshot restore (for debugging polluted state)
./tests/vm-tests/scripts/run-vm-tests.sh --shared --no-restore
```

### CI Integration Features

The test runner includes several features for CI environments:

- **Unique VM names**: Each run gets a unique VM name based on `RUN_ID`, preventing parallel run collisions
- **Auto-cleanup**: VMs are destroyed after tests (unless `--preserve`)
- **Signal handling**: Proper cleanup on SIGTERM/SIGINT (CI cancellation)
- **JUnit output**: Default `--junitxml` for CI test reporting
- **Snapshot isolation**: Prepared VMs are restored to clean state before each run

```bash
# CI job example - unique VM, auto-cleanup, JUnit output
GITHUB_RUN_ID=12345 ./tests/vm-tests/scripts/run-vm-tests.sh

# Clean up stale VMs (CI maintenance)
python3 ./tests/vm-tests/scripts/vm-ctl.py cleanup --dry-run
python3 ./tests/vm-tests/scripts/vm-ctl.py cleanup
```

## vm-ctl.py Commands

The VM controller provides a CLI for VM lifecycle management:

```bash
# Create a VM
./scripts/vm-ctl.py create --name test-vm --distro ubuntu-24.04 --image prepared

# List VMs
./scripts/vm-ctl.py list

# Get VM info
./scripts/vm-ctl.py info --name test-vm

# SSH to VM
./scripts/vm-ctl.py ssh --name test-vm
./scripts/vm-ctl.py ssh --name test-vm -- ls -la /opt/boxctl

# Create/restore snapshots
./scripts/vm-ctl.py snapshot --name test-vm --snapshot clean-state
./scripts/vm-ctl.py restore --name test-vm --snapshot clean-state

# Copy files
./scripts/vm-ctl.py scp --name test-vm --direction to --local ./file --remote /tmp/file
./scripts/vm-ctl.py scp --name test-vm --direction from --remote /tmp/file --local ./file

# Destroy VM
./scripts/vm-ctl.py destroy --name test-vm

# Clean up stale test VMs (CI maintenance)
./scripts/vm-ctl.py cleanup --dry-run  # Show what would be destroyed
./scripts/vm-ctl.py cleanup            # Actually destroy matching VMs
./scripts/vm-ctl.py cleanup --pattern "^boxctl-.*-20240101"  # Custom pattern
```

## Test Reuse

Since pytest runs inside the VM, **existing DinD test helpers work unchanged**:

- `helpers/cli.py` - Calls local `boxctl` (works in VM)
- `helpers/docker.py` - Calls local `docker` (works in VM)
- `helpers/config.py` - Manipulates local files (works in VM)
- `helpers/git.py` - Calls local `git` (works in VM)
- `conftest.py` - Same fixtures work

You can run the existing DinD tests directly from within a VM:

```bash
# SSH into prepared VM and run DinD tests
./scripts/vm-ctl.py ssh --name boxctl-prepared-ubuntu-24.04
cd /opt/boxctl
pytest tests/dind-tests/ -v
```

## Snapshot Strategy

### Regression Tests (prepared image)

```
Minimal Cloud Image (Ubuntu/Fedora)
    │
    └── prepared-image (docker + boxctl + base image)
            │
            └── clean-prepared (snapshot at boot)
                    │
                    └── (restore here between test modules)
```

### Zero-to-Hero Tests (minimal image)

```
Minimal Cloud Image (Ubuntu/Fedora)
    │
    └── (tests run from scratch each time)
        (VM destroyed after test suite)
```

## Observability

```bash
# Watch VM console in real-time
virsh console boxctl-test-vm

# Stream logs
./scripts/vm-ctl.py ssh --name test-vm -- tail -f /var/log/syslog

# VNC for graphical debugging (if enabled)
virt-viewer boxctl-test-vm
```

## CI Integration

### Requirements for CI Runner

- KVM support (`/dev/kvm` accessible)
- libvirt installed and running
- ~20GB disk space for images
- 8GB+ RAM for VM + host

### GitHub Actions Example

```yaml
jobs:
  vm-test:
    runs-on: self-hosted  # With KVM support
    strategy:
      matrix:
        distro: [ubuntu-24.04, fedora-41]
    steps:
      - uses: actions/checkout@v4
      - name: Run VM tests
        run: |
          DISTRO=${{ matrix.distro }} ./tests/vm-tests/scripts/run-vm-tests.sh
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: results-${{ matrix.distro }}
          path: tests/vm-tests/results/
```

### Fallback for No KVM

```bash
# vm-ctl.py detects missing KVM and uses TCG (software emulation)
./scripts/vm-ctl.py create --name test --accel tcg
```

This is much slower but works anywhere.

## Auth Handling

For tests requiring Claude/Codex credentials:

```bash
# Mount auth directories when running tests
./scripts/run-vm-tests.sh --with-auth

# Auth files are copied to VM via SCP (not mounted)
# They're placed at /home/testuser/.claude, etc.
```

## Comparison: VM vs DinD

| Aspect | DinD | VM |
|--------|------|----|
| "0 to hero" testing | Impossible | Full installation flow |
| Docker performance | Slow (vfs driver) | Native (overlay2) |
| Observability | Limited | Console, VNC, full logs |
| Snapshots | Slow commits | Fast libvirt snapshots |
| Multi-distro | Rebuild container | Multiple VM images |
| Isolation | Privileged container | True VM isolation |
| Setup time | Fast | Slower (boot VM) |
| Resource usage | Lower | Higher (full VM) |

## Troubleshooting

### VM Won't Start

```bash
# Check libvirt status
sudo systemctl status libvirtd

# Check for errors
virsh list --all
journalctl -u libvirtd
```

### KVM Not Available

```bash
# Check CPU virtualization support
egrep -c '(vmx|svm)' /proc/cpuinfo

# Load KVM module
sudo modprobe kvm_intel  # or kvm_amd

# Fall back to TCG
./scripts/vm-ctl.py create --name test --accel tcg
```

### SSH Connection Refused

```bash
# Check if VM is running
virsh domstate test-vm

# Check VM IP
virsh domifaddr test-vm --source lease

# Check firewall
sudo iptables -L -n
```

### Cloud-init Timeout

```bash
# SSH in manually and check logs
virsh console test-vm
# Or
ssh testuser@VM_IP

# Inside VM
cat /var/log/cloud-init.log
cloud-init status
```

## Development

### Adding a New Distro

1. Add cloud image URL to `vm-ctl.py` CLOUD_IMAGES dict
2. Create distro config in `images/distros/`
3. Test with `make minimal DISTRO=new-distro`

### Modifying cloud-init

1. Edit `images/cloud-init/*.yaml`
2. Rebuild images: `make rebuild`

### Adding New Tests

Zero-to-hero tests go in `zero-to-hero/`.
Regression tests can use existing `dind-tests/` structure directly.
