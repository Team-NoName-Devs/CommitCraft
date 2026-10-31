"""Validation for AI proposals and user plan modifications."""

from pathlib import Path
from commitcraft.change_units import ChangeUnit
from commitcraft.dependencies import DependencyResolver
from commitcraft.errors import DependencyError, PlanValidationError
from commitcraft.schemas import CONVENTIONAL_COMMIT_REGEX, PlanProposal, parse_conventional_commit


class PlanValidator:
    """Strictly validates commit plans against the change inventory and integrity invariants."""

    @classmethod
    def validate(cls, plan: PlanProposal, inventory: list[ChangeUnit]) -> list[str]:
        """Validate a plan against inventory and invariants. Returns list of error messages."""
        errors: list[str] = []

        if not plan.groups:
            errors.append("Plan contains no commit groups.")
            return errors

        inventory_ids = {u.id for u in inventory}
        unit_map = {u.id: u for u in inventory}
        assigned_ids: list[str] = []
        group_ids: set[str] = set()

        for g in plan.groups:
            # Group ID uniqueness
            if g.id in group_ids:
                errors.append(f"Duplicate group identifier '{g.id}'.")
            group_ids.add(g.id)

            # Empty groups
            if not g.unit_ids:
                errors.append(f"Group '{g.id}' ({g.title}) contains no change units.")

            # Commit message and type/scope coherence validation
            msg = g.message.strip()
            if not msg:
                errors.append(f"Group '{g.id}' has an empty commit message.")
            else:
                first_line = msg.splitlines()[0].strip()
                if not CONVENTIONAL_COMMIT_REGEX.match(first_line):
                    errors.append(
                        f"Group '{g.id}' commit message '{msg}' does not conform to Conventional Commits "
                        "(e.g. 'type(scope): summary')."
                    )
                else:
                    c_type, c_scope, _, _ = parse_conventional_commit(first_line)
                    if c_type and g.commit_type and g.commit_type.lower() != c_type:
                        errors.append(
                            f"Group '{g.id}' commit_type '{g.commit_type}' does not match message prefix '{c_type}'."
                        )
                    if g.scope and c_scope and g.scope.lower() != c_scope.lower():
                        errors.append(
                            f"Group '{g.id}' scope '{g.scope}' does not match message scope '{c_scope}'."
                        )
                    elif g.scope and not c_scope:
                        errors.append(
                            f"Group '{g.id}' specifies scope '{g.scope}', but commit message does not include it."
                        )
                    if g.scope and g.commit_type and g.scope.lower() == g.commit_type.lower():
                        errors.append(
                            f"Group '{g.id}' has redundant scope '{g.scope}' matching commit_type. Omit the scope or specify the component name."
                        )

            # Semantic type vs change unit validation
            group_units = [unit_map[uid] for uid in g.unit_ids if uid in unit_map]
            if group_units:
                def is_test_unit(u: ChangeUnit) -> bool:
                    p = Path(u.path)
                    stem = p.stem.lower()
                    return (
                        u.type_hint == "test"
                        or "tests" in p.parts
                        or "test" in p.parts
                        or stem.startswith("test_")
                        or stem.endswith("_test")
                    )

                def is_doc_unit(u: ChangeUnit) -> bool:
                    p = Path(u.path)
                    stem = p.stem.lower()
                    return (
                        u.type_hint == "docs"
                        or "docs" in p.parts
                        or p.suffix.lower() in (".md", ".rst", ".adoc")
                        or stem in ("license", "contributing", "readme")
                    )

                def is_ci_unit(u: ChangeUnit) -> bool:
                    p = Path(u.path)
                    return u.type_hint == "ci" or ".github" in p.parts or ".gitlab-ci.yml" in p.parts

                if all(is_test_unit(u) for u in group_units):
                    if g.commit_type.lower() in ("feat", "fix", "docs", "build", "ci"):
                        errors.append(
                            f"Group '{g.id}' contains only test files but has commit_type '{g.commit_type}'. "
                            "Groups containing only tests must have commit_type 'test'."
                        )
                elif all(is_doc_unit(u) for u in group_units):
                    if g.commit_type.lower() in ("feat", "fix", "test"):
                        errors.append(
                            f"Group '{g.id}' contains only documentation files but has commit_type '{g.commit_type}'. "
                            "Groups containing only documentation must have commit_type 'docs'."
                        )
                elif all(is_ci_unit(u) for u in group_units):
                    if g.commit_type.lower() in ("feat", "fix", "test", "docs"):
                        errors.append(
                            f"Group '{g.id}' contains only CI workflow files but has commit_type '{g.commit_type}'. "
                            "Groups containing only CI changes must have commit_type 'ci'."
                        )

            for uid in g.unit_ids:
                # Unknown unit ID
                if uid not in inventory_ids:
                    errors.append(f"Group '{g.id}' references unknown change unit ID '{uid}'.")
                assigned_ids.append(uid)

        # Duplicate assignments across groups
        seen: set[str] = set()
        duplicates: set[str] = set()
        for uid in assigned_ids:
            if uid in seen:
                duplicates.add(uid)
            seen.add(uid)

        if duplicates:
            errors.append(f"Change units assigned more than once: {sorted(duplicates)}.")

        # Missing unit assignments
        unassigned = inventory_ids - set(assigned_ids)
        if unassigned:
            errors.append(f"Change units missing from plan (unassigned): {sorted(unassigned)}.")

        # Dependency resolution and cycle checks
        ordered_groups = []
        try:
            ordered_groups = DependencyResolver.resolve_order(plan.groups)
        except DependencyError as e:
            errors.append(str(e))

        # Check for file creation ordering invariant across groups
        if ordered_groups and not errors:
            unit_map = {u.id: u for u in inventory}
            add_creators: dict[str, str] = {}
            for g in ordered_groups:
                for uid in g.unit_ids:
                    u = unit_map.get(uid)
                    if u and u.kind == "add":
                        add_creators[u.path] = g.id

            if add_creators:
                order_index = {g.id: idx for idx, g in enumerate(ordered_groups)}
                for g in ordered_groups:
                    for uid in g.unit_ids:
                        u = unit_map.get(uid)
                        if u and u.kind in ("modify", "delete"):
                            creator_id = add_creators.get(u.path)
                            if creator_id and creator_id != g.id:
                                if order_index[creator_id] > order_index[g.id]:
                                    errors.append(
                                        f"Group '{g.id}' {u.kind}s '{u.path}' before it is created in Group '{creator_id}'. "
                                        f"Group '{g.id}' must be ordered after '{creator_id}'."
                                    )

        return errors

    @classmethod
    def assert_valid(cls, plan: PlanProposal, inventory: list[ChangeUnit]) -> None:
        """Assert plan is valid or raise PlanValidationError with actionable details."""
        errors = cls.validate(plan, inventory)
        if errors:
            formatted = "\n  - " + "\n  - ".join(errors)
            raise PlanValidationError(
                f"Plan validation failed with {len(errors)} error(s):{formatted}",
                resolution="Revise group assignments, commit messages, or dependencies to satisfy invariants.",
            )
