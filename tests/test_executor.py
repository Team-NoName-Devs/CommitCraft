"""Tests for isolated patch replay and guarded commit execution."""

from pathlib import Path
import git
import pytest

from commitcraft.diff_parser import DiffParser
from commitcraft.errors import (
    BranchMovementError,
    ExecutionError,
    TreeMismatchError,
)
from commitcraft.executor import PlanExecutor
from commitcraft.repository import RepositoryInspector
from commitcraft.schemas import CommitGroupProposal
from commitcraft.snapshot import SnapshotEngine


def test_executor_preflight_and_execution_success(test_repo: git.Repo):
    """Test full execution of two independent changes into two distinct commits."""
    repo_dir = Path(test_repo.working_tree_dir)
    original_head = test_repo.head.commit.hexsha

    # Make two changes: edit README and add a new file
    (repo_dir / "README.md").write_text("# New Title\nContent\n", encoding="utf-8")
    (repo_dir / "feature.py").write_text("print('feature')\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 2

    # Group 1: README
    # Group 2: feature.py
    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=[units[0].id if units[0].path == "README.md" else units[1].id],
        title="Docs update",
        explanation="Update readme",
        commit_type="docs",
        message="docs: update README title",
        depends_on=[],
    )
    g2 = CommitGroupProposal(
        id="G02",
        unit_ids=[units[1].id if units[0].path == "README.md" else units[0].id],
        title="Add feature",
        explanation="Add feature script",
        commit_type="feat",
        message="feat: add feature module",
        depends_on=["G01"],
    )

    executor = PlanExecutor(repo, runner, snapshot_engine)

    # 1. Preflight
    preflight = executor.preflight_replay([g1, g2], units, snapshot)
    assert preflight.patch_replay_success
    assert preflight.tree_equality
    assert len(preflight.intermediate_trees) == 2

    # 2. Execution without approval should fail
    with pytest.raises(ExecutionError) as exc_info:
        executor.execute(preflight, snapshot, approval_confirmed=False)
    assert "approval was not confirmed" in str(exc_info.value)
    # Repo HEAD must remain unchanged
    assert test_repo.head.commit.hexsha == original_head

    # 3. Execution with approval
    res = executor.execute(preflight, snapshot, approval_confirmed=True)
    assert len(res.created_commits) == 2
    assert res.old_head == original_head
    assert res.new_head == test_repo.head.commit.hexsha
    assert res.final_tree == snapshot.target_tree

    # Verify commit messages and parent linkage
    commits = list(test_repo.iter_commits("HEAD", max_count=3))
    assert commits[0].hexsha == res.created_commits[1]
    assert commits[0].message.strip() == "feat: add feature module"
    assert commits[0].parents[0].hexsha == res.created_commits[0]

    assert commits[1].hexsha == res.created_commits[0]
    assert commits[1].message.strip() == "docs: update README title"
    assert commits[1].parents[0].hexsha == original_head

    # Verify working tree is clean
    assert test_repo.git.status("--short") == ""


def test_executor_same_file_hunks_in_separate_commits(test_repo: git.Repo):
    """Test same-file hunk splitting executed into two separate commits."""
    repo_dir = Path(test_repo.working_tree_dir)
    code_file = repo_dir / "math_utils.py"

    lines = [f"# Line {i}" for i in range(1, 45)]
    code_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    test_repo.index.add(["math_utils.py"])
    test_repo.index.commit("chore: add math_utils.py")

    # Modify Line 2 and Line 40
    lines[1] = "# Line 2 FIXED"
    lines[39] = "# Line 40 REFACTORED"
    code_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 2  # 2 hunks from the same file!

    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=[units[0].id],
        title="Fix bug in header",
        explanation="Fix top line",
        commit_type="fix",
        message="fix(math): fix header comment",
        depends_on=[],
    )
    g2 = CommitGroupProposal(
        id="G02",
        unit_ids=[units[1].id],
        title="Refactor footer",
        explanation="Refactor bottom line",
        commit_type="refactor",
        message="refactor(math): clean up footer comment",
        depends_on=["G01"],
    )

    executor = PlanExecutor(repo, runner, snapshot_engine)
    preflight = executor.preflight_replay([g1, g2], units, snapshot)
    assert preflight.patch_replay_success
    assert preflight.tree_equality

    res = executor.execute(preflight, snapshot, approval_confirmed=True)
    assert len(res.created_commits) == 2
    assert res.final_tree == snapshot.target_tree
    assert test_repo.git.status("--short") == ""


def test_executor_guarded_update_ref_prevents_race(test_repo: git.Repo):
    """Test that concurrent branch movement causes guarded update-ref to fail safely."""
    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "file.txt").write_text("change\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=[units[0].id],
        title="File update",
        explanation="Update file",
        commit_type="feat",
        message="feat: add file",
    )

    executor = PlanExecutor(repo, runner, snapshot_engine)
    preflight = executor.preflight_replay([g1], units, snapshot)

    # Simulate concurrent branch movement in the repo before execution
    test_repo.index.commit("chore: concurrent external commit")

    with pytest.raises(Exception):
        executor.execute(preflight, snapshot, approval_confirmed=True)
