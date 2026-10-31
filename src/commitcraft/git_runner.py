"""Safe native Git subprocess runner."""

from pathlib import Path
import subprocess
from typing import Optional, Union
from commitcraft.errors import GitCommandError


class GitRunner:
    """Safe wrapper around native Git commands."""

    def __init__(self, repo_root: Path, timeout: float = 30.0):
        self.repo_root = Path(repo_root).resolve()
        self.timeout = timeout

    def run(
        self,
        args: list[str],
        env_override: Optional[dict[str, str]] = None,
        input_data: Optional[Union[bytes, str]] = None,
        check: bool = True,
        cwd: Optional[Path] = None,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a git command safely using argument vectors without a shell."""
        full_cmd = ["git", "--no-pager", "-C", str(cwd or self.repo_root)] + args

        # Standard clean environment for deterministic output
        import os
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_OPTIONAL_LOCKS"] = "0"

        if env_override:
            env.update(env_override)

        input_bytes: Optional[bytes] = None
        if input_data is not None:
            if isinstance(input_data, bytes):
                input_bytes = input_data
            else:
                input_bytes = str(input_data).encode("utf-8")

        timeout_sec = timeout if timeout is not None else self.timeout
        try:
            raw_result = subprocess.run(
                full_cmd,
                input=input_bytes,
                capture_output=True,
                check=False,
                timeout=timeout_sec,
                env=env,
            )
            stdout_str = raw_result.stdout.decode("utf-8", errors="replace") if raw_result.stdout else ""
            stderr_str = raw_result.stderr.decode("utf-8", errors="replace") if raw_result.stderr else ""
            result = subprocess.CompletedProcess(
                args=raw_result.args,
                returncode=raw_result.returncode,
                stdout=stdout_str,
                stderr=stderr_str,
            )
        except subprocess.TimeoutExpired as e:
            raise GitCommandError(
                command=args,
                exit_code=-1,
                stderr=f"Git command timed out after {self.timeout} seconds.",
                resolution="Check for repository locks or heavy file operations.",
            ) from e
        except FileNotFoundError as e:
            raise GitCommandError(
                command=args,
                exit_code=-1,
                stderr=f"Git executable not found in PATH: {e}",
                resolution="Install Git and ensure it is available in system PATH.",
            ) from e

        if check and result.returncode != 0:
            raise GitCommandError(
                command=args,
                exit_code=result.returncode,
                stderr=result.stderr,
                stdout=result.stdout,
            )

        return result

    def rev_parse(self, rev: str, env_override: Optional[dict[str, str]] = None) -> str:
        """Resolve a revision to an object ID."""
        res = self.run(["rev-parse", "--verify", rev], env_override=env_override)
        return res.stdout.strip()

    def get_symbolic_ref(self, ref: str = "HEAD") -> str:
        """Get symbolic reference name (e.g. refs/heads/main)."""
        res = self.run(["symbolic-ref", "-q", ref])
        return res.stdout.strip()

    def write_tree(self, env_override: Optional[dict[str, str]] = None) -> str:
        """Write index out to a tree object and return tree ID."""
        res = self.run(["write-tree"], env_override=env_override)
        return res.stdout.strip()

    def read_tree(self, tree_ish: str, env_override: Optional[dict[str, str]] = None) -> None:
        """Read a tree object into the index."""
        self.run(["read-tree", tree_ish], env_override=env_override)

    def commit_tree(
        self,
        tree_id: str,
        parents: list[str],
        message: str,
        env_override: Optional[dict[str, str]] = None,
    ) -> str:
        """Create a commit object from a tree ID and parent commit IDs."""
        args = ["commit-tree", tree_id, "-m", message]
        for p in parents:
            args.extend(["-p", p])
        res = self.run(args, env_override=env_override)
        return res.stdout.strip()

    def update_ref(
        self,
        ref_name: str,
        new_commit_id: str,
        old_commit_id: str,
        reason: str = "commitcraft: update branch",
        env_override: Optional[dict[str, str]] = None,
    ) -> None:
        """Update a branch reference guarded by the expected old commit ID."""
        self.run(
            ["update-ref", "-m", reason, ref_name, new_commit_id, old_commit_id],
            env_override=env_override,
        )

    def apply_patch(
        self,
        patch_text: str,
        cached: bool = True,
        check_only: bool = False,
        env_override: Optional[dict[str, str]] = None,
        whitespace: str = "nowarn",
    ) -> subprocess.CompletedProcess[str]:
        """Apply a unified diff patch to the index (cached) or test applicability."""
        args = ["apply", f"--whitespace={whitespace}", "--unidiff-zero"]
        if cached:
            args.append("--cached")
        if check_only:
            args.append("--check")
        args.append("-")

        return self.run(
            args,
            env_override=env_override,
            input_data=patch_text.encode("utf-8"),
            check=True,
        )

    def diff_tree(
        self,
        old_tree_or_commit: str,
        new_tree: str,
        env_override: Optional[dict[str, str]] = None,
    ) -> str:
        """Generate full unified diff between two trees."""
        args = [
            "diff-tree",
            "-p",
            "--binary",
            "--no-color",
            "--no-ext-diff",
            "--full-index",
            old_tree_or_commit,
            new_tree,
        ]
        res = self.run(args, env_override=env_override)
        return res.stdout

    def get_remotes(self) -> list[str]:
        """List configured Git remotes."""
        res = self.run(["remote"], check=False)
        return [r.strip() for r in res.stdout.splitlines() if r.strip()]

    def push(
        self,
        remote: str,
        branch_name: str,
        set_upstream: bool = True,
        force: bool = False,
        env_override: Optional[dict[str, str]] = None,
        timeout: Optional[float] = 60.0,
    ) -> subprocess.CompletedProcess[str]:
        """Push a branch to a remote repository."""
        args = ["push"]
        if set_upstream:
            args.append("-u")
        if force:
            args.append("--force")
        args.extend([remote, branch_name])
        return self.run(args, env_override=env_override, check=True, timeout=timeout)

