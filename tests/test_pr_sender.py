"""Tests for PRSender module (branch push and GitHub PR creation via gh)."""

from pathlib import Path
import subprocess
import git
import pytest

from commitcraft.errors import PRSubmissionError
from commitcraft.git_runner import GitRunner
from commitcraft.pr_sender import PRSender, PRSubmissionResult
from commitcraft.schemas import CommitGroupProposal


def test_pr_sender_is_gh_available(monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo):
    """Test is_gh_available checks for gh in PATH."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh" if cmd == "gh" else None)
    assert sender.is_gh_available() is True

    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert sender.is_gh_available() is False


def test_pr_sender_get_remote(test_repo: git.Repo, temp_dir: Path):
    """Test get_remote resolution logic."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    # No remotes
    assert sender.get_remote() is None

    # Add upstream
    bare1 = temp_dir / "bare1.git"
    git.Repo.init(bare1, bare=True)
    test_repo.create_remote("upstream", str(bare1))
    assert sender.get_remote() == "upstream"

    # Add origin: origin should be preferred
    bare2 = temp_dir / "bare2.git"
    git.Repo.init(bare2, bare=True)
    test_repo.create_remote("origin", str(bare2))
    assert sender.get_remote() == "origin"


def test_pr_sender_push_branch_success(test_repo: git.Repo, temp_dir: Path):
    """Test push_branch pushes successfully to configured remote."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    bare = temp_dir / "remote.git"
    git.Repo.init(bare, bare=True)
    test_repo.create_remote("origin", str(bare))

    runner.run(["branch", "feat/my-feature"])
    assert sender.push_branch("feat/my-feature") is True

    bare_repo = git.Repo(bare)
    assert "feat/my-feature" in [h.name for h in bare_repo.heads]


def test_pr_sender_push_branch_no_remote_raises(test_repo: git.Repo):
    """Test push_branch raises PRSubmissionError if no remote exists."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    with pytest.raises(PRSubmissionError) as exc_info:
        sender.push_branch("feat/my-feature")
    assert "No Git remote found" in str(exc_info.value)


def test_pr_sender_create_pr_gh_not_available(monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo):
    """Test create_pr returns error tuple when gh is missing."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    monkeypatch.setattr("shutil.which", lambda cmd: None)
    success, pr_url, err = sender.create_pr(
        branch_name="feat/foo",
        base_branch="main",
        title="feat: add foo",
    )
    assert success is False
    assert pr_url is None
    assert "not installed or not found in PATH" in err


def test_pr_sender_create_pr_success(monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo, temp_dir: Path):
    """Test create_pr calls gh pr create and parses resulting URL."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh")

    pr_md = temp_dir / "PR_G01.md"
    pr_md.write_text("# PR Title\nBody text\n", encoding="utf-8")

    captured_cmds = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="https://github.com/Team-NoName-Devs/CommitCraft/pull/42\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    success, pr_url, err = sender.create_pr(
        branch_name="feat/user-auth",
        base_branch="main",
        title="feat(auth): implement user authentication",
        body_file=pr_md,
    )

    assert success is True
    assert pr_url == "https://github.com/Team-NoName-Devs/CommitCraft/pull/42"
    assert err is None

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert cmd[0] == "gh"
    assert cmd[1:3] == ["pr", "create"]
    assert "--base" in cmd and "main" in cmd
    assert "--head" in cmd and "feat/user-auth" in cmd
    assert "--title" in cmd and "feat(auth): implement user authentication" in cmd
    assert "--body-file" in cmd and str(pr_md) in cmd


def test_pr_sender_create_pr_failure(monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo):
    """Test create_pr handles gh failure and reports error message."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh")

    def mock_subprocess_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="GraphQL: a pull request for branch 'feat/foo' into branch 'main' already exists: https://github.com/foo/bar/pull/1\n",
        )

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    success, pr_url, err = sender.create_pr(
        branch_name="feat/foo",
        base_branch="main",
        title="feat: foo",
    )

    assert success is False
    assert pr_url is None
    assert "already exists" in err


def test_pr_sender_create_pr_timeout(monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo):
    """Test create_pr handles TimeoutExpired gracefully."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh")

    def mock_subprocess_run(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=60.0)

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    success, pr_url, err = sender.create_pr(
        branch_name="feat/foo",
        base_branch="main",
        title="feat: foo",
    )
    assert success is False
    assert "Timed out waiting for GitHub CLI" in err


