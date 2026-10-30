"""Tests for repository state inspection and validation."""

from pathlib import Path
import git
import pytest

from commitcraft.errors import (
    GitCommandError,
    RepositoryError,
    UnsupportedRepositoryStateError,
)
from commitcraft.git_runner import GitRunner
from commitcraft.repository import RepositoryInspector


def test_valid_repository_inspection(test_repo: git.Repo):
    """Test inspection of a valid repository on a named branch with an initial commit."""
    inspector = RepositoryInspector(Path(test_repo.working_tree_dir))
    repo, runner, state = inspector.inspect()

    assert state.branch_name == "main"
    assert state.branch_ref == "refs/heads/main"
    assert state.head_commit == test_repo.head.commit.hexsha
    assert not state.is_bare
    assert state.staged_files == []
    assert state.unstaged_files == []
    assert state.untracked_files == []


def test_non_repository_directory(temp_dir: Path):
    """Test that a non-Git directory raises RepositoryError."""
    inspector = RepositoryInspector(temp_dir)
    with pytest.raises(RepositoryError) as exc_info:
        inspector.inspect()
    assert "not a Git repository" in str(exc_info.value)


def test_bare_repository(temp_dir: Path):
    """Test that bare repositories are rejected."""
    git.Repo.init(temp_dir, bare=True)
    inspector = RepositoryInspector(temp_dir)
    with pytest.raises(UnsupportedRepositoryStateError) as exc_info:
        inspector.inspect()
    assert "Bare" in str(exc_info.value)


def test_repository_no_initial_commit(temp_dir: Path):
    """Test that a repository without an initial commit is rejected."""
    git.Repo.init(temp_dir, initial_branch="main")
    inspector = RepositoryInspector(temp_dir)
    with pytest.raises(UnsupportedRepositoryStateError) as exc_info:
        inspector.inspect()
    assert "no initial commit" in str(exc_info.value)


def test_detached_head_rejected(test_repo: git.Repo):
    """Test that detached HEAD states are rejected."""
    hexsha = test_repo.head.commit.hexsha
    test_repo.git.checkout(hexsha)
    assert test_repo.head.is_detached

    inspector = RepositoryInspector(Path(test_repo.working_tree_dir))
    with pytest.raises(UnsupportedRepositoryStateError) as exc_info:
        inspector.inspect()
    assert "detached HEAD" in str(exc_info.value)


def test_in_progress_merge_rejected(test_repo: git.Repo):
    """Test that in-progress merge markers cause rejection."""
    git_dir = Path(test_repo.git_dir)
    merge_head = git_dir / "MERGE_HEAD"
    merge_head.write_text("0123456789abcdef", encoding="utf-8")

    inspector = RepositoryInspector(Path(test_repo.working_tree_dir))
    with pytest.raises(UnsupportedRepositoryStateError) as exc_info:
        inspector.inspect()
    assert "Merge in progress" in str(exc_info.value)


def test_in_progress_rebase_rejected(test_repo: git.Repo):
    """Test that in-progress rebase markers cause rejection."""
    git_dir = Path(test_repo.git_dir)
    rebase_dir = git_dir / "rebase-merge"
    rebase_dir.mkdir()

    inspector = RepositoryInspector(Path(test_repo.working_tree_dir))
    with pytest.raises(UnsupportedRepositoryStateError) as exc_info:
        inspector.inspect()
    assert "Rebase in progress" in str(exc_info.value)


def test_git_runner_command_failure(test_repo: git.Repo):
    """Test GitRunner error handling for invalid commands."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    with pytest.raises(GitCommandError) as exc_info:
        runner.run(["non-existent-subcommand-12345"])
    assert exc_info.value.exit_code != 0


def test_git_runner_timeout(test_repo: git.Repo, monkeypatch: pytest.MonkeyPatch):
    """Test GitRunner handles timeout appropriately."""
    runner = GitRunner(Path(test_repo.working_tree_dir), timeout=0.001)

    import subprocess
    def mock_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=0.001)

    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(GitCommandError) as exc_info:
        runner.run(["status"])
    assert "timed out" in str(exc_info.value)
