"""Tests for Pydantic schemas, validation rules, and Conventional Commits enforcement."""

import pytest
from pydantic import ValidationError

from commitcraft.schemas import (
    COMMIT_TYPES,
    CommitGroupProposal,
    PlanProposal,
)


def test_commit_group_proposal_valid_types():
    """Verify that all standard Conventional Commit types are accepted."""
    for ctype in COMMIT_TYPES:
        group = CommitGroupProposal(
            id="G01",
            unit_ids=["U001"],
            title=f"{ctype} group",
            explanation=f"Group for {ctype}",
            commit_type=ctype,
            message=f"{ctype}: valid message",
        )
        assert group.commit_type == ctype


def test_commit_group_proposal_type_case_insensitive():
    """Verify that commit_type is normalized to lowercase stripped string."""
    group = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="Feat group",
        explanation="Explanation",
        commit_type="  FEAT  ",
        message="feat: uppercase type normalized",
    )
    assert group.commit_type == "feat"


def test_commit_group_proposal_invalid_type():
    """Verify that non-standard commit types are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        CommitGroupProposal(
            id="G01",
            unit_ids=["U001"],
            title="Invalid",
            explanation="Explanation",
            commit_type="enhancement",
            message="enhancement: invalid type",
        )
    assert "Invalid commit type 'enhancement'" in str(exc_info.value)


@pytest.mark.parametrize(
    "valid_message",
    [
        "feat: add user authentication",
        "fix: resolve null pointer exception",
        "docs(readme): update getting started instructions",
        "refactor(executor/git): simplify subprocess calls",
        "perf(db): optimize query caching",
        "test(auth): add edge case tests",
        "chore: bump dependencies",
        "build(pyproject): update hatchling build backend",
        "ci(github): add windows matrix to workflow",
        "style(css): format table alignment",
        "revert: rollback broken migration",
        "feat!: breaking api change",
        "fix(core)!: breaking fix in core logic",
    ],
)
def test_commit_group_proposal_valid_messages(valid_message: str):
    """Verify valid Conventional Commit messages pass validation."""
    group = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="Title",
        explanation="Explanation",
        commit_type="feat",
        message=valid_message,
    )
    assert group.message == valid_message.strip()


@pytest.mark.parametrize(
    "invalid_message",
    [
        "",
        "   ",
        "Add new user login feature",
        "WIP: working on stuff",
        "feat : space before colon",
        "feat(scope) missing colon description",
        "unknown: custom unknown type",
        "feat(): empty scope",
    ],
)
def test_commit_group_proposal_invalid_messages(invalid_message: str):
    """Verify invalid commit messages are rejected with clear validation error."""
    with pytest.raises(ValidationError):
        CommitGroupProposal(
            id="G01",
            unit_ids=["U001"],
            title="Title",
            explanation="Explanation",
            commit_type="feat",
            message=invalid_message,
        )


def test_plan_proposal_empty_groups_rejected():
    """Verify that PlanProposal requires at least one group."""
    with pytest.raises(ValidationError) as exc_info:
        PlanProposal(groups=[])
    assert "Plan must contain at least one commit group" in str(exc_info.value)


def test_plan_proposal_serialization_roundtrip():
    """Verify PlanProposal serialization to/from JSON and dictionary."""
    group = CommitGroupProposal(
        id="G01",
        unit_ids=["U001", "U002"],
        title="Core logic",
        explanation="Initial core implementation",
        commit_type="feat",
        scope="core",
        message="feat(core): implement core logic",
        depends_on=[],
    )
    plan = PlanProposal(version="1.0", groups=[group], summary="Test summary")

    dumped_json = plan.model_dump_json()
    loaded_plan = PlanProposal.model_validate_json(dumped_json)

    assert loaded_plan.version == "1.0"
    assert loaded_plan.summary == "Test summary"
    assert len(loaded_plan.groups) == 1
    assert loaded_plan.groups[0].id == "G01"
    assert loaded_plan.groups[0].message == "feat(core): implement core logic"
