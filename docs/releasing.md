# Releasing

Publishing to PyPI is triggered by creating a GitHub release, and it cannot be undone.
Before tagging, the checks below must all pass. CI covers the first two on every push;
the third needs a machine with an O3DE editor and is the only thing that has ever caught
the bugs that matter.

## 1. Static and mocked (CI)

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest
```

## 2. Generated scripts against the reflected `azlmbr` surface (CI)

`tests/test_editor_scripts.py` runs the Python each editor tool sends to the editor
against a stub built from the editor's own reflection dump. It fails on any bus event,
function or class the editor does not reflect, and on the wrong call type. This is part
of `pytest`, so it runs in CI, but the surface file has to match the engine you support:

```bash
python scripts/extract-azlmbr-surface.py <project>/user/python_symbols/azlmbr tests/data/azlmbr_surface.json
```

Regenerate it from a project the target engine version has opened, and commit the
result, whenever the supported O3DE version changes.

## 3. Live editor suite (manual, required)

Every editor tool is socket-mocked in CI. The mocked tests cannot tell whether a tool
does what it claims: three tools reported success for months while calling bus events
that do not exist, and one crashed the editor. All of that was found in the first ten
minutes of running the live suite. Do not tag a release without it.

You need a project with the AiCompanion gem enabled and built for the engine under test,
and a level in it. The launcher runs an isolated editor on its own display and ports, so
an editor you already have open is not touched.

```bash
export O3DE_SANDBOX_PROJECT=/path/to/ProjectWithAiCompanion
export O3DE_SANDBOX_ENGINE=/opt/O3DE/26.10.0      # default

scripts/live-sandbox.sh up      # Xvfb, AssetProcessor, Editor, loads DefaultLevel
scripts/live-sandbox.sh test    # pytest tests/test_live_editor.py against it
scripts/live-sandbox.sh down
```

Expected result: every test in `tests/test_live_editor.py` passes and the editor
process is still running afterwards. A test that fails with `editor_unavailable`
partway through means the editor crashed; the core dump and `Editor.log` under
`<project>/user/log/` say why.

When a tool gains a new editor-side code path, add a live test for it in the same
change. The mocked test proves the tool dispatches; only the live test proves it works.

## 4. Tag

Update `CHANGELOG.md` (move Unreleased into a version section), bump the version in
`pyproject.toml`, and create the GitHub release. The publish workflow does the rest.
