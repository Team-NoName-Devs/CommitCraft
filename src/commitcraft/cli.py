"""Typer command-line interface for CommitCraft."""

import os
from pathlib import Path
import sys
from typing import Optional
import typer
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from commitcraft.config import AppConfig, REQUIRED_MODEL
from commitcraft.dependencies import DependencyResolver
from commitcraft.diff_parser import DiffParser
from commitcraft.errors import (
    CommitCraftError,
    ModelUnavailableError,
    PlanValidationError,
    StaleSnapshotError,
)
from commitcraft.executor import PlanExecutor
from commitcraft.hooks import HookManager
from commitcraft.model_client import OllamaClient
from commitcraft.planner import SemanticPlanner
from commitcraft.pr_description import PRDescriptionGenerator
from commitcraft.pr_sender import PRSender
from commitcraft.repository import RepositoryInspector
from commitcraft.review import PlanEditor, ReviewUI
from commitcraft.snapshot import SnapshotEngine


__version__ = "0.1.0"

app = typer.Typer(
    name="commitcraft",
    help="Turn a messy Git working tree into logical, reviewable commits with local AI.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

hook_app = typer.Typer(help="Manage optional CommitCraft advisory Git hooks.")
app.add_typer(hook_app, name="hook")


def show_version() -> None:
    """Display CommitCraft version and runtime diagnostic information."""
    info_table = Table(box=box.ROUNDED, show_header=False, border_style="cyan")
    info_table.add_column("Property", style="bold cyan", width=22)
    info_table.add_column("Value", style="white")

    info_table.add_row("CommitCraft Version", f"[bold green]{__version__}[/bold green]")
    info_table.add_row("Python Version", sys.version.split()[0])
    info_table.add_row("Required Model", f"[cyan]{REQUIRED_MODEL}[/cyan] (via Ollama)")
    info_table.add_row("License", "MIT")
    info_table.add_row("Repository", "https://github.com/Team-NoName-Devs/CommitCraft")

    console.print(
        Panel(
            info_table,
            title="[bold cyan]CommitCraft ✦ AI-Powered Semantic Commit Splitter[/bold cyan]",
            subtitle="Local • Private • Tree-Verified",
            border_style="cyan",
            box=box.ROUNDED,
            expand=False,
        )
    )


def version_callback(value: bool) -> None:
    """Typer callback for --version / -v flag."""
    if value:
        show_version()
        raise typer.Exit(code=0)


@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show CommitCraft version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """CommitCraft: Logical, reviewable commits with local AI."""
    pass


@app.command(name="version")
def version_cmd() -> None:
    """Display CommitCraft version and runtime diagnostic information."""
    show_version()


@app.command()
def inspect(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Path to Git repository (defaults to current directory)"
    ),
) -> None:
    """Inspect repository status, working changes, and Ollama model connectivity."""
    target_dir = Path(repo_path) if repo_path else Path.cwd()
    config = AppConfig.load()

    console.print("[bold cyan]CommitCraft Diagnostic Inspection[/bold cyan]\n")

    # 1. Repository inspection
    try:
        inspector = RepositoryInspector(target_dir)
        repo, runner, state = inspector.inspect()
        console.print(f"[bold green]✔[/bold green] Repository Root: [white]{state.root_dir}[/white]")
        console.print(f"[bold green]✔[/bold green] Active Branch:   [cyan]{state.branch_name}[/cyan] ({state.branch_ref})")
        console.print(f"[bold green]✔[/bold green] HEAD Commit:     [yellow]{state.head_commit[:8]}[/yellow]")

        status_table = Table(title="Working Tree Changes", box=box.ROUNDED)
        status_table.add_column("Category", style="bold cyan", width=12)
        status_table.add_column("Files", justify="left")

        staged_display = f"{len(state.staged_files)}: {', '.join(state.staged_files[:5]) or 'None'}"
        if len(state.staged_files) > 5:
            staged_display += f" (+{len(state.staged_files) - 5} more)"

        unstaged_display = f"{len(state.unstaged_files)}: {', '.join(state.unstaged_files[:5]) or 'None'}"
        if len(state.unstaged_files) > 5:
            unstaged_display += f" (+{len(state.unstaged_files) - 5} more)"

        untracked_display = f"{len(state.untracked_files)}: {', '.join(state.untracked_files[:5]) or 'None'}"
        if len(state.untracked_files) > 5:
            untracked_display += f" (+{len(state.untracked_files) - 5} more)"

        status_table.add_row("Staged", staged_display)
        status_table.add_row("Unstaged", unstaged_display)
        status_table.add_row("Untracked", untracked_display)
        console.print(status_table)

        total_changes = len(state.staged_files) + len(state.unstaged_files) + len(state.untracked_files)
        if total_changes > 0:
            from commitcraft.diff_parser import infer_scope_hint
            all_paths = state.staged_files + state.unstaged_files + state.untracked_files
            detected_scopes = sorted(list({s for p in all_paths if (s := infer_scope_hint(p))}))
            if detected_scopes:
                console.print(f"[bold cyan]Detected Scopes/Components:[/bold cyan] {', '.join(detected_scopes)}")
            console.print(
                "[dim]💡 Run [bold white]commitcraft split[/bold white] to analyze and group changes into logical commits.[/dim]\n"
            )

    except CommitCraftError as e:
        console.print(f"[bold red]✘ Repository check failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Ollama & model inspection
    console.print("[bold cyan]Ollama Runtime Status[/bold cyan]")
    client = OllamaClient(
        base_url=config.ollama_base_url,
        connect_timeout=config.connect_timeout,
        read_timeout=config.read_timeout,
    )
    try:
        client.check_health()
        console.print(f"[bold green]✔[/bold green] Endpoint: [white]{config.ollama_base_url}[/white] (Connected)")
        console.print(f"[bold green]✔[/bold green] Required Model: [cyan]{REQUIRED_MODEL}[/cyan] (Available)")
        console.print("[bold green]● Ready[/bold green] [dim]— Local AI planner is operational.[/dim]\n")
    except ModelUnavailableError as e:
        console.print(f"[bold red]✘ Ollama unavailable:[/bold red] {e}")
        if e.resolution:
            console.print(f"  [yellow]-> {e.resolution}[/yellow]")
        raise typer.Exit(code=1)


@app.command(name="config")
def config_cmd(
    url: Optional[str] = typer.Option(None, "--url", help="Set Ollama base URL"),
    timeout: Optional[float] = typer.Option(None, "--timeout", help="Set inference read timeout in seconds"),
) -> None:
    """View and update CommitCraft configuration."""
    cfg = AppConfig.load()
    updated = False

    if url:
        cfg.ollama_base_url = url
        updated = True
    if timeout:
        cfg.read_timeout = timeout
        updated = True

    if updated:
        save_path = cfg.save()
        console.print(f"[bold green]✔ Configuration saved to {save_path}[/bold green]")

    console.print("\n[bold cyan]Current Configuration:[/bold cyan]")
    console.print(f"  Ollama URL:       [white]{cfg.ollama_base_url}[/white]")
    console.print(f"  Required Model:   [cyan]{cfg.model}[/cyan] [dim](Mandatory, no substitution)[/dim]")
    console.print(f"  Connect Timeout:  [white]{cfg.connect_timeout}s[/white]")
    console.print(f"  Read Timeout:     [white]{cfg.read_timeout}s[/white]")
    console.print(f"  Max Corrections:  [white]{cfg.max_correction_attempts}[/white]")

    cfg_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="dim")
    cfg_table.add_column("Setting", style="bold white", width=20)
    cfg_table.add_column("Value", style="cyan")
    cfg_table.add_column("Env Variable Override", style="dim")

    cfg_table.add_row("Ollama Base URL", cfg.ollama_base_url, "COMMITCRAFT_OLLAMA_URL")
    cfg_table.add_row("Required Model", cfg.model, "Fixed (llama3.2:3b)")
    cfg_table.add_row("Connect Timeout", f"{cfg.connect_timeout}s", "COMMITCRAFT_CONNECT_TIMEOUT")
    cfg_table.add_row("Read Timeout", f"{cfg.read_timeout}s", "COMMITCRAFT_READ_TIMEOUT")
    cfg_table.add_row("Max Corrections", str(cfg.max_correction_attempts), "COMMITCRAFT_MAX_CORRECTIONS")

    console.print("\n[bold]Configuration Overview Table:[/bold]")
    console.print(cfg_table)


