"""Tests for PR description generation."""

from pathlib import Path
import pytest

from commitcraft.change_units import ChangeUnit
from commitcraft.executor import ExecutionResult
from commitcraft.pr_description import PRDescriptionGenerator
from commitcraft.schemas import CommitGroupProposal, PlanProposal


def test_pr_description_generation(temp_dir: Path):
    """Test generating and saving individual PR descriptions per group."""
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
        created_branches={"G01": "feat/auth-login", "G02": "test/auth-login"},
    )

    prs = PRDescriptionGenerator.generate_individual_prs(plan, execution_res, inventory)
    assert len(prs) == 2
    assert "feat(auth): add login endpoint" in prs["G01"]
    assert "test(auth): add login tests" in prs["G02"]
    assert "11111111" in prs["G01"]
    assert "22222222" in prs["G02"]
    assert "feat/auth-login" in prs["G01"]
    assert "test/auth-login" in prs["G02"]
    assert "tests/test_login.py" in prs["G02"]

    # Save to file
    saved_paths = PRDescriptionGenerator.save_individual_prs(prs, repo_root=temp_dir)
    assert len(saved_paths) == 2
    for p in saved_paths:
        assert p.is_file()
    assert (temp_dir / ".commit_craft" / "prs" / "PR_G01.md").is_file()
    assert (temp_dir / ".commit_craft" / "prs" / "PR_G02.md").is_file()
    # Verify no unified PR file was created
    assert not (temp_dir / ".commit_craft" / "COMMITCRAFT_PR.md").exists()


def test_pr_description_no_test_files_and_custom_path(temp_dir: Path):
    """Test generating individual PR description when no test files are touched and saving with custom path."""
    u1 = ChangeUnit(
        id="U001",
        path="src/main.py",
        kind="modify",
        summary="Update main",
        hunk_header=None,
        added_lines=3,
        removed_lines=1,
        is_binary=False,
        is_splittable=False,
        excerpt="+print('hello')",
        patch_text="",
    )
    inventory = [u1]

    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="Main logic",
        explanation="Update main logic",
        commit_type="refactor",
        message="refactor: update main entrypoint",
    )
    plan = PlanProposal(groups=[g1], summary=None)

    execution_res = ExecutionResult(
        created_commits=["3333333344444444"],
        new_head="3333333344444444",
        old_head="0000000000000000",
        branch_ref="refs/heads/main",
        final_tree="8888888888888888",
        ordered_groups=[g1],
    )

    prs = PRDescriptionGenerator.generate_individual_prs(plan, execution_res, inventory)
    assert len(prs) == 1
    assert "refactor: update main entrypoint" in prs["G01"]
    assert "Suggested verification steps based on modified test files" not in prs["G01"]

    # Custom single file path saving
    custom_output = temp_dir / "my_pr.md"
    saved = PRDescriptionGenerator.save_individual_prs(prs, custom_path=custom_output)
    assert saved == [custom_output]
    assert custom_output.is_file()


def test_pr_description_breaking_changes():
    """Test that breaking change commits are highlighted prominently in individual PR description."""
    u1 = ChangeUnit(
        id="U001",
        path="src/api.py",
        kind="modify",
        summary="Revamp API response schema",
        hunk_header=None,
        added_lines=5,
        removed_lines=5,
        is_binary=False,
        is_splittable=False,
        excerpt="+new_api()",
        patch_text="",
        context_info="class ApiHandler",
    )
    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="Breaking API overhaul",
        explanation="Remove deprecated v1 endpoints",
        commit_type="feat",
        message="feat(api)!: remove deprecated v1 endpoints",
    )
    plan = PlanProposal(groups=[g1])
    md = PRDescriptionGenerator.generate_group_markdown(
        group=g1,
        commit_sha=None,
        inventory=[u1],
        plan=plan,
        branch_name="feat/api-breaking-change",
    )

    assert "### ⚠ Breaking Changes" in md
    assert "BREAKING CHANGE: Remove deprecated v1 endpoints" in md
    assert "Breaking API overhaul" in md
    assert "Remove deprecated v1 endpoints" in md
    assert "`class ApiHandler`" in md
    assert "- `BREAKING-CHANGE: Remove deprecated v1 endpoints`" in md


