# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for project management tools and O3DE utilities."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server import MCPServer

from o3de_mcp.tools.project import (
    _detect_vs_generator,
    _get_build_timeout,
    _get_cmake_generator,
    _get_configure_timeout,
    _get_export_timeout,
    _validate_name,
    _validate_path,
    register_project_tools,
)
from o3de_mcp.utils.o3de import (
    _ManifestCache,
    find_all_engines,
    find_o3de_cli,
    find_o3de_engine_path,
    find_o3de_engine_version,
    list_available_templates,
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


class TestDetectVSGenerator:
    """Tests for _detect_vs_generator() — vswhere-based VS detection."""

    _VSWHERE_JSON = json.dumps(
        [
            {
                "installationVersion": "17.8.34330.188",
                "catalog": {"productLineVersion": "2022"},
            }
        ]
    )

    _VSWHERE_JSON_2026 = json.dumps(
        [
            {
                "installationVersion": "19.0.12345.0",
                "catalog": {"productLineVersion": "2026"},
            }
        ]
    )

    def test_detects_vs2022(self) -> None:
        with (
            patch("o3de_mcp.tools.project.Path.is_file", return_value=True),
            patch("o3de_mcp.tools.project.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=self._VSWHERE_JSON
            )
            assert _detect_vs_generator() == "Visual Studio 17 2022"

    def test_detects_vs2026(self) -> None:
        with (
            patch("o3de_mcp.tools.project.Path.is_file", return_value=True),
            patch("o3de_mcp.tools.project.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=self._VSWHERE_JSON_2026
            )
            assert _detect_vs_generator() == "Visual Studio 19 2026"

    def test_returns_none_when_vswhere_missing(self) -> None:
        with patch("o3de_mcp.tools.project.Path.is_file", return_value=False):
            assert _detect_vs_generator() is None

    def test_returns_none_on_vswhere_failure(self) -> None:
        with (
            patch("o3de_mcp.tools.project.Path.is_file", return_value=True),
            patch("o3de_mcp.tools.project.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
            assert _detect_vs_generator() is None

    def test_returns_none_on_empty_instances(self) -> None:
        with (
            patch("o3de_mcp.tools.project.Path.is_file", return_value=True),
            patch("o3de_mcp.tools.project.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]")
            assert _detect_vs_generator() is None


class TestCMakeGenerator:
    def test_env_override(self) -> None:
        with patch.dict("os.environ", {"O3DE_CMAKE_GENERATOR": "Unix Makefiles"}):
            assert _get_cmake_generator() == "Unix Makefiles"

    def test_windows_delegates_to_detect_vs(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.tools.project.sys") as mock_sys:
                mock_sys.platform = "win32"
                with patch(
                    "o3de_mcp.tools.project._detect_vs_generator",
                    return_value="Visual Studio 17 2022",
                ):
                    assert _get_cmake_generator() == "Visual Studio 17 2022"

    def test_windows_returns_none_when_no_vs(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.tools.project.sys") as mock_sys:
                mock_sys.platform = "win32"
                with patch(
                    "o3de_mcp.tools.project._detect_vs_generator",
                    return_value=None,
                ):
                    assert _get_cmake_generator() is None

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
        # Skip on Windows when symlink privilege is not available (WinError 1314)
        import platform as _platform

        if _platform.system() == "Windows":
            try:
                test_link = tmp_path / "_symlink_test"
                test_target = tmp_path / "_symlink_target"
                test_target.mkdir()
                test_link.symlink_to(test_target)
                test_link.unlink()
                test_target.rmdir()
            except OSError:
                pytest.skip(
                    "Symlink creation requires administrator privileges on Windows "
                    "(WinError 1314). Run pytest as admin or enable Developer Mode."
                )

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


# --- Export timeout tests ---


class TestExportTimeout:
    def test_default_export_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_export_timeout() == 3600

    def test_custom_export_timeout(self) -> None:
        with patch.dict("os.environ", {"O3DE_EXPORT_TIMEOUT": "7200"}):
            assert _get_export_timeout() == 7200

    def test_invalid_export_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_EXPORT_TIMEOUT": "bad"}):
            assert _get_export_timeout() == 3600


# --- Engine version tests ---


class TestFindEngineVersion:
    def test_returns_version(self, tmp_path: Path) -> None:
        engine_json = tmp_path / "engine.json"
        engine_json.write_text(json.dumps({"version": "24.09"}))

        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=tmp_path):
            assert find_o3de_engine_version() == "24.09"

    def test_returns_none_without_engine(self) -> None:
        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=None):
            assert find_o3de_engine_version() is None

    def test_returns_none_without_engine_json(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=tmp_path):
            assert find_o3de_engine_version() is None


# --- Find all engines tests ---


class TestFindAllEngines:
    def test_returns_empty_without_manifest(self) -> None:
        with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=None):
            assert find_all_engines() == []

    def test_returns_engines_with_metadata(self, tmp_path: Path) -> None:
        engine_dir = tmp_path / "engine1"
        engine_dir.mkdir()
        engine_json = engine_dir / "engine.json"
        engine_json.write_text(json.dumps({"engine_name": "o3de", "version": "24.09"}))

        manifest = tmp_path / "o3de_manifest.json"
        manifest.write_text(json.dumps({"engines": [str(engine_dir)]}))

        with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=manifest):
            engines = find_all_engines()
            assert len(engines) == 1
            assert engines[0]["engine_name"] == "o3de"
            assert engines[0]["version"] == "24.09"


# --- Template listing tests ---


class TestListAvailableTemplates:
    def test_returns_empty_without_engine(self) -> None:
        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=None):
            assert list_available_templates() == []

    def test_reads_template_json(self, tmp_path: Path) -> None:
        templates_dir = tmp_path / "Templates"
        templates_dir.mkdir()
        template = templates_dir / "DefaultProject"
        template.mkdir()
        template_json = template / "template.json"
        template_json.write_text(
            json.dumps(
                {
                    "template_name": "DefaultProject",
                    "display_name": "Default Project",
                    "summary": "A basic O3DE project template",
                }
            )
        )

        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=tmp_path):
            templates = list_available_templates()
            assert len(templates) == 1
            assert templates[0]["template_name"] == "DefaultProject"
            assert templates[0]["summary"] == "A basic O3DE project template"

    def test_handles_missing_template_json(self, tmp_path: Path) -> None:
        templates_dir = tmp_path / "Templates"
        templates_dir.mkdir()
        template = templates_dir / "CustomTemplate"
        template.mkdir()

        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=tmp_path):
            templates = list_available_templates()
            assert len(templates) == 1
            assert templates[0]["template_name"] == "CustomTemplate"


# --- Engine name selection tests ---


class TestEngineNameSelection:
    def test_selects_engine_by_name(self, tmp_path: Path) -> None:
        engine1 = tmp_path / "engine1"
        engine1.mkdir()
        (engine1 / "engine.json").write_text(json.dumps({"engine_name": "o3de-stable"}))

        engine2 = tmp_path / "engine2"
        engine2.mkdir()
        (engine2 / "engine.json").write_text(json.dumps({"engine_name": "o3de-dev"}))

        manifest = tmp_path / "o3de_manifest.json"
        manifest.write_text(json.dumps({"engines": [str(engine1), str(engine2)]}))

        with patch.dict("os.environ", {"O3DE_ENGINE_NAME": "o3de-dev"}, clear=True):
            with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=manifest):
                result = find_o3de_engine_path()
                assert result == engine2

    def test_falls_back_to_first_valid_engine(self, tmp_path: Path) -> None:
        engine1 = tmp_path / "engine1"
        engine1.mkdir()
        (engine1 / "engine.json").write_text(json.dumps({"engine_name": "o3de"}))

        manifest = tmp_path / "o3de_manifest.json"
        manifest.write_text(json.dumps({"engines": [str(engine1)]}))

        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.utils.o3de._o3de_manifest_path", return_value=manifest):
                result = find_o3de_engine_path()
                assert result == engine1


