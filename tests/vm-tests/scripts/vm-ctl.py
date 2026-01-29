#!/usr/bin/env python3
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""
VM Controller for boxctl VM-based tests.

Manages libvirt VMs for isolated, repeatable testing. Provides:
- VM creation from cloud images
- Snapshot management for fast test isolation
- SSH access to VMs
- Multi-distro support

Usage:
    ./vm-ctl.py create --name test-vm --distro ubuntu-24.04 --image prepared
    ./vm-ctl.py create --name hero-vm --distro ubuntu-24.04 --image minimal
    ./vm-ctl.py snapshot --name test-vm --snapshot clean-state
    ./vm-ctl.py restore --name test-vm --snapshot clean-state
    ./vm-ctl.py ssh --name test-vm [-- command]
    ./vm-ctl.py destroy --name test-vm
    ./vm-ctl.py list
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ============================================================================
# Constants
# ============================================================================

SCRIPT_DIR = Path(__file__).parent.resolve()
VM_TESTS_DIR = SCRIPT_DIR.parent
IMAGES_DIR = VM_TESTS_DIR / "images"
REPO_ROOT = VM_TESTS_DIR.parent.parent

# Default paths for libvirt
DEFAULT_POOL_PATH = Path.home() / ".local/share/boxctl-vm-tests"
DEFAULT_SSH_KEY_PATH = Path.home() / ".ssh/boxctl-vm-test"

# VM configuration defaults
DEFAULT_RAM_MB = 4096
DEFAULT_VCPUS = 2
DEFAULT_DISK_GB = 40

# Cloud image URLs by distro
CLOUD_IMAGES = {
    "ubuntu-24.04": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "name": "ubuntu-24.04-cloudimg.qcow2",
        "os_variant": "ubuntu24.04",
    },
    "ubuntu-22.04": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "name": "ubuntu-22.04-cloudimg.qcow2",
        "os_variant": "ubuntu22.04",
    },
    "fedora-41": {
        "url": "https://download.fedoraproject.org/pub/fedora/linux/releases/41/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-41-1.4.x86_64.qcow2",
        "name": "fedora-41-cloudimg.qcow2",
        "os_variant": "fedora-unknown",
    },
    "fedora-40": {
        "url": "https://download.fedoraproject.org/pub/fedora/linux/releases/40/Cloud/x86_64/images/Fedora-Cloud-Base-Generic.x86_64-40-1.14.qcow2",
        "name": "fedora-40-cloudimg.qcow2",
        "os_variant": "fedora-unknown",
    },
}

# Colors for output
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
NC = "\033[0m"


# ============================================================================
# Logging
# ============================================================================


