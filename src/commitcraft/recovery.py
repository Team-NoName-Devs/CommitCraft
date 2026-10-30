"""Failure recovery tracking and safe restoration procedures."""

import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


RECOVERY_FILE_NAME = "COMMITCRAFT_RECOVERY.json"


class RecoveryRecord(BaseModel):
    """Metadata recorded when branch update succeeds but index synchronization fails."""

    branch_ref: str
    original_head: str
    new_head: str
    target_tree: str
    created_commits: list[str]
    failure_reason: str
    recovery_command: str = "git read-tree HEAD"

    def get_instructions(self) -> str:
        return (
            "CRITICAL: CommitCraft safely installed the new commit chain on your branch,\n"
            f"updating {self.branch_ref} from {self.original_head[:8]} to {self.new_head[:8]}.\n"
            "However, the real Git index could not be refreshed automatically.\n\n"
            "YOUR COMMITS ARE FULLY SAFE AND PRESERVED.\n"
            "To synchronize your working index cleanly without altering any working files, run:\n\n"
            f"    {self.recovery_command}\n\n"
            "Do NOT run 'git reset --hard' or 'git clean', as that would discard uncommitted files."
        )


class RecoveryManager:
    """Manages saving, checking, and clearing recovery state inside .git directory."""

    def __init__(self, git_dir: Path):
        self.git_dir = Path(git_dir).resolve()
        self.recovery_path = self.git_dir / RECOVERY_FILE_NAME

    def has_recovery(self) -> bool:
        """Check if an unresolved recovery record exists."""
        return self.recovery_path.is_file()

    def save_record(self, record: RecoveryRecord) -> Path:
        """Save recovery record to .git/COMMITCRAFT_RECOVERY.json."""
        self.recovery_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.recovery_path, "w", encoding="utf-8") as f:
            f.write(record.model_dump_json(indent=2))
        return self.recovery_path

    def load_record(self) -> Optional[RecoveryRecord]:
        """Load recovery record if present."""
        if not self.has_recovery():
            return None
        try:
            with open(self.recovery_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RecoveryRecord.model_validate(data)
        except Exception:
            return None

    def clear(self) -> None:
        """Remove recovery file after verified recovery."""
        if self.recovery_path.exists():
            self.recovery_path.unlink()
