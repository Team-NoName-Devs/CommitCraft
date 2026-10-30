"""Tests for local plan validation against change inventory."""

import pytest
from commitcraft.change_units import ChangeUnit
from commitcraft.errors import PlanValidationError
from commitcraft.schemas import CommitGroupProposal, PlanProposal
from commitcraft.validator import PlanValidator


def make_unit(uid: str, path: str = "app.py") -> ChangeUnit:
    return ChangeUnit(
        id=uid,
        path=path,
        kind="modify",
        summary="Test unit",
        hunk_header=None,
        added_lines=1,
        removed_lines=1,
        is_binary=False,
        is_splittable=False,
        excerpt="+test",
        patch_text="",
    )


def test_valid_plan_passes_validation():
    """Test valid complete plan passes without errors."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="Auth feature",
                explanation="Initial auth logic",
                commit_type="feat",
                scope="auth",
                message="feat(auth): add login handler",
                depends_on=[],
            ),
            CommitGroupProposal(
                id="G02",
                unit_ids=["U002"],
                title="Auth tests",
                explanation="Regression tests for auth",
                commit_type="test",
                scope="auth",
                message="test(auth): add login test cases",
                depends_on=["G01"],
            ),
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert errors == []
    # Assert does not raise
    PlanValidator.assert_valid(plan, inventory)


def test_missing_unit_assignment():
    """Test that omitting a change unit reports validation error."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="Partial group",
                explanation="Only U001",
                commit_type="feat",
                message="feat: only u001",
            )
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert any("missing from plan" in e and "U002" in e for e in errors)


def test_duplicate_unit_assignment():
    """Test assigning the same unit to multiple groups reports validation error."""
    u1 = make_unit("U001")
    inventory = [u1]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="Group 1",
                explanation="First",
                commit_type="feat",
                message="feat: group 1",
            ),
            CommitGroupProposal(
                id="G02",
                unit_ids=["U001"],
                title="Group 2",
                explanation="Duplicate",
                commit_type="fix",
                message="fix: group 2",
            ),
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert any("more than once" in e for e in errors)


def test_unknown_unit_id():
    """Test referencing a non-existent unit ID reports validation error."""
    u1 = make_unit("U001")
    inventory = [u1]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001", "U999"],
                title="Group with ghost unit",
                explanation="Includes U999",
                commit_type="feat",
                message="feat: test",
            )
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert any("unknown change unit ID 'U999'" in e for e in errors)


def test_empty_group_rejected():
    """Test empty group without units is rejected."""
    u1 = make_unit("U001")
    inventory = [u1]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="G1",
                explanation="Valid",
                commit_type="feat",
                message="feat: valid",
            ),
            CommitGroupProposal(
                id="G02",
                unit_ids=[],
                title="Empty group",
                explanation="Empty",
                commit_type="chore",
                message="chore: empty",
            ),
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert any("contains no change units" in e for e in errors)