@hook_app.command("install")
def hook_install(
    repo_path: Optional[str] = typer.Option(None, "--repo", "-r", help="Path to Git repository"),
) -> None:
    """Install optional CommitCraft advisory pre-commit hook."""
    inspector = RepositoryInspector(Path(repo_path) if repo_path else Path.cwd())
    root = inspector.discover_root()
    mgr = HookManager(root / ".git")
    hook_file = mgr.install()
    console.print(f"[bold green]✔ Advisory Git pre-commit hook installed at {hook_file}[/bold green]")
    console.print("[dim]The hook advises when >3 files are staged simultaneously to prevent accidental monolithic commits.[/dim]")


@hook_app.command("remove")
def hook_remove(
    repo_path: Optional[str] = typer.Option(None, "--repo", "-r", help="Path to Git repository"),
) -> None:
    """Remove CommitCraft advisory pre-commit hook."""
    inspector = RepositoryInspector(Path(repo_path) if repo_path else Path.cwd())
    root = inspector.discover_root()
    mgr = HookManager(root / ".git")
    if mgr.remove():
        console.print("[bold green]✔ Advisory Git pre-commit hook removed.[/bold green]")
    else:
        console.print("[yellow]No CommitCraft pre-commit hook was found.[/yellow]")


@app.command()
def split(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Path to Git repository (defaults to current directory)"
    ),
    auto_approve: bool = typer.Option(
        False, "--yes", "-y", help="Approve execution immediately if preflight succeeds (testing only)"
    ),
    custom_pr_path: Optional[str] = typer.Option(
        None, "--pr-output", help="Optional custom path for generated PR markdown"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Simulate planning and preflight verification without writing commits"
    ),
    show_diffs: bool = typer.Option(
        False, "--diff", "-d", help="Display full unified diffs for change units in plan"
    ),
    base_branch: Optional[str] = typer.Option(
        None, "--base", "-b", help="Base branch for PR submission (defaults to active branch)"
    ),
    send_pr: Optional[bool] = typer.Option(
        None, "--send-pr/--no-send-pr", help="Automatically send or skip pull requests to base branch"
    ),
) -> None:
    """Analyze working tree and interactively split into logical commits."""
    target_dir = Path(repo_path) if repo_path else Path.cwd()
    app_config = AppConfig.load()
    ui = ReviewUI(console)

    console.print("[bold cyan]══════════════ COMMITCRAFT SPLIT ══════════════[/bold cyan]\n")

    # 1. Repository inspection
    try:
        inspector = RepositoryInspector(target_dir)
        repo, runner, state = inspector.inspect()
    except CommitCraftError as e:
        console.print(f"[bold red]Repository error:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Target snapshot capture
    snapshot_engine = SnapshotEngine(repo, runner, state)
    try:
        with console.status("[cyan]Capturing target snapshot using isolated index...[/cyan]"):
            snapshot = snapshot_engine.capture_snapshot()
    except CommitCraftError as e:
        console.print(f"[bold red]Snapshot error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if not snapshot.has_changes:
        console.print("[bold green]Working tree is clean. Nothing to commit or split.[/bold green]")
        raise typer.Exit(code=0)

    # 3. Diff extraction and Change-Unit construction
    units = DiffParser.parse(snapshot.diff_text)
    if not units:
        console.print("[yellow]No parseable change units found.[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"Extracted [bold green]{len(units)}[/bold green] change unit(s) across target changes.")

    if show_diffs:
        console.print("\n[bold cyan]Diff Inspection for Extracted Units:[/bold cyan]")
        ui.display_diff(units)

    # 4. Mandatory Ollama AI planner
    ollama_client = OllamaClient(
        base_url=app_config.ollama_base_url,
        connect_timeout=app_config.connect_timeout,
        read_timeout=app_config.read_timeout,
    )
    repo_context = {
        "branch": state.branch_name,
        "total_units": len(units),
        "staged_count": len(state.staged_files),
        "unstaged_count": len(state.unstaged_files),
        "untracked_count": len(state.untracked_files),
        "components": sorted(list({u.scope_hint for u in units if u.scope_hint})),
        "detected_types": sorted(list({u.type_hint for u in units if u.type_hint})),
    }
    planner = SemanticPlanner(
        ollama_client,
        max_corrections=app_config.max_correction_attempts,
        repo_context=repo_context,
    )

    try:
        with console.status(f"[cyan]Requesting semantic plan from {REQUIRED_MODEL} via Ollama...[/cyan]"):
            plan = planner.plan(units)
    except CommitCraftError as e:
        console.print(f"\n[bold red]AI Planning Failed:[/bold red] {e}")
        console.print("[yellow]CommitCraft requires a valid plan from the local model to proceed. Aborting.[/yellow]")
        raise typer.Exit(code=1)

    executor = PlanExecutor(repo, runner, snapshot_engine)

    # 5. Interactive review and editing loop
    try:
        while True:
            try:
                ordered_groups = DependencyResolver.resolve_order(plan.groups)
            except Exception:
                ordered_groups = plan.groups

            preflight = executor.preflight_replay(ordered_groups, units, snapshot)
            ui.display_plan(plan, units, preflight)

            if dry_run:
                if not preflight.tree_equality:
                    console.print(f"[bold red]Preflight failed: {preflight.error_message}[/bold red]")
                    raise typer.Exit(code=1)
                console.print("\n[bold cyan]══════════════ DRY-RUN COMPLETE ══════════════[/bold cyan]")
                console.print("[bold green]✔ All preflight replays succeeded and tree equality verified![/bold green]")
                console.print("[dim]Dry-run mode active. No commits were written or installed to the Git branch.[/dim]")
                prs = PRDescriptionGenerator.generate_individual_prs(plan, None, units)
                console.print(f"\n[bold cyan]Individual PR Descriptions Preview ({len(prs)} PRs):[/bold cyan]")
                for grp in ordered_groups:
                    pr_text = prs.get(grp.id, "")
                    branch_hint = PlanExecutor.generate_branch_name(grp)
                    preview_snip = pr_text[:500] + ("\n... [truncated preview]" if len(pr_text) > 500 else "")
                    console.print(
                        Panel(
                            preview_snip,
                            title=f"[bold cyan]PR Description Preview — {grp.title}[/bold cyan] [dim](Branch: {branch_hint})[/dim]",
                            border_style="cyan",
                            box=box.ROUNDED,
                        )
                    )
                raise typer.Exit(code=0)

            if auto_approve:
                if not preflight.tree_equality:
                    console.print(f"[bold red]Preflight failed: {preflight.error_message}[/bold red]")
                    raise typer.Exit(code=1)
                confirmed = True
                break

            # Polished interactive menu
            menu_table = Table(box=box.ROUNDED, show_header=False, border_style="cyan", padding=(0, 1))
            menu_table.add_column("Key", style="bold cyan", width=8)
            menu_table.add_column("Action", style="bold white", width=22)
            menu_table.add_column("Description", style="dim")

            menu_table.add_row("[1/a]", "Approve & Execute", "Verify preflight and install commits to branch")
            menu_table.add_row("[2/m]", "Move Unit", "Reassign a change unit to another group")
            menu_table.add_row("[3/g]", "Merge Groups", "Combine two groups into one commit")
            menu_table.add_row("[4/s]", "Split Group", "Carve out units into a new commit group")
            menu_table.add_row("[5/e]", "Edit Message/Title", "Update Conventional Commit message or title")
            menu_table.add_row("[6/d]", "Edit Dependencies", "Update prerequisite groups for ordering")
            menu_table.add_row("[7/r]", "Regenerate Plan", "Request a fresh proposal from local Ollama model")
            menu_table.add_row("[8/v]", "View Diff", "Inspect syntax-highlighted diffs of units or groups")
            menu_table.add_row("[0/q]", "Abort", "Exit safely without touching Git state")

            console.print("\n[bold]Options:[/bold]")
            console.print(menu_table)

            raw_choice = Prompt.ask(
                "\nEnter choice",
                choices=["1", "2", "3", "4", "5", "6", "7", "8", "0", "a", "m", "g", "s", "e", "d", "r", "v", "q"],
                default="1",
            ).strip().lower()

            key_map = {
                "a": "1",
                "m": "2",
                "g": "3",
                "s": "4",
                "e": "5",
                "d": "6",
                "r": "7",
                "v": "8",
                "q": "0",
            }
            choice = key_map.get(raw_choice, raw_choice)

            if choice == "0":
                console.print("[yellow]Operation aborted by user. Working tree and branch untouched.[/yellow]")
                raise typer.Exit(code=0)

            elif choice == "1":
                if not preflight.tree_equality:
                    console.print(f"[bold red]Cannot execute: Preflight failed ({preflight.error_message}). Fix plan first.[/bold red]")
                    continue

                # Section 9.6: Require explicit confirmation, default to declining
                confirmed = Confirm.ask(
                    f"\nAre you sure you want to install {len(ordered_groups)} commit(s) on branch '{state.branch_name}'?",
                    default=False,
                )
                if confirmed:
                    break
                else:
                    console.print("[yellow]Execution cancelled. Returning to plan menu.[/yellow]")

            elif choice == "2":
                uid = Prompt.ask("Unit ID to move (e.g. U001, or 'cancel')").strip()
                if not uid or uid.lower() in ("c", "cancel"):
                    console.print("[yellow]Move cancelled.[/yellow]")
                    continue

                current_grp = next(
                    (g for g in plan.groups if uid.upper() in g.unit_ids or uid in g.unit_ids), None
                )
                actual_uid = uid.upper() if (current_grp and uid.upper() in current_grp.unit_ids) else uid

                from_g_default = current_grp.id if current_grp else "G01"
                from_g = Prompt.ask(f"Source Group ID (e.g. {from_g_default})", default=from_g_default).strip()
                if not from_g or from_g.lower() in ("c", "cancel"):
                    console.print("[yellow]Move cancelled.[/yellow]")
                    continue

                avail_targets = [g.id for g in plan.groups if g.id != from_g]
                to_default = avail_targets[0] if avail_targets else "G02"
                to_g = Prompt.ask(f"Target Group ID (e.g. {to_default})", default=to_default).strip()
                if not to_g or to_g.lower() in ("c", "cancel"):
                    console.print("[yellow]Move cancelled.[/yellow]")
                    continue

                try:
                    plan = PlanEditor.move_unit(plan, actual_uid, from_g, to_g, units)
                    console.print(f"[bold green]✔ Unit {actual_uid} moved from {from_g} to {to_g} successfully.[/bold green]")
                except PlanValidationError as e:
                    console.print(f"[bold red]Edit rejected:[/bold red] {e}")

            elif choice == "3":
                console.print(f"Available groups: {', '.join(f'[{g.id}: {g.title}]' for g in plan.groups)}")
                src = Prompt.ask("Source Group ID to merge from (e.g. G02)").strip()
                if not src or src.lower() in ("c", "cancel"):
                    continue
                tgt = Prompt.ask("Target Group ID to merge into (e.g. G01)").strip()
                if not tgt or tgt.lower() in ("c", "cancel"):
                    continue
                try:
                    plan = PlanEditor.merge_groups(plan, src, tgt, units)
                    console.print(f"[bold green]✔ Groups {src} merged into {tgt} successfully.[/bold green]")
                except PlanValidationError as e:
                    console.print(f"[bold red]Merge rejected:[/bold red] {e}")

            elif choice == "4":
                console.print(f"Available groups: {', '.join(f'[{g.id}: {g.title}]' for g in plan.groups)}")
                grp = Prompt.ask("Group ID to split (e.g. G01)").strip()
                if not grp or grp.lower() in ("c", "cancel"):
                    continue

                target_grp = next((g for g in plan.groups if g.id == grp), None)
                if target_grp:
                    console.print(f"Change units currently in {grp}: {', '.join(target_grp.unit_ids)}")

                existing_ids = [g.id for g in plan.groups]
                next_num = 1
                while f"G{next_num:02d}" in existing_ids:
                    next_num += 1
                suggested_new_id = f"G{next_num:02d}"

                new_id = Prompt.ask(f"New Group ID", default=suggested_new_id).strip()
                uids_str = Prompt.ask("Unit IDs for new group (comma-separated, e.g. U002, U003)").strip()
                uids = [u.strip() for u in uids_str.split(",") if u.strip()]
                new_title = Prompt.ask("New group title").strip()
                new_type = Prompt.ask("Conventional commit type (feat, fix, refactor, test, docs, etc.)", default="feat").strip()
                suggested_msg = f"{new_type}: {new_title.lower()}" if new_title else "feat: new feature"
                new_msg = Prompt.ask("Commit message", default=suggested_msg).strip()
                try:
                    plan = PlanEditor.split_group(plan, grp, new_id, uids, new_title, new_msg, new_type, units)
                    console.print(f"[bold green]✔ Group {new_id} split from {grp} successfully.[/bold green]")
                except PlanValidationError as e:
                    console.print(f"[bold red]Split rejected:[/bold red] {e}")

            elif choice == "5":
                console.print(f"Available groups: {', '.join(f'[{g.id}: {g.title}]' for g in plan.groups)}")
                grp = Prompt.ask("Group ID to edit (e.g. G01)").strip()
                if not grp or grp.lower() in ("c", "cancel"):
                    continue

                target_grp = next((g for g in plan.groups if g.id == grp), None)
                default_msg = target_grp.message if target_grp else ""
                new_msg = Prompt.ask("New Conventional Commit message", default=default_msg).strip()
                try:
                    plan = PlanEditor.edit_message(plan, grp, new_msg, units)
                    console.print("[bold green]✔ Commit message updated successfully.[/bold green]")
                except PlanValidationError as e:
                    console.print(f"[bold red]Edit rejected:[/bold red] {e}")

            elif choice == "6":
                console.print(f"Available groups: {', '.join(f'[{g.id}: {g.title}]' for g in plan.groups)}")
                grp = Prompt.ask("Group ID to update dependencies for (e.g. G02)").strip()
                if not grp or grp.lower() in ("c", "cancel"):
                    continue

                target_grp = next((g for g in plan.groups if g.id == grp), None)
                default_deps = ", ".join(target_grp.depends_on) if target_grp and target_grp.depends_on else ""
                deps_str = Prompt.ask("Prerequisite group IDs (comma-separated, or empty for none)", default=default_deps).strip()
                deps = [d.strip() for d in deps_str.split(",") if d.strip()]
                try:
                    plan = PlanEditor.set_dependencies(plan, grp, deps, units)
                    console.print("[bold green]✔ Dependencies updated successfully.[/bold green]")
                except PlanValidationError as e:
                    console.print(f"[bold red]Update rejected:[/bold red] {e}")

            elif choice == "7":
                with console.status(f"[cyan]Requesting fresh proposal from {REQUIRED_MODEL}...[/cyan]"):
                    try:
                        plan = planner.plan(units)
                        console.print("[bold green]✔ Fresh plan generated from local AI model.[/bold green]")
                    except CommitCraftError as e:
                        console.print(f"[bold red]AI Planning Failed:[/bold red] {e}")

            elif choice == "8":
                target_inspect = Prompt.ask("Enter Unit ID (e.g. U001), Group ID (e.g. G01), or 'all' to view diffs").strip()
                if target_inspect.lower() == "all":
                    ui.display_diff(units)
                elif target_inspect.upper() in [g.id for g in plan.groups]:
                    grp_match = next(g for g in plan.groups if g.id == target_inspect.upper())
                    grp_units = [u for u in units if u.id in grp_match.unit_ids]
                    ui.display_diff(grp_units)
                elif any(u.id == target_inspect.upper() for u in units):
                    matching_unit = next(u for u in units if u.id == target_inspect.upper())
                    ui.display_diff([matching_unit])
                else:
                    console.print(f"[yellow]Unit or group '{target_inspect}' not found.[/yellow]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation aborted by user. Working tree and branch untouched.[/yellow]")
        raise typer.Exit(code=0)

    # 6. Execute commit construction and guarded branch update
    try:
        with console.status("[cyan]Creating Git commit objects and updating branch...[/cyan]"):
            exec_res = executor.execute(preflight, snapshot, approval_confirmed=True)
    except CommitCraftError as e:
        console.print(f"\n[bold red]Execution error:[/bold red] {e}")
        raise typer.Exit(code=1)

    console.print("\n[bold green]══════════════ EXECUTION COMPLETE ══════════════[/bold green]")
    console.print(f"[bold]Branch:[/bold] [cyan]{exec_res.branch_ref}[/cyan]")
    console.print(f"[bold]New HEAD:[/bold] [yellow]{exec_res.new_head[:8]}[/yellow]")
    console.print(f"[bold]Verified Tree:[/bold] [green]{exec_res.final_tree[:8]}[/green] [dim](Matches exact snapshot)[/dim]\n")

    for idx, (commit_sha, grp) in enumerate(zip(exec_res.created_commits, exec_res.ordered_groups), 1):
        branch_name = exec_res.created_branches.get(grp.id, "")
        branch_info = f" [cyan]({branch_name})[/cyan]" if branch_name else ""
        console.print(f"  [{idx}/{len(exec_res.created_commits)}] [yellow]{commit_sha[:8]}[/yellow]{branch_info} {grp.message}")

    # 7. Generate individual PR descriptions for each group
    prs = PRDescriptionGenerator.generate_individual_prs(
        plan, exec_res, units, branch_names=exec_res.created_branches
    )
    saved_paths = PRDescriptionGenerator.save_individual_prs(
        prs,
        repo_root=Path(repo.working_tree_dir) if repo.working_tree_dir else Path(repo.git_dir).parent,
        git_dir=Path(repo.git_dir),
        custom_path=Path(custom_pr_path) if custom_pr_path else None,
    )
    primary_pr_display = str(saved_paths[0]) if saved_paths else ""
    console.print(f"\n[bold green]✔ PR Description generated and saved to:[/bold green] [white]{primary_pr_display}[/white]")
    if len(saved_paths) > 1:
        console.print(f"[bold cyan]All individual PR descriptions ({len(saved_paths)}):[/bold cyan]")
        for p in saved_paths:
            console.print(f"  • [white]{p}[/white]")

    if exec_res.created_branches:
        console.print("\n[bold cyan]Individual Git branches created for PR submission:[/bold cyan]")
        for grp in exec_res.ordered_groups:
            b_name = exec_res.created_branches.get(grp.id)
            if b_name:
                console.print(f"  • [bold white]{b_name}[/bold white] [dim]({grp.title})[/dim]")

    pr_note = f"Review the generated PR descriptions in [bold white]{primary_pr_display}[/bold white]."
    if len(saved_paths) > 1:
        prs_dir = saved_paths[0].parent
        pr_note = f"Review individual PR descriptions in [bold white]{prs_dir}[/bold white] (e.g. {saved_paths[0].name})."

    console.print(
        Panel(
            f"[bold green]CommitCraft successfully created {len(exec_res.created_commits)} logical commit(s) "
            f"and {len(exec_res.created_branches)} PR branch(es).[/bold green]\n"
            f"[dim]• Run [bold white]git log -n {len(exec_res.created_commits)}[/bold white] to review your clean history.\n"
            f"• {pr_note}[/dim]",
            border_style="green",
            box=box.ROUNDED,
            expand=False,
        )
    )

    # 8. Submit Pull Requests via GitHub CLI (gh)
    target_base = base_branch or state.branch_name
    branches_to_submit = [
        (grp, exec_res.created_branches[grp.id])
        for grp in exec_res.ordered_groups
        if grp.id in exec_res.created_branches and exec_res.created_branches[grp.id] != target_base
    ]

    if branches_to_submit:
        should_send = False
        if send_pr is not None:
            should_send = send_pr
        elif not auto_approve:
            try:
                should_send = Confirm.ask(
                    f"\nDo you want to send pull request(s) to the base branch '[cyan]{target_base}[/cyan]'?",
                    default=False,
                )
            except (EOFError, KeyboardInterrupt):
                should_send = False

        if should_send:
            repo_root = Path(repo.working_tree_dir) if repo.working_tree_dir else Path(repo.git_dir).parent
            pr_sender = PRSender(repo_root=repo_root, runner=runner)

            if not pr_sender.is_gh_available():
                console.print("\n[bold red]✘ GitHub CLI ('gh') is not installed or not found in PATH.[/bold red]")
                console.print("[dim]Install gh (https://cli.github.com/) and run 'gh auth login' to send pull requests automatically.[/dim]")
            else:
                remote = pr_sender.get_remote()
                if not remote:
                    console.print("\n[bold red]✘ No Git remote found in repository. Cannot push branches or send PRs.[/bold red]")
                    console.print("[dim]Add a remote using 'git remote add origin <url>' before sending PRs.[/dim]")
                else:
                    console.print(f"\n[bold cyan]Pushing {len(branches_to_submit)} branch(es) to remote '{remote}' and creating pull request(s)...[/bold cyan]")

                    # Map each group to its saved PR markdown file
                    pr_file_map: dict[str, Path] = {}
                    for grp in exec_res.ordered_groups:
                        for sp in saved_paths:
                            if sp.name == f"PR_{grp.id}.md" or f"_{grp.id}" in sp.stem or len(saved_paths) == 1:
                                pr_file_map[grp.id] = sp
                                break

                    # Clean PR markdown files and text for GitHub submission (strip title and body instructions)
                    clean_prs: dict[str, str] = {
                        grp.id: PRDescriptionGenerator.clean_pr_markdown_for_gh(prs[grp.id])
                        for grp in exec_res.ordered_groups
                        if grp.id in prs
                    }
                    for grp_id, clean_content in clean_prs.items():
                        sp = pr_file_map.get(grp_id)
                        if sp and sp.is_file():
                            sp.write_text(clean_content, encoding="utf-8")

                    created_prs_count = 0
                    for grp, b_name in branches_to_submit:
                        # 1. Push branch to remote first
                        push_ok = False
                        with console.status(f"[cyan]Pushing branch '{b_name}' to {remote}...[/cyan]"):
                            try:
                                pr_sender.push_branch(branch_name=b_name, remote=remote)
                                push_ok = True
                                console.print(f"  [bold green]✔ Pushed branch:[/bold green] [cyan]{b_name}[/cyan] -> [dim]{remote}/{b_name}[/dim]")
                            except Exception as e:
                                console.print(f"  [bold red]✘ Failed to push branch '{b_name}':[/bold red] {e}")

                        if not push_ok:
                            console.print(f"  [yellow]Skipping PR creation for '{b_name}' because push failed.[/yellow]")
                            continue

                        # 2. Create pull request via gh
                        pr_file = pr_file_map.get(grp.id)
                        pr_body = clean_prs.get(grp.id, prs.get(grp.id))
                        with console.status(f"[cyan]Creating PR for '{b_name}' -> '{target_base}' via gh...[/cyan]"):
                            success, pr_url, err_msg = pr_sender.create_pr(
                                branch_name=b_name,
                                base_branch=target_base,
                                title=grp.message,
                                body_file=pr_file,
                                body=pr_body,
                            )

                        if success:
                            created_prs_count += 1
                            console.print(f"  [bold green]✔ PR Created:[/bold green] [white]{pr_url or b_name}[/white]")
                        else:
                            if err_msg and "already exists" in err_msg.lower():
                                console.print(f"  [yellow]ℹ PR for '{b_name}' already exists:[/yellow] {err_msg}")
                            else:
                                console.print(f"  [bold red]✘ Failed to create PR for '{b_name}':[/bold red] {err_msg}")

                    if created_prs_count > 0:
                        console.print(f"\n[bold green]✔ Successfully created {created_prs_count} pull request(s) on GitHub![/bold green]\n")
        elif not auto_approve and send_pr is False:
            console.print("[dim]Skipping remote push and pull request creation.[/dim]")



def main() -> None:
    """CLI entrypoint with safe interrupt handling."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation aborted by user.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