def log_info(msg: str) -> None:
    print(f"{GREEN}[INFO]{NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)


def log_step(msg: str) -> None:
    print(f"{BLUE}[====]{NC} {msg}")


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class VMConfig:
    """VM configuration."""

    name: str
    distro: str
    image_type: str  # "minimal" or "prepared"
    ram_mb: int = DEFAULT_RAM_MB
    vcpus: int = DEFAULT_VCPUS
    disk_gb: int = DEFAULT_DISK_GB
    accel: str = "kvm"  # "kvm" or "tcg" (software emulation)


@dataclass
class VMInfo:
    """VM information returned from list/inspect."""

    name: str
    state: str
    distro: str
    image_type: str
    ip_address: Optional[str]
    disk_path: Path
    snapshots: list


# ============================================================================
# Utility Functions
# ============================================================================


def run_cmd(
    cmd: list,
    check: bool = True,
    capture_output: bool = True,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Run a shell command."""
    result = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result


def check_kvm_available() -> bool:
    """Check if KVM acceleration is available."""
    if not Path("/dev/kvm").exists():
        return False
    try:
        run_cmd(["kvm-ok"], check=False)
        return True
    except FileNotFoundError:
        # kvm-ok not installed, check /dev/kvm directly
        return os.access("/dev/kvm", os.R_OK | os.W_OK)


def ensure_pool_exists(pool_path: Path) -> None:
    """Ensure the storage pool directory exists."""
    pool_path.mkdir(parents=True, exist_ok=True)
    (pool_path / "base-images").mkdir(exist_ok=True)
    (pool_path / "vm-disks").mkdir(exist_ok=True)
    (pool_path / "cloud-init").mkdir(exist_ok=True)


def ensure_ssh_key() -> Path:
    """Ensure SSH key exists for VM access."""
    key_path = DEFAULT_SSH_KEY_PATH
    if not key_path.exists():
        log_info(f"Generating SSH key: {key_path}")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(key_path),
                "-N",
                "",
                "-C",
                "boxctl-vm-test",
            ]
        )
    return key_path


def get_ssh_public_key() -> str:
    """Get the SSH public key content."""
    key_path = ensure_ssh_key()
    return (key_path.with_suffix(".pub")).read_text().strip()


# ============================================================================
# Cloud Image Management
# ============================================================================


def download_cloud_image(distro: str, pool_path: Path) -> Path:
    """Download cloud image if not already present."""
    if distro not in CLOUD_IMAGES:
        raise ValueError(f"Unknown distro: {distro}. Available: {list(CLOUD_IMAGES.keys())}")

    image_info = CLOUD_IMAGES[distro]
    image_path = pool_path / "base-images" / image_info["name"]

    if image_path.exists():
        log_info(f"Using cached cloud image: {image_path}")
        return image_path

    log_step(f"Downloading {distro} cloud image...")
    url = image_info["url"]

    # Download with wget (more reliable for large files)
    run_cmd(
        [
            "wget",
            "-O",
            str(image_path),
            "--progress=dot:giga",
            url,
        ],
        timeout=1800,
    )  # 30 min timeout for download

    log_info(f"Downloaded: {image_path}")
    return image_path


# ============================================================================
# Cloud-Init Configuration
# ============================================================================


def create_cloud_init_iso(
    config: VMConfig,
    pool_path: Path,
) -> Path:
    """Create cloud-init ISO for VM provisioning."""
    ci_dir = pool_path / "cloud-init" / config.name
    ci_dir.mkdir(parents=True, exist_ok=True)

    # Determine cloud-init source file
    if config.image_type == "minimal":
        user_data_src = IMAGES_DIR / "cloud-init" / "minimal-user-data.yaml"
    else:
        user_data_src = IMAGES_DIR / "cloud-init" / "prepared-user-data.yaml"

    # Read and customize user-data
    user_data = user_data_src.read_text()

    # Inject SSH public key
    ssh_pubkey = get_ssh_public_key()
    user_data = user_data.replace("${SSH_PUBLIC_KEY}", ssh_pubkey)

    # Note: We don't inject local repo paths because host paths aren't
    # visible inside the VM. Use --sync-repo in run-vm-tests.sh instead.

    # Write customized user-data
    user_data_path = ci_dir / "user-data"
    user_data_path.write_text(user_data)

    # Copy meta-data
    meta_data_src = IMAGES_DIR / "cloud-init" / "meta-data.yaml"
    meta_data_path = ci_dir / "meta-data"
    meta_data_content = meta_data_src.read_text().replace("${VM_NAME}", config.name)
    meta_data_path.write_text(meta_data_content)

    # Create ISO
    iso_path = ci_dir / "cloud-init.iso"
    run_cmd(
        [
            "genisoimage",
            "-output",
            str(iso_path),
            "-volid",
            "cidata",
            "-joliet",
            "-rock",
            str(user_data_path),
            str(meta_data_path),
        ]
    )

    log_info(f"Created cloud-init ISO: {iso_path}")
    return iso_path


# ============================================================================
# VM Operations
# ============================================================================


def create_vm(
    config: VMConfig,
    pool_path: Path = DEFAULT_POOL_PATH,
) -> VMInfo:
    """Create a new VM from cloud image."""
    ensure_pool_exists(pool_path)

    log_step(f"Creating VM: {config.name}")

    # Check if VM already exists
    result = run_cmd(["virsh", "list", "--all", "--name"], check=False)
    if config.name in result.stdout.split():
        raise RuntimeError(f"VM already exists: {config.name}")

    # Download/locate base image
    base_image = download_cloud_image(config.distro, pool_path)

    # Create disk from base image
    disk_path = pool_path / "vm-disks" / f"{config.name}.qcow2"
    log_info("Creating VM disk...")
    run_cmd(
        [
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            "-b",
            str(base_image),
            str(disk_path),
            f"{config.disk_gb}G",
        ]
    )

    # Create cloud-init ISO
    ci_iso = create_cloud_init_iso(config, pool_path)

    # Determine acceleration
    accel = config.accel
    if accel == "kvm" and not check_kvm_available():
        log_warn("KVM not available, falling back to TCG (software emulation)")
        accel = "tcg"

    # Get OS variant
    os_variant = CLOUD_IMAGES[config.distro]["os_variant"]

    # Build virt-install command
    virt_cmd = [
        "virt-install",
        "--name",
        config.name,
        "--ram",
        str(config.ram_mb),
        "--vcpus",
        str(config.vcpus),
        "--disk",
        f"path={disk_path},format=qcow2",
        "--disk",
        f"path={ci_iso},device=cdrom",
        "--os-variant",
        os_variant,
        "--network",
        "network=default",
        "--graphics",
        "none",
        "--console",
        "pty,target_type=serial",
        "--import",
        "--noautoconsole",
    ]

    if accel == "tcg":
        virt_cmd.extend(["--virt-type", "qemu"])

    # Create VM
    log_info("Starting VM...")
    run_cmd(virt_cmd, timeout=120)

    # Store metadata
    metadata = {
        "distro": config.distro,
        "image_type": config.image_type,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    metadata_path = pool_path / "vm-disks" / f"{config.name}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))

    log_info(f"VM created: {config.name}")

    return get_vm_info(config.name, pool_path)


def destroy_vm(name: str, pool_path: Path = DEFAULT_POOL_PATH) -> None:
    """Destroy a VM and its disk."""
    log_step(f"Destroying VM: {name}")

    # Stop if running
    result = run_cmd(["virsh", "domstate", name], check=False)
    if result.returncode == 0 and "running" in result.stdout:
        run_cmd(["virsh", "destroy", name], check=False)

    # Undefine (remove from libvirt)
    run_cmd(["virsh", "undefine", name, "--remove-all-storage"], check=False)

    # Clean up our files
    disk_path = pool_path / "vm-disks" / f"{name}.qcow2"
    if disk_path.exists():
        disk_path.unlink()

    metadata_path = pool_path / "vm-disks" / f"{name}.json"
    if metadata_path.exists():
        metadata_path.unlink()

    ci_dir = pool_path / "cloud-init" / name
    if ci_dir.exists():
        shutil.rmtree(ci_dir)

    log_info(f"VM destroyed: {name}")


def start_vm(name: str) -> None:
    """Start a stopped VM."""
    log_info(f"Starting VM: {name}")
    run_cmd(["virsh", "start", name])


def stop_vm(name: str, force: bool = False) -> None:
    """Stop a running VM."""
    log_info(f"Stopping VM: {name}")
    if force:
        run_cmd(["virsh", "destroy", name])
    else:
        run_cmd(["virsh", "shutdown", name])


def get_vm_ip(name: str, timeout: int = 120) -> Optional[str]:
    """Get VM IP address via DHCP lease."""
    start = time.time()
    while time.time() - start < timeout:
        result = run_cmd(
            ["virsh", "domifaddr", name, "--source", "lease"],
            check=False,
        )
        if result.returncode == 0:
            # Parse output for IP
            for line in result.stdout.split("\n"):
                if "ipv4" in line:
                    # Format: vnet0 ... 192.168.122.123/24
                    parts = line.split()
                    for part in parts:
                        if "/" in part and "." in part:
                            return part.split("/")[0]
        time.sleep(2)
    return None


def get_vm_info(name: str, pool_path: Path = DEFAULT_POOL_PATH) -> VMInfo:
    """Get information about a VM."""
    # Check state
    result = run_cmd(["virsh", "domstate", name], check=False)
    if result.returncode != 0:
        raise RuntimeError(f"VM not found: {name}")
    state = result.stdout.strip()

    # Load metadata
    metadata_path = pool_path / "vm-disks" / f"{name}.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    else:
        metadata = {"distro": "unknown", "image_type": "unknown"}

    # Get IP if running
    ip_address = None
    if state == "running":
        ip_address = get_vm_ip(name, timeout=5)

    # Get snapshots
    result = run_cmd(["virsh", "snapshot-list", name, "--name"], check=False)
    snapshots = [s.strip() for s in result.stdout.split("\n") if s.strip()]

    disk_path = pool_path / "vm-disks" / f"{name}.qcow2"

    return VMInfo(
        name=name,
        state=state,
        distro=metadata.get("distro", "unknown"),
        image_type=metadata.get("image_type", "unknown"),
        ip_address=ip_address,
        disk_path=disk_path,
        snapshots=snapshots,
    )


def list_vms(pool_path: Path = DEFAULT_POOL_PATH) -> list:
    """List all VMs."""
    result = run_cmd(["virsh", "list", "--all", "--name"], check=False)
    vms = []
    for name in result.stdout.split("\n"):
        name = name.strip()
        if name:
            try:
                info = get_vm_info(name, pool_path)
                vms.append(info)
            except Exception:
                pass
    return vms


# ============================================================================
# Snapshot Operations
# ============================================================================


def create_snapshot(name: str, snapshot_name: str) -> None:
    """Create a VM snapshot."""
    log_info(f"Creating snapshot '{snapshot_name}' for VM: {name}")
    run_cmd(
        [
            "virsh",
            "snapshot-create-as",
            name,
            "--name",
            snapshot_name,
            "--description",
            f"boxctl-test snapshot: {snapshot_name}",
        ]
    )


def restore_snapshot(name: str, snapshot_name: str) -> None:
    """Restore a VM to a snapshot."""
    log_info(f"Restoring VM '{name}' to snapshot: {snapshot_name}")
    run_cmd(["virsh", "snapshot-revert", name, snapshot_name])


def delete_snapshot(name: str, snapshot_name: str) -> None:
    """Delete a VM snapshot."""
    log_info(f"Deleting snapshot '{snapshot_name}' from VM: {name}")
    run_cmd(["virsh", "snapshot-delete", name, snapshot_name])


def list_snapshots(name: str) -> list:
    """List snapshots for a VM."""
    result = run_cmd(["virsh", "snapshot-list", name, "--name"], check=False)
    return [s.strip() for s in result.stdout.split("\n") if s.strip()]


# ============================================================================
# SSH Operations
# ============================================================================


def wait_for_ssh(name: str, timeout: int = 300) -> str:
    """Wait for SSH to become available on VM."""
    log_info(f"Waiting for SSH on VM: {name}")

    # Get IP
    ip = get_vm_ip(name, timeout=60)
    if not ip:
        raise RuntimeError(f"Could not get IP for VM: {name}")

    log_info(f"VM IP: {ip}")

    # Wait for SSH
    key_path = ensure_ssh_key()
    start = time.time()
    while time.time() - start < timeout:
        result = run_cmd(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=5",
                "-i",
                str(key_path),
                f"testuser@{ip}",
                "echo",
                "ssh-ready",
            ],
            check=False,
            timeout=10,
        )
        if result.returncode == 0 and "ssh-ready" in result.stdout:
            log_info("SSH is ready")
            return ip
        time.sleep(5)

    raise RuntimeError(f"SSH timeout for VM: {name}")


def ssh_exec(
    name: str,
    command: list,
    pool_path: Path = DEFAULT_POOL_PATH,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Execute command on VM via SSH."""
    info = get_vm_info(name, pool_path)
    if info.state != "running":
        raise RuntimeError(f"VM not running: {name}")

    ip = info.ip_address or get_vm_ip(name)
    if not ip:
        raise RuntimeError(f"Could not get IP for VM: {name}")

    key_path = ensure_ssh_key()

    ssh_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-i",
        str(key_path),
        f"testuser@{ip}",
    ]
    ssh_cmd.extend(command)

    return run_cmd(ssh_cmd, check=False, timeout=timeout)


def ssh_interactive(name: str, pool_path: Path = DEFAULT_POOL_PATH) -> None:
    """Start interactive SSH session to VM."""
    info = get_vm_info(name, pool_path)
    if info.state != "running":
        raise RuntimeError(f"VM not running: {name}")

    ip = info.ip_address or get_vm_ip(name)
    if not ip:
        raise RuntimeError(f"Could not get IP for VM: {name}")

    key_path = ensure_ssh_key()

    os.execvp(
        "ssh",
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-i",
            str(key_path),
            f"testuser@{ip}",
        ],
    )