def test_generate_group_markdown_individual():
    """Test generating an individual PR description for a single commit group."""
    u1 = ChangeUnit(
        id="U001",
        path="src/auth.py",
        kind="modify",
        summary="Add JWT validation",
        hunk_header="@@ -1,5 +1,10 @@",
        added_lines=10,
        removed_lines=2,
        is_binary=False,
        is_splittable=False,
        excerpt="+def verify_jwt():",
        patch_text="",
        context_info="def verify_jwt",
    )
    g0 = CommitGroupProposal(
        id="G00",
        unit_ids=[],
        title="Initial auth",
        explanation="setup auth",
        commit_type="feat",
        message="feat(auth): initial auth setup",
    )
    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="JWT validation",
        explanation="Enforce secure JWT checks",
        commit_type="feat",
        scope="auth",
        message="feat(auth): enforce secure JWT checks",
        depends_on=["G00"],
    )
    plan = PlanProposal(groups=[g0, g1])

    md = PRDescriptionGenerator.generate_group_markdown(
        group=g1,
        commit_sha="abcd1234ef567890",
        inventory=[u1],
        plan=plan,
        branch_name="feat/auth-jwt-validation",
    )

    assert "# Pull Request Description: feat(auth): enforce secure JWT checks" in md
    assert "## PR Title (Conventional Commit)" in md
    assert "## PR Body (Conventional Commit Style)" in md
    assert "Enforce secure JWT checks" in md
    assert "- **Type**: `feat` (scope: `auth`)" in md
    assert "- **Dedicated Branch**: `feat/auth-jwt-validation`" in md
    assert "- **Commit**: `abcd1234`: feat(auth): enforce secure JWT checks" in md
    assert "Depends on `feat(auth): initial auth setup`" in md
    assert "## Conventional Commit Footers" in md
    assert "`Depends-On: feat(auth): initial auth setup`" in md
    assert "`Branch: feat/auth-jwt-validation`" in md
    assert "`src/auth.py`" in md
    assert "`def verify_jwt`" in md
    assert "Stacked PR" in md
    # Ensure internal CommitCraft IDs (unit ID, group ID) are NOT rendered in PR description
    assert "Group ID" not in md
    assert "G01" not in md
    assert "G00" not in md
    assert "[U001]" not in md


def test_generate_individual_prs_and_save_to_subfolder(temp_dir: Path):
    """Test generating individual PRs for each group and saving in .git/prs/ subfolder."""
    u1 = ChangeUnit(
        id="U001",
        path="src/login.py",
        kind="modify",
        summary="Login route",
        hunk_header=None,
        added_lines=5,
        removed_lines=1,
        is_binary=False,
        is_splittable=False,
        excerpt="+login()",
        patch_text="",
    )
    u2 = ChangeUnit(
        id="U002",
        path="src/cache.py",
        kind="modify",
        summary="Cache layer",
        hunk_header=None,
        added_lines=8,
        removed_lines=0,
        is_binary=False,
        is_splittable=False,
        excerpt="+cache()",
        patch_text="",
    )
    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=["U001"],
        title="Login route",
        explanation="Add login handler",
        commit_type="feat",
        scope="auth",
        message="feat(auth): add login handler",
        depends_on=[],
    )
    g2 = CommitGroupProposal(
        id="G02",
        unit_ids=["U002"],
        title="Cache store",
        explanation="Add redis cache store",
        commit_type="perf",
        scope="cache",
        message="perf(cache): add redis cache store",
        depends_on=["G01"],
    )
    plan = PlanProposal(groups=[g1, g2])

    execution_res = ExecutionResult(
        created_commits=["1111111122222222", "3333333344444444"],
        new_head="3333333344444444",
        old_head="0000000000000000",
        branch_ref="refs/heads/main",
        final_tree="8888888888888888",
        ordered_groups=[g1, g2],
        created_branches={"G01": "feat/auth-login-handler", "G02": "perf/cache-redis-store"},
    )

    prs = PRDescriptionGenerator.generate_individual_prs(
        plan=plan,
        execution_res=execution_res,
        inventory=[u1, u2],
    )

    assert len(prs) == 2
    assert "G01" in prs
    assert "G02" in prs
    assert "feat(auth): add login handler" in prs["G01"]
    assert "perf(cache): add redis cache store" in prs["G02"]
    assert "feat/auth-login-handler" in prs["G01"]
    assert "perf/cache-redis-store" in prs["G02"]

    # Save to .commit_craft/prs/
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    saved_files = PRDescriptionGenerator.save_individual_prs(prs, repo_root=temp_dir, git_dir=git_dir)

    assert len(saved_files) == 2
    pr_g01_file = temp_dir / ".commit_craft" / "prs" / "PR_G01.md"
    pr_g02_file = temp_dir / ".commit_craft" / "prs" / "PR_G02.md"
    assert pr_g01_file.is_file()
    assert pr_g02_file.is_file()
    assert pr_g01_file.read_text(encoding="utf-8") == prs["G01"]
    assert pr_g02_file.read_text(encoding="utf-8") == prs["G02"]

    # Ensure unified summary file does NOT exist
    summary_file = temp_dir / ".commit_craft" / "COMMITCRAFT_PR.md"
    assert not summary_file.exists()


def test_save_individual_prs_custom_directory_and_file_mode(temp_dir: Path):
    """Test saving individual PRs with custom directory and custom file destinations."""
    prs = {
        "G01": "# PR G01\nContent 1",
        "G02": "# PR G02\nContent 2",
    }
    git_dir = temp_dir / ".git"
    git_dir.mkdir()

    # 1. Custom directory target
    custom_dir = temp_dir / "my_custom_prs"
    saved = PRDescriptionGenerator.save_individual_prs(prs, git_dir, custom_path=custom_dir)
    assert len(saved) == 2
    assert (custom_dir / "PR_G01.md").is_file()
    assert (custom_dir / "PR_G02.md").is_file()

    # 2. Custom file target with multiple groups
    custom_file = temp_dir / "export_pr.md"
    saved_files = PRDescriptionGenerator.save_individual_prs(prs, git_dir, custom_path=custom_file)
    assert len(saved_files) == 2
    assert (temp_dir / "export_pr_G01.md").is_file()
    assert (temp_dir / "export_pr_G02.md").is_file()
    # Ensure unified file does not exist
    assert not custom_file.exists()


