# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""VM-based tests for boxctl.

This package contains VM-based testing infrastructure that provides:
- True VM isolation (vs privileged DinD containers)
- Zero-to-hero installation testing
- Native Docker performance (overlay2 vs vfs)
- Multi-distro support
"""