# ============================================================================
# SCP Operations
# ============================================================================


def scp_to_vm(
    name: str,
    local_path: str,
    remote_path: str,
    pool_path: Path = DEFAULT_POOL_PATH,
) -> None:
    """Copy file to VM."""
    info = get_vm_info(name, pool_path)
    ip = info.ip_address or get_vm_ip(name)
    if not ip:
        raise RuntimeError(f"Could not get IP for VM: {name}")

    key_path = ensure_ssh_key()
    run_cmd(
        [
            "scp",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-i",
            str(key_path),
            "-r",
            local_path,
            f"testuser@{ip}:{remote_path}",
        ]
    )


def scp_from_vm(
    name: str,
    remote_path: str,
    local_path: str,
    pool_path: Path = DEFAULT_POOL_PATH,
) -> None:
    """Copy file from VM."""
    info = get_vm_info(name, pool_path)
    ip = info.ip_address or get_vm_ip(name)
    if not ip:
        raise RuntimeError(f"Could not get IP for VM: {name}")

    key_path = ensure_ssh_key()
    run_cmd(
        [
            "scp",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-i",
            str(key_path),
            "-r",
            f"testuser@{ip}:{remote_path}",
            local_path,
        ]
    )


# ============================================================================
# CLI
# ============================================================================


