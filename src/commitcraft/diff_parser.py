"""Diff parsing and change unit extraction."""

from pathlib import Path
from typing import Optional
from unidiff import PatchSet
from commitcraft.change_units import ChangeUnit


def infer_scope_hint(path: str) -> Optional[str]:
    """Infer a conventional commit scope hint from a file path."""
    p = Path(path)
    parts = p.parts

    # CI workflows
    if ".github" in parts:
        return "ci"

    # Documentation
    if p.suffix in (".md", ".rst", ".adoc") or "docs" in parts:
        return "docs"

    # Build and config files
    if p.name in ("pyproject.toml", "setup.py", "setup.cfg", "package.json", "Cargo.toml", "go.mod", "Makefile"):
        return "build"
    if p.name in (".gitignore", ".env.example", ".editorconfig", "ruff.toml"):
        return "config"

    # Tests
    if "tests" in parts or "test" in parts or p.stem.startswith("test_") or p.stem.endswith("_test"):
        stem = p.stem
        if stem.startswith("test_"):
            return stem[5:].replace("_", "-")
        elif stem.endswith("_test"):
            return stem[:-5].replace("_", "-")
        return "test"

    # Source code: use module or directory stem
    if p.stem and p.stem not in ("__init__", "__main__"):
        return p.stem.replace("_", "-")
    elif len(parts) >= 2:
        return parts[-2].replace("_", "-")

    return None


def extract_context_info(hunk_header: Optional[str], section_header: Optional[str] = None) -> Optional[str]:
    """Extract class, function, or symbol context from hunk or section header."""
    if section_header and section_header.strip():
        return section_header.strip()

    if hunk_header and "@@" in hunk_header:
        parts = hunk_header.split("@@")
        if len(parts) >= 3 and parts[2].strip():
            return parts[2].strip()

    return None


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
            scope_hint = infer_scope_hint(clean_path)

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
                        scope_hint=scope_hint,
                        context_info=None,
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
                summary = f"Create new file {clean_path}"
                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="add",
                        summary=summary,
                        hunk_header=None,
                        added_lines=pf.added,
                        removed_lines=0,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=make_excerpt(patch_str),
                        patch_text=patch_str,
                        scope_hint=scope_hint,
                        context_info=None,
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
                summary = f"Delete file {clean_path}"
                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="delete",
                        summary=summary,
                        hunk_header=None,
                        added_lines=0,
                        removed_lines=pf.removed,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=make_excerpt(patch_str),
                        patch_text=patch_str,
                        scope_hint=scope_hint,
                        context_info=None,
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
                    section_hdr = getattr(hunk, "section_header", None)
                    context_info = extract_context_info(hunk_header, section_hdr)

                    ctx_suffix = f" in {context_info}" if context_info else f" (hunk {idx}/{hunk_count})"
                    summary = f"Update {clean_path}{ctx_suffix}"

                    units.append(
                        ChangeUnit(
                            id=unit_id,
                            path=clean_path,
                            kind="modify",
                            summary=summary,
                            hunk_header=hunk_header,
                            added_lines=hunk.added,
                            removed_lines=hunk.removed,
                            is_binary=False,
                            is_splittable=True,
                            excerpt=make_excerpt(hunk_str),
                            patch_text=header + hunk_str,
                            scope_hint=scope_hint,
                            context_info=context_info,
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
                section_hdr = getattr(hunk, "section_header", None)
                context_info = extract_context_info(hunk_header, section_hdr)

                ctx_suffix = f" in {context_info}" if context_info else ""
                summary = f"Update {clean_path}{ctx_suffix}"

                units.append(
                    ChangeUnit(
                        id=unit_id,
                        path=clean_path,
                        kind="modify",
                        summary=summary,
                        hunk_header=hunk_header,
                        added_lines=hunk.added,
                        removed_lines=hunk.removed,
                        is_binary=False,
                        is_splittable=False,
                        excerpt=make_excerpt(str(hunk)),
                        patch_text=patch_str,
                        scope_hint=scope_hint,
                        context_info=context_info,
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
                        scope_hint=scope_hint,
                        context_info=None,
                    )
                )

        return units
