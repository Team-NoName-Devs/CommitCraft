"""Tests for SemanticPlanner using mock Ollama responses."""

import json
import httpx
import pytest

from commitcraft.change_units import ChangeUnit
from commitcraft.errors import ModelResponseError, PlanValidationError
from commitcraft.model_client import OllamaClient
from commitcraft.planner import SemanticPlanner


def make_unit(uid: str) -> ChangeUnit:
    return ChangeUnit(
        id=uid,
        path=f"{uid}.txt",
        kind="add",
        summary=f"Add {uid}",
        hunk_header=None,
        added_lines=1,
        removed_lines=0,
        is_binary=False,
        is_splittable=False,
        excerpt="+content",
        patch_text="",
    )


def test_planner_successful_plan():
    """Test planner produces validated plan on first valid model output."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan_dict = {
        "version": "1.0",
        "summary": "Implement feature and tests",
        "groups": [
            {
                "id": "G01",
                "unit_ids": ["U001"],
                "title": "Feature",
                "explanation": "Core feature",
                "commit_type": "feat",
                "scope": "core",
                "message": "feat(core): implement core feature",
                "depends_on": [],
            },
            {
                "id": "G02",
                "unit_ids": ["U002"],
                "title": "Tests",
                "explanation": "Regression tests",
                "commit_type": "test",
                "scope": "core",
                "message": "test(core): add feature tests",
                "depends_on": ["G01"],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps(plan_dict)}},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)
    planner = SemanticPlanner(ollama)

    plan = planner.plan(inventory)
    assert len(plan.groups) == 2
    assert plan.groups[0].id == "G01"
    assert plan.groups[1].id == "G02"


def test_planner_bounded_correction_success():
    """Test planner corrects an initially invalid plan (missing unit) via feedback loop."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    # Attempt 1: only includes U001 (invalid because U002 is missing)
    invalid_plan = {
        "version": "1.0",
        "groups": [
            {
                "id": "G01",
                "unit_ids": ["U001"],
                "title": "Incomplete",
                "explanation": "Missing U002",
                "commit_type": "feat",
                "message": "feat: incomplete",
                "depends_on": [],
            }
        ],
    }

    # Attempt 2: corrected plan with both units
    valid_plan = {
        "version": "1.0",
        "groups": [
            {
                "id": "G01",
                "unit_ids": ["U001"],
                "title": "Feature",
                "explanation": "U001",
                "commit_type": "feat",
                "message": "feat: u001",
                "depends_on": [],
            },
            {
                "id": "G02",
                "unit_ids": ["U002"],
                "title": "Test",
                "explanation": "U002",
                "commit_type": "test",
                "message": "test: u002",
                "depends_on": ["G01"],
            },
        ],
    }

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        calls += 1
        content = invalid_plan if calls == 1 else valid_plan
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps(content)}},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)
    planner = SemanticPlanner(ollama, max_corrections=2)

    plan = planner.plan(inventory)
    assert calls == 2  # Proves correction was requested and satisfied
    assert len(plan.groups) == 2


def test_planner_exhausted_corrections_aborts():
    """Test planner aborts with error when correction attempts are exhausted without fallback."""
    u1 = make_unit("U001")
    inventory = [u1]

    # Repeatedly return invalid response (unknown unit)
    invalid_plan = {
        "version": "1.0",
        "groups": [
            {
                "id": "G01",
                "unit_ids": ["U999"],
                "title": "Invalid",
                "explanation": "Unknown unit",
                "commit_type": "feat",
                "message": "feat: invalid",
                "depends_on": [],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps(invalid_plan)}},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)
    planner = SemanticPlanner(ollama, max_corrections=2)

    with pytest.raises(PlanValidationError) as exc_info:
        planner.plan(inventory)
    assert "correction attempts" in str(exc_info.value)


def test_extract_json_markdown_blocks():
    """Test extract_json strips markdown code blocks and preambles cleanly."""
    from commitcraft.planner import extract_json

    # 1. Clean JSON
    assert extract_json('{"key": "value"}') == {"key": "value"}

    # 2. Markdown fenced with ```json
    markdown_json = "```json\n{\n  \"version\": \"1.0\",\n  \"groups\": []\n}\n```"
    assert extract_json(markdown_json) == {"version": "1.0", "groups": []}

    # 3. Conversational preamble before JSON
    preamble_json = "Here is the commit plan you requested:\n```json\n{\"foo\": \"bar\"}\n```\nHope this helps!"
    assert extract_json(preamble_json) == {"foo": "bar"}


def test_planner_with_repo_context():
    """Test planner includes repo_context in user prompt."""
    u1 = make_unit("U001")
    captured_messages = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_messages
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        body = json.loads(request.content)
        captured_messages = body.get("messages", [])
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "version": "1.0",
                        "groups": [
                            {
                                "id": "G01",
                                "unit_ids": ["U001"],
                                "title": "Unit 1",
                                "explanation": "Exp",
                                "commit_type": "feat",
                                "message": "feat: unit 1",
                            }
                        ],
                    }),
                }
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)
    repo_context = {"branch": "feat/my-feature", "components": ["auth", "cli"]}
    planner = SemanticPlanner(ollama, repo_context=repo_context)

    plan = planner.plan([u1])
    assert len(plan.groups) == 1
    # Check that repo_context was sent in the user prompt payload
    user_prompt = captured_messages[1]["content"]
    assert "feat/my-feature" in user_prompt
    assert "components" in user_prompt
