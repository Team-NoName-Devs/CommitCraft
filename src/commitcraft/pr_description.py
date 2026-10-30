"""Pull-request description generator for individual and modular commit groups."""

from pathlib import Path
from typing import Optional

from commitcraft.change_units import ChangeUnit
from commitcraft.executor import ExecutionResult
from commitcraft.schemas import CommitGroupProposal, PlanProposal


DEFAULT_PR_FILENAME = "COMMITCRAFT_PR.md"
DEFAULT_PRS_DIR = "prs"


class PRDescriptionGenerator:
    """Generates honest, structured, editable Markdown PR descriptions for individual commit groups."""

    @classmethod
    def generate_group_markdown(
        cls,
        group: CommitGroupProposal,
        commit_sha: Optional[str],
        inventory: list[ChangeUnit],
        plan: Optional[PlanProposal] = None,
        branch_name: Optional[str] = None,
    ) -> str:
        """Compose individual PR markdown text for a specific commit group."""
        unit_map = {u.id: u for u in inventory}
        sha_disp = (
            commit_sha[:8]
            if commit_sha and len(commit_sha) >= 8 and commit_sha != "(dry-run)"
            else (commit_sha or "(dry-run)")
        )

        lines: list[str] = [
            f"# Pull Request Description: {group.title}",
            "",
            "## Summary",
            "",
            group.explanation.strip(),
            "",
        ]

        is_breaking = (
            "!" in group.message.split(":")[0]
            or "BREAKING CHANGE" in group.explanation.upper()
            or "BREAKING CHANGE" in group.message.upper()
        )
        if is_breaking:
            lines.extend([
                "## ⚠ Breaking Changes",
                "",
                f"- **{group.title}**: {group.explanation}",
                "",
            ])

        lines.extend([
            "## PR Details",
            "",
            f"- **Group ID**: `{group.id}`",
            f"- **Type**: `{group.commit_type}`" + (f" (scope: `{group.scope}`)" if group.scope else ""),
        ])
        if branch_name:
            lines.append(f"- **Dedicated Branch**: `{branch_name}`")
        lines.append(f"- **Commit**: `{sha_disp}`: {group.message}")

        if group.depends_on:
            lines.append(f"- **Prerequisites**: Depends on group(s) {', '.join(f'`{d}`' for d in group.depends_on)}")
        lines.append("")

        lines.extend([
            "## Key Changes",
            "",
            f"### {group.title}",
            f"- **Rationale**: {group.explanation}",
            "- **Change Units**:",
        ])
        for uid in group.unit_ids:
            unit = unit_map.get(uid)
            if unit:
                desc = f"`{unit.path}` ({unit.kind}"
                if unit.context_info:
                    desc += f", `{unit.context_info}`"
                elif unit.hunk_header:
                    desc += f", {unit.hunk_header}"
                desc += f", +{unit.added_lines}/-{unit.removed_lines})"
                lines.append(f"  - [{unit.id}] {desc}")
        lines.append("")

        lines.extend([
            "## Commits",
            "",
            f"- `{sha_disp}`: {group.message}",
            "",
        ])

        # Testing Performed
        lines.extend([
            "## Testing Performed",
            "",
            "> [!NOTE]",
            "> CommitCraft validates patch replay and tree equality. Automated project tests "
            "were not executed by CommitCraft during splitting.",
            "",
        ])
        group_units = [unit_map[uid] for uid in group.unit_ids if uid in unit_map]
        group_test_units = [u for u in group_units if "test" in u.path.lower()]
        if group_test_units:
            lines.append("**Suggested verification steps based on modified test files:**")
            for tu in group_test_units:
                lines.append(f"- Run tests in `{tu.path}`")
            lines.append("")
        else:
            test_units = [u for u in inventory if "test" in u.path.lower()]
            if test_units:
                lines.append("**Suggested verification steps based on modified test files:**")
                for tu in test_units:
                    lines.append(f"- Run tests in `{tu.path}`")
                lines.append("")

        lines.extend([
            "## Notes for Reviewers",
            "",
            f"- This pull request contains focused changes for **{group.title}** as part of modular commit splitting.",
            "- Replayed and verified against the exact target snapshot tree in an isolated Git index.",
        ])
        if group.depends_on:
            lines.append(
                f"- **Stacked PR**: This branch depends on prerequisite group(s) "
                f"{', '.join(f'`{d}`' for d in group.depends_on)}. Please merge or base on prerequisites first."
            )
        lines.extend([
            "",
            "---",
            "*Generated automatically by [CommitCraft](https://github.com/Team-NoName-Devs/CommitCraft).* "
            "Please review and edit before opening your PR.",
            "",
        ])

        return "\n".join(lines)

    @classmethod
    def generate_individual_prs(
        cls,
        plan: PlanProposal,
        execution_res: Optional[ExecutionResult],
        inventory: list[ChangeUnit],
        branch_names: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        """Generate a mapping of group_id -> PR markdown for every group in the plan."""
        ordered_groups = execution_res.ordered_groups if execution_res else plan.groups
        created_commits = (
            execution_res.created_commits
            if execution_res
            else ["(dry-run)"] * len(ordered_groups)
        )
        branches = branch_names or (execution_res.created_branches if execution_res else {})

        prs: dict[str, str] = {}
        for grp, commit_sha in zip(ordered_groups, created_commits):
            b_name = branches.get(grp.id)
            prs[grp.id] = cls.generate_group_markdown(
                group=grp,
                commit_sha=commit_sha,
                inventory=inventory,
                plan=plan,
                branch_name=b_name,
            )
        return prs

    @classmethod
    def generate_markdown(
        cls,
        plan: PlanProposal,
        execution_res: Optional[ExecutionResult],
        inventory: list[ChangeUnit],
    ) -> str:
        """Compose PR markdown text covering the plan (for unified or single-group output)."""
        unit_map = {u.id: u for u in inventory}

        ordered_groups = execution_res.ordered_groups if execution_res else plan.groups
        created_commits = execution_res.created_commits if execution_res else ["(dry-run)"] * len(ordered_groups)

        lines: list[str] = [
            "# Pull Request Description",
            "",
            "## Summary",
            "",
        ]

        if plan.summary:
            lines.append(plan.summary.strip())
        else:
            lines.append(
                f"This pull request structures {len(inventory)} change unit(s) "
                f"into {len(created_commits)} logical, cohesive commit(s)."
            )
        lines.append("")

        breaking = [
            g for g in ordered_groups
            if "!" in g.message.split(":")[0] or "BREAKING CHANGE" in g.explanation.upper() or "BREAKING CHANGE" in g.message.upper()
        ]
        if breaking:
            lines.extend([
                "## ⚠ Breaking Changes",
                "",
            ])
            for bg in breaking:
                lines.append(f"- **{bg.title}**: {bg.explanation}")
            lines.append("")

        lines.extend([
            "## Key Changes",
            "",
        ])
        for group in ordered_groups:
            lines.append(f"### {group.title}")
            lines.append(f"- **Type**: `{group.commit_type}`" + (f" (scope: `{group.scope}`)" if group.scope else ""))
            lines.append(f"- **Rationale**: {group.explanation}")
            lines.append("- **Change Units**:")
            for uid in group.unit_ids:
                unit = unit_map.get(uid)
                if unit:
                    desc = f"`{unit.path}` ({unit.kind}"
                    if unit.context_info:
                        desc += f", `{unit.context_info}`"
                    elif unit.hunk_header:
                        desc += f", {unit.hunk_header}"
                    desc += f", +{unit.added_lines}/-{unit.removed_lines})"
                    lines.append(f"  - [{unit.id}] {desc}")
            lines.append("")

        lines.extend([
            "## Commits",
            "",
        ])
        for commit_sha, group in zip(created_commits, ordered_groups):
            sha_disp = commit_sha[:8] if len(commit_sha) >= 8 else commit_sha
            lines.append(f"- `{sha_disp}`: {group.message}")
        lines.append("")

        # Testing Performed
        lines.extend([
            "## Testing Performed",
            "",
            "> [!NOTE]",
            "> CommitCraft validates patch replay and tree equality. Automated project tests "
            "were not executed by CommitCraft during splitting.",
            "",
        ])
        test_units = [u for u in inventory if "test" in u.path.lower()]
        if test_units:
            lines.append("**Suggested verification steps based on modified test files:**")
            for tu in test_units:
                lines.append(f"- Run tests in `{tu.path}`")
            lines.append("")

        lines.extend([
            "## Notes for Reviewers",
            "",
            "- All commits have been replayed and verified against the exact target snapshot tree.",
            "- Independent hunks and files have been placed in separate logical commits for reviewability.",
            "",
            "---",
            "*Generated automatically by [CommitCraft](https://github.com/Team-NoName-Devs/CommitCraft).* "
            "Please review and edit before opening your PR.",
            "",
        ])

        return "\n".join(lines)

    @classmethod
    def save_individual_prs(
        cls,
        prs: dict[str, str],
        git_dir: Path,
        custom_path: Optional[Path] = None,
    ) -> list[Path]:
        """Save individual PR descriptions to disk under .git/prs/PR_<group_id>.md.

        If custom_path is specified:
        - If custom_path has no file extension or is a directory, writes PR_<group_id>.md inside it.
        - If custom_path is a file path:
          * If only 1 group, writes directly to custom_path.
          * If multiple groups, writes <stem>_<group_id><suffix> and also writes combined to custom_path.
        """
        saved_paths: list[Path] = []
        git_dir_resolved = Path(git_dir).resolve()

        if custom_path:
            target = Path(custom_path).resolve()
            if not target.suffix or target.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                for group_id, content in prs.items():
                    file_path = target / f"PR_{group_id}.md"
                    file_path.write_text(content, encoding="utf-8")
                    saved_paths.append(file_path)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if len(prs) == 1:
                    group_id, content = next(iter(prs.items()))
                    target.write_text(content, encoding="utf-8")
                    saved_paths.append(target)
                else:
                    for group_id, content in prs.items():
                        group_file = target.parent / f"{target.stem}_{group_id}{target.suffix}"
                        group_file.write_text(content, encoding="utf-8")
                        saved_paths.append(group_file)
                    # Also write target file for single-file expectations
                    combined = "\n\n---\n\n".join(prs.values())
                    target.write_text(combined, encoding="utf-8")
                    if target not in saved_paths:
                        saved_paths.append(target)
        else:
            prs_dir = git_dir_resolved / DEFAULT_PRS_DIR
            prs_dir.mkdir(parents=True, exist_ok=True)
            for group_id, content in prs.items():
                file_path = prs_dir / f"PR_{group_id}.md"
                file_path.write_text(content, encoding="utf-8")
                saved_paths.append(file_path)

            # Backwards compatibility: also write combined to .git/COMMITCRAFT_PR.md
            legacy_file = git_dir_resolved / DEFAULT_PR_FILENAME
            combined_md = "\n\n---\n\n".join(prs.values())
            legacy_file.write_text(combined_md, encoding="utf-8")

        return saved_paths

    @classmethod
    def save_pr_description(
        cls,
        content: str,
        git_dir: Path,
        custom_path: Optional[Path] = None,
    ) -> Path:
        """Save PR description to disk safely without dirtying working tree by default."""
        if custom_path:
            target_path = Path(custom_path).resolve()
        else:
            target_path = Path(git_dir).resolve() / DEFAULT_PR_FILENAME

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return target_path
