"""Diff parsing and change unit extraction."""

from typing import Optional
from unidiff import PatchSet
from commitcraft.change_units import ChangeUnit


def make_excerpt(text: str, max_lines: int = 10, max_chars: int = 600) -> str:
    """Create a bounded excerpt from patch text focusing on added and removed lines."""
    lines = text.strip().splitlines()
    meaningful = [line for line in lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    if not meaningful:
        meaningful = lines[:max_lines]
    else:
        meaningful = meaningful[:max_lines]

    excerpt = "\n".join(meaningful)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n... [truncated]"
    return excerpt


class DiffParser:
    """Parses raw unified diff into independently addressable ChangeUnits."""

    @classmethod
    def parse(cls, diff_text: str) -> list[ChangeUnit]:
        """Parse unified diff text and construct ChangeUnits with stable IDs."""
        if not diff_text or not diff_text.strip():
            return []

        patch_set = PatchSet(diff_text)
        units: list[ChangeUnit] = []
        unit_counter = 1

        for pf in patch_set:
            clean_path = pf.path

            # Binary file
            if pf.is_binary_file:
                unit_id = f"U{unit_counter:03d}"
                unit_counter += 1
                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="binary",
                        summary=f"Binary change in {clean_path}",
                        hunk_header=None,
                        added_lines=0,
                        removed_lines=0,
                        is_binary=True,
                        is_splittable=False,
                        excerpt="[Binary content]",
                        patch_text=str(pf),
                    )
                )
                continue

            # Added file
            if pf.is_added_file:
                unit_id = f"U{unit_counter:03d}"
                unit_counter += 1
                patch_str = str(pf)
                if not patch_str.endswith("\n"):
                    patch_str += "\n"
                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="add",
                        summary=f"Create new file {clean_path}",
                        hunk_header=None,
                        added_lines=pf.added,
                        removed_lines=0,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=make_excerpt(patch_str),
                        patch_text=patch_str,
                    )
                )
                continue

            # Deleted file
            if pf.is_removed_file:
                unit_id = f"U{unit_counter:03d}"
                unit_counter += 1
                patch_str = str(pf)
                if not patch_str.endswith("\n"):
                    patch_str += "\n"
                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="delete",
                        summary=f"Delete file {clean_path}",
                        hunk_header=None,
                        added_lines=0,
                        removed_lines=pf.removed,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=make_excerpt(patch_str),
                        patch_text=patch_str,
                    )
                )
                continue

            # Text modifications: check for multiple hunks
            hunk_count = len(pf)
            if hunk_count > 1:
                # Same-file hunk splitting: Each independent hunk becomes a separate ChangeUnit
                header = f"diff --git a/{clean_path} b/{clean_path}\n--- a/{clean_path}\n+++ b/{clean_path}\n"
                for idx, hunk in enumerate(pf, 1):
                    unit_id = f"U{unit_counter:03d}"
                    unit_counter += 1
                    hunk_str = str(hunk)
                    if not hunk_str.endswith("\n"):
                        hunk_str += "\n"
                    hunk_header = hunk_str.splitlines()[0] if hunk_str.splitlines() else f"Hunk {idx}"

                    units.append(
                        ChangeUnit(
                            id=unit_id,
                            path=clean_path,
                            kind="modify",
                            summary=f"Update {clean_path} (hunk {idx}/{hunk_count})",
                            hunk_header=hunk_header,
                            added_lines=hunk.added,
                            removed_lines=hunk.removed,
                            is_binary=False,
                            is_splittable=True,
                            excerpt=make_excerpt(hunk_str),
                            patch_text=header + hunk_str,
                        )
                    )
            elif hunk_count == 1:
                # Single hunk
                unit_id = f"U{unit_counter:03d}"
                unit_counter += 1
                hunk = pf[0]
                patch_str = str(pf)
                if not patch_str.endswith("\n"):
                    patch_str += "\n"
                hunk_header = str(hunk).splitlines()[0] if str(hunk).splitlines() else None

                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="modify",
                        summary=f"Update {clean_path}",
                        hunk_header=hunk_header,
                        added_lines=hunk.added,
                        removed_lines=hunk.removed,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=make_excerpt(str(hunk)),
                        patch_text=patch_str,
                    )
                )
            else:
                # Mode change or metadata only
                unit_id = f"U{unit_counter:03d}"
                unit_counter += 1
                patch_str = str(pf)
                if not patch_str.endswith("\n"):
                    patch_str += "\n"
                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="mode_change",
                        summary=f"Mode change in {clean_path}",
                        hunk_header=None,
                        added_lines=0,
                        removed_lines=0,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=patch_str.strip(),
                        patch_text=patch_str,
                    )
                )

        return units
