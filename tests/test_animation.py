# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""EMotion FX anim graph tools: thin wrappers over the gem's native requests."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server import MCPServer

from o3de_mcp.tools.animation import (
    _validate_anim_graph_id,
    _validate_file_name,
    _validate_node_id,
    _validate_parameter_value,
    _validate_position,
    _validate_type_name,
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


def _params(tool: str, arguments: dict) -> dict:
    """Call a tool against an ok reply and return the params it sent the gem."""
    _, calls = asyncio.run(_call(tool, arguments, {"status": "ok", "output": "{}"}))
    assert calls[0].args[0] == tool
    return calls[0].kwargs.get("params") or {}


class TestAuthoringValidators:
    @pytest.mark.parametrize(("value", "expected"), [("123", "123"), (456, "456"), (" 7 ", "7")])
    def test_node_id_becomes_a_decimal_string(self, value: object, expected: str) -> None:
        assert _validate_node_id(value) == expected  # type: ignore[arg-type]

    def test_node_id_keeps_full_u64_precision(self) -> None:
        big = str(2**64 - 1)
        assert _validate_node_id(big) == big

    @pytest.mark.parametrize("value", ["abc", "-1", "", str(2**64), True])
    def test_node_id_rejects(self, value: object) -> None:
        with pytest.raises(ValueError):
            _validate_node_id(value)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "value", ["AnimGraphMotionNode", "Blend Tree", "EMotionFX::FloatSliderParameter", "Float"]
    )
    def test_type_name_accepts(self, value: str) -> None:
        assert _validate_type_name(value, "node_type") == value

    @pytest.mark.parametrize("value", ["", "1Node", "Bad;Name", "x" * 129, "a\nb"])
    def test_type_name_rejects(self, value: str) -> None:
        with pytest.raises(ValueError):
            _validate_type_name(value, "node_type")

    def test_position_accepts_integers_and_integral_floats(self) -> None:
        assert _validate_position([10, -20]) == [10, -20]
        assert _validate_position([3.0, 4.0]) == [3, 4]

    @pytest.mark.parametrize(
        "value", [[1], [1, 2, 3], [1.5, 2], [True, 2], ["1", 2], [float("inf"), 0]]
    )
    def test_position_rejects(self, value: list) -> None:
        with pytest.raises(ValueError):
            _validate_position(value)

    @pytest.mark.parametrize("value", [0.5, 3, True, "walk", [1.0, 2.0], [0, 0, 0, 1]])
    def test_parameter_value_accepts(self, value: object) -> None:
        assert _validate_parameter_value(value, "default") == value  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [float("nan"), [1.0], [1, 2, 3, 4, 5], [1, "a"], {"a": 1}])
    def test_parameter_value_rejects(self, value: object) -> None:
        with pytest.raises(ValueError):
            _validate_parameter_value(value, "default")  # type: ignore[arg-type]


class TestGraphLifecycle:
    def test_create_sends_no_params(self) -> None:
        assert _params("create_anim_graph", {}) == {}

    def test_remove(self) -> None:
        assert _params("remove_anim_graph", {"anim_graph_id": "9"}) == {"anim_graph_id": 9}

    def test_load(self) -> None:
        assert _params("load_anim_graph", {"file_name": " Assets/Hero.animgraph "}) == {
            "file_name": "Assets/Hero.animgraph"
        }

    def test_save_without_a_file_name_keeps_the_current_one(self) -> None:
        assert _params("save_anim_graph", {"anim_graph_id": 9}) == {"anim_graph_id": 9}

    def test_save_to_a_file(self) -> None:
        assert _params(
            "save_anim_graph", {"anim_graph_id": 9, "file_name": "Assets/Hero.animgraph"}
        ) == {"anim_graph_id": 9, "file_name": "Assets/Hero.animgraph"}


class TestNodes:
    def test_add_node_sends_only_what_was_given(self) -> None:
        assert _params(
            "add_anim_graph_node", {"anim_graph_id": 9, "node_type": "AnimGraphMotionNode"}
        ) == {"anim_graph_id": 9, "node_type": "AnimGraphMotionNode"}

    def test_add_node_with_every_field(self) -> None:
        assert _params(
            "add_anim_graph_node",
            {
                "anim_graph_id": "9",
                "node_type": "BlendTree",
                "parent_id": 123,
                "name": " Locomotion ",
                "position": [100, 50],
            },
        ) == {
            "anim_graph_id": 9,
            "node_type": "BlendTree",
            "parent_id": "123",
            "name": "Locomotion",
            "position": [100, 50],
        }

    def test_add_node_returns_the_gem_node_verbatim(self) -> None:
        node = '{"id": "77", "name": "Idle", "type": "AnimGraphMotionNode"}'
        text, _ = asyncio.run(
            _call(
                "add_anim_graph_node",
                {"anim_graph_id": 9, "node_type": "AnimGraphMotionNode"},
                {"status": "ok", "output": node},
            )
        )
        assert text == node

    def test_add_node_rejects_a_fractional_position(self) -> None:
        assert "position" in _raises(
            "add_anim_graph_node",
            {"anim_graph_id": 9, "node_type": "AnimGraphMotionNode", "position": [1.5, 2]},
        )

    def test_remove_node(self) -> None:
        assert _params("remove_anim_graph_node", {"anim_graph_id": 9, "node_id": 77}) == {
            "anim_graph_id": 9,
            "node_id": "77",
        }

    def test_set_entry_state(self) -> None:
        assert _params("set_anim_graph_entry_state", {"anim_graph_id": 9, "node_id": "77"}) == {
            "anim_graph_id": 9,
            "node_id": "77",
        }


class TestParameters:
    def test_add_a_ranged_float(self) -> None:
        assert _params(
            "add_anim_graph_parameter",
            {
                "anim_graph_id": 9,
                "name": "Speed",
                "parameter_type": "Float",
                "default": 0.5,
                "min": 0,
                "max": 1,
                "description": "Run speed",
                "group": "Locomotion",
            },
        ) == {
            "anim_graph_id": 9,
            "name": "Speed",
            "parameter_type": "Float",
            "default": 0.5,
            "min": 0,
            "max": 1,
            "description": "Run speed",
            "group": "Locomotion",
        }

    def test_add_a_bool_sends_a_real_bool(self) -> None:
        params = _params(
            "add_anim_graph_parameter",
            {"anim_graph_id": 9, "name": "Grounded", "parameter_type": "Bool", "default": True},
        )
        assert params["default"] is True

    def test_add_a_vector_default(self) -> None:
        params = _params(
            "add_anim_graph_parameter",
            {"anim_graph_id": 9, "name": "Aim", "parameter_type": "Vector2", "default": [0, 1]},
        )
        assert params["default"] == [0, 1]

    def test_remove_parameter(self) -> None:
        assert _params("remove_anim_graph_parameter", {"anim_graph_id": 9, "name": "Speed"}) == {
            "anim_graph_id": 9,
            "name": "Speed",
        }


class TestAuthoringErrors:
    def test_an_owned_graph_refusal_uses_the_envelope(self) -> None:
        text, _ = asyncio.run(
            _call(
                "add_anim_graph_node",
                {"anim_graph_id": 9, "node_type": "AnimGraphMotionNode"},
                {
                    "status": "error",
                    "error": "anim graph 9 is owned by an asset; author a graph from "
                    "create_anim_graph or load_anim_graph",
                    "code": "validation_failed",
                },
            )
        )
        parsed = json.loads(text)
        assert parsed["status"] == "error"
        assert parsed["code"] == "validation_failed"
        assert "owned" in parsed["message"]
