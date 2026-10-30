"""Tests for safe native Git subprocess runner."""

from pathlib import Path
import subprocess
import pytest
import git

from commitcraft.errors import GitCommandError
from commitcraft.git_runner import GitRunner


def test_git_runner_run_basic(test_repo: git.Repo):
    """Test basic run execution and stdout capture."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    res = runner.run(["status", "--porcelain"])
    assert res.returncode == 0
    assert isinstance(res.stdout, str)


def test_git_runner_stdin_string_and_bytes(test_repo: git.Repo):
    """Test passing stdin as both string and bytes to Git subprocess."""
    runner = GitRunner(Path(test_repo.working_tree_dir))

    # hash-object with string stdin
    res1 = runner.run(["hash-object", "-w", "--stdin"], input_data="hello world string\n")
    sha1 = res1.stdout.strip()
    assert len(sha1) == 40

    # hash-object with bytes stdin
    res2 = runner.run(["hash-object", "-w", "--stdin"], input_data=b"hello world bytes\n")
    sha2 = res2.stdout.strip()
    assert len(sha2) == 40
    assert sha1 != sha2


def test_git_runner_rev_parse(test_repo: git.Repo):
    """Test rev_parse resolves commit and tree hashes accurately."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    head_sha = runner.rev_parse("HEAD")
    assert head_sha == test_repo.head.commit.hexsha

    tree_sha = runner.rev_parse("HEAD^{tree}")
    assert tree_sha == test_repo.head.commit.tree.hexsha


def test_git_runner_get_symbolic_ref(test_repo: git.Repo):
    """Test get_symbolic_ref retrieves the active branch ref."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    branch_ref = runner.get_symbolic_ref("HEAD")
    assert branch_ref == "refs/heads/main"


def test_git_runner_write_tree_and_read_tree(test_repo: git.Repo):
    """Test write_tree and read_tree operations."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    initial_tree = runner.write_tree()
    assert len(initial_tree) == 40

    # Modify a file and stage it
    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "temp.txt").write_text("temporary content\n", encoding="utf-8")
    test_repo.index.add(["temp.txt"])
    new_tree = runner.write_tree()
    assert new_tree != initial_tree

    # Reset index using read_tree back to initial_tree
    runner.read_tree(initial_tree)
    restored_tree = runner.write_tree()
    assert restored_tree == initial_tree


def test_git_runner_commit_tree_single_parent(test_repo: git.Repo):
    """Test commit_tree creates a valid commit object with one parent."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    tree_id = runner.write_tree()
    parent_id = runner.rev_parse("HEAD")

    commit_id = runner.commit_tree(
        tree_id=tree_id,
        parents=[parent_id],
        message="feat: commit via runner commit_tree",
    )
    assert len(commit_id) == 40

    # Verify commit details via rev-parse and log
    parent_of_new = runner.run(["rev-parse", f"{commit_id}^"]).stdout.strip()
    assert parent_of_new == parent_id


def test_git_runner_commit_tree_multiple_parents(test_repo: git.Repo):
    """Test commit_tree creates a merge commit with multiple parents."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    tree_id = runner.write_tree()
    parent1 = runner.rev_parse("HEAD")

    # Create dummy parent2 commit
    parent2 = runner.commit_tree(tree_id=tree_id, parents=[parent1], message="chore: parent 2")

    merge_commit = runner.commit_tree(
        tree_id=tree_id,
        parents=[parent1, parent2],
        message="merge: combine branches",
    )
    parents = runner.run(["rev-list", "--parents", "-n", "1", merge_commit]).stdout.strip().split()
    assert parents == [merge_commit, parent1, parent2]


def test_git_runner_update_ref_guarded(test_repo: git.Repo):
    """Test update_ref succeeds with expected old SHA and fails with mismatched old SHA."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    current_head = runner.rev_parse("HEAD")
    tree_id = runner.write_tree()
    new_commit = runner.commit_tree(tree_id=tree_id, parents=[current_head], message="test: update_ref")

    # Successful guarded update
    runner.update_ref(
        ref_name="refs/heads/main",
        new_commit_id=new_commit,
        old_commit_id=current_head,
    )
    assert runner.rev_parse("refs/heads/main") == new_commit

    # Failed guarded update (old_head does not match current_head)
    with pytest.raises(GitCommandError) as exc_info:
        runner.update_ref(
            ref_name="refs/heads/main",
            new_commit_id=current_head,
            old_commit_id="0000000000000000000000000000000000000000",
        )
    assert exc_info.value.exit_code != 0


def test_git_runner_diff_tree(test_repo: git.Repo):
    """Test diff_tree generates unified diff between two revisions."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    head_tree = runner.rev_parse("HEAD^{tree}")

    # Stage a change and get new tree
    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "sample.py").write_text("x = 10\n", encoding="utf-8")
    test_repo.index.add(["sample.py"])
    new_tree = runner.write_tree()

    diff_output = runner.diff_tree(head_tree, new_tree)
    assert "diff --git a/sample.py b/sample.py" in diff_output
    assert "+x = 10" in diff_output


def test_git_runner_check_false_returns_completed_process(test_repo: git.Repo):
    """Test that check=False returns CompletedProcess on non-zero exit code instead of raising."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    res = runner.run(["rev-parse", "--verify", "non-existent-ref-xyz"], check=False)
    assert res.returncode != 0


def test_git_runner_executable_not_found(test_repo: git.Repo, monkeypatch: pytest.MonkeyPatch):
    """Test GitRunner raises GitCommandError with clear resolution when git binary is missing."""
    runner = GitRunner(Path(test_repo.working_tree_dir))

    def mock_run(*args, **kwargs):
        raise FileNotFoundError("No such file: 'git'")

    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(GitCommandError) as exc_info:
        runner.run(["status"])
    assert exc_info.value.exit_code == -1
    assert "Git executable not found in PATH" in exc_info.value.stderr
    assert "Install Git" in exc_info.value.resolution
