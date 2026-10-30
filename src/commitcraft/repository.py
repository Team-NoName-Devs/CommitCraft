"""Repository inspection and state validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import git

from commitcraft.errors import (
    RepositoryError,
    UnsupportedRepositoryStateError,
)
from commitcraft.git_runner import GitRunner


@dataclass
class RepositoryState:
    """Snapshot of discovered repository metadata."""

    root_dir: Path
    git_dir: Path
    branch_name: str
    branch_ref: str
    head_commit: str
    is_bare: bool
    staged_files: list[str]
    unstaged_files: list[str]
    untracked_files: list[str]


class RepositoryInspector:
    """Inspects Git repository and strictly validates supported state."""

    def __init__(self, target_path: Optional[Path] = None):
        self.target_path = Path(target_path or Path.cwd()).resolve()

    def discover_root(self) -> Path:
        """Find repository root directory or raise RepositoryError."""
        try:
            repo = git.Repo(self.target_path, search_parent_directories=True)
            if repo.working_tree_dir is None:
                raise UnsupportedRepositoryStateError(
                    "Bare Git repository detected. CommitCraft requires a working tree.",
                    resolution="Run CommitCraft within a standard non-bare Git repository.",
                )
            return Path(repo.working_tree_dir).resolve()
        except git.InvalidGitRepositoryError as e:
            raise RepositoryError(
                f"Directory '{self.target_path}' is not a Git repository.",
                resolution="Initialize a Git repository with 'git init' or change to a valid repo.",
            ) from e
        except git.NoSuchPathError as e:
            raise RepositoryError(
                f"Path '{self.target_path}' does not exist.",
                resolution="Specify a valid path to an existing Git repository.",
            ) from e

    def inspect(self) -> tuple[git.Repo, GitRunner, RepositoryState]:
        """Validate and inspect repository state, rejecting any unsupported conditions."""
        root = self.discover_root()
        repo = git.Repo(root)
        runner = GitRunner(root)

        # 1. Bare repository check
        if repo.bare:
            raise UnsupportedRepositoryStateError(
                "Bare repository is not supported.",
                resolution="Clone or work within a non-bare repository.",
            )

        git_dir = Path(repo.git_dir).resolve()

        # 2. Check for in-progress operations (merge, rebase, cherry-pick, revert, bisect)
        in_progress_markers = [
            (git_dir / "MERGE_HEAD", "Merge in progress"),
            (git_dir / "rebase-merge", "Rebase in progress"),
            (git_dir / "rebase-apply", "Rebase in progress"),
            (git_dir / "CHERRY_PICK_HEAD", "Cherry-pick in progress"),
            (git_dir / "REVERT_HEAD", "Revert in progress"),
            (git_dir / "BISECT_LOG", "Git bisect in progress"),
        ]
        for marker_path, desc in in_progress_markers:
            if marker_path.exists():
                raise UnsupportedRepositoryStateError(
                    f"Unsupported repository state: {desc}.",
                    resolution="Complete or abort the current operation before running CommitCraft.",
                )

        # 3. Check for initial commit (HEAD must exist)
        try:
            head_commit = str(repo.head.commit.hexsha)
        except (ValueError, git.GitCommandError) as e:
            raise UnsupportedRepositoryStateError(
                "Repository has no initial commit.",
                resolution="Create an initial commit before running CommitCraft.",
            ) from e

        # 4. Check for detached HEAD
        if repo.head.is_detached:
            raise UnsupportedRepositoryStateError(
                f"Repository is in a detached HEAD state (at {head_commit[:8]}).",
                resolution="Checkout or create a named branch (e.g. 'git checkout -b feature-branch').",
            )

        branch_name = repo.active_branch.name
        branch_ref = repo.active_branch.path

        # 5. Check for unmerged index entries (conflicts)
        index = repo.index
        if index.unmerged_blobs():
            raise UnsupportedRepositoryStateError(
                "Repository contains unmerged index entries (conflicts).",
                resolution="Resolve all merge conflicts and stage them before running CommitCraft.",
            )

        # 6. Check for unsupported sparse checkout
        sparse_file = git_dir / "info" / "sparse-checkout"
        if sparse_file.exists():
            raise UnsupportedRepositoryStateError(
                "Sparse checkout repository detected.",
                resolution="CommitCraft does not currently support sparse checkout repositories.",
            )

        # 7. Collect working changes
        # Staged vs HEAD
        diff_head = index.diff(repo.head.commit)
        staged_files = [d.a_path or d.b_path for d in diff_head if (d.a_path or d.b_path)]

        # Unstaged working tree vs Index
        diff_work = index.diff(None)
        unstaged_files = [d.a_path or d.b_path for d in diff_work if (d.a_path or d.b_path)]

        # Untracked
        untracked_files = repo.untracked_files

        state = RepositoryState(
            root_dir=root,
            git_dir=git_dir,
            branch_name=branch_name,
            branch_ref=branch_ref,
            head_commit=head_commit,
            is_bare=False,
            staged_files=staged_files,
            unstaged_files=unstaged_files,
            untracked_files=untracked_files,
        )

        return repo, runner, state
