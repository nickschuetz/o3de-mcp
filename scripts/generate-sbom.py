#!/usr/bin/env python3
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Generate a CycloneDX SBOM for o3de-mcp.

Uses two isolated venvs so the SBOM only contains runtime dependencies:
  1. A "project" venv with only o3de-mcp and its runtime deps installed.
  2. A "tools" venv with cyclonedx-bom installed, pointed at the project venv.

Usage:
    python scripts/generate-sbom.py              # JSON + XML
    python scripts/generate-sbom.py --format json # JSON only
    python scripts/generate-sbom.py --format xml  # XML only
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _venv_bin(venv_dir: Path, name: str) -> Path:
    """Return the path to an executable inside a venv, cross-platform."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def _run(cmd: list[str | Path], label: str) -> None:
    """Run a subprocess, raising on failure."""
    result = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: {label} failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def generate_sbom(fmt: str, ext: str, tools_venv: Path, project_venv: Path) -> None:
    """Generate an SBOM in the given format."""
    print(f"Generating SBOM (CycloneDX {fmt})...")
    output = PROJECT_ROOT / f"sbom.cdx.{ext}"
    _run(
        [
            _venv_bin(tools_venv, "cyclonedx-py"),
            "environment",
            "--pyproject",
            PROJECT_ROOT / "pyproject.toml",
            "--of",
            fmt,
            "-o",
            output,
            str(project_venv),
        ],
        f"cyclonedx-py ({fmt})",
    )
    print(f"  -> {output.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CycloneDX SBOM for o3de-mcp")
    parser.add_argument(
        "--format",
        choices=["json", "xml", "both"],
        default="both",
        help="Output format (default: both)",
    )
    args = parser.parse_args()

    work_dir = Path(tempfile.mkdtemp(prefix="o3de-mcp-sbom-"))
    try:
        project_venv = work_dir / "project"
        tools_venv = work_dir / "tools"

        print("Creating project environment (runtime deps only)...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(project_venv)],
            check=True,
        )
        _run(
            [_venv_bin(project_venv, "pip"), "install", "--quiet", str(PROJECT_ROOT)],
            "pip install (project)",
        )

        print("Creating tools environment...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(tools_venv)],
            check=True,
        )
        _run(
            [_venv_bin(tools_venv, "pip"), "install", "--quiet", "cyclonedx-bom"],
            "pip install (tools)",
        )

        if args.format in ("json", "both"):
            generate_sbom("json", "json", tools_venv, project_venv)
        if args.format in ("xml", "both"):
            generate_sbom("xml", "xml", tools_venv, project_venv)

        print("Done.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
