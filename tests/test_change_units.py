"""Tests for ChangeUnit data model and methods."""

from commitcraft.change_units import ChangeUnit


def test_change_unit_to_prompt_dict():
    """Test serializing ChangeUnit to compact prompt dictionary."""
    unit = ChangeUnit(
        id="U001",
        path="src/app.py",
        kind="modify",
        summary="Update app.py",
        hunk_header="@@ -10,4 +10,5 @@",
        added_lines=3,
        removed_lines=1,
        is_binary=False,
        is_splittable=True,
        excerpt="+new_line",
        patch_text="diff --git ...",
    )

    pdict = unit.to_prompt_dict()
    assert pdict["id"] == "U001"
    assert pdict["path"] == "src/app.py"
    assert pdict["kind"] == "modify"
    assert pdict["added_lines"] == 3
    assert pdict["removed_lines"] == 1
    assert "patch_text" not in pdict  # Patch text must not be in prompt dict


def test_binary_change_unit_to_prompt_dict():
    """Test serializing binary ChangeUnit to prompt dictionary."""
    unit = ChangeUnit(
        id="U002",
        path="assets/logo.png",
        kind="binary",
        summary="Binary change in logo.png",
        hunk_header=None,
        added_lines=0,
        removed_lines=0,
        is_binary=True,
        is_splittable=False,
        excerpt="[Binary content]",
        patch_text="GIT binary patch ...",
    )
    pdict = unit.to_prompt_dict()
    assert pdict["id"] == "U002"
    assert pdict["path"] == "assets/logo.png"
    assert pdict["kind"] == "binary"
    assert pdict["is_binary"] is True
    assert pdict["hunk_header"] == ""
    assert pdict["excerpt"] == "[Binary content]"
    assert "patch_text" not in pdict


def test_change_unit_empty_hunk_header():
    """Test hunk_header falls back to empty string when None."""
    unit = ChangeUnit(
        id="U003",
        path="file.txt",
        kind="add",
        summary="Add file.txt",
        hunk_header=None,
        added_lines=5,
        removed_lines=0,
        is_binary=False,
        is_splittable=False,
        excerpt="+content",
        patch_text="",
    )
    pdict = unit.to_prompt_dict()
    assert pdict["hunk_header"] == ""


def test_change_unit_with_scope_and_context():
    """Test ChangeUnit serializes scope_hint and context_info when provided."""
    unit = ChangeUnit(
        id="U004",
        path="src/commitcraft/planner.py",
        kind="modify",
        summary="Update planner.py in plan",
        hunk_header="@@ -50,5 +50,10 @@ def plan():",
        added_lines=10,
        removed_lines=2,
        is_binary=False,
        is_splittable=True,
        excerpt="+plan()",
        patch_text="",
        scope_hint="planner",
        context_info="def plan():",
    )
    pdict = unit.to_prompt_dict()
    assert pdict["scope_hint"] == "planner"
    assert pdict["context_info"] == "def plan():"

