# Makefile for VM image management
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

SHELL := /bin/bash
.PHONY: all minimal prepared ubuntu fedora clean help list

# Default distro
DISTRO ?= ubuntu-24.04

# Scripts
BUILD_MINIMAL := ./build-minimal.sh
BUILD_PREPARED := ./build-prepared.sh
VM_CTL := ../scripts/vm-ctl.py

# Image names
MINIMAL_VM := boxctl-minimal-$(DISTRO)
PREPARED_VM := boxctl-prepared-$(DISTRO)

help:
	@echo "VM Image Build System"
	@echo ""
	@echo "Usage: make [target] [DISTRO=distro]"
	@echo ""
	@echo "Targets:"
	@echo "  all            Build both minimal and prepared images"
	@echo "  minimal        Build minimal image (no Docker)"
	@echo "  prepared       Build prepared image (Docker + boxctl)"
	@echo "  ubuntu         Build Ubuntu 24.04 images"
	@echo "  fedora         Build Fedora 41 images"
	@echo "  list           List all VM images"
	@echo "  clean          Destroy all test VMs"
	@echo "  clean-minimal  Destroy minimal VMs"
	@echo "  clean-prepared Destroy prepared VMs"
	@echo ""
	@echo "Distros:"
	@echo "  ubuntu-24.04 (default)"
	@echo "  ubuntu-22.04"
	@echo "  fedora-41"
	@echo "  fedora-40"
	@echo ""
	@echo "Examples:"
	@echo "  make minimal                    # Build minimal Ubuntu 24.04"
	@echo "  make prepared DISTRO=fedora-41  # Build prepared Fedora 41"
	@echo "  make ubuntu                     # Build both Ubuntu 24.04 images"
	@echo "  make all DISTRO=ubuntu-22.04    # Build both Ubuntu 22.04 images"

all: minimal prepared

minimal:
	@echo "Building minimal $(DISTRO) image..."
	DISTRO=$(DISTRO) $(BUILD_MINIMAL)

prepared:
	@echo "Building prepared $(DISTRO) image..."
	DISTRO=$(DISTRO) $(BUILD_PREPARED)

# Convenience targets for specific distros
ubuntu: ubuntu-24.04
ubuntu-24.04:
	$(MAKE) all DISTRO=ubuntu-24.04

ubuntu-22.04:
	$(MAKE) all DISTRO=ubuntu-22.04

fedora: fedora-41
fedora-41:
	$(MAKE) all DISTRO=fedora-41

fedora-40:
	$(MAKE) all DISTRO=fedora-40

# List all images
list:
	@python3 $(VM_CTL) list

# Clean targets
clean: clean-minimal clean-prepared

clean-minimal:
	@for vm in $$(python3 $(VM_CTL) list --json 2>/dev/null | jq -r '.[].name' | grep "^boxctl-minimal"); do \
		echo "Destroying $$vm..."; \
		python3 $(VM_CTL) destroy --name "$$vm" || true; \
	done

clean-prepared:
	@for vm in $$(python3 $(VM_CTL) list --json 2>/dev/null | jq -r '.[].name' | grep "^boxctl-prepared"); do \
		echo "Destroying $$vm..."; \
		python3 $(VM_CTL) destroy --name "$$vm" || true; \
	done

# Rebuild targets (force rebuild)
rebuild-minimal: clean-minimal minimal
rebuild-prepared: clean-prepared prepared
rebuild: clean all
