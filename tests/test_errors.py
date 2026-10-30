"""Tests for custom exception hierarchy and error string formatting."""

import pytest
from commitcraft.errors import (
    BranchMovementError,
    CommitCraftError,
    ConfigurationError,
    DependencyCycleError,
    DependencyError,
    ExecutionError,
    GitCommandError,
    HookError,
    IndexSyncError,
    InvalidDependencyError,
    ModelResponseError,
    ModelUnavailableError,
    PlanValidationError,
    RepositoryError,
    SnapshotError,
    StaleSnapshotError,
    TreeMismatchError,
    UnsupportedRepositoryStateError,
)


def test_commitcraft_error_str_formatting():
    """Test CommitCraftError string formatting with and without resolution."""
    err_simple = CommitCraftError("Simple error message")
    assert str(err_simple) == "Simple error message"
    assert err_simple.resolution is None

    err_with_res = CommitCraftError("Something failed", resolution="Try doing X")
    assert "Something failed" in str(err_with_res)
    assert "-> Recommendation: Try doing X" in str(err_with_res)
    assert err_with_res.resolution == "Try doing X"


def test_git_command_error_attributes_and_str():
    """Test GitCommandError attributes and rich error message."""
    cmd_err = GitCommandError(
        command=["commit", "-m", "test"],
        exit_code=128,
        stderr="fatal: empty ident name",
        stdout="some standard output",
        resolution="Set git user.name and user.email",
    )
    assert cmd_err.command == ["commit", "-m", "test"]
    assert cmd_err.exit_code == 128
    assert cmd_err.stderr == "fatal: empty ident name"
    assert cmd_err.stdout == "some standard output"
    assert cmd_err.resolution == "Set git user.name and user.email"

    err_str = str(cmd_err)
    assert "Git command failed (exit code 128): git commit -m test" in err_str
    assert "fatal: empty ident name" in err_str
    assert "-> Recommendation: Set git user.name and user.email" in err_str


def test_error_class_hierarchy():
    """Verify that all domain-specific errors inherit from CommitCraftError."""
    assert issubclass(RepositoryError, CommitCraftError)
    assert issubclass(UnsupportedRepositoryStateError, RepositoryError)
    assert issubclass(GitCommandError, CommitCraftError)
    assert issubclass(SnapshotError, CommitCraftError)
    assert issubclass(TreeMismatchError, SnapshotError)
    assert issubclass(ModelUnavailableError, CommitCraftError)
    assert issubclass(ModelResponseError, CommitCraftError)
    assert issubclass(PlanValidationError, CommitCraftError)
    assert issubclass(DependencyError, CommitCraftError)
    assert issubclass(DependencyCycleError, DependencyError)
    assert issubclass(InvalidDependencyError, DependencyError)
    assert issubclass(ExecutionError, CommitCraftError)
    assert issubclass(BranchMovementError, ExecutionError)
    assert issubclass(StaleSnapshotError, ExecutionError)
    assert issubclass(IndexSyncError, ExecutionError)
    assert issubclass(ConfigurationError, CommitCraftError)
    assert issubclass(HookError, CommitCraftError)
