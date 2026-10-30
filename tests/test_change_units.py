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