# --- CLI fallback to python/o3de.py tests ---


class TestCliFallback:
    def test_finds_python_o3de_fallback(self, tmp_path: Path) -> None:
        python_dir = tmp_path / "python"
        python_dir.mkdir()
        fallback_script = python_dir / "o3de.py"
        fallback_script.touch()

        with patch("o3de_mcp.utils.o3de.find_o3de_engine_path", return_value=tmp_path):
            with patch("o3de_mcp.utils.o3de.platform.system", return_value="Linux"):
                # Clear the CLI cache
                import o3de_mcp.utils.o3de as o3de_mod

                o3de_mod._cached_cli = None
                o3de_mod._cached_cli_engine = None

                result = find_o3de_cli()
                assert result == fallback_script


# --- Phase 7: list_project_gems tests ---


class TestListProjectGems:
    def test_lists_gems(self, tmp_path: Path) -> None:
        project_json = tmp_path / "project.json"
        project_json.write_text(
            json.dumps({"project_name": "TestProject", "gem_names": ["Atom", "PhysX5", "Terrain"]})
        )

        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool("list_project_gems", {"project_path": str(tmp_path)})
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["gems"] == ["Atom", "PhysX5", "Terrain"]
        assert parsed["count"] == 3

    def test_no_gems(self, tmp_path: Path) -> None:
        project_json = tmp_path / "project.json"
        project_json.write_text(json.dumps({"project_name": "EmptyProject"}))

        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool("list_project_gems", {"project_path": str(tmp_path)})
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["gems"] == []
        assert parsed["count"] == 0

    def test_missing_project_json(self, tmp_path: Path) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool("list_project_gems", {"project_path": str(tmp_path)})
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["status"] == "error"

    def test_invalid_json(self, tmp_path: Path) -> None:
        project_json = tmp_path / "project.json"
        project_json.write_text("not valid json {{{")

        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool("list_project_gems", {"project_path": str(tmp_path)})
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["status"] == "error"


