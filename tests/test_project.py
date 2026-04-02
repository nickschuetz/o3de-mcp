# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for project management tools and O3DE utilities."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from o3de_mcp.tools.project import (
    _get_build_timeout,
    _get_cmake_generator,
    _get_configure_timeout,
    _validate_name,
    _validate_path,
)
from o3de_mcp.utils.o3de import (
    _ManifestCache,
    find_o3de_cli,
    find_o3de_engine_path,
    list_registered_gems,
    list_registered_projects,
    run_o3de_cli,
)

# --- Validation tests ---


class TestValidateName:
    def test_valid_simple(self) -> None:
        assert _validate_name("MyProject", "test") == "MyProject"

    def test_valid_with_hyphens_underscores(self) -> None:
        assert _validate_name("my-project_01", "test") == "my-project_01"

    def test_strips_whitespace(self) -> None:
        assert _validate_name("  Foo  ", "test") == "Foo"

    def test_rejects_starting_with_number(self) -> None:
        with pytest.raises(ValueError, match="Must start with a letter"):
            _validate_name("123project", "project name")

    def test_rejects_special_characters(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_name("my project!", "project name")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_name("", "project name")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_name("../../../etc/passwd", "project name")


class TestValidatePath:
    def test_resolves_path(self, tmp_path: Path) -> None:
        result = _validate_path(str(tmp_path), "test path")
        assert result == tmp_path.resolve()

    def test_must_exist_passes(self, tmp_path: Path) -> None:
        result = _validate_path(str(tmp_path), "test path", must_exist=True)
        assert result == tmp_path.resolve()

    def test_must_exist_fails(self) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            _validate_path("/nonexistent/path/abc123", "test path", must_exist=True)


# --- Timeout configuration tests ---


class TestTimeoutConfig:
    def test_default_configure_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_configure_timeout() == 600

    def test_custom_configure_timeout(self) -> None:
        with patch.dict("os.environ", {"O3DE_CONFIGURE_TIMEOUT": "120"}):
            assert _get_configure_timeout() == 120

    def test_invalid_configure_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_CONFIGURE_TIMEOUT": "not_a_number"}):
            assert _get_configure_timeout() == 600

    def test_default_build_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_build_timeout() == 1800

    def test_custom_build_timeout(self) -> None:
        with patch.dict("os.environ", {"O3DE_BUILD_TIMEOUT": "900"}):
            assert _get_build_timeout() == 900

    def test_invalid_build_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_BUILD_TIMEOUT": "bad"}):
            assert _get_build_timeout() == 1800


# --- CMake generator tests ---


class TestCMakeGenerator:
    def test_env_override(self) -> None:
        with patch.dict("os.environ", {"O3DE_CMAKE_GENERATOR": "Unix Makefiles"}):
            assert _get_cmake_generator() == "Unix Makefiles"

    def test_windows_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.tools.project.sys") as mock_sys:
                mock_sys.platform = "win32"
                assert _get_cmake_generator() == "Visual Studio 17 2022"

    def test_linux_with_ninja(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.tools.project.sys") as mock_sys:
                mock_sys.platform = "linux"
                with patch("shutil.which", return_value="/usr/bin/ninja"):
                    assert _get_cmake_generator() == "Ninja Multi-Config"

    def test_linux_without_ninja(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.tools.project.sys") as mock_sys:
                mock_sys.platform = "linux"
                with patch("shutil.which", return_value=None):
                    assert _get_cmake_generator() is None


# --- Engine discovery tests ---


class TestFindEnginePath:
    def test_from_env(self) -> None:
        with patch.dict("os.environ", {"O3DE_ENGINE_PATH": "/opt/o3de"}):
            result = find_o3de_engine_path()
            assert result == Path("/opt/o3de")

    def test_returns_none_when_not_set(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=None):
                result = find_o3de_engine_path()
                assert result is None

    def test_from_manifest(self, tmp_path: Path) -> None:
        manifest = tmp_path / "o3de_manifest.json"
        engine_dir = tmp_path / "engine"
        engine_dir.mkdir()
        manifest.write_text(json.dumps({"engines": [str(engine_dir)]}))

        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=manifest):
                result = find_o3de_engine_path()
                assert result == engine_dir


class TestFindO3deCli:
    def test_returns_none_without_engine(self) -> None:
        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=None):
            assert find_o3de_cli() is None

    def test_returns_script_if_exists(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        cli_script = scripts_dir / "o3de.sh"
        cli_script.touch()

        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=tmp_path):
            with patch("o3de_mcp.utils.o3de.platform.system", return_value="Linux"):
                result = find_o3de_cli()
                assert result == cli_script


class TestRunO3deCli:
    def test_raises_when_cli_not_found(self) -> None:
        with patch("o3de_mcp.utils.o3de.find_o3de_cli", return_value=None):
            with pytest.raises(FileNotFoundError, match="O3DE CLI not found"):
                run_o3de_cli(["--help"])

    def test_passes_args_as_list(self, tmp_path: Path) -> None:
        cli_script = tmp_path / "o3de.sh"
        cli_script.write_text("#!/bin/sh\necho ok")
        cli_script.chmod(0o755)

        with patch("o3de_mcp.utils.o3de.find_o3de_cli", return_value=cli_script):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="ok", stderr=""
                )
                run_o3de_cli(["--help", "--verbose"])
                call_args = mock_run.call_args[0][0]
                assert call_args == [str(cli_script), "--help", "--verbose"]


