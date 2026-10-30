"""Tests for Typer CLI commands and options."""

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner
import git

from commitcraft.cli import app
from commitcraft.config import AppConfig
from commitcraft.errors import ModelUnavailableError
from commitcraft.model_client import OllamaClient
from commitcraft.planner import SemanticPlanner
from commitcraft.schemas import CommitGroupProposal, PlanProposal


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_cli_help(cli_runner: CliRunner):
    """Test that commitcraft --help displays usage and available commands."""
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Turn a messy Git working tree into logical, reviewable commits" in result.stdout
    assert "inspect" in result.stdout
    assert "split" in result.stdout
    assert "config" in result.stdout
    assert "hook" in result.stdout


def test_cli_inspect_clean_repo(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test commitcraft inspect on a clean repository with mocked healthy Ollama."""
    repo_dir = str(test_repo.working_tree_dir)

    # Mock Ollama health check to succeed
    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    result = cli_runner.invoke(app, ["inspect", "--repo", repo_dir])
    assert result.exit_code == 0
    assert "CommitCraft Diagnostic Inspection" in result.stdout
    assert "Active Branch:" in result.stdout
    assert "main" in result.stdout
    assert "Working Tree Changes" in result.stdout
    assert "Ollama Runtime Status" in result.stdout
    assert "Connected" in result.stdout
    assert "llama3.2:3b" in result.stdout


def test_cli_inspect_with_modified_files(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test commitcraft inspect displays staged, unstaged, and untracked files."""
    repo_dir = Path(test_repo.working_tree_dir)

    # 1. Staged file
    (repo_dir / "staged.py").write_text("a = 1\n", encoding="utf-8")
    test_repo.index.add(["staged.py"])

    # 2. Unstaged modification
    (repo_dir / "README.md").write_text("unstaged modification\n", encoding="utf-8")

    # 3. Untracked file
    (repo_dir / "untracked.txt").write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    result = cli_runner.invoke(app, ["inspect", "--repo", str(repo_dir)])
    assert result.exit_code == 0
    assert "staged.py" in result.stdout
    assert "README.md" in result.stdout
    assert "untracked.txt" in result.stdout


def test_cli_inspect_non_git_repo(temp_dir: Path, cli_runner: CliRunner):
    """Test commitcraft inspect on a non-Git directory fails with exit code 1."""
    result = cli_runner.invoke(app, ["inspect", "--repo", str(temp_dir)])
    assert result.exit_code == 1
    assert "Repository check failed" in result.stdout


def test_cli_inspect_ollama_unavailable(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test commitcraft inspect when Ollama is unavailable exits with code 1 and advice."""
    repo_dir = str(test_repo.working_tree_dir)

    def mock_fail(self):
        raise ModelUnavailableError(
            "Cannot connect to Ollama service.",
            resolution="Run 'ollama serve' in a separate terminal.",
        )

    monkeypatch.setattr(OllamaClient, "check_health", mock_fail)

    result = cli_runner.invoke(app, ["inspect", "--repo", repo_dir])
    assert result.exit_code == 1
    assert "Ollama unavailable" in result.stdout
    assert "ollama serve" in result.stdout


def test_cli_config_view(cli_runner: CliRunner):
    """Test viewing config via commitcraft config."""
    result = cli_runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Current Configuration" in result.stdout
    assert "Ollama URL" in result.stdout
    assert "llama3.2:3b" in result.stdout


def test_cli_config_update(temp_dir: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test updating config options via commitcraft config --url --timeout."""
    config_file = temp_dir / "custom_config.json"
    monkeypatch.setattr("commitcraft.config.get_default_config_path", lambda: config_file)

    result = cli_runner.invoke(app, ["config", "--url", "http://127.0.0.1:11434", "--timeout", "90.0"])
    assert result.exit_code == 0
    assert "Configuration saved" in result.stdout
    assert "90.0s" in result.stdout

    # Verify saved file
    assert config_file.is_file()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["ollama_base_url"] == "http://127.0.0.1:11434"
    assert data["read_timeout"] == 90.0


def test_cli_hook_install_and_remove(test_repo: git.Repo, cli_runner: CliRunner):
    """Test installing and removing advisory pre-commit hook via CLI."""
    repo_dir = str(test_repo.working_tree_dir)

    # Install hook
    install_res = cli_runner.invoke(app, ["hook", "install", "--repo", repo_dir])
    assert install_res.exit_code == 0
    assert "Advisory Git pre-commit hook installed" in install_res.stdout
    hook_file = Path(test_repo.git_dir) / "hooks" / "pre-commit"
    assert hook_file.is_file()

    # Remove hook
    remove_res = cli_runner.invoke(app, ["hook", "remove", "--repo", repo_dir])
    assert remove_res.exit_code == 0
    assert "Advisory Git pre-commit hook removed" in remove_res.stdout
    assert not hook_file.exists()

    # Remove again when already removed
    remove_res2 = cli_runner.invoke(app, ["hook", "remove", "--repo", repo_dir])
    assert remove_res2.exit_code == 0
    assert "No CommitCraft pre-commit hook was found" in remove_res2.stdout


def test_cli_split_clean_working_tree(test_repo: git.Repo, cli_runner: CliRunner):
    """Test commitcraft split on clean working tree exits with code 0."""
    result = cli_runner.invoke(app, ["split", "--repo", str(test_repo.working_tree_dir)])
    assert result.exit_code == 0
    assert "Working tree is clean. Nothing to commit or split." in result.stdout


def test_cli_split_auto_approve_execution(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test commitcraft split with --yes executes commits and generates PR description."""
    repo_dir = Path(test_repo.working_tree_dir)
    original_head = test_repo.head.commit.hexsha

    # Add changes to repo
    (repo_dir / "new_feature.py").write_text("def feat(): pass\n", encoding="utf-8")
    (repo_dir / "docs.md").write_text("# Documentation\n", encoding="utf-8")

    # Mock OllamaClient health check and SemanticPlanner.plan
    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    def mock_plan(self, inventory):
        feat_unit = next(u for u in inventory if "new_feature.py" in u.path)
        docs_unit = next(u for u in inventory if "docs.md" in u.path)
        return PlanProposal(
            summary="Add new feature and documentation",
            groups=[
                CommitGroupProposal(
                    id="G01",
                    unit_ids=[feat_unit.id],
                    title="Feature implementation",
                    explanation="New feature code",
                    commit_type="feat",
                    message="feat: add new feature module",
                    depends_on=[],
                ),
                CommitGroupProposal(
                    id="G02",
                    unit_ids=[docs_unit.id],
                    title="Documentation",
                    explanation="Project docs",
                    commit_type="docs",
                    message="docs: add documentation",
                    depends_on=["G01"],
                ),
            ],
        )

    monkeypatch.setattr(SemanticPlanner, "plan", mock_plan)

    result = cli_runner.invoke(app, ["split", "--repo", str(repo_dir), "--yes"])
    assert result.exit_code == 0
    assert "EXECUTION COMPLETE" in result.stdout
    assert "feat: add new feature module" in result.stdout
    assert "docs: add documentation" in result.stdout
    assert "PR Description generated and saved to" in result.stdout

    # Verify commits in repo
    assert test_repo.head.commit.hexsha != original_head
    commits = list(test_repo.iter_commits("HEAD", max_count=2))
    assert len(commits) == 2
    assert commits[0].message.strip() == "docs: add documentation"
    assert commits[1].message.strip() == "feat: add new feature module"


def test_cli_split_with_custom_pr_output(
    test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    """Test commitcraft split --pr-output saves PR markdown to custom destination."""
    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "fix.py").write_text("x = 42\n", encoding="utf-8")

    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    def mock_plan(self, inventory):
        return PlanProposal(
            summary="Bug fix",
            groups=[
                CommitGroupProposal(
                    id="G01",
                    unit_ids=[inventory[0].id],
                    title="Fix",
                    explanation="Fix bug",
                    commit_type="fix",
                    message="fix: resolve logic error",
                    depends_on=[],
                )
            ],
        )

    monkeypatch.setattr(SemanticPlanner, "plan", mock_plan)
    custom_pr_file = temp_dir / "my_custom_pr.md"

    result = cli_runner.invoke(
        app,
        ["split", "--repo", str(repo_dir), "--yes", "--pr-output", str(custom_pr_file)],
    )
    assert result.exit_code == 0
    assert custom_pr_file.is_file()
    content = custom_pr_file.read_text(encoding="utf-8")
    assert "# Pull Request Description" in content
    assert "fix: resolve logic error" in content


def test_cli_split_interactive_abort(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test interactive review menu abort choice ('0') exits safely without altering Git state."""
    repo_dir = Path(test_repo.working_tree_dir)
    original_head = test_repo.head.commit.hexsha
    (repo_dir / "sample.txt").write_text("sample content\n", encoding="utf-8")

    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    def mock_plan(self, inventory):
        return PlanProposal(
            groups=[
                CommitGroupProposal(
                    id="G01",
                    unit_ids=[inventory[0].id],
                    title="Sample",
                    explanation="Sample update",
                    commit_type="chore",
                    message="chore: update sample",
                )
            ]
        )

    monkeypatch.setattr(SemanticPlanner, "plan", mock_plan)

    # Send choice "0" (Abort)
    result = cli_runner.invoke(app, ["split", "--repo", str(repo_dir)], input="0\n")
    assert result.exit_code == 0
    assert "Operation aborted by user" in result.stdout
    # Head and working tree must be untouched
    assert test_repo.head.commit.hexsha == original_head


def test_cli_version_flag_and_command(cli_runner: CliRunner):
    """Test --version and version command outputs."""
    res_flag = cli_runner.invoke(app, ["--version"])
    assert res_flag.exit_code == 0
    assert "CommitCraft Version" in res_flag.stdout
    assert "0.1.0" in res_flag.stdout

    res_cmd = cli_runner.invoke(app, ["version"])
    assert res_cmd.exit_code == 0
    assert "CommitCraft Version" in res_cmd.stdout
    assert "llama3.2:3b" in res_cmd.stdout


def test_cli_split_dry_run(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test commitcraft split --dry-run verifies tree and prints preview without writing commits."""
    repo_dir = Path(test_repo.working_tree_dir)
    original_head = test_repo.head.commit.hexsha
    (repo_dir / "dry_run_test.py").write_text("x = 100\n", encoding="utf-8")

    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    def mock_plan(self, inventory):
        return PlanProposal(
            groups=[
                CommitGroupProposal(
                    id="G01",
                    unit_ids=[inventory[0].id],
                    title="Dry run change",
                    explanation="Dry run test",
                    commit_type="feat",
                    message="feat: dry run change",
                )
            ]
        )

    monkeypatch.setattr(SemanticPlanner, "plan", mock_plan)

    result = cli_runner.invoke(app, ["split", "--repo", str(repo_dir), "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN COMPLETE" in result.stdout
    assert "tree equality verified" in result.stdout
    assert "PR Description Preview" in result.stdout
    # Head must remain untouched!
    assert test_repo.head.commit.hexsha == original_head


def test_cli_split_interactive_letter_shortcut_abort(test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Test typing 'q' (letter shortcut for abort) cleanly cancels operation."""
    repo_dir = Path(test_repo.working_tree_dir)
    original_head = test_repo.head.commit.hexsha
    (repo_dir / "shortcut_test.txt").write_text("shortcut\n", encoding="utf-8")

    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    def mock_plan(self, inventory):
        return PlanProposal(
            groups=[
                CommitGroupProposal(
                    id="G01",
                    unit_ids=[inventory[0].id],
                    title="Shortcut",
                    explanation="Shortcut",
                    commit_type="chore",
                    message="chore: test shortcut",
                )
            ]
        )

    monkeypatch.setattr(SemanticPlanner, "plan", mock_plan)

    result = cli_runner.invoke(app, ["split", "--repo", str(repo_dir)], input="q\n")
    assert result.exit_code == 0
    assert "Operation aborted by user" in result.stdout
    assert test_repo.head.commit.hexsha == original_head


def test_cli_split_creates_individual_prs_and_branches(
    test_repo: git.Repo, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """Test split creates individual PR files in .commit_craft/prs/ and dedicated branches for each group."""
    repo_dir = Path(test_repo.working_tree_dir)
    (repo_dir / "service.py").write_text("service = 1\n", encoding="utf-8")
    (repo_dir / "test_service.py").write_text("assert service == 1\n", encoding="utf-8")

    monkeypatch.setattr(OllamaClient, "check_health", lambda self: None)

    def mock_plan(self, inventory):
        svc_u = next(u for u in inventory if "service.py" == u.path)
        test_u = next(u for u in inventory if "test_service.py" == u.path)
        return PlanProposal(
            groups=[
                CommitGroupProposal(
                    id="G01",
                    unit_ids=[svc_u.id],
                    title="Service logic",
                    explanation="Add core service",
                    commit_type="feat",
                    scope="service",
                    message="feat(service): add core service",
                ),
                CommitGroupProposal(
                    id="G02",
                    unit_ids=[test_u.id],
                    title="Service tests",
                    explanation="Add test coverage",
                    commit_type="test",
                    scope="service",
                    message="test(service): add test coverage",
                    depends_on=["G01"],
                ),
            ]
        )

    monkeypatch.setattr(SemanticPlanner, "plan", mock_plan)

    result = cli_runner.invoke(app, ["split", "--repo", str(repo_dir), "--yes"])
    assert result.exit_code == 0
    assert "Individual Git branches created for PR submission" in result.stdout
    assert "PR_G01.md" in result.stdout
    assert "PR_G02.md" in result.stdout

    prs_dir = repo_dir / ".commit_craft" / "prs"
    assert (prs_dir / "PR_G01.md").is_file()
    assert (prs_dir / "PR_G02.md").is_file()

    pr1_text = (prs_dir / "PR_G01.md").read_text(encoding="utf-8")
    assert "# Pull Request Description: Service logic" in pr1_text
    assert "feat(service): add core service" in pr1_text

    pr2_text = (prs_dir / "PR_G02.md").read_text(encoding="utf-8")
    assert "# Pull Request Description: Service tests" in pr2_text
    assert "test(service): add test coverage" in pr2_text
    assert "Prerequisites" in pr2_text


