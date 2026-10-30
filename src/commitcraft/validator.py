"""Validation for AI proposals and user plan modifications."""

from commitcraft.change_units import ChangeUnit
from commitcraft.dependencies import DependencyResolver
from commitcraft.errors import DependencyError, PlanValidationError
from commitcraft.schemas import CONVENTIONAL_COMMIT_REGEX, PlanProposal


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

            # Commit message validation
            msg = g.message.strip()
            if not msg:
                errors.append(f"Group '{g.id}' has an empty commit message.")
            elif not CONVENTIONAL_COMMIT_REGEX.match(msg):
                errors.append(
                    f"Group '{g.id}' commit message '{msg}' does not conform to Conventional Commits "
                    "(e.g. 'type(scope): summary')."
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
        try:
            DependencyResolver.resolve_order(plan.groups)
        except DependencyError as e:
            errors.append(str(e))

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
