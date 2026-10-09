# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""The one failure shape every tool returns.

Tools report failure as a JSON object ``{"status": "error", "code": <slug>,
"message": <text>}``. ``status`` is always the literal ``"error"`` so a caller
can detect any failure with a single ``parsed.get("status") == "error"`` check;
``code`` is a stable machine-readable slug to branch on; ``message`` is the
human-readable explanation. Success payloads are tool-specific and never carry a
top-level ``status`` of ``"error"``.

Use :func:`format_error` for a failure returned directly by a tool (a JSON
string), and :func:`error_dict` when a failure travels as a dict first (for
example a native request response assembled before serialization).

Input that is rejected before any editor or CLI work begins is raised as a
``ValueError`` instead, which the MCP layer surfaces as a tool error rather than
this envelope.
"""

from __future__ import annotations

import json


def error_dict(code: str, message: str) -> dict[str, str]:
    """Return the canonical failure envelope as a dict."""
    return {"status": "error", "code": code, "message": message}


def format_error(code: str, message: str) -> str:
    """Return the canonical failure envelope as a JSON string."""
    return json.dumps(error_dict(code, message))
