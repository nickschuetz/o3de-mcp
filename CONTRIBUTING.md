# Contributing to o3de-mcp

## License

This project is dual-licensed under **Apache-2.0 OR MIT** (matching O3DE).
By submitting a pull request, you agree to license your contribution under both licenses.

Copyright (c) Contributors to the Open 3D Engine Project.
For complete copyright and license terms please see the LICENSE at the root of this distribution.

## Development Setup

Clone the repo and install in editable mode with dev dependencies:

```bash
pip install -e ".[dev]"
```

Run the MCP server locally:

```bash
o3de-mcp
```

## Code Quality

All of the following must pass before submitting a PR:

```bash
# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type checking
mypy src/

# Tests
pytest
```

Every source file must include the SPDX license header:

```python
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
```

## Adding New Tools

Follow the `register_*_tools(mcp: MCPServer)` pattern:

1. Create a new file in `src/o3de_mcp/tools/`.
2. Define a `register_*_tools(mcp)` function that decorates tool functions with `@mcp.tool()`.
3. Call your registration function from `server.py`.

Requirements:

- **Validate all user inputs at tool boundaries.** See existing validators in `editor.py` and `project.py` for examples.
- **Never interpolate raw user strings into editor Python scripts.** Use a `json.dumps`/`json.loads` round-trip to pass values into the script. Scripts are sent to the AiCompanion gem's AgentServer as framed `execute_python` requests; `pyRunScript` is only the legacy RemoteConsole fallback.
- **Report every failure with the one envelope** `{"status": "error", "code": "<slug>", "message": "<text>"}`: `format_error` from `utils/errors.py` in server code, and `_o3de_fail(code, message)` inside generated editor scripts. Never print a plain-text failure.
- **Get entities in editor scripts with `_resolve_entity_id(id)`**, which finds the entity's own id object through the search bus. Never build an id with `entity.EntityId(n)`: on O3DE 26.10.0 it gives an invalid id for every `n`.
- **Annotate entity-id parameters with `EntityIdArg` or `OptionalEntityIdArg`** from `tools/editor.py`, not `int | str`, so a bracketed id like `"[1234]"` is not JSON-decoded into a list.
- **Keep the surface test passing.** `tests/test_editor_scripts.py` runs every generated editor script against the reflected `azlmbr` surface in `tests/data/azlmbr_surface.json`; check that file before calling a bus event or function the tools do not already use.
- **Add a live test for any new editor-side path** in `tests/test_live_editor.py`, and run it with `scripts/live-sandbox.sh` (see `docs/releasing.md`). A mocked test proves only that the tool dispatches.

## Security

Input validation is mandatory for all tools. Any data that flows into subprocess calls, socket messages, or file paths must be validated and sanitized. Refer to the existing validation patterns in `src/o3de_mcp/tools/editor.py` and `src/o3de_mcp/tools/project.py`.

## Pull Requests

- Keep PRs focused on a single change.
- Include tests for new tools.
- Update documentation if adding or changing features.
- Ensure all code quality checks pass (see above).

## Issues

Bug reports should include:

- Python version
- O3DE version
- Steps to reproduce
- Expected vs actual behavior
