"""
Integration tests for image selection in the orchestrator.

Tests the select_image_node, graph integration, and commit with image_id.
"""

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.orchestrator import (
    GraphState,
    IMAGE_SELECTION_ENABLED,
    create_initial_state,
    select_image_node,
    should_continue_after_select_image,
)
from tests.helpers.mock_tool_call import make_tool_mock


def make_test_state(**overrides) -> GraphState:
    """Create a minimal test state with a draft."""
    state = create_initial_state(str(uuid4()))
    state["current_intent"] = "problem"
    state["current_draft"] = {
        "intent": "problem",
        "title": "The Problem with External Vector Databases",
        "bullets": [
            "Data duplication across systems",
            "Network latency for similarity search",
            "Additional infrastructure to manage",
        ],
        "speaker_notes": "This slide covers challenges with external vector databases.",
        "citations": [],
    }
    state["current_gate_results"] = []
    state.update(overrides)
    return state


class TestSelectImageNode:
    """Tests for the select_image_node orchestrator node."""

    @pytest.mark.asyncio
    async def test_select_image_node_disabled_skips(self):
        """When IMAGE_SELECTION_ENABLED=false, node should return state unchanged."""
        state = make_test_state()
        
        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", False):
            result = await select_image_node(state)
        
        assert result["current_draft"] == state["current_draft"]
        assert "image_id" not in result["current_draft"]

    @pytest.mark.asyncio
    async def test_select_image_node_with_match(self):
        """When a matching image is found above threshold, it should be selected."""
        state = make_test_state()
        
        mock_candidates = [
            {
                "image_id": str(uuid4()),
                "storage_path": "diagram.png",
                "caption": "Architecture diagram",
                "alt_text": "Diagram",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.85,
            }
        ]
        
        mock_validation = {"is_valid": True, "errors": []}
        
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })
        
        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):
            
            result = await select_image_node(state)
        
        assert result["current_draft"]["image_id"] == mock_candidates[0]["image_id"]
        
        g5_gates = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"]
        assert len(g5_gates) == 1
        assert g5_gates[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_select_image_node_no_match_still_passes(self):
        """When no image matches, gate should still pass (image is optional)."""
        state = make_test_state()
        
        mock = make_tool_mock({"mcp_search_images": []})
        
        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):
            
            result = await select_image_node(state)
        
        assert "image_id" not in result["current_draft"]
        
        g5_gates = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"]
        assert len(g5_gates) == 1
        assert g5_gates[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_select_image_node_below_threshold(self):
        """Image below min score threshold should not be selected."""
        state = make_test_state()
        
        mock_candidates = [
            {
                "image_id": str(uuid4()),
                "storage_path": "low_match.png",
                "caption": "Unrelated image",
                "alt_text": "Something",
                "use_cases": [],
                "style": "photo",
                "similarity": 0.3,
            }
        ]
        
        mock = make_tool_mock({"mcp_search_images": mock_candidates})
        
        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):
            
            result = await select_image_node(state)
        
        assert "image_id" not in result["current_draft"]

    @pytest.mark.asyncio
    async def test_g5_gate_logged(self):
        """g5_image gate result should always be logged."""
        state = make_test_state()
        
        mock = make_tool_mock({"mcp_search_images": []})
        
        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):
            
            result = await select_image_node(state)
        
        gate_names = [g["gate_name"] for g in result["current_gate_results"]]
        assert "g5_image" in gate_names