def cmd_create(args: argparse.Namespace) -> int:
    """Handle create command."""
    config = VMConfig(
        name=args.name,
        distro=args.distro,
        image_type=args.image,
        ram_mb=args.ram,
        vcpus=args.vcpus,
        disk_gb=args.disk,
        accel=args.accel,
    )
    try:
        info = create_vm(config)
        print(f"\nVM created successfully:")
        print(f"  Name: {info.name}")
        print(f"  Distro: {info.distro}")
        print(f"  Image: {info.image_type}")
        print(f"  State: {info.state}")

        if args.wait_ssh:
            ip = wait_for_ssh(info.name)
            print(f"  IP: {ip}")

        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_destroy(args: argparse.Namespace) -> int:
    """Handle destroy command."""
    try:
        destroy_vm(args.name)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_start(args: argparse.Namespace) -> int:
    """Handle start command."""
    try:
        start_vm(args.name)
        if args.wait_ssh:
            wait_for_ssh(args.name)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    """Handle stop command."""
    try:
        stop_vm(args.name, force=args.force)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """Handle list command."""
    try:
        vms = list_vms()
        if not vms:
            print("No VMs found")
            return 0

        if args.json:
            data = [
                {
                    "name": v.name,
                    "state": v.state,
                    "distro": v.distro,
                    "image_type": v.image_type,
                    "ip": v.ip_address,
                    "snapshots": v.snapshots,
                }
                for v in vms
            ]
            print(json.dumps(data, indent=2))
        else:
            print(f"{'NAME':<30} {'STATE':<12} {'DISTRO':<15} {'IMAGE':<10} {'IP':<15}")
            print("-" * 85)
            for v in vms:
                print(
                    f"{v.name:<30} {v.state:<12} {v.distro:<15} "
                    f"{v.image_type:<10} {v.ip_address or 'N/A':<15}"
                )
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_info(args: argparse.Namespace) -> int:
    """Handle info command."""
    try:
        info = get_vm_info(args.name)
        if args.json:
            data = {
                "name": info.name,
                "state": info.state,
                "distro": info.distro,
                "image_type": info.image_type,
                "ip": info.ip_address,
                "disk_path": str(info.disk_path),
                "snapshots": info.snapshots,
            }
            print(json.dumps(data, indent=2))
        else:
            print(f"Name: {info.name}")
            print(f"State: {info.state}")
            print(f"Distro: {info.distro}")
            print(f"Image Type: {info.image_type}")
            print(f"IP Address: {info.ip_address or 'N/A'}")
            print(f"Disk: {info.disk_path}")
            print(f"Snapshots: {', '.join(info.snapshots) or 'None'}")
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Handle snapshot command."""
    try:
        create_snapshot(args.name, args.snapshot)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_restore(args: argparse.Namespace) -> int:
    """Handle restore command."""
    try:
        restore_snapshot(args.name, args.snapshot)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_ssh(args: argparse.Namespace) -> int:
    """Handle ssh command."""
    try:
        if args.command:
            result = ssh_exec(args.name, args.command)
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        else:
            ssh_interactive(args.name)
            return 0  # Won't reach here - exec replaces process
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_wait_ssh(args: argparse.Namespace) -> int:
    """Handle wait-ssh command."""
    try:
        ip = wait_for_ssh(args.name, timeout=args.timeout)
        print(ip)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_scp(args: argparse.Namespace) -> int:
    """Handle scp command."""
    try:
        if args.direction == "to":
            scp_to_vm(args.name, args.local, args.remote)
        else:
            scp_from_vm(args.name, args.remote, args.local)
        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    """Handle cleanup command - remove stale test VMs."""
    import re

    try:
        vms = list_vms()
        # Default pattern requires a run-id suffix (timestamp or CI job ID)
        # This avoids matching shared VMs like "boxctl-prepared-ubuntu-24.04"
        pattern = args.pattern or r"^boxctl-(minimal|prepared)-[^-]+-[0-9]"

        destroyed = []
        skipped = []

        for vm in vms:
            if re.match(pattern, vm.name):
                if args.dry_run:
                    log_info(f"Would destroy: {vm.name}")
                    skipped.append(vm.name)
                else:
                    log_info(f"Destroying: {vm.name}")
                    try:
                        destroy_vm(vm.name)
                        destroyed.append(vm.name)
                    except Exception as e:
                        log_warn(f"Failed to destroy {vm.name}: {e}")
                        skipped.append(vm.name)
            else:
                skipped.append(vm.name)

        print("")
        if args.dry_run:
            print(
                f"Dry run: would destroy {len(destroyed) + len([v for v in vms if re.match(pattern, v.name)])} VMs"
            )
        else:
            print(f"Destroyed {len(destroyed)} VMs")
            if skipped:
                print(f"Skipped {len(skipped)} VMs (no match or error)")

        return 0
    except Exception as e:
        log_error(str(e))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VM Controller for boxctl tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Create a new VM")
    p_create.add_argument("--name", required=True, help="VM name")
    p_create.add_argument(
        "--distro",
        default="ubuntu-24.04",
        choices=list(CLOUD_IMAGES.keys()),
        help="Linux distribution",
    )
    p_create.add_argument(
        "--image",
        default="prepared",
        choices=["minimal", "prepared"],
        help="Image type (minimal for 0-to-hero, prepared for regression)",
    )
    p_create.add_argument("--ram", type=int, default=DEFAULT_RAM_MB, help="RAM in MB")
    p_create.add_argument("--vcpus", type=int, default=DEFAULT_VCPUS, help="vCPUs")
    p_create.add_argument("--disk", type=int, default=DEFAULT_DISK_GB, help="Disk in GB")
    p_create.add_argument(
        "--accel",
        default="kvm",
        choices=["kvm", "tcg"],
        help="Acceleration (tcg = software emulation)",
    )
    p_create.add_argument(
        "--wait-ssh",
        action="store_true",
        help="Wait for SSH to become available",
    )
    p_create.set_defaults(func=cmd_create)

    # destroy
    p_destroy = subparsers.add_parser("destroy", help="Destroy a VM")
    p_destroy.add_argument("--name", required=True, help="VM name")
    p_destroy.set_defaults(func=cmd_destroy)

    # start
    p_start = subparsers.add_parser("start", help="Start a stopped VM")
    p_start.add_argument("--name", required=True, help="VM name")
    p_start.add_argument("--wait-ssh", action="store_true", help="Wait for SSH")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = subparsers.add_parser("stop", help="Stop a running VM")
    p_stop.add_argument("--name", required=True, help="VM name")
    p_stop.add_argument("--force", action="store_true", help="Force stop (destroy)")
    p_stop.set_defaults(func=cmd_stop)

    # list
    p_list = subparsers.add_parser("list", help="List all VMs")
    p_list.add_argument("--json", action="store_true", help="JSON output")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = subparsers.add_parser("info", help="Get VM information")
    p_info.add_argument("--name", required=True, help="VM name")
    p_info.add_argument("--json", action="store_true", help="JSON output")
    p_info.set_defaults(func=cmd_info)

    # snapshot
    p_snapshot = subparsers.add_parser("snapshot", help="Create a VM snapshot")
    p_snapshot.add_argument("--name", required=True, help="VM name")
    p_snapshot.add_argument("--snapshot", required=True, help="Snapshot name")
    p_snapshot.set_defaults(func=cmd_snapshot)

    # restore
    p_restore = subparsers.add_parser("restore", help="Restore VM to snapshot")
    p_restore.add_argument("--name", required=True, help="VM name")
    p_restore.add_argument("--snapshot", required=True, help="Snapshot name")
    p_restore.set_defaults(func=cmd_restore)

    # ssh
    p_ssh = subparsers.add_parser("ssh", help="SSH to VM")
    p_ssh.add_argument("--name", required=True, help="VM name")
    p_ssh.add_argument("command", nargs="*", help="Command to execute")
    p_ssh.set_defaults(func=cmd_ssh)

    # wait-ssh
    p_wait = subparsers.add_parser("wait-ssh", help="Wait for SSH to be available")
    p_wait.add_argument("--name", required=True, help="VM name")
    p_wait.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    p_wait.set_defaults(func=cmd_wait_ssh)

    # scp
    p_scp = subparsers.add_parser("scp", help="Copy files to/from VM")
    p_scp.add_argument("--name", required=True, help="VM name")
    p_scp.add_argument(
        "--direction",
        required=True,
        choices=["to", "from"],
        help="Copy direction",
    )
    p_scp.add_argument("--local", required=True, help="Local path")
    p_scp.add_argument("--remote", required=True, help="Remote path")
    p_scp.set_defaults(func=cmd_scp)

    # cleanup
    p_cleanup = subparsers.add_parser(
        "cleanup",
        help="Clean up stale test VMs",
        description="Remove test VMs matching a pattern. Useful for CI maintenance.",
    )
    p_cleanup.add_argument(
        "--pattern",
        default=None,
        help="Regex pattern to match VM names (default: VMs with run-id suffix, not shared VMs)",
    )
    p_cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be destroyed without actually destroying",
    )
    p_cleanup.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
