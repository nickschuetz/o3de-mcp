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

Follow the `register_*_tools(mcp: FastMCP)` pattern:

1. Create a new file in `src/o3de_mcp/tools/`.
2. Define a `register_*_tools(mcp)` function that decorates tool functions with `@mcp.tool()`.
3. Call your registration function from `server.py`.

Requirements:

- **Validate all user inputs at tool boundaries.** See existing validators in `editor.py` and `project.py` for examples.
- **Never interpolate raw user strings into editor Python scripts.** Use `json.dumps`/`json.loads` round-trip to safely pass values into `pyRunScript` commands.

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