class TestSelectImageDedup:
    """Tests for image deduplication logic in select_image_node."""

    @pytest.mark.asyncio
    async def test_select_image_skips_used_image(self):
        """When top candidate is already used, second-best should be selected."""
        used_id = str(uuid4())
        second_id = str(uuid4())

        state = make_test_state(used_image_ids=[used_id], images_deduplicated=0)

        mock_candidates = [
            {
                "image_id": used_id,
                "storage_path": "used.png",
                "caption": "Already used",
                "alt_text": "Used",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.90,
            },
            {
                "image_id": second_id,
                "storage_path": "second.png",
                "caption": "Second best",
                "alt_text": "Second",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.80,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert result["current_draft"]["image_id"] == second_id
        g5_gates = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"]
        assert len(g5_gates) == 1
        assert g5_gates[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_select_image_all_used_no_image(self):
        """When all candidates are already used, no image is selected and gate still passes."""
        id1 = str(uuid4())
        id2 = str(uuid4())

        state = make_test_state(used_image_ids=[id1, id2], images_deduplicated=0)

        mock_candidates = [
            {
                "image_id": id1,
                "storage_path": "used1.png",
                "caption": "Used 1",
                "alt_text": "U1",
                "use_cases": [],
                "style": "diagram",
                "similarity": 0.90,
            },
            {
                "image_id": id2,
                "storage_path": "used2.png",
                "caption": "Used 2",
                "alt_text": "U2",
                "use_cases": [],
                "style": "diagram",
                "similarity": 0.85,
            },
        ]

        mock = make_tool_mock({"mcp_search_images": mock_candidates})

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert "image_id" not in result["current_draft"]
        g5_gates = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"]
        assert len(g5_gates) == 1
        assert g5_gates[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_select_image_tracks_in_used_list(self):
        """After selection, used_image_ids should contain the newly selected image_id."""
        new_id = str(uuid4())

        state = make_test_state(used_image_ids=[], images_deduplicated=0)

        mock_candidates = [
            {
                "image_id": new_id,
                "storage_path": "new.png",
                "caption": "New image",
                "alt_text": "New",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.85,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert new_id in result["used_image_ids"]
        assert state["used_image_ids"] == []

    @pytest.mark.asyncio
    async def test_select_image_logs_dedup_count(self):
        """images_deduplicated counter should increment when candidates are filtered."""
        used_id = str(uuid4())
        new_id = str(uuid4())

        state = make_test_state(used_image_ids=[used_id], images_deduplicated=3)

        mock_candidates = [
            {
                "image_id": used_id,
                "storage_path": "used.png",
                "caption": "Used",
                "alt_text": "U",
                "use_cases": [],
                "style": "diagram",
                "similarity": 0.90,
            },
            {
                "image_id": new_id,
                "storage_path": "new.png",
                "caption": "New",
                "alt_text": "N",
                "use_cases": [],
                "style": "diagram",
                "similarity": 0.80,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert result["images_deduplicated"] == 4


class TestSelectImageIntentBoost:
    """Tests for intent-matching weighted-random image selection."""

    @pytest.mark.asyncio
    async def test_intent_match_preferred_over_non_match(self):
        """Intent-matching candidates should always be selected over
        higher-similarity non-matching ones (intent pool takes priority)."""
        better_semantic_id = str(uuid4())
        intent_match_id = str(uuid4())

        state = make_test_state(current_intent="comparison")

        mock_candidates = [
            {
                "image_id": better_semantic_id,
                "storage_path": "generic_diagram.png",
                "caption": "Generic diagram",
                "alt_text": "Diagram",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.90,
            },
            {
                "image_id": intent_match_id,
                "storage_path": "comparison_table.png",
                "caption": "Comparison table",
                "alt_text": "Comparison",
                "use_cases": ["comparison", "why-postgres"],
                "style": "chart",
                "similarity": 0.55,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert result["current_draft"]["image_id"] == intent_match_id

        g5 = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"][0]
        assert g5["details"]["intent"] == "comparison"
        assert g5["details"]["intent_boosted"] is True
        assert g5["details"]["selection_method"] == "intent_weighted_random"

    @pytest.mark.asyncio
    async def test_fallback_to_semantic_when_no_intent_match(self):
        """When no candidates match the intent, fall back to top semantic match."""
        cand_id = str(uuid4())

        state = make_test_state(current_intent="comparison")

        mock_candidates = [
            {
                "image_id": cand_id,
                "storage_path": "diagram.png",
                "caption": "A diagram",
                "alt_text": "Diagram",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.85,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert result["current_draft"]["image_id"] == cand_id

        g5 = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"][0]
        assert g5["details"]["selection_method"] == "semantic_top"
        assert g5["details"]["intent_boosted"] is False

    @pytest.mark.asyncio
    async def test_no_selection_when_no_intent_and_no_match(self):
        """When current_intent is None, fall back to semantic top."""
        cand_id = str(uuid4())

        state = make_test_state(current_intent=None)

        mock_candidates = [
            {
                "image_id": cand_id,
                "storage_path": "diagram.png",
                "caption": "A diagram",
                "alt_text": "Diagram",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.85,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert result["current_draft"]["image_id"] == cand_id

        g5 = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"][0]
        assert g5["details"]["intent_pool_size"] == 0
        assert g5["details"]["selection_method"] == "semantic_top"

    @pytest.mark.asyncio
    async def test_intent_match_below_threshold_not_selected(self):
        """Intent-matching candidate below IMAGE_MIN_SCORE should not be selected."""
        low_id = str(uuid4())

        state = make_test_state(current_intent="comparison")

        mock_candidates = [
            {
                "image_id": low_id,
                "storage_path": "weak.png",
                "caption": "Weak match",
                "alt_text": "Weak",
                "use_cases": ["comparison"],
                "style": "photo",
                "similarity": 0.30,
            },
        ]

        mock = make_tool_mock({"mcp_search_images": mock_candidates})

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        assert "image_id" not in result["current_draft"]

    @pytest.mark.asyncio
    async def test_weighted_random_produces_variety(self):
        """Weighted-random selection across intent-matched candidates should
        produce variety across runs."""
        id_a = str(uuid4())
        id_b = str(uuid4())
        id_c = str(uuid4())

        def make_candidates():
            """Fresh copies each call."""
            return [
                {
                    "image_id": id_a,
                    "storage_path": "problem_01.png",
                    "caption": "Fragmented architecture",
                    "alt_text": "Fragmented",
                    "use_cases": ["problem"],
                    "style": "diagram",
                    "similarity": 0.57,
                },
                {
                    "image_id": id_b,
                    "storage_path": "problem_02.jpg",
                    "caption": "Split reality",
                    "alt_text": "Split",
                    "use_cases": ["problem"],
                    "style": "diagram",
                    "similarity": 0.43,
                },
                {
                    "image_id": id_c,
                    "storage_path": "problem_03.jpg",
                    "caption": "Crumbling stack",
                    "alt_text": "Crumbling",
                    "use_cases": ["problem"],
                    "style": "diagram",
                    "similarity": 0.32,
                },
            ]

        mock_validation = {"is_valid": True, "errors": []}
        selected_ids = set()

        for _ in range(50):
            state = make_test_state(current_intent="problem")

            async def _dispatch(name, **kwargs):
                if name == "mcp_search_images":
                    return make_candidates()
                if name == "mcp_validate_image":
                    return mock_validation
                raise ValueError(f"Unmocked: {name}")

            with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
                 patch("src.orchestrator.should_select_image", return_value=True), \
                 patch("src.orchestrator.IMAGE_MIN_SCORE", 0.4), \
                 patch("src.orchestrator.tool_call", side_effect=_dispatch):

                result = await select_image_node(state)

            selected_ids.add(result["current_draft"]["image_id"])

        assert len(selected_ids) >= 2, (
            f"Expected variety but always selected the same image: {selected_ids}"
        )
        assert id_c not in selected_ids

    @pytest.mark.asyncio
    async def test_selection_method_recorded_in_g5(self):
        """G5 gate details should record the selection method for observability."""
        cand_id = str(uuid4())

        state = make_test_state(current_intent="architecture")

        mock_candidates = [
            {
                "image_id": cand_id,
                "storage_path": "arch.png",
                "caption": "Architecture",
                "alt_text": "Arch",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.85,
            },
        ]

        mock_validation = {"is_valid": True, "errors": []}
        mock = make_tool_mock({
            "mcp_search_images": mock_candidates,
            "mcp_validate_image": mock_validation,
        })

        with patch("src.orchestrator.IMAGE_SELECTION_ENABLED", True), \
             patch("src.orchestrator.should_select_image", return_value=True), \
             patch("src.orchestrator.IMAGE_MIN_SCORE", 0.5), \
             patch("src.orchestrator.tool_call", side_effect=mock):

            result = await select_image_node(state)

        g5 = [g for g in result["current_gate_results"] if g["gate_name"] == "g5_image"][0]
        assert g5["details"]["selection_method"] == "intent_weighted_random"
        assert g5["details"]["intent_pool_size"] == 1
        assert g5["details"]["score"] == 0.85


class TestSelectImageEdge:
    """Tests for the select_image conditional edge."""

    def test_should_continue_after_select_image_always_commits(self):
        """After image selection, should always proceed to commit."""
        state = make_test_state()
        result = should_continue_after_select_image(state)
        assert result == "commit"

    def test_should_continue_after_select_image_with_image(self):
        """Even with image selected, should proceed to commit."""
        state = make_test_state()
        state["current_draft"]["image_id"] = str(uuid4())
        result = should_continue_after_select_image(state)
        assert result == "commit"
