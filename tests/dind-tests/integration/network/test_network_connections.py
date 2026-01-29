# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for network connect/disconnect in True DinD."""

import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container


@pytest.mark.integration
class TestNetworkConnections:
    """Validate network connections to external containers."""

    def test_network_connect_and_disconnect(self, running_container, test_project, nginx_container):
        container_name = f"boxctl-{test_project.name}"

        result = run_abox("network", "connect", nginx_container, cwd=test_project)
        assert result.returncode == 0, f"network connect failed: {result.stderr}"

        result = None
        for _ in range(10):
            result = exec_in_container(container_name, f"getent hosts {nginx_container}")
            if result.returncode == 0:
                break
            time.sleep(1)
        assert result is not None and result.returncode == 0, (
            f"hostname {nginx_container} not resolvable after connect. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )

        result = run_abox("network", "list", cwd=test_project)
        assert result.returncode == 0, f"network list failed: {result.stderr}"
        assert (
            nginx_container in result.stdout
        ), f"Connected container not shown in network list. stdout: {result.stdout}"

        result = run_abox("network", "disconnect", nginx_container, cwd=test_project)
        assert result.returncode == 0, f"network disconnect failed: {result.stderr}"

        result = None
        for _ in range(10):
            result = exec_in_container(container_name, f"getent hosts {nginx_container}")
            if result.returncode != 0:
                break
            time.sleep(1)
        assert (
            result is not None and result.returncode != 0
        ), "hostname still resolvable after disconnect; expected failure"