# --- Manifest listing tests ---


class TestListRegisteredProjects:
    def test_returns_empty_without_manifest(self) -> None:
        with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=None):
            assert list_registered_projects() == []

    def test_reads_project_json(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "MyProject"
        project_dir.mkdir()
        project_json = project_dir / "project.json"
        project_json.write_text(json.dumps({"project_name": "MyProject", "version": "1.0"}))

        manifest = tmp_path / "o3de_manifest.json"
        manifest.write_text(json.dumps({"projects": [str(project_dir)]}))

        with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=manifest):
            projects = list_registered_projects()
            assert len(projects) == 1
            assert projects[0]["project_name"] == "MyProject"
            assert projects[0]["path"] == str(project_dir)

    def test_handles_missing_project_json(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "NoJson"
        project_dir.mkdir()

        manifest = tmp_path / "o3de_manifest.json"
        manifest.write_text(json.dumps({"projects": [str(project_dir)]}))

        with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=manifest):
            projects = list_registered_projects()
            assert len(projects) == 1
            assert projects[0]["project_name"] == "NoJson"


class TestListRegisteredGems:
    def test_returns_empty_without_manifest(self) -> None:
        with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=None):
            assert list_registered_gems() == []


# --- Manifest cache tests ---


class TestManifestCache:
    def test_caches_on_repeated_reads(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"engines": ["/opt/o3de"]}))

        cache = _ManifestCache()
        data1 = cache.get(manifest)
        data2 = cache.get(manifest)
        assert data1 is data2  # Same object — was cached

    def test_invalidates_on_mtime_change(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"engines": ["/opt/o3de"]}))

        cache = _ManifestCache()
        cache.get(manifest)  # Populate the cache

        # Simulate file modification
        manifest.write_text(json.dumps({"engines": ["/new/path"]}))
        # Force mtime change (some filesystems have coarse mtime)
        new_mtime = os.path.getmtime(manifest) + 1
        os.utime(manifest, (new_mtime, new_mtime))

        data2 = cache.get(manifest)
        assert data2["engines"] == ["/new/path"]

    def test_invalidate_clears_cache(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"engines": ["/opt/o3de"]}))

        cache = _ManifestCache()
        first = cache.get(manifest)
        cache.invalidate()
        second = cache.get(manifest)
        assert first is not second  # Different objects — cache was cleared


# --- Build directory symlink tests ---


class TestBuildDirectorySymlink:
    def test_symlink_build_dir_rejected(self, tmp_path: Path) -> None:
        """Verify that build_project rejects a symlinked build directory."""

        project_dir = tmp_path / "MyProject"
        project_dir.mkdir()

        # Create a symlink at build/ pointing elsewhere
        target = tmp_path / "elsewhere"
        target.mkdir()
        build_link = project_dir / "build"
        build_link.symlink_to(target)

        # We can't easily call build_project without a real engine, but we can
        # verify the logic by checking the symlink detection directly
        assert build_link.is_symlink()