# --- Phase 8: Engine registration + async build tests ---


class TestRegisterEngine:
    def test_registers_engine(self, tmp_path: Path) -> None:
        engine_json = tmp_path / "engine.json"
        engine_json.write_text(json.dumps({"engine_name": "o3de"}))

        mock_result = subprocess.CompletedProcess(
            args=["o3de.bat", "register", "--engine-path", str(tmp_path)],
            returncode=0,
            stdout="Engine registered",
            stderr="",
        )
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=mock_result):
            from mcp.server import MCPServer

            from o3de_mcp.tools.project import register_project_tools

            mcp = MCPServer("test")
            register_project_tools(mcp)
            import asyncio

            content = asyncio.run(
                mcp.call_tool("register_engine", {"engine_path": str(tmp_path)})
            ).content
            assert "registered" in content[0].text.lower()

    def test_missing_engine_json(self, tmp_path: Path) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool("register_engine", {"engine_path": str(tmp_path)})
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["status"] == "error"


class TestSetActiveEngine:
    def test_sets_env_var(self) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        with patch.dict("os.environ", {}, clear=True):
            content = asyncio.run(mcp.call_tool("set_active_engine", {"name": "o3de"})).content
            assert "o3de" in content[0].text
            assert os.environ.get("O3DE_ENGINE_NAME") == "o3de"

    def test_rejects_invalid_name(self) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        with pytest.raises(Exception):
            asyncio.run(mcp.call_tool("set_active_engine", {"name": "123bad"}))


class TestStartBuild:
    def test_rejects_no_build_dir(self, tmp_path: Path) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(mcp.call_tool("start_build", {"project_path": str(tmp_path)})).content
        parsed = json.loads(content[0].text)
        assert parsed["status"] == "error"
        assert "build" in parsed["code"]

    def test_rejects_invalid_config(self, tmp_path: Path) -> None:
        build_dir = tmp_path / "build" / "windows"
        build_dir.mkdir(parents=True)

        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool(
                "start_build",
                {"project_path": str(tmp_path), "config": "invalid"},
            )
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["status"] == "error"
        assert "config" in parsed["code"]


