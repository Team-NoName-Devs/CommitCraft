"""Dependency graph construction and topological commit ordering."""

from graphlib import CycleError, TopologicalSorter
from commitcraft.errors import DependencyCycleError, InvalidDependencyError
from commitcraft.schemas import CommitGroupProposal


class DependencyResolver:
    """Computes dependency-aware commit ordering using TopologicalSorter."""

    @classmethod
    def resolve_order(cls, groups: list[CommitGroupProposal]) -> list[CommitGroupProposal]:
        """Compute a valid topological order for commit groups.

        Raises InvalidDependencyError on missing or self-dependencies.
        Raises DependencyCycleError if cycles are present.
        """
        group_map = {g.id: g for g in groups}
        graph: dict[str, set[str]] = {}

        for g in groups:
            # Self-dependency check
            if g.id in g.depends_on:
                raise InvalidDependencyError(
                    f"Group '{g.id}' ({g.title}) cannot depend on itself.",
                    resolution="Remove the self-referencing dependency.",
                )

            # Unknown dependency reference check
            for dep_id in g.depends_on:
                if dep_id not in group_map:
                    raise InvalidDependencyError(
                        f"Group '{g.id}' ({g.title}) references unknown dependency group '{dep_id}'.",
                        resolution=f"Ensure '{dep_id}' is a valid group ID among: {list(group_map.keys())}.",
                    )

            graph[g.id] = set(g.depends_on)

        # Topological sort
        sorter = TopologicalSorter(graph)
        try:
            sorted_ids = list(sorter.static_order())
        except CycleError as e:
            cycle_nodes = e.args[1] if len(e.args) > 1 else list(graph.keys())
            cycle_str = " -> ".join(str(n) for n in cycle_nodes)
            raise DependencyCycleError(
                f"Dependency cycle detected among commit groups: {cycle_str}",
                resolution="Edit group dependencies to remove the circular reference.",
            ) from e

        return [group_map[gid] for gid in sorted_ids if gid in group_map]
