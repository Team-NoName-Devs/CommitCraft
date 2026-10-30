"""Test fixtures for CommitCraft test suite."""

from pathlib import Path
import shutil
import tempfile
import git
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory cleaned up after test."""
    td = tempfile.mkdtemp()
    yield Path(td)
    shutil.rmtree(td, ignore_errors=True)


@pytest.fixture
def test_repo(temp_dir: Path):
    """Create an initialized Git repository with an initial commit on branch 'main'."""
    repo = git.Repo.init(temp_dir, initial_branch="main")
    # Configure author identity for deterministic commits
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "CommitCraft Tester")
        writer.set_value("user", "email", "tester@commitcraft.test")
        writer.set_value("init", "defaultBranch", "main")
        writer.set_value("commit", "gpgsign", "false")

    # Create initial commit
    init_file = temp_dir / "README.md"
    init_file.write_text("# Test Repo\nInitial content.\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("chore: initial commit")

    return repo
