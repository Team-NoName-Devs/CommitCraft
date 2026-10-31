"""Interactive review and editing interface for commit plans."""

import copy
from typing import Optional
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from commitcraft.change_units import ChangeUnit
from commitcraft.dependencies import DependencyResolver
from commitcraft.errors import PlanValidationError
from commitcraft.executor import PreflightResult
from commitcraft.schemas import CommitGroupProposal, PlanProposal, parse_conventional_commit
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

        parsed_type, parsed_scope, _, _ = parse_conventional_commit(new_message.strip())
        new_grp = CommitGroupProposal(
            id=new_group_id,
            unit_ids=unit_ids_for_new,
            title=new_title,
            explanation=f"Split from {group_id}",
            commit_type=parsed_type or new_commit_type,
            scope=parsed_scope,
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

        clean_msg = new_message.strip()
        parsed_type, parsed_scope, _, _ = parse_conventional_commit(clean_msg)
        if parsed_type:
            grp.commit_type = parsed_type
            grp.scope = parsed_scope
        grp.message = clean_msg

        PlanValidator.assert_valid(new_plan, inventory)
        return new_plan

    @classmethod
    def edit_title(
        cls,
        plan: PlanProposal,
        group_id: str,
        new_title: str,
        inventory: list[ChangeUnit],
    ) -> PlanProposal:
        """Edit the title for a group."""
        new_plan = copy.deepcopy(plan)
        grp = next((g for g in new_plan.groups if g.id == group_id), None)
        if not grp:
            raise PlanValidationError(f"Group {group_id} not found.")
        grp.title = new_title.strip()

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

    def display_banner(self) -> None:
        """Render a sleek CommitCraft branding banner."""
        self.console.print(
            Panel(
                "[bold cyan]CommitCraft[/bold cyan] [bold white]✦ AI-Powered Semantic Commit Splitter[/bold white]\n"
                "[dim]Local Llama 3.2 3B • Isolated Git Index Replay • Mathematical Tree Equality[/dim]",
                border_style="cyan",
                box=box.ROUNDED,
                expand=False,
            )
        )

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
            self.console.print(f"[dim italic]{plan.summary}[/dim italic]\n")

        ordered_groups = plan.groups
        try:
            ordered_groups = DependencyResolver.resolve_order(plan.groups)
        except Exception:
            pass

        for idx, group in enumerate(ordered_groups, 1):
            deps_str = ", ".join(group.depends_on) if group.depends_on else "None"
            table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="dim")
            table.add_column("Unit ID", style="bold cyan", width=9)
            table.add_column("Kind", width=10)
            table.add_column("Path", style="green")
            table.add_column("Lines", justify="right", width=13)

            for uid in group.unit_ids:
                unit = unit_map.get(uid)
                if unit:
                    kind_badge = {
                        "add": "[bold green]ADD[/bold green]",
                        "modify": "[bold cyan]MODIFY[/bold cyan]",
                        "delete": "[bold red]DELETE[/bold red]",
                        "binary": "[bold yellow]BINARY[/bold yellow]",
                        "mode_change": "[bold magenta]CHMOD[/bold magenta]",
                    }.get(unit.kind, unit.kind)
                    ctx_desc = ""
                    if unit.context_info:
                        ctx_desc = f" [dim cyan]({unit.context_info})[/dim cyan]"
                    elif unit.hunk_header:
                        ctx_desc = f" [dim yellow]({unit.hunk_header})[/dim yellow]"

                    table.add_row(
                        unit.id,
                        kind_badge,
                        unit.path + ctx_desc,
                        f"[green]+{unit.added_lines}[/green] / [red]-{unit.removed_lines}[/red]",
                    )
                else:
                    table.add_row(uid, "unknown", "?", "?")

            total_added = sum(unit_map[u].added_lines for u in group.unit_ids if u in unit_map)
            total_removed = sum(unit_map[u].removed_lines for u in group.unit_ids if u in unit_map)

            meta_grid = Table.grid(padding=(0, 2))
            meta_grid.add_column(style="bold yellow", justify="right")
            meta_grid.add_column()
            meta_grid.add_row("Commit Message:", f"[bold white]{group.message}[/bold white]")
            meta_grid.add_row("Rationale:", f"[white]{group.explanation}[/white]")
            meta_grid.add_row(
                "Commit Type:",
                f"[cyan]{group.commit_type}[/cyan]"
                + (f" [dim](scope: {group.scope})[/dim]" if group.scope else "")
                + f"  •  [bold]Dependencies:[/bold] [magenta]{deps_str}[/magenta]"
                + f"  •  [bold]Impact:[/bold] [green]+{total_added}[/green]/[red]-{total_removed}[/red]"
            )

            card_content = Group(
                meta_grid,
                Text(""),
                table,
            )

            self.console.print(
                Panel(
                    card_content,
                    title=f"[bold green]Commit #{idx}: [{group.id}] {group.title}[/bold green]",
                    border_style="cyan",
                    box=box.ROUNDED,
                    expand=False,
                )
            )

        if preflight:
            if preflight.tree_equality:
                self.console.print(
                    Panel(
                        "[bold green]✔ Preflight replay succeeded. Target tree equality verified![/bold green]\n"
                        "[dim]All intermediate patches apply cleanly in isolated index and match target snapshot tree.[/dim]",
                        border_style="green",
                        box=box.ROUNDED,
                    )
                )
            else:
                self.console.print(
                    Panel(
                        f"[bold red]✘ Preflight check failed: {preflight.error_message}[/bold red]\n"
                        "[yellow]Please adjust unit assignments, dependencies, or order before executing.[/yellow]",
                        border_style="red",
                        box=box.ROUNDED,
                    )
                )

    def display_diff(self, units: list[ChangeUnit]) -> None:
        """Render syntax-highlighted diffs for the requested change units."""
        if not units:
            self.console.print("[yellow]No change units to display.[/yellow]")
            return

        for unit in units:
            diff_text = unit.patch_text if unit.patch_text else (f"# Binary or empty patch\n# Path: {unit.path}\n# Kind: {unit.kind}\n")
            syntax = Syntax(diff_text, "diff", theme="monokai", background_color="default")
            header = f"[bold cyan]Unit {unit.id}[/bold cyan] • [bold white]{unit.path}[/bold white]"
            if unit.context_info:
                header += f" [dim cyan]({unit.context_info})[/dim cyan]"
            elif unit.hunk_header:
                header += f" [dim yellow]{unit.hunk_header}[/dim yellow]"
            stats = f"[green]+{unit.added_lines}[/green] / [red]-{unit.removed_lines}[/red]"

            self.console.print(
                Panel(
                    syntax,
                    title=header,
                    subtitle=stats,
                    border_style="blue",
                    box=box.ROUNDED,
                )
            )
