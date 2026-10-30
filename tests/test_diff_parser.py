"""Tests for diff parsing and same-file hunk splitting."""

from pathlib import Path
import git
import pytest

from commitcraft.diff_parser import DiffParser
from commitcraft.git_runner import GitRunner
from commitcraft.repository import RepositoryInspector
from commitcraft.snapshot import SnapshotEngine


def test_single_hunk_file_parsing(test_repo: git.Repo):
    """Test parsing a single hunk modification in one file."""
    repo_dir = Path(test_repo.working_tree_dir)
    readme = repo_dir / "README.md"
    readme.write_text("# Updated Title\nInitial content.\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)
    snapshot = engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 1
    unit = units[0]
    assert unit.id == "U001"
    assert unit.path == "README.md"
    assert unit.kind == "modify"
    assert not unit.is_splittable
    assert "Updated Title" in unit.excerpt


def test_multiple_hunks_same_file_splitting(test_repo: git.Repo):
    """Test same-file hunk splitting on distant hunks in one text file."""
    repo_dir = Path(test_repo.working_tree_dir)
    test_file = repo_dir / "code.py"
    # Create 40 lines
    lines = [f"# Line {i}" for i in range(1, 45)]
    test_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    test_repo.index.add(["code.py"])
    test_repo.index.commit("chore: add code.py")

    # Mutate Line 2 (hunk 1) and Line 40 (hunk 2)
    lines[1] = "# Line 2 MODIFIED"
    lines[39] = "# Line 40 MODIFIED"
    test_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)
    snapshot = engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 2
    u1, u2 = units[0], units[1]
    assert u1.id == "U001"
    assert u2.id == "U002"
    assert u1.path == "code.py"
    assert u2.path == "code.py"
    assert u1.is_splittable
    assert u2.is_splittable
    assert "Line 2 MODIFIED" in u1.patch_text
    assert "Line 40 MODIFIED" in u2.patch_text


def test_file_addition_and_deletion(test_repo: git.Repo):
    """Test file addition and deletion units."""
    repo_dir = Path(test_repo.working_tree_dir)

    # Delete README.md
    (repo_dir / "README.md").unlink()

    # Add new file
    (repo_dir / "new_module.py").write_text("def hello(): pass\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)
    snapshot = engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 2
    kinds = {u.kind for u in units}
    assert kinds == {"add", "delete"}
    for u in units:
        assert not u.is_splittable


def test_file_path_with_spaces(test_repo: git.Repo):
    """Test files with spaces in their path."""
    repo_dir = Path(test_repo.working_tree_dir)
    space_file = repo_dir / "my special file.txt"
    space_file.write_text("some content\n", encoding="utf-8")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)
    snapshot = engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 1
    assert units[0].path == "my special file.txt"


def test_empty_diff_parsing():
    """Test parsing empty diff string."""
    units = DiffParser.parse("")
    assert units == []
    units = DiffParser.parse("   ")
    assert units == []


def test_make_excerpt_truncation():
    """Test that make_excerpt properly truncates long excerpts by lines and characters."""
    from commitcraft.diff_parser import make_excerpt

    # 1. More than 10 meaningful lines
    long_diff = "\n".join([f"+line {i}" for i in range(25)])
    excerpt = make_excerpt(long_diff, max_lines=5)
    assert len(excerpt.splitlines()) == 5

    # 2. Character truncation (> 600 chars)
    very_long_line = "+" + "A" * 700
    char_excerpt = make_excerpt(very_long_line, max_chars=100)
    assert "... [truncated]" in char_excerpt
    assert len(char_excerpt) <= 120


def test_binary_file_diff_parsing(test_repo: git.Repo):
    """Test parsing binary file diff into a non-splittable binary ChangeUnit."""
    repo_dir = Path(test_repo.working_tree_dir)
    bin_file = repo_dir / "image.png"
    # Write arbitrary non-text bytes
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01")

    inspector = RepositoryInspector(repo_dir)
    repo, runner, state = inspector.inspect()
    engine = SnapshotEngine(repo, runner, state)
    snapshot = engine.capture_snapshot()

    units = DiffParser.parse(snapshot.diff_text)
    assert len(units) == 1
    unit = units[0]
    assert unit.path == "image.png"
    assert unit.is_binary is True
    assert unit.kind == "binary"
    assert not unit.is_splittable
    assert "[Binary content]" in unit.excerpt


def test_infer_scope_hint():
    """Test inferring conventional commit scopes from various file paths."""
    from commitcraft.diff_parser import infer_scope_hint

    assert infer_scope_hint("src/commitcraft/diff_parser.py") == "diff-parser"
    assert infer_scope_hint("src/commitcraft/cli.py") == "cli"
    assert infer_scope_hint("tests/test_planner.py") == "planner"
    assert infer_scope_hint("README.md") == "docs"
    assert infer_scope_hint("docs/index.md") == "docs"
    assert infer_scope_hint("pyproject.toml") == "build"
    assert infer_scope_hint(".github/workflows/ci.yml") == "ci"
    assert infer_scope_hint(".gitignore") == "config"


def test_extract_context_info():
    """Test extracting symbol context from diff hunk headers."""
    from commitcraft.diff_parser import extract_context_info

    # 1. Extracted from section_header
    assert extract_context_info(None, "def calculate_total():") == "def calculate_total():"

    # 2. Extracted from @@ ... @@ header line
    header = "@@ -20,6 +20,10 @@ class OrderProcessor:"
    assert extract_context_info(header) == "class OrderProcessor:"

    # 3. None when no symbol present
    assert extract_context_info("@@ -1,5 +1,5 @@") is None
    assert extract_context_info(None, None) is None

