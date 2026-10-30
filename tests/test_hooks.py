"""Tests for optional Git hook installation and removal."""

from pathlib import Path
import pytest
from commitcraft.hooks import HookManager


def test_hook_install_and_remove(temp_dir: Path):
    """Test installing and removing advisory pre-commit hook."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()

    mgr = HookManager(git_dir)
    assert not mgr.is_installed()

    # Install
    hook_path = mgr.install()
    assert hook_path.is_file()
    assert mgr.is_installed()
    assert "# CommitCraft pre-commit advisory hook" in hook_path.read_text(encoding="utf-8")

    # Second install should be idempotent
    mgr.install()
    assert mgr.is_installed()

    # Remove
    assert mgr.remove()
    assert not mgr.is_installed()
    assert not hook_path.exists()


def test_hook_preserves_and_restores_existing_hook(temp_dir: Path):
    """Test that an existing pre-commit hook is backed up on install and restored on remove."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir()
    user_hook = hooks_dir / "pre-commit"
    user_hook.write_text("#!/bin/sh\necho 'my custom linter'\nexit 0\n", encoding="utf-8")

    mgr = HookManager(git_dir)
    assert not mgr.is_installed()

    # Install CommitCraft hook
    mgr.install()
    assert mgr.is_installed()
    assert mgr.backup_file.is_file()
    assert "my custom linter" in mgr.backup_file.read_text(encoding="utf-8")

    # Remove CommitCraft hook
    assert mgr.remove()
    assert not mgr.is_installed()
    assert user_hook.is_file()
    assert "my custom linter" in user_hook.read_text(encoding="utf-8")
    assert not mgr.backup_file.exists()


def test_hook_remove_foreign_hook_raises(temp_dir: Path):
    """Test that attempting to remove a foreign hook not installed by CommitCraft raises HookError."""
    from commitcraft.errors import HookError

    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir()
    user_hook = hooks_dir / "pre-commit"
    user_hook.write_text("#!/bin/sh\n# External linter hook\nexit 0\n", encoding="utf-8")

    mgr = HookManager(git_dir)
    with pytest.raises(HookError) as exc_info:
        mgr.remove()
    assert "not installed by CommitCraft" in str(exc_info.value)


def test_hook_remove_nonexistent(temp_dir: Path):
    """Test that removing when no hook exists returns False without error."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    mgr = HookManager(git_dir)
    assert mgr.remove() is False

