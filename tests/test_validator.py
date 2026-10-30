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


def test_duplicate_group_id_rejected():
    """Test that duplicate group identifiers report validation errors."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="G1 First",
                explanation="First",
                commit_type="feat",
                message="feat: first",
            ),
            CommitGroupProposal(
                id="G01",  # Duplicate ID
                unit_ids=["U002"],
                title="G1 Second",
                explanation="Second",
                commit_type="feat",
                message="feat: second",
            ),
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert any("Duplicate group identifier 'G01'" in e for e in errors)


def test_assert_valid_raises_plan_validation_error():
    """Test that assert_valid raises PlanValidationError with formatted errors."""
    u1 = make_unit("U001")
    inventory = [u1]

    # Empty unit_ids
    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=[],
                title="G1",
                explanation="Exp",
                commit_type="feat",
                message="feat: msg",
            )
        ]
    )

    with pytest.raises(PlanValidationError) as exc_info:
        PlanValidator.assert_valid(plan, inventory)
    assert "Plan validation failed with" in str(exc_info.value)
    assert "contains no change units" in str(exc_info.value)


def test_modify_before_add_rejected():
    """Test that modifying a file in a group ordered before the file's creation group is rejected."""
    # u_add creates new_module.py
    u_add = ChangeUnit(
        id="U001",
        path="new_module.py",
        kind="add",
        summary="Create new_module.py",
        hunk_header=None,
        added_lines=10,
        removed_lines=0,
        is_binary=False,
        is_splittable=False,
        excerpt="+def hello(): pass",
        patch_text="",
    )
    # u_mod modifies new_module.py
    u_mod = ChangeUnit(
        id="U002",
        path="new_module.py",
        kind="modify",
        summary="Update new_module.py",
        hunk_header="@@ -1,5 +1,6 @@",
        added_lines=2,
        removed_lines=0,
        is_binary=False,
        is_splittable=False,
        excerpt="+def world(): pass",
        patch_text="",
    )
    inventory = [u_add, u_mod]

    # G01 modifies new_module.py, G02 adds new_module.py. G01 has no dependency on G02 (so G01 is ordered first!)
    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U002"],
                title="Modify before create",
                explanation="Modifying",
                commit_type="feat",
                message="feat: modify module",
                depends_on=[],
            ),
            CommitGroupProposal(
                id="G02",
                unit_ids=["U001"],
                title="Create module",
                explanation="Creating",
                commit_type="feat",
                message="feat: create module",
                depends_on=["G01"],  # G02 depends on G01, putting G01 first!
            ),
        ]
    )

    errors = PlanValidator.validate(plan, inventory)
    assert any("before it is created" in e for e in errors)

