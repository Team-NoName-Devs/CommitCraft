"""Isolated-index patch replay, tree equality verification, and guarded commit execution."""

import re
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Optional
import git

from commitcraft.change_units import ChangeUnit
from commitcraft.errors import (
    BranchMovementError,
    ExecutionError,
    IndexSyncError,
    TreeMismatchError,
)
from commitcraft.git_runner import GitRunner
from commitcraft.recovery import RecoveryManager, RecoveryRecord
from commitcraft.schemas import CommitGroupProposal
from commitcraft.snapshot import SnapshotEngine, SnapshotTarget


def slugify(text: str, max_length: int = 30) -> str:
    """Convert arbitrary text into a safe, clean git branch component."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_length:
        text = text[:max_length].rstrip("-")
    return text or "change"


@dataclass
class PreflightResult:
    """Outcome of isolated patch replay and tree verification."""

    ordered_groups: list[CommitGroupProposal]
    intermediate_trees: list[str]
    final_tree: str
    target_tree: str
    tree_equality: bool
    patch_replay_success: bool
    error_message: Optional[str] = None


@dataclass
class ExecutionResult:
    """Outcome of commit creation and branch installation."""

    created_commits: list[str]
    new_head: str
    old_head: str
    branch_ref: str
    final_tree: str
    ordered_groups: list[CommitGroupProposal]
    created_branches: dict[str, str] = field(default_factory=dict)


class PlanExecutor:
    """Executes preflight replay and guarded commit creation."""

    def __init__(
        self,
        repo: git.Repo,
        runner: GitRunner,
        snapshot_engine: SnapshotEngine,
    ):
        self.repo = repo
        self.runner = runner
        self.snapshot_engine = snapshot_engine
        self.recovery_mgr = RecoveryManager(Path(repo.git_dir))

    def preflight_replay(
        self,
        ordered_groups: list[CommitGroupProposal],
        inventory: list[ChangeUnit],
        snapshot: SnapshotTarget,
    ) -> PreflightResult:
        """Replay patches in an isolated temporary index and check tree equality against target snapshot."""
        unit_map = {u.id: u for u in inventory}
        intermediate_trees: list[str] = []

        with tempfile.TemporaryDirectory(prefix="commitcraft_preflight_") as tmp_dir_str:
            tmp_index = Path(tmp_dir_str) / "preflight_index"
            env = {"GIT_INDEX_FILE": str(tmp_index)}

            # Initialize isolated index to starting HEAD tree
            try:
                self.runner.read_tree(snapshot.head_tree, env_override=env)
            except Exception as e:
                return PreflightResult(
                    ordered_groups=ordered_groups,
                    intermediate_trees=[],
                    final_tree="",
                    target_tree=snapshot.target_tree,
                    tree_equality=False,
                    patch_replay_success=False,
                    error_message=f"Failed to initialize isolated index from HEAD tree: {e}",
                )

            # Apply groups sequentially in topological order
            for group in ordered_groups:
                for uid in group.unit_ids:
                    unit = unit_map.get(uid)
                    if not unit:
                        return PreflightResult(
                            ordered_groups=ordered_groups,
                            intermediate_trees=[],
                            final_tree="",
                            target_tree=snapshot.target_tree,
                            tree_equality=False,
                            patch_replay_success=False,
                            error_message=f"Unknown change unit '{uid}' in group '{group.id}'.",
                        )

                    try:
                        self.runner.apply_patch(
                            patch_text=unit.patch_text,
                            cached=True,
                            check_only=False,
                            env_override=env,
                        )
                    except Exception as e:
                        return PreflightResult(
                            ordered_groups=ordered_groups,
                            intermediate_trees=intermediate_trees,
                            final_tree="",
                            target_tree=snapshot.target_tree,
                            tree_equality=False,
                            patch_replay_success=False,
                            error_message=(
                                f"Patch application failed for unit {uid} ({unit.path}) "
                                f"in group {group.id}: {e}"
                            ),
                        )

                # Record cumulative intermediate tree for this group
                try:
                    tree_id = self.runner.write_tree(env_override=env)
                    intermediate_trees.append(tree_id)
                except Exception as e:
                    return PreflightResult(
                        ordered_groups=ordered_groups,
                        intermediate_trees=intermediate_trees,
                        final_tree="",
                        target_tree=snapshot.target_tree,
                        tree_equality=False,
                        patch_replay_success=False,
                        error_message=f"Failed to write intermediate tree for group {group.id}: {e}",
                    )

        final_tree = intermediate_trees[-1] if intermediate_trees else ""
        tree_equality = final_tree == snapshot.target_tree
        err_msg = None
        if not tree_equality:
            err_msg = (
                f"Target tree mismatch: preflight final tree ({final_tree[:8]}) != "
                f"expected snapshot target tree ({snapshot.target_tree[:8]})."
            )

        return PreflightResult(
            ordered_groups=ordered_groups,
            intermediate_trees=intermediate_trees,
            final_tree=final_tree,
            target_tree=snapshot.target_tree,
            tree_equality=tree_equality,
            patch_replay_success=True,
            error_message=err_msg,
        )

    def _verify_git_identity(self) -> None:
        """Verify Git author/committer identity exists before constructing commits."""
        import os
        name = self.runner.run(["config", "user.name"], check=False).stdout.strip()
        email = self.runner.run(["config", "user.email"], check=False).stdout.strip()

        name = name or os.environ.get("GIT_AUTHOR_NAME") or os.environ.get("GIT_COMMITTER_NAME")
        email = email or os.environ.get("GIT_AUTHOR_EMAIL") or os.environ.get("GIT_COMMITTER_EMAIL")

        if not name or not email:
            raise ExecutionError(
                "Git user identity (user.name and user.email) is not configured.",
                resolution="Run 'git config user.name \"Your Name\"' and 'git config user.email \"you@example.com\"'.",
            )

    @classmethod
    def generate_branch_name(
        cls,
        group: CommitGroupProposal,
        existing_branches: Optional[set[str]] = None,
    ) -> str:
        """Generate a clean, conventional git branch name for a commit group."""
        prefix = slugify(group.commit_type or "feature", max_length=15)
        title_slug = slugify(group.title or "change", max_length=30)

        if group.scope:
            scope_slug = slugify(group.scope, max_length=15)
            if title_slug.startswith(scope_slug):
                base_name = f"{prefix}/{title_slug}"
            else:
                base_name = f"{prefix}/{scope_slug}-{title_slug}"
        else:
            base_name = f"{prefix}/{title_slug}"

        candidate = base_name
        counter = 2
        while existing_branches and candidate in existing_branches:
            candidate = f"{base_name}-{counter}"
            counter += 1

        return candidate

    def execute(
        self,
        preflight: PreflightResult,
        snapshot: SnapshotTarget,
        approval_confirmed: bool = False,
        create_group_branches: bool = True,
    ) -> ExecutionResult:
        """Build commit chain, guarded update-ref, individual group branches, and index synchronization."""
        if not approval_confirmed:
            raise ExecutionError(
                "Execution aborted: deliberate user approval was not confirmed.",
                resolution="Review the plan and confirm approval before executing.",
            )

        if not preflight.tree_equality or not preflight.patch_replay_success:
            raise TreeMismatchError(
                f"Cannot execute plan: {preflight.error_message or 'Tree equality failed.'}",
                resolution="Revise group ordering or assignments until preflight succeeds.",
            )

        # 1. Verify Git author identity
        self._verify_git_identity()

        # 2. Revalidate snapshot (verify HEAD hasn't moved and working tree hasn't changed)
        self.snapshot_engine.revalidate_snapshot(snapshot)

        # 3. Construct commit objects via git commit-tree
        created_commits: list[str] = []
        created_branches: dict[str, str] = {}
        parent = snapshot.head_commit

        existing_branches: set[str] = set()
        if create_group_branches:
            try:
                branch_output = self.runner.run(
                    ["branch", "--list", "--format=%(refname:short)"], check=False
                ).stdout
                existing_branches = {b.strip() for b in branch_output.splitlines() if b.strip()}
            except Exception:
                pass

        for group, tree_id in zip(preflight.ordered_groups, preflight.intermediate_trees):
            commit_id = self.runner.commit_tree(
                tree_id=tree_id,
                parents=[parent],
                message=group.message,
            )
            created_commits.append(commit_id)
            parent = commit_id

            if create_group_branches:
                b_name = self.generate_branch_name(group, existing_branches)
                if b_name == snapshot.branch_name and len(preflight.ordered_groups) > 1:
                    b_name = f"{b_name}-2"

                if b_name != snapshot.branch_name:
                    try:
                        self.runner.run(["branch", "-f", b_name, commit_id])
                        created_branches[group.id] = b_name
                        existing_branches.add(b_name)
                    except Exception:
                        pass
                else:
                    created_branches[group.id] = b_name

        new_head = created_commits[-1]

        # 4. Guarded branch reference update
        try:
            self.runner.update_ref(
                ref_name=snapshot.branch_ref,
                new_commit_id=new_head,
                old_commit_id=snapshot.head_commit,
                reason=f"commitcraft: create {len(created_commits)} logical commits",
            )
        except Exception as e:
            raise BranchMovementError(
                f"Guarded branch update failed for {snapshot.branch_ref}: {e}",
                resolution="The branch was modified concurrently. Your commits were not installed.",
            ) from e

        # 5. Real index synchronization
        try:
            self.runner.run(["read-tree", "HEAD"])
        except Exception as e:
            # Branch moved, but index sync failed: record recovery state
            record = RecoveryRecord(
                branch_ref=snapshot.branch_ref,
                original_head=snapshot.head_commit,
                new_head=new_head,
                target_tree=snapshot.target_tree,
                created_commits=created_commits,
                failure_reason=str(e),
            )
            rec_file = self.recovery_mgr.save_record(record)
            raise IndexSyncError(
                f"Branch moved to {new_head[:8]} but real index could not be refreshed.\n"
                f"Recovery instructions saved to {rec_file}:\n{record.get_instructions()}",
                resolution="Run 'git read-tree HEAD' to safely synchronize your index.",
            ) from e

        # 6. Verify result
        current_head = self.runner.rev_parse("HEAD")
        current_tree = self.runner.rev_parse("HEAD^{tree}")
        if current_head != new_head or current_tree != snapshot.target_tree:
            raise ExecutionError(
                f"Post-execution verification failed (HEAD={current_head[:8]}, tree={current_tree[:8]}).",
                resolution="Check git status and git log.",
            )

        return ExecutionResult(
            created_commits=created_commits,
            new_head=new_head,
            old_head=snapshot.head_commit,
            branch_ref=snapshot.branch_ref,
            final_tree=current_tree,
            ordered_groups=preflight.ordered_groups,
            created_branches=created_branches,
        )
