# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""EMotion FX anim graph tools: thin wrappers over the gem's native reads."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server import MCPServer

from o3de_mcp.tools.animation import (
    _validate_anim_graph_id,
    _validate_file_name,
    register_animation_tools,
)


async def _call(tool: str, arguments: dict, response: dict) -> tuple[str, list]:
    mcp = MCPServer("test")
    register_animation_tools(mcp)
    with patch("o3de_mcp.tools.editor._pool") as pool:
        pool.send_request = AsyncMock(return_value=response)
        pool.send_script = AsyncMock(return_value="")
        content = (await mcp.call_tool(tool, arguments)).content
        assert pool.send_script.await_count == 0  # native only, never editor Python
        return content[0].text, pool.send_request.call_args_list


def _raises(tool: str, arguments: dict) -> str:
    with pytest.raises(Exception) as excinfo:
        asyncio.run(_call(tool, arguments, {"status": "ok", "output": "{}"}))
    return str(excinfo.value.__cause__ or excinfo.value)


class TestValidators:
    @pytest.mark.parametrize(("value", "expected"), [(7, 7), ("7", 7), (" 42 ", 42), (0, 0)])
    def test_accepts_a_number_or_digit_string(self, value: object, expected: int) -> None:
        assert _validate_anim_graph_id(value) == expected  # type: ignore[arg-type]

    def test_accepts_the_u32_maximum(self) -> None:
        assert _validate_anim_graph_id(str(2**32 - 1)) == 2**32 - 1

    @pytest.mark.parametrize("value", ["abc", "-1", "1.5", "", 2**32, -1, True])
    def test_rejects_anything_else(self, value: object) -> None:
        with pytest.raises(ValueError):
            _validate_anim_graph_id(value)  # type: ignore[arg-type]

    def test_file_name_is_trimmed(self) -> None:
        assert _validate_file_name("  Hero.animgraph ") == "Hero.animgraph"

    @pytest.mark.parametrize("value", ["", "   ", "bad\nname", "x" * 1025])
    def test_file_name_rejects(self, value: str) -> None:
        with pytest.raises(ValueError):
            _validate_file_name(value)


class TestListAnimGraphs:
    def test_returns_the_native_output_verbatim(self) -> None:
        payload = '{"editor_mode": true, "anim_graphs": []}'
        text, calls = asyncio.run(
            _call("list_anim_graphs", {}, {"status": "ok", "output": payload})
        )
        assert text == payload
        assert calls[0].args[0] == "list_anim_graphs"


class TestGetAnimGraph:
    def test_by_id_sends_a_number(self) -> None:
        _, calls = asyncio.run(
            _call("get_anim_graph", {"anim_graph_id": "12"}, {"status": "ok", "output": "{}"})
        )
        assert calls[0].args[0] == "get_anim_graph"
        assert calls[0].kwargs["params"] == {"anim_graph_id": 12}

    def test_by_file_name(self) -> None:
        _, calls = asyncio.run(
            _call(
                "get_anim_graph",
                {"file_name": "Hero.animgraph"},
                {"status": "ok", "output": "{}"},
            )
        )
        assert calls[0].kwargs["params"] == {"file_name": "Hero.animgraph"}

    def test_returns_the_native_output_verbatim(self) -> None:
        payload = '{"id": 12, "nodes": [], "transitions": [], "parameters": []}'
        text, _ = asyncio.run(
            _call("get_anim_graph", {"anim_graph_id": 12}, {"status": "ok", "output": payload})
        )
        assert text == payload

    @pytest.mark.parametrize("arguments", [{}, {"anim_graph_id": 1, "file_name": "Hero.animgraph"}])
    def test_needs_exactly_one_selector(self, arguments: dict) -> None:
        assert "exactly one" in _raises("get_anim_graph", arguments)

    def test_rejects_a_bad_id_before_any_request(self) -> None:
        assert "anim_graph_id" in _raises("get_anim_graph", {"anim_graph_id": "not-an-id"})


class TestGemErrors:
    """Gem refusals come back as the o3de-mcp failure envelope."""

    def test_not_found_keeps_the_gem_code(self) -> None:
        text, _ = asyncio.run(
            _call(
                "get_anim_graph",
                {"anim_graph_id": 4000000000},
                {
                    "status": "error",
                    "error": "anim graph not found: 4000000000",
                    "code": "not_found",
                },
            )
        )
        assert json.loads(text) == {
            "status": "error",
            "code": "not_found",
            "message": "anim graph not found: 4000000000",
        }

    def test_an_error_without_a_code_still_uses_the_envelope(self) -> None:
        # Gems before the error-code envelope send no code on this refusal.
        text, _ = asyncio.run(
            _call(
                "list_anim_graphs",
                {},
                {"status": "error", "error": "EMotion FX is not available"},
            )
        )
        parsed = json.loads(text)
        assert parsed["status"] == "error"
        assert parsed["code"] == "editor_error"
        assert parsed["message"] == "EMotion FX is not available"

    def test_an_older_gem_reports_the_request_as_unknown(self) -> None:
        text, _ = asyncio.run(
            _call(
                "list_anim_graphs",
                {},
                {
                    "status": "error",
                    "error": "Unknown request type: list_anim_graphs",
                    "code": "unknown_request_type",
                },
            )
        )
        assert json.loads(text)["code"] == "unknown_request_type"
