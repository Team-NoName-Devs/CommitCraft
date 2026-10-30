"""Tests for dependency resolution and topological ordering."""

import pytest
from commitcraft.dependencies import DependencyResolver
from commitcraft.errors import DependencyCycleError, InvalidDependencyError
from commitcraft.schemas import CommitGroupProposal


def make_group(gid: str, depends_on: list[str] = None) -> CommitGroupProposal:
    return CommitGroupProposal(
        id=gid,
        unit_ids=["U001"],
        title=f"Group {gid}",
        explanation="Testing",
        commit_type="feat",
        scope=None,
        message=f"feat: implement {gid}",
        depends_on=depends_on or [],
    )


def test_linear_dependencies():
    """Test resolving linear dependencies: G03 -> G02 -> G01."""
    g1 = make_group("G01")
    g2 = make_group("G02", depends_on=["G01"])
    g3 = make_group("G03", depends_on=["G02"])

    # Give them in reverse order
    ordered = DependencyResolver.resolve_order([g3, g2, g1])
    assert [g.id for g in ordered] == ["G01", "G02", "G03"]


def test_branching_dependencies():
    """Test branching graph: G03 depends on G01 and G02."""
    g1 = make_group("G01")
    g2 = make_group("G02")
    g3 = make_group("G03", depends_on=["G01", "G02"])

    ordered = DependencyResolver.resolve_order([g3, g1, g2])
    ordered_ids = [g.id for g in ordered]
    assert ordered_ids.index("G01") < ordered_ids.index("G03")
    assert ordered_ids.index("G02") < ordered_ids.index("G03")


def test_self_dependency_raises_error():
    """Test self-dependency raises InvalidDependencyError."""
    g1 = make_group("G01", depends_on=["G01"])
    with pytest.raises(InvalidDependencyError) as exc_info:
        DependencyResolver.resolve_order([g1])
    assert "cannot depend on itself" in str(exc_info.value)


def test_unknown_dependency_raises_error():
    """Test unknown dependency ID raises InvalidDependencyError."""
    g1 = make_group("G01", depends_on=["G99"])
    with pytest.raises(InvalidDependencyError) as exc_info:
        DependencyResolver.resolve_order([g1])
    assert "references unknown dependency group 'G99'" in str(exc_info.value)


def test_circular_dependency_raises_cycle_error():
    """Test cyclic dependency G01 -> G02 -> G01 raises DependencyCycleError."""
    g1 = make_group("G01", depends_on=["G02"])
    g2 = make_group("G02", depends_on=["G01"])

    with pytest.raises(DependencyCycleError) as exc_info:
        DependencyResolver.resolve_order([g1, g2])
    assert "Dependency cycle detected" in str(exc_info.value)
