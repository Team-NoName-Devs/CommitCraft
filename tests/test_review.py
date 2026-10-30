"""Tests for interactive plan editing and modifications."""

import pytest
from commitcraft.change_units import ChangeUnit
from commitcraft.errors import PlanValidationError
from commitcraft.review import PlanEditor
from commitcraft.schemas import CommitGroupProposal, PlanProposal


def make_unit(uid: str) -> ChangeUnit:
    return ChangeUnit(
        id=uid,
        path=f"{uid}.py",
        kind="modify",
        summary=f"Unit {uid}",
        hunk_header=None,
        added_lines=1,
        removed_lines=1,
        is_binary=False,
        is_splittable=False,
        excerpt="+code",
        patch_text="",
    )


def test_plan_editor_move_unit():
    """Test moving a change unit from G01 to G02."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001", "U002"],
                title="G1",
                explanation="Initial",
                commit_type="feat",
                message="feat: group 1",
            ),
            CommitGroupProposal(
                id="G02",
                unit_ids=[],
                title="G2",
                explanation="Initial",
                commit_type="test",
                message="test: group 2",
            ),
        ]
    )

    # Move U002 to G02
    updated = PlanEditor.move_unit(plan, "U002", "G01", "G02", inventory)
    g1 = next(g for g in updated.groups if g.id == "G01")
    g2 = next(g for g in updated.groups if g.id == "G02")
    assert g1.unit_ids == ["U001"]
    assert g2.unit_ids == ["U002"]


def test_plan_editor_merge_groups():
    """Test merging G02 into G01."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="G1",
                explanation="G1",
                commit_type="feat",
                message="feat: g1",
            ),
            CommitGroupProposal(
                id="G02",
                unit_ids=["U002"],
                title="G2",
                explanation="G2",
                commit_type="test",
                message="test: g2",
            ),
        ]
    )

    merged = PlanEditor.merge_groups(plan, "G02", "G01", inventory)
    assert len(merged.groups) == 1
    assert set(merged.groups[0].unit_ids) == {"U001", "U002"}


def test_plan_editor_split_group():
    """Test splitting a unit out into a new group."""
    u1 = make_unit("U001")
    u2 = make_unit("U002")
    inventory = [u1, u2]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001", "U002"],
                title="Combined",
                explanation="Both",
                commit_type="feat",
                message="feat: both",
            )
        ]
    )

    split = PlanEditor.split_group(
        plan,
        group_id="G01",
        new_group_id="G02",
        unit_ids_for_new=["U002"],
        new_title="Split tests",
        new_message="test: add tests",
        new_commit_type="test",
        inventory=inventory,
    )
    assert len(split.groups) == 2
    g1 = next(g for g in split.groups if g.id == "G01")
    g2 = next(g for g in split.groups if g.id == "G02")
    assert g1.unit_ids == ["U001"]
    assert g2.unit_ids == ["U002"]


def test_plan_editor_edit_message():
    """Test updating commit message with validation."""
    u1 = make_unit("U001")
    inventory = [u1]

    plan = PlanProposal(
        groups=[
            CommitGroupProposal(
                id="G01",
                unit_ids=["U001"],
                title="G1",
                explanation="G1",
                commit_type="feat",
                message="feat: old message",
            )
        ]
    )

    # Valid conventional commit message
    updated = PlanEditor.edit_message(plan, "G01", "fix(core): new valid message", inventory)
    assert updated.groups[0].message == "fix(core): new valid message"

    # Invalid message format should raise PlanValidationError
    with pytest.raises(PlanValidationError):
        PlanEditor.edit_message(plan, "G01", "bad message without prefix", inventory)