def test_pr_sender_push_and_create_prs(monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo, temp_dir: Path):
    """Test push_and_create_prs high-level orchestration."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    bare = temp_dir / "remote.git"
    git.Repo.init(bare, bare=True)
    test_repo.create_remote("origin", str(bare))

    runner.run(["branch", "feat/auth"])
    runner.run(["branch", "docs/auth"])

    groups = [
        CommitGroupProposal(
            id="G01",
            unit_ids=["U001"],
            title="Authentication",
            explanation="Auth logic",
            commit_type="feat",
            message="feat: add authentication",
            depends_on=[],
        ),
        CommitGroupProposal(
            id="G02",
            unit_ids=["U002"],
            title="Documentation",
            explanation="Docs for auth",
            commit_type="docs",
            message="docs: add auth docs",
            depends_on=["G01"],
        ),
        CommitGroupProposal(
            id="G03",
            unit_ids=["U003"],
            title="Base update",
            explanation="Direct main change",
            commit_type="chore",
            message="chore: update main",
            depends_on=[],
        ),
    ]

    created_branches = {
        "G01": "feat/auth",
        "G02": "docs/auth",
        "G03": "main",  # Should be skipped because it is base branch
    }

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh")

    orig_run = subprocess.run
    created_prs = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            head = cmd[cmd.index("--head") + 1]
            created_prs.append(head)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=f"https://github.com/Team-NoName-Devs/CommitCraft/pull/{len(created_prs)}\n",
                stderr="",
            )
        return orig_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    results = sender.push_and_create_prs(
        groups=groups,
        created_branches=created_branches,
        base_branch="main",
    )

    assert len(results) == 3

    # G01
    assert results[0].group_id == "G01"
    assert results[0].pushed is True
    assert results[0].pr_created is True
    assert "pull/1" in results[0].pr_url

    # G02
    assert results[1].group_id == "G02"
    assert results[1].pushed is True
    assert results[1].pr_created is True
    assert "pull/2" in results[1].pr_url

    # G03 (base branch)
    assert results[2].group_id == "G03"
    assert results[2].pushed is False
    assert results[2].pr_created is False
    assert "is the base branch" in results[2].error_message


def test_pr_sender_create_pr_strips_title_and_body_instructions(
    monkeypatch: pytest.MonkeyPatch, test_repo: git.Repo, temp_dir: Path
):
    """Test create_pr removes PR title instructions and body wrappers before sending via gh."""
    runner = GitRunner(Path(test_repo.working_tree_dir))
    sender = PRSender(Path(test_repo.working_tree_dir), runner)

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh")

    raw_markdown = (
        "# Pull Request Description: feat: add widget\n\n"
        "## PR Title (Conventional Commit)\n\n"
        "```text\nfeat: add widget\n```\n\n"
        "## PR Body (Conventional Commit Style)\n\n"
        "### Description\n\n"
        "Core widget logic\n\n"
        "## Key Changes\n\n"
        "- Widget file\n\n"
        "---\n"
        "*Generated automatically by [CommitCraft](https://github.com/Team-NoName-Devs/CommitCraft).* "
        "Please review and edit before opening your PR.\n"
    )

    pr_file = temp_dir / "PR_G01.md"
    pr_file.write_text(raw_markdown, encoding="utf-8")

    def mock_subprocess_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="https://github.com/Team-NoName-Devs/CommitCraft/pull/99\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    success, pr_url, err = sender.create_pr(
        branch_name="feat/widget",
        base_branch="main",
        title="feat: add widget",
        body_file=pr_file,
    )

    assert success is True
    assert pr_url == "https://github.com/Team-NoName-Devs/CommitCraft/pull/99"

    # Verify instructions were removed from the file used by gh
    cleaned_file_content = pr_file.read_text(encoding="utf-8")
    assert "# Pull Request Description" not in cleaned_file_content
    assert "## PR Title (Conventional Commit)" not in cleaned_file_content
    assert "## PR Body (Conventional Commit Style)" not in cleaned_file_content
    assert "Please review and edit before opening your PR" not in cleaned_file_content
    assert "## Description\n\nCore widget logic" in cleaned_file_content

