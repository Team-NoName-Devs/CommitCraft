"""Interactive review and editing interface for commit plans."""

import copy
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from commitcraft.change_units import ChangeUnit
from commitcraft.dependencies import DependencyResolver
from commitcraft.errors import PlanValidationError
from commitcraft.executor import PreflightResult
from commitcraft.schemas import CommitGroupProposal, PlanProposal
from commitcraft.validator import PlanValidator


class PlanEditor:
    """Provides pure, validated editing operations on a PlanProposal."""

    @classmethod
    def move_unit(
        cls,
        plan: PlanProposal,
        unit_id: str,
        from_group_id: str,
        to_group_id: str,
        inventory: list[ChangeUnit],
    ) -> PlanProposal:
        """Move a change unit from one group to another."""
        new_plan = copy.deepcopy(plan)
        from_grp = next((g for g in new_plan.groups if g.id == from_group_id), None)
        to_grp = next((g for g in new_plan.groups if g.id == to_group_id), None)

        if not from_grp or not to_grp:
            raise PlanValidationError(f"Invalid group IDs: {from_group_id} or {to_group_id}.")
        if unit_id not in from_grp.unit_ids:
            raise PlanValidationError(f"Unit {unit_id} is not in group {from_group_id}.")

        from_grp.unit_ids.remove(unit_id)
        if unit_id not in to_grp.unit_ids:
            to_grp.unit_ids.append(unit_id)

        # Remove from_grp if empty
        if not from_grp.unit_ids:
            new_plan.groups = [g for g in new_plan.groups if g.id != from_group_id]
            # Remove any dependency references to deleted group
            for g in new_plan.groups:
                g.depends_on = [d for d in g.depends_on if d != from_group_id]

        PlanValidator.assert_valid(new_plan, inventory)
        return new_plan

    @classmethod
    def merge_groups(
        cls,
        plan: PlanProposal,
        source_id: str,
        target_id: str,
        inventory: list[ChangeUnit],
    ) -> PlanProposal:
        """Merge source group into target group."""
        new_plan = copy.deepcopy(plan)
        src = next((g for g in new_plan.groups if g.id == source_id), None)
        tgt = next((g for g in new_plan.groups if g.id == target_id), None)

        if not src or not tgt:
            raise PlanValidationError(f"Invalid group ID for merge: {source_id} or {target_id}.")

        for uid in src.unit_ids:
            if uid not in tgt.unit_ids:
                tgt.unit_ids.append(uid)

        # Merge dependencies
        for dep in src.depends_on:
            if dep != target_id and dep not in tgt.depends_on:
                tgt.depends_on.append(dep)

        # Remove source group
        new_plan.groups = [g for g in new_plan.groups if g.id != source_id]
        # Update references to source group to point to target group
        for g in new_plan.groups:
            g.depends_on = [tgt.id if d == source_id else d for d in g.depends_on if d != g.id]
            g.depends_on = list(dict.fromkeys(g.depends_on))

        PlanValidator.assert_valid(new_plan, inventory)
        return new_plan

    @classmethod
    def split_group(
        cls,
        plan: PlanProposal,
        group_id: str,
        new_group_id: str,
        unit_ids_for_new: list[str],
        new_title: str,
        new_message: str,
        new_commit_type: str,
        inventory: list[ChangeUnit],
    ) -> PlanProposal:
        """Split a subset of units from an existing group into a new group."""
        new_plan = copy.deepcopy(plan)
        orig = next((g for g in new_plan.groups if g.id == group_id), None)
        if not orig:
            raise PlanValidationError(f"Group {group_id} not found.")

        for uid in unit_ids_for_new:
            if uid not in orig.unit_ids:
                raise PlanValidationError(f"Unit {uid} is not in group {group_id}.")
            orig.unit_ids.remove(uid)

        if not orig.unit_ids:
            raise PlanValidationError("Cannot split all units out; original group would be empty.")

        new_grp = CommitGroupProposal(
            id=new_group_id,
            unit_ids=unit_ids_for_new,
            title=new_title,
            explanation=f"Split from {group_id}",
            commit_type=new_commit_type,
            message=new_message,
            depends_on=[group_id],
        )
        new_plan.groups.append(new_grp)

        PlanValidator.assert_valid(new_plan, inventory)
        return new_plan

    @classmethod
    def edit_message(
        cls,
        plan: PlanProposal,
        group_id: str,
        new_message: str,
        inventory: list[ChangeUnit],
    ) -> PlanProposal:
        """Edit the Conventional Commit message for a group."""
        new_plan = copy.deepcopy(plan)
        grp = next((g for g in new_plan.groups if g.id == group_id), None)
        if not grp:
            raise PlanValidationError(f"Group {group_id} not found.")
        grp.message = new_message.strip()

        PlanValidator.assert_valid(new_plan, inventory)
        return new_plan

    @classmethod
    def set_dependencies(
        cls,
        plan: PlanProposal,
        group_id: str,
        depends_on: list[str],
        inventory: list[ChangeUnit],
    ) -> PlanProposal:
        """Update dependencies for a group."""
        new_plan = copy.deepcopy(plan)
        grp = next((g for g in new_plan.groups if g.id == group_id), None)
        if not grp:
            raise PlanValidationError(f"Group {group_id} not found.")
        grp.depends_on = depends_on

        PlanValidator.assert_valid(new_plan, inventory)
        return new_plan


class ReviewUI:
    """Rich terminal user interface for reviewing and modifying plans."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def display_plan(
        self,
        plan: PlanProposal,
        inventory: list[ChangeUnit],
        preflight: Optional[PreflightResult] = None,
    ) -> None:
        """Render a formatted view of the current plan."""
        unit_map = {u.id: u for u in inventory}

        self.console.print("\n[bold cyan]══════════════ PROPOSED COMMIT PLAN ══════════════[/bold cyan]")
        if plan.summary:
            self.console.print(f"[dim]{plan.summary}[/dim]\n")

        ordered_groups = plan.groups
        try:
            ordered_groups = DependencyResolver.resolve_order(plan.groups)
        except Exception:
            pass

        for idx, group in enumerate(ordered_groups, 1):
            deps_str = ", ".join(group.depends_on) if group.depends_on else "None"
            table = Table(box=None, show_header=True, header_style="bold")
            table.add_column("Unit ID", style="cyan", width=10)
            table.add_column("Kind", width=10)
            table.add_column("Path", style="green")
            table.add_column("Lines", justify="right", width=12)

            for uid in group.unit_ids:
                unit = unit_map.get(uid)
                if unit:
                    table.add_row(
                        unit.id,
                        unit.kind,
                        unit.path + (f" ({unit.hunk_header})" if unit.hunk_header else ""),
                        f"+{unit.added_lines} / -{unit.removed_lines}",
                    )
                else:
                    table.add_row(uid, "unknown", "?", "?")

            panel_content = [
                f"[bold yellow]Commit Message:[/bold yellow] [bold white]{group.message}[/bold white]",
                f"[bold]Rationale:[/bold] {group.explanation}",
                f"[bold]Dependencies:[/bold] {deps_str}",
            ]
            self.console.print(
                Panel(
                    table,
                    title=f"[bold green]Commit #{idx}: [{group.id}] {group.title}[/bold green]",
                    subtitle=" \n ".join(panel_content),
                    expand=False,
                )
            )

        if preflight:
            if preflight.tree_equality:
                self.console.print(
                    "[bold green]✔ Preflight replay succeeded. Target tree equality verified![/bold green]"
                )
            else:
                self.console.print(
                    f"[bold red]✘ Preflight check failed: {preflight.error_message}[/bold red]"
                )
