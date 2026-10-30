"""Pull-request description generator based on approved plan and execution results."""

from pathlib import Path
from typing import Optional

from commitcraft.change_units import ChangeUnit
from commitcraft.executor import ExecutionResult
from commitcraft.schemas import PlanProposal


DEFAULT_PR_FILENAME = "COMMITCRAFT_PR.md"


class PRDescriptionGenerator:
    """Generates an honest, structured, editable Markdown PR description."""

    @classmethod
    def generate_markdown(
        cls,
        plan: PlanProposal,
        execution_res: Optional[ExecutionResult],
        inventory: list[ChangeUnit],
    ) -> str:
        """Compose the PR markdown text."""
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
                    if unit.hunk_header:
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
        # Look for test units in inventory to suggest tests
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