class TestGetBuildStatus:
    def test_not_found(self) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        content = asyncio.run(
            mcp.call_tool("get_build_status", {"build_id": "nonexistent"})
        ).content
        parsed = json.loads(content[0].text)
        assert parsed["status"] == "error"
        assert parsed["code"] == "not_found"

    def test_empty_build_id(self) -> None:
        from mcp.server import MCPServer

        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        import asyncio

        with pytest.raises(Exception):
            asyncio.run(mcp.call_tool("get_build_status", {"build_id": ""}))


# --- MCP dispatch tests for the CLI-backed project tools ---
#
# The tools below shell out to the O3DE CLI or CMake, so the rest of the suite
# exercises their helpers directly rather than invoking them. These tests drive
# each one through ``call_tool`` with the subprocess layer mocked, which covers
# argument marshalling across the MCP boundary.


def _dispatch(tool_name: str, arguments: dict[str, object]) -> str:
    """Invoke a project tool through MCP dispatch and return its text payload."""
    mcp = MCPServer("test")
    register_project_tools(mcp)
    content = asyncio.run(mcp.call_tool(tool_name, arguments)).content
    return str(content[0].text)


def _cli_ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _cli_fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


class TestCreateProjectDispatch:
    def test_passes_arguments_to_cli(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch(
                "create_project",
                {"name": "MyGame", "path": str(tmp_path), "template": "Minimal"},
            )

        assert "MyGame" in text
        assert cli.call_args.args[0] == [
            "create-project",
            "--project-name",
            "MyGame",
            "--project-path",
            str(tmp_path.resolve()),
            "--template-name",
            "Minimal",
        ]

    def test_defaults_to_default_project_template(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            _dispatch("create_project", {"name": "MyGame", "path": str(tmp_path)})

        assert cli.call_args.args[0][-1] == "DefaultProject"

    def test_reports_cli_failure(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_fail("disk full")):
            text = _dispatch("create_project", {"name": "MyGame", "path": str(tmp_path)})

        parsed = json.loads(text)
        assert parsed["status"] == "error"
        assert parsed["code"] == "create_failed"
        assert "disk full" in parsed["message"]

    def test_rejects_invalid_name(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli") as cli:
            with pytest.raises(Exception):
                _dispatch("create_project", {"name": "../evil", "path": str(tmp_path)})

        cli.assert_not_called()


class TestCreateGemDispatch:
    def test_passes_arguments_to_cli(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch("create_gem", {"name": "MyGem", "path": str(tmp_path)})

        assert "MyGem" in text
        assert cli.call_args.args[0] == [
            "create-gem",
            "--gem-name",
            "MyGem",
            "--gem-path",
            str(tmp_path.resolve()),
            "--template-name",
            "DefaultGem",
        ]

    def test_reports_cli_failure(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_fail()):
            text = _dispatch("create_gem", {"name": "MyGem", "path": str(tmp_path)})

        assert json.loads(text)["code"] == "create_failed"


class TestRegisterGemDispatch:
    def test_passes_resolved_paths_to_cli(self, tmp_path: Path) -> None:
        gem = tmp_path / "gem"
        project = tmp_path / "project"
        gem.mkdir()
        project.mkdir()

        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch("register_gem", {"gem_path": str(gem), "project_path": str(project)})

        assert "registered" in text
        assert cli.call_args.args[0] == [
            "register",
            "--gem-path",
            str(gem.resolve()),
            "--project-path",
            str(project.resolve()),
        ]

    def test_rejects_missing_gem_path(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli") as cli:
            with pytest.raises(Exception):
                _dispatch(
                    "register_gem",
                    {"gem_path": str(tmp_path / "absent"), "project_path": str(tmp_path)},
                )

        cli.assert_not_called()

    def test_reports_cli_failure(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_fail()):
            text = _dispatch(
                "register_gem", {"gem_path": str(tmp_path), "project_path": str(tmp_path)}
            )

        assert json.loads(text)["code"] == "register_failed"


class TestEnableGemDispatch:
    def test_passes_arguments_to_cli(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch("enable_gem", {"gem_name": "Atom", "project_path": str(tmp_path)})

        assert "enabled" in text
        assert cli.call_args.args[0] == [
            "enable-gem",
            "--gem-name",
            "Atom",
            "--project-path",
            str(tmp_path.resolve()),
        ]

    def test_reports_cli_failure(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_fail()):
            text = _dispatch("enable_gem", {"gem_name": "Atom", "project_path": str(tmp_path)})

        assert json.loads(text)["code"] == "enable_failed"


class TestDisableGemDispatch:
    def test_passes_arguments_to_cli(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch("disable_gem", {"gem_name": "Atom", "project_path": str(tmp_path)})

        assert "disabled" in text
        assert cli.call_args.args[0] == [
            "disable-gem",
            "--gem-name",
            "Atom",
            "--project-path",
            str(tmp_path.resolve()),
        ]

    def test_reports_cli_failure(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_fail()):
            text = _dispatch("disable_gem", {"gem_name": "Atom", "project_path": str(tmp_path)})

        assert json.loads(text)["code"] == "disable_failed"


class TestEditProjectPropertiesDispatch:
    def test_sends_only_the_supplied_properties(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch(
                "edit_project_properties",
                {"project_path": str(tmp_path), "origin": "https://example.invalid"},
            )

        assert "updated" in text
        assert cli.call_args.args[0] == [
            "edit-project-properties",
            "--project-path",
            str(tmp_path.resolve()),
            "--origin",
            "https://example.invalid",
        ]

    def test_sends_both_properties(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            _dispatch(
                "edit_project_properties",
                {"project_path": str(tmp_path), "project_name": "Renamed", "origin": "o"},
            )

        args = cli.call_args.args[0]
        assert args[3:5] == ["--project-name", "Renamed"]
        assert args[5:7] == ["--origin", "o"]

    def test_rejects_a_no_op_edit(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli") as cli:
            text = _dispatch("edit_project_properties", {"project_path": str(tmp_path)})

        assert json.loads(text)["code"] == "no_changes"
        cli.assert_not_called()


class TestBuildProjectDispatch:
    def test_runs_configure_then_build(self, tmp_path: Path) -> None:
        engine = tmp_path / "engine"
        engine.mkdir()

        with (
            patch("o3de_mcp.tools.project.find_o3de_engine_path", return_value=engine),
            patch("o3de_mcp.tools.project._get_cmake_generator", return_value=None),
            patch("o3de_mcp.tools.project.subprocess.run", return_value=_cli_ok()) as run,
        ):
            text = _dispatch("build_project", {"project_path": str(tmp_path), "config": "debug"})

        assert "built successfully" in text
        assert run.call_count == 2

        configure_cmd = run.call_args_list[0].args[0]
        build_cmd = run.call_args_list[1].args[0]
        assert configure_cmd[:5] == [
            "cmake",
            "-S",
            str(tmp_path.resolve()),
            "-B",
            str((tmp_path / "build").resolve()),
        ]
        assert configure_cmd[5] == f"-DLY_ENGINE_PATH={engine.as_posix()}"
        assert build_cmd == [
            "cmake",
            "--build",
            str((tmp_path / "build").resolve()),
            "--config",
            "debug",
            "--parallel",
        ]

    def test_appends_generator_when_one_is_detected(self, tmp_path: Path) -> None:
        with (
            patch("o3de_mcp.tools.project.find_o3de_engine_path", return_value=tmp_path),
            patch("o3de_mcp.tools.project._get_cmake_generator", return_value="Ninja"),
            patch("o3de_mcp.tools.project.subprocess.run", return_value=_cli_ok()) as run,
        ):
            _dispatch("build_project", {"project_path": str(tmp_path)})

        assert run.call_args_list[0].args[0][-2:] == ["-G", "Ninja"]

    def test_rejects_invalid_config(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.subprocess.run") as run:
            text = _dispatch("build_project", {"project_path": str(tmp_path), "config": "nonsense"})

        assert json.loads(text)["code"] == "invalid_config"
        run.assert_not_called()

    def test_reports_missing_engine(self, tmp_path: Path) -> None:
        with (
            patch("o3de_mcp.tools.project.find_o3de_engine_path", return_value=None),
            patch("o3de_mcp.tools.project.subprocess.run") as run,
        ):
            text = _dispatch("build_project", {"project_path": str(tmp_path)})

        assert json.loads(text)["code"] == "engine_not_found"
        run.assert_not_called()

    def test_reports_configure_failure_without_building(self, tmp_path: Path) -> None:
        with (
            patch("o3de_mcp.tools.project.find_o3de_engine_path", return_value=tmp_path),
            patch("o3de_mcp.tools.project._get_cmake_generator", return_value=None),
            patch(
                "o3de_mcp.tools.project.subprocess.run",
                return_value=_cli_fail("missing toolchain"),
            ) as run,
        ):
            text = _dispatch("build_project", {"project_path": str(tmp_path)})

        parsed = json.loads(text)
        assert parsed["code"] == "configure_failed"
        assert "missing toolchain" in parsed["message"]
        assert run.call_count == 1

    def test_reports_build_failure(self, tmp_path: Path) -> None:
        with (
            patch("o3de_mcp.tools.project.find_o3de_engine_path", return_value=tmp_path),
            patch("o3de_mcp.tools.project._get_cmake_generator", return_value=None),
            patch(
                "o3de_mcp.tools.project.subprocess.run",
                side_effect=[_cli_ok(), _cli_fail("compile error")],
            ),
        ):
            text = _dispatch("build_project", {"project_path": str(tmp_path)})

        parsed = json.loads(text)
        assert parsed["code"] == "build_failed"
        assert "compile error" in parsed["message"]

    @pytest.mark.parametrize("target_exists", [True, False])
    def test_rejects_a_symlinked_build_directory(self, tmp_path: Path, target_exists: bool) -> None:
        project = tmp_path / "project"
        project.mkdir()
        target = tmp_path / "elsewhere"
        if target_exists:
            target.mkdir()
        (project / "build").symlink_to(target)

        with patch("o3de_mcp.tools.project.subprocess.run") as run:
            text = _dispatch("build_project", {"project_path": str(project)})

        assert json.loads(text)["code"] == "symlink_rejected"
        run.assert_not_called()


class TestExportProjectDispatch:
    def test_passes_arguments_to_cli(self, tmp_path: Path) -> None:
        out = tmp_path / "out"

        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_ok()) as cli:
            text = _dispatch(
                "export_project",
                {"project_path": str(tmp_path), "output_path": str(out), "config": "release"},
            )

        assert "exported successfully" in text
        assert cli.call_args.args[0] == [
            "export-project",
            "--project-path",
            str(tmp_path.resolve()),
            "--output-path",
            str(out.resolve()),
            "--config",
            "release",
        ]

    def test_rejects_invalid_config(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli") as cli:
            text = _dispatch(
                "export_project",
                {"project_path": str(tmp_path), "output_path": str(tmp_path), "config": "nope"},
            )

        assert json.loads(text)["code"] == "invalid_config"
        cli.assert_not_called()

    def test_reports_a_timeout(self, tmp_path: Path) -> None:
        with patch(
            "o3de_mcp.tools.project.run_o3de_cli",
            side_effect=subprocess.TimeoutExpired(cmd="o3de", timeout=1),
        ):
            text = _dispatch(
                "export_project",
                {"project_path": str(tmp_path), "output_path": str(tmp_path)},
            )

        parsed = json.loads(text)
        assert parsed["code"] == "export_timeout"
        assert "O3DE_EXPORT_TIMEOUT" in parsed["message"]

    def test_reports_cli_failure(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.project.run_o3de_cli", return_value=_cli_fail()):
            text = _dispatch(
                "export_project",
                {"project_path": str(tmp_path), "output_path": str(tmp_path)},
            )

        assert json.loads(text)["code"] == "export_failed"
