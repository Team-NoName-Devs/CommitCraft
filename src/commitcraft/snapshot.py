"""Target snapshot capture and isolated index operations."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import Optional
import git

from commitcraft.errors import SnapshotError, StaleSnapshotError
from commitcraft.git_runner import GitRunner
from commitcraft.repository import RepositoryState


@dataclass
class SnapshotTarget:
    """Captured target snapshot representing the intended final repository state."""

    head_commit: str
    head_tree: str
    branch_ref: str
    branch_name: str
    target_tree: str
    diff_text: str
    has_changes: bool


class SnapshotEngine:
    """Manages isolated index operations for snapshot capture and revalidation."""

    def __init__(self, repo: git.Repo, runner: GitRunner, state: RepositoryState):
        self.repo = repo
        self.runner = runner
        self.state = state

    def _create_isolated_index(self, temp_dir: Path) -> Path:
        """Create an isolated index file, copying existing staging state if present."""
        temp_index = temp_dir / "isolated_index"
        real_index = Path(self.repo.git_dir) / "index"
        if real_index.exists():
            shutil.copy2(real_index, temp_index)
        return temp_index

    def capture_snapshot(self) -> SnapshotTarget:
        """Capture the intended target snapshot tree using an isolated index.

        The real index and working tree remain completely unmodified.
        """
        head_commit = self.state.head_commit
        head_tree = self.runner.rev_parse(f"{head_commit}^{{tree}}")

        with tempfile.TemporaryDirectory(prefix="commitcraft_snapshot_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            isolated_index = self._create_isolated_index(tmp_dir)
            env_override = {"GIT_INDEX_FILE": str(isolated_index)}

            # Stage working-tree changes (modifications, deletions, eligible untracked files)
            # into the isolated index only.
            try:
                # Add all tracked updates and untracked files respecting .gitignore
                self.runner.run(["add", "-A"], env_override=env_override)
            except Exception as e:
                raise SnapshotError(
                    f"Failed to capture snapshot in isolated index: {e}",
                    resolution="Ensure all modified/untracked files have read permissions.",
                ) from e

            # Write out the target tree
            target_tree = self.runner.write_tree(env_override=env_override)

        has_changes = target_tree != head_tree
        diff_text = ""
        if has_changes:
            diff_text = self.runner.diff_tree(head_commit, target_tree)

        return SnapshotTarget(
            head_commit=head_commit,
            head_tree=head_tree,
            branch_ref=self.state.branch_ref,
            branch_name=self.state.branch_name,
            target_tree=target_tree,
            diff_text=diff_text,
            has_changes=has_changes,
        )

    def revalidate_snapshot(self, snapshot: SnapshotTarget) -> None:
        """Verify that current working tree and HEAD still match the captured target.

        Raises StaleSnapshotError or BranchMovementError if state changed.
        """
        current_head = self.runner.rev_parse("HEAD")
        if current_head != snapshot.head_commit:
            raise StaleSnapshotError(
                f"HEAD commit moved from {snapshot.head_commit[:8]} to {current_head[:8]}.",
                resolution="The repository was updated during review. Restart commitcraft.",
            )

        # Recapture current target tree to verify working tree content has not changed
        current_snapshot = self.capture_snapshot()
        if current_snapshot.target_tree != snapshot.target_tree:
            raise StaleSnapshotError(
                f"Working tree changed during operation (target tree was {snapshot.target_tree[:8]}, "
                f"now {current_snapshot.target_tree[:8]}).",
                resolution="Files were modified during the session. Please review and restart.",
            )
