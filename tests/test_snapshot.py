"""Tests for snapshot capture and isolated index operations."""

from pathlib import Path
import git
import pytest

from commitcraft.git_runner import GitRunner
from commitcraft.repository import RepositoryInspector
from commitcraft.snapshot import SnapshotEngine
from commitcraft.errors import StaleSnapshotError


def test_clean_working_tree_snapshot(test_repo: git.Repo):
    """Test snapshot when working tree is completely clean."""
    inspector = RepositoryInspector(Path(test_repo.working_tree_dir))
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)

    snapshot = engine.capture_snapshot()
    assert not snapshot.has_changes
    assert snapshot.target_tree == snapshot.head_tree
    assert snapshot.diff_text == ""


def test_tracked_unstaged_modification(test_repo: git.Repo):
    """Test capturing an unstaged modification in a tracked file."""
    repo_dir = Path(test_repo.working_tree_dir)
    readme = repo_dir / "README.md"
    readme.write_text("# Updated README\nNew line here.\n", encoding="utf-8")

    real_index_mtime_before = (Path(test_repo.git_dir) / "index").stat().st_mtime_ns

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)

    snapshot = engine.capture_snapshot()
    assert snapshot.has_changes
    assert snapshot.target_tree != snapshot.head_tree
    assert "New line here." in snapshot.diff_text

    # Verify real index is completely untouched
    real_index_mtime_after = (Path(test_repo.git_dir) / "index").stat().st_mtime_ns
    assert real_index_mtime_before == real_index_mtime_after
    assert len(test_repo.index.diff(test_repo.head.commit)) == 0  # Nothing staged in real index


def test_staged_and_unstaged_mixed(test_repo: git.Repo):
    """Test capturing both staged and unstaged modifications."""
    repo_dir = Path(test_repo.working_tree_dir)

    # 1. Modify and stage file A
    file_a = repo_dir / "file_a.txt"
    file_a.write_text("Staged content\n", encoding="utf-8")
    test_repo.index.add(["file_a.txt"])

    # 2. Modify file B without staging
    file_b = repo_dir / "file_b.txt"
    file_b.write_text("Unstaged content\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)

    snapshot = engine.capture_snapshot()
    assert snapshot.has_changes
    assert "file_a.txt" in snapshot.diff_text
    assert "file_b.txt" in snapshot.diff_text

    # Real index should still have ONLY file_a staged
    staged = [d.a_path for d in test_repo.index.diff(test_repo.head.commit)]
    assert staged == ["file_a.txt"]


def test_untracked_files_and_gitignore(test_repo: git.Repo):
    """Test untracked files are captured while ignored files are omitted."""
    repo_dir = Path(test_repo.working_tree_dir)

    # Add .gitignore
    gitignore = repo_dir / ".gitignore"
    gitignore.write_text("*.log\nignored_dir/\n", encoding="utf-8")
    test_repo.index.add([".gitignore"])
    test_repo.index.commit("chore: add gitignore")

    # Untracked eligible file
    code_file = repo_dir / "src.py"
    code_file.write_text("print('hello')\n", encoding="utf-8")

    # Ignored file
    log_file = repo_dir / "debug.log"
    log_file.write_text("secret log\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)

    snapshot = engine.capture_snapshot()
    assert "src.py" in snapshot.diff_text
    assert "debug.log" not in snapshot.diff_text


def test_deleted_tracked_file(test_repo: git.Repo):
    """Test capturing a deleted tracked file."""
    repo_dir = Path(test_repo.working_tree_dir)
    readme = repo_dir / "README.md"
    readme.unlink()

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)

    snapshot = engine.capture_snapshot()
    assert snapshot.has_changes
    assert "deleted file mode" in snapshot.diff_text or "--- a/README.md" in snapshot.diff_text


def test_revalidate_snapshot_detects_changes(test_repo: git.Repo):
    """Test that revalidate_snapshot detects subsequent working tree mutations."""
    repo_dir = Path(test_repo.working_tree_dir)
    readme = repo_dir / "README.md"
    readme.write_text("Initial update\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)

    snapshot = engine.capture_snapshot()
    # First revalidation without changes should succeed
    engine.revalidate_snapshot(snapshot)

    # Mutate file
    readme.write_text("Mutated update during review\n", encoding="utf-8")

    with pytest.raises(StaleSnapshotError) as exc_info:
        engine.revalidate_snapshot(snapshot)
    assert "Working tree changed" in str(exc_info.value)
