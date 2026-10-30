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
