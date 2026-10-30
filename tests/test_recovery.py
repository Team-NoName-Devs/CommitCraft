"""Tests for recovery manager and records."""

from pathlib import Path
import pytest
from commitcraft.recovery import RecoveryManager, RecoveryRecord


def test_recovery_lifecycle(temp_dir: Path):
    """Test saving, loading, and clearing a recovery record."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()

    mgr = RecoveryManager(git_dir)
    assert not mgr.has_recovery()
    assert mgr.load_record() is None

    record = RecoveryRecord(
        branch_ref="refs/heads/main",
        original_head="1111111111111111111111111111111111111111",
        new_head="2222222222222222222222222222222222222222",
        target_tree="3333333333333333333333333333333333333333",
        created_commits=["2222222222222222222222222222222222222222"],
        failure_reason="Simulated index sync lock failure",
    )

    rec_path = mgr.save_record(record)
    assert rec_path.is_file()
    assert mgr.has_recovery()

    loaded = mgr.load_record()
    assert loaded is not None
    assert loaded.new_head == record.new_head
    assert "git read-tree HEAD" in loaded.get_instructions()

    mgr.clear()
    assert not mgr.has_recovery()
