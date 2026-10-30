"""Tests for PR description generation."""

from pathlib import Path
import pytest

from commitcraft.change_units import ChangeUnit
from commitcraft.executor import ExecutionResult
from commitcraft.pr_description import PRDescriptionGenerator
from commitcraft.schemas import CommitGroupProposal, PlanProposal


def test_pr_description_generation(temp_dir: Path):
    """Test generating and saving a structured PR description."""
    u1 = ChangeUnit(
        id="U001",
        path="src/login.py",
        kind="modify",
        summary="Add login route",
        hunk_header="@@ -1,5 +1,5 @@",
        added_lines=5,
        removed_lines=1,
        is_binary=False,
        is_splittable=False,
        excerpt="+login()",
        patch_text="",
    )
    u2 = ChangeUnit(
        id="U002",
        path="tests/test_login.py",
        kind="add",
        summary="Add login unit tests",
        hunk_header=None,
        added_lines=20,
        removed_lines=0,
        is_binary=False,
        is_splittable=False,
        excerpt="+def test_login():",
        patch_text="",
    )
    inventory = [u1, u2]

    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="Login route",
        explanation="Add login endpoint",
        commit_type="feat",
        scope="auth",
        message="feat(auth): add login endpoint",
        depends_on=[],
    )
    g2 = CommitGroupProposal(
        id="G02",
        unit_ids=["U002"],
        title="Login tests",
        explanation="Regression test suite",
        commit_type="test",
        scope="auth",
        message="test(auth): add login tests",
        depends_on=["G01"],
    )
    plan = PlanProposal(groups=[g1, g2])

    execution_res = ExecutionResult(
        created_commits=["11111111aaaaaaaa", "22222222bbbbbbbb"],
        new_head="22222222bbbbbbbb",
        old_head="0000000000000000",
        branch_ref="refs/heads/main",
        final_tree="9999999999999999",
        ordered_groups=[g1, g2],
    )

    md = PRDescriptionGenerator.generate_markdown(plan, execution_res, inventory)
    assert "# Pull Request Description" in md
    assert "feat(auth): add login endpoint" in md
    assert "test(auth): add login tests" in md
    assert "11111111" in md
    assert "22222222" in md
    assert "Automated project tests were not executed by CommitCraft" in md
    assert "tests/test_login.py" in md

    # Save to file
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    saved_path = PRDescriptionGenerator.save_pr_description(md, git_dir)
    assert saved_path.is_file()
    assert saved_path.read_text(encoding="utf-8") == md
