"""Complete end-to-end integration and demonstration tests."""

import json
from pathlib import Path
import httpx
import pytest
import git

from commitcraft.diff_parser import DiffParser
from commitcraft.executor import PlanExecutor
from commitcraft.model_client import OllamaClient
from commitcraft.planner import SemanticPlanner
from commitcraft.pr_description import PRDescriptionGenerator
from commitcraft.repository import RepositoryInspector
from commitcraft.snapshot import SnapshotEngine


def test_end_to_end_full_pipeline(test_repo: git.Repo):
    """Execute complete end-to-end pipeline:

    1. Messy working tree:
       - Multi-hunk modifications in app.py (bug fix + refactor)
       - Related regression test in tests/test_auth.py
       - Documentation file in docs/arch.md
    2. Target snapshot capture in isolated index.
    3. Change-unit extraction with same-file hunk splitting.
    4. Mock Ollama client proposing Conventional Commits.
    5. Local plan validation and topological ordering.
    6. Isolated-index patch replay and target tree verification.
    7. Commit-tree object construction and guarded update-ref.
    8. Real index synchronization.
    9. PR description generation.
    """
    repo_dir = Path(test_repo.working_tree_dir)
    original_head = test_repo.head.commit.hexsha

    # 1. Setup initial tracked app.py
    app_file = repo_dir / "app.py"
    lines = [f"# Line {i}: normal code" for i in range(1, 45)]
    app_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    test_repo.index.add(["app.py"])
    test_repo.index.commit("chore: add initial app.py")
    starting_head = test_repo.head.commit.hexsha

    # 2. Introduce messy working tree changes:
    # 2a. Modify Line 2 (auth bug fix)
    lines[1] = "def authenticate(user, token): return token == 'secret-token'  # Auth fix"
    # 2b. Modify Line 40 (refactoring)
    lines[39] = "# Line 40: REFACTORED formatting helper"
    app_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 2c. Add related regression test
    test_dir = repo_dir / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "test_auth.py").write_text("def test_auth(): assert True\n", encoding="utf-8")

    # 2d. Add documentation file
    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "arch.md").write_text("# Architecture Overview\nSystem details.\n", encoding="utf-8")

    # 3. Repository inspection
    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    assert state.head_commit == starting_head

    # 4. Target snapshot capture
    snapshot_engine = SnapshotEngine(repo, runner, state)
    snapshot = snapshot_engine.capture_snapshot()
    assert snapshot.has_changes
    assert snapshot.target_tree != snapshot.head_tree

    # 5. Diff extraction & change-unit construction
    units = DiffParser.parse(snapshot.diff_text)
    # Must have 4 units: 2 hunks from app.py, 1 test file, 1 doc file
    assert len(units) == 4
    app_units = [u for u in units if u.path == "app.py"]
    assert len(app_units) == 2  # Proves same-file hunk splitting!

    auth_hunk = next(u for u in app_units if "Auth fix" in u.excerpt)
    refactor_hunk = next(u for u in app_units if "REFACTORED" in u.excerpt)
    test_unit = next(u for u in units if u.path == "tests/test_auth.py")
    doc_unit = next(u for u in units if u.path == "docs/arch.md")

    # 6. Mock Ollama service proposing semantic groups:
    # Group 1: Bug fix + regression test (related source & test in one commit!)
    # Group 2: Refactoring hunk from app.py
    # Group 3: Documentation
    mock_plan_payload = {
        "version": "1.0",
        "summary": "Fix authentication, refactor formatting, and add architecture documentation",
        "groups": [
            {
                "id": "G01",
                "unit_ids": [auth_hunk.id, test_unit.id],
                "title": "Auth bug fix and tests",
                "explanation": "Fix authentication logic and add regression test suite",
                "commit_type": "fix",
                "scope": "auth",
                "message": "fix(auth): validate token against active secret",
                "depends_on": [],
            },
            {
                "id": "G02",
                "unit_ids": [refactor_hunk.id],
                "title": "Refactor app formatting",
                "explanation": "Clean up bottom helper formatting in app.py",
                "commit_type": "refactor",
                "scope": "core",
                "message": "refactor(core): streamline formatting helpers",
                "depends_on": ["G01"],
            },
            {
                "id": "G03",
                "unit_ids": [doc_unit.id],
                "title": "Architecture docs",
                "explanation": "Add system architecture guide",
                "commit_type": "docs",
                "scope": "arch",
                "message": "docs(arch): add initial architecture guide",
                "depends_on": [],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps(mock_plan_payload)}},
        )

    transport = httpx.MockTransport(handler)
    mock_client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=mock_client)
    planner = SemanticPlanner(ollama)

    plan = planner.plan(units)
    assert len(plan.groups) == 3

    # 7. Preflight replay in isolated index
    executor = PlanExecutor(repo, runner, snapshot_engine)
    preflight = executor.preflight_replay(plan.groups, units, snapshot)
    assert preflight.patch_replay_success
    assert preflight.tree_equality
    assert len(preflight.intermediate_trees) == 3

    # 8. Execution with explicit user approval
    exec_res = executor.execute(preflight, snapshot, approval_confirmed=True)
    assert len(exec_res.created_commits) == 3
    assert exec_res.final_tree == snapshot.target_tree

    # 9. Verify Git history integrity
    commits = list(test_repo.iter_commits("HEAD", max_count=5))
    assert len(commits) >= 4
    # Check messages and parent linkage
    assert commits[0].hexsha == exec_res.created_commits[2]
    assert commits[0].message.strip() == "docs(arch): add initial architecture guide"

    assert commits[1].hexsha == exec_res.created_commits[1]
    assert commits[1].message.strip() == "refactor(core): streamline formatting helpers"

    assert commits[2].hexsha == exec_res.created_commits[0]
    assert commits[2].message.strip() == "fix(auth): validate token against active secret"
    assert commits[2].parents[0].hexsha == starting_head

    # 10. Verify working tree is clean and matches final tree
    assert test_repo.git.status("--short") == ""
    assert test_repo.head.commit.tree.hexsha == snapshot.target_tree

    # 11. Generate and verify individual PR descriptions
    prs = PRDescriptionGenerator.generate_individual_prs(
        plan, exec_res, units, branch_names=exec_res.created_branches
    )
    saved_files = PRDescriptionGenerator.save_individual_prs(
        prs, repo_root=Path(test_repo.working_tree_dir)
    )
    assert len(saved_files) == 3
    for f in saved_files:
        assert f.is_file()
    assert "fix(auth): validate token against active secret" in prs["G01"]
    assert "refactor(core): streamline formatting helpers" in prs["G02"]
    assert "docs(arch): add initial architecture guide" in prs["G03"]
    assert "test_auth.py" in prs["G01"]
