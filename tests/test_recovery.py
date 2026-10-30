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


def test_recovery_instructions_details():
    """Test that RecoveryRecord generates complete, safe recovery instructions."""
    record = RecoveryRecord(
        branch_ref="refs/heads/feature-x",
        original_head="abcdef1234567890abcdef1234567890abcdef12",
        new_head="1234567890abcdef1234567890abcdef12345678",
        target_tree="9999999999999999999999999999999999999999",
        created_commits=["1234567890abcdef1234567890abcdef12345678"],
        failure_reason="Unable to write index",
    )
    instructions = record.get_instructions()
    assert "refs/heads/feature-x" in instructions
    assert "abcdef12" in instructions
    assert "12345678" in instructions
    assert "git read-tree HEAD" in instructions
    assert "Do NOT run 'git reset --hard'" in instructions
    assert "YOUR COMMITS ARE FULLY SAFE AND PRESERVED" in instructions


def test_recovery_corrupted_json_file(temp_dir: Path):
    """Test that RecoveryManager safely handles corrupted or unparseable JSON files."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    rec_file = git_dir / "COMMITCRAFT_RECOVERY.json"
    rec_file.write_text("CORRUPTED NON-JSON CONTENT", encoding="utf-8")

    mgr = RecoveryManager(git_dir)
    assert mgr.has_recovery()
    assert mgr.load_record() is None


def test_recovery_clear_nonexistent(temp_dir: Path):
    """Test that calling clear() on nonexistent recovery file does not raise an exception."""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    mgr = RecoveryManager(git_dir)
    # Should not raise
    mgr.clear()
    assert not mgr.has_recovery()

