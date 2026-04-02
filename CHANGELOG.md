# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-02

### Added

- Initial release of o3de-mcp.
- **Editor tools** (16 tools):
  - `run_editor_python` — execute arbitrary Python in the editor
  - `list_entities`, `create_entity`, `delete_entity`, `duplicate_entity`
  - `get_entity_components`, `add_component`
  - `get_component_property`, `set_component_property`
  - `load_level`, `get_level_info`, `save_level`
  - `enter_game_mode`, `exit_game_mode`
  - `undo`, `redo`
- **Project tools** (7 tools):
  - `get_engine_info`, `list_projects`, `list_gems`
  - `create_project`, `register_gem`, `enable_gem`
  - `build_project`
- Input validation for entity IDs, component types, project/gem names, paths.
- Injection-safe parameter passing via JSON round-trip for editor scripts.
- Configurable editor connection via `O3DE_EDITOR_HOST` / `O3DE_EDITOR_PORT` env vars.
- Engine discovery via `O3DE_ENGINE_PATH` env var or `~/.o3de/o3de_manifest.json`.
- GitHub Actions CI: lint, type checking, tests (Python 3.10 + 3.12), SBOM generation.
- CycloneDX SBOM generation via `python scripts/generate-sbom.py`.
- Comprehensive documentation: tool reference, recipes, component catalog, 5 progressive examples.
- Agent-optimized guide (`AGENTS.md`) for token-efficient usage.
- Dual-licensed under Apache-2.0 OR MIT (matching O3DE).
