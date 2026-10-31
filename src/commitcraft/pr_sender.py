"""Push branches and submit GitHub pull requests via GitHub CLI (gh)."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional

from commitcraft.errors import PRSubmissionError
from commitcraft.git_runner import GitRunner
from commitcraft.schemas import CommitGroupProposal


@dataclass
class PRSubmissionResult:
    """Outcome of attempting to push and open a pull request for a commit group."""

    group_id: str
    branch_name: str
    title: str
    pushed: bool = False
    pr_created: bool = False
    pr_url: Optional[str] = None
    error_message: Optional[str] = None


class PRSender:
    """Handles pushing individual branches to remote and creating pull requests via gh."""

    def __init__(self, repo_root: Path, runner: GitRunner):
        self.repo_root = Path(repo_root).resolve()
        self.runner = runner

    @classmethod
    def is_gh_available(cls) -> bool:
        """Check if the GitHub CLI ('gh') executable is available on PATH."""
        return shutil.which("gh") is not None

    def get_remote(self, preferred: str = "origin") -> Optional[str]:
        """Get the Git remote name to push to (defaults to 'origin' if present)."""
        remotes = self.runner.get_remotes()
        if not remotes:
            return None
        if preferred in remotes:
            return preferred
        return remotes[0]

    def push_branch(self, branch_name: str, remote: Optional[str] = None) -> bool:
        """Push a branch to the specified remote with upstream tracking."""
        target_remote = remote or self.get_remote()
        if not target_remote:
            raise PRSubmissionError(
                "No Git remote found in repository.",
                resolution="Configure a remote with 'git remote add origin <url>'.",
            )
        self.runner.push(remote=target_remote, branch_name=branch_name, set_upstream=True)
        return True

    def create_pr(
        self,
        branch_name: str,
        base_branch: str,
        title: str,
        body_file: Optional[Path] = None,
        body: Optional[str] = None,
        timeout: float = 60.0,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Create a pull request using GitHub CLI ('gh pr create').

        Returns:
            (success, pr_url, error_message)
        """
        if not self.is_gh_available():
            return False, None, "GitHub CLI ('gh') is not installed or not found in PATH."

        cmd = [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            branch_name,
            "--title",
            title,
        ]

        if body_file and Path(body_file).is_file():
            cmd.extend(["--body-file", str(body_file)])
        elif body:
            cmd.extend(["--body", body])

        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=os.environ,
            )
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()

            if res.returncode == 0:
                # gh pr create prints the URL of the created PR on stdout
                pr_url = stdout.splitlines()[-1] if stdout else None
                return True, pr_url, None
            else:
                err_msg = stderr or stdout or f"gh pr create failed with exit code {res.returncode}"
                return False, None, err_msg
        except subprocess.TimeoutExpired:
            return False, None, f"Timed out waiting for GitHub CLI ('gh pr create') after {timeout} seconds."
        except Exception as e:
            return False, None, str(e)

    def push_and_create_prs(
        self,
        groups: list[CommitGroupProposal],
        created_branches: dict[str, str],
        base_branch: str,
        remote: Optional[str] = None,
        pr_paths: Optional[dict[str, Path]] = None,
        pr_bodies: Optional[dict[str, str]] = None,
    ) -> list[PRSubmissionResult]:
        """Push branches to remote and create PRs for each commit group."""
        target_remote = remote or self.get_remote()
        results: list[PRSubmissionResult] = []

        if not target_remote:
            raise PRSubmissionError(
                "No Git remote found in repository.",
                resolution="Configure a remote with 'git remote add origin <url>'.",
            )

        for grp in groups:
            b_name = created_branches.get(grp.id)
            if not b_name:
                continue

            if b_name == base_branch:
                results.append(
                    PRSubmissionResult(
                        group_id=grp.id,
                        branch_name=b_name,
                        title=grp.message,
                        pushed=False,
                        pr_created=False,
                        error_message=f"Branch '{b_name}' is the base branch.",
                    )
                )
                continue

            # 1. Push branch to remote
            pushed = False
            try:
                self.push_branch(branch_name=b_name, remote=target_remote)
                pushed = True
            except Exception as e:
                results.append(
                    PRSubmissionResult(
                        group_id=grp.id,
                        branch_name=b_name,
                        title=grp.message,
                        pushed=False,
                        pr_created=False,
                        error_message=f"Failed to push branch: {e}",
                    )
                )
                continue

            # 2. Create PR via gh
            b_file = pr_paths.get(grp.id) if pr_paths else None
            b_text = pr_bodies.get(grp.id) if pr_bodies else None
            success, pr_url, error = self.create_pr(
                branch_name=b_name,
                base_branch=base_branch,
                title=grp.message,
                body_file=b_file,
                body=b_text,
            )

            results.append(
                PRSubmissionResult(
                    group_id=grp.id,
                    branch_name=b_name,
                    title=grp.message,
                    pushed=pushed,
                    pr_created=success,
                    pr_url=pr_url,
                    error_message=error,
                )
            )

        return results
