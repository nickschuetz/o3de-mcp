# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Shared pytest configuration and fixtures for live editor tests."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_editor: mark a test as requiring a running O3DE Editor instance. "
        "Skipped unless O3DE_LIVE_EDITOR_TEST=1 is set.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("O3DE_LIVE_EDITOR_TEST", "0") not in ("1", "true"):
        skip_live = pytest.mark.skip(reason="Live editor tests require O3DE_LIVE_EDITOR_TEST=1")
        for item in items:
            if "live_editor" in item.keywords:
                item.add_marker(skip_live)
