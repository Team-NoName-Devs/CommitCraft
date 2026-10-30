"""Tests for isolated patch replay and guarded commit execution."""

from pathlib import Path
import git
import pytest

from commitcraft.diff_parser import DiffParser
from commitcraft.errors import (
    BranchMovementError,
    ExecutionError,
    IndexSyncError,
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


def test_executor_preserves_line_endings_tree_equality(test_repo: git.Repo):
    """Verify that CRLF and mixed line endings maintain mathematical tree equality."""
    repo_dir = Path(test_repo.working_tree_dir)

    # Write files with CRLF and mixed line endings
    crlf_file = repo_dir / "crlf_doc.md"
    crlf_file.write_bytes(b"# Title\r\nLine 2 with CRLF\r\n")

    mixed_file = repo_dir / "mixed_code.py"
    mixed_file.write_bytes(b"def func():\n    return True\r\n")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 2

    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=[u.id for u in units],
        title="CRLF and mixed files",
        explanation="Add documentation and code with CRLF line endings",
        commit_type="docs",
        message="docs: add files with preserved line endings",
    )

    executor = PlanExecutor(repo, runner, snapshot_engine)
    preflight = executor.preflight_replay([g1], units, snapshot)

    assert preflight.patch_replay_success
    assert preflight.tree_equality
    assert preflight.final_tree == snapshot.target_tree

    res = executor.execute(preflight, snapshot, approval_confirmed=True)
    assert res.final_tree == snapshot.target_tree
    assert test_repo.git.status("--short") == ""


def test_executor_missing_git_identity(test_repo: git.Repo, monkeypatch: pytest.MonkeyPatch):
    """Test that execution halts if Git author/committer identity is unconfigured."""
    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "file.py").write_text("a = 1\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()
    units = DiffParser.parse(snapshot.diff_text)

    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=[units[0].id],
        title="File",
        explanation="File",
        commit_type="feat",
        message="feat: add file",
    )
    executor = PlanExecutor(repo, runner, snapshot_engine)
    preflight = executor.preflight_replay([g1], units, snapshot)

    # Mock git config user.name / user.email to return empty and strip env vars
    monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_NAME", raising=False)
    monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)

    orig_run = runner.run

    def mock_run(args, **kwargs):
        if len(args) >= 2 and args[0] == "config" and args[1] in ("user.name", "user.email"):
            import subprocess
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        return orig_run(args, **kwargs)

    monkeypatch.setattr(runner, "run", mock_run)

    with pytest.raises(ExecutionError) as exc_info:
        executor.execute(preflight, snapshot, approval_confirmed=True)
    assert "Git user identity (user.name and user.email) is not configured" in str(exc_info.value)
    assert "git config user.name" in exc_info.value.resolution


def test_executor_index_sync_failure_creates_recovery_record(
    test_repo: git.Repo, monkeypatch: pytest.MonkeyPatch
):
    """Test that if branch pointer moves but index sync fails, a recovery record is safely persisted."""
    from commitcraft.recovery import RecoveryManager

    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "sync_fail.py").write_text("data = True\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()
    units = DiffParser.parse(snapshot.diff_text)

    g1 = CommitGroupProposal(
        id="G01",
        unit_ids=[units[0].id],
        title="Sync fail",
        explanation="Testing recovery record",
        commit_type="feat",
        message="feat: test recovery on sync failure",
    )
    executor = PlanExecutor(repo, runner, snapshot_engine)
    preflight = executor.preflight_replay([g1], units, snapshot)

    orig_run = runner.run

    def mock_run(args, **kwargs):
        if args == ["read-tree", "HEAD"]:
            raise Exception("Simulated fatal index lock error during read-tree")
        return orig_run(args, **kwargs)

    monkeypatch.setattr(runner, "run", mock_run)

    with pytest.raises(IndexSyncError) as exc_info:
        executor.execute(preflight, snapshot, approval_confirmed=True)

    assert "Branch moved to" in str(exc_info.value)
    assert "Recovery instructions saved" in str(exc_info.value)

    # Verify recovery manager recorded the state
    rec_mgr = RecoveryManager(Path(test_repo.git_dir))
    assert rec_mgr.has_recovery()
    record = rec_mgr.load_record()
    assert record is not None
    assert record.branch_ref == snapshot.branch_ref
    assert record.original_head == snapshot.head_commit
    assert "git read-tree HEAD" in record.get_instructions()


