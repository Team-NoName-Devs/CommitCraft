"""Custom exception hierarchy for CommitCraft."""

from typing import Optional


class CommitCraftError(Exception):
    """Base exception for all CommitCraft errors."""

    def __init__(self, message: str, resolution: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.resolution = resolution

    def __str__(self) -> str:
        if self.resolution:
            return f"{self.message}\n  -> Recommendation: {self.resolution}"
        return self.message


class RepositoryError(CommitCraftError):
    """Raised when repository discovery or inspection fails."""


class UnsupportedRepositoryStateError(RepositoryError):
    """Raised when the repository is in an unsupported state (e.g. merge in progress)."""


class GitCommandError(CommitCraftError):
    """Raised when a native Git subprocess command fails."""

    def __init__(
        self,
        command: list[str],
        exit_code: int,
        stderr: str,
        stdout: str = "",
        resolution: Optional[str] = None,
    ):
        cmd_str = " ".join(command)
        msg = f"Git command failed (exit code {exit_code}): git {cmd_str}\n{stderr.strip()}"
        super().__init__(msg, resolution)
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout


class SnapshotError(CommitCraftError):
    """Raised when capturing or replaying isolated snapshots fails."""


class TreeMismatchError(SnapshotError):
    """Raised when intermediate or final tree ID does not match expected target tree ID."""


class ModelUnavailableError(CommitCraftError):
    """Raised when Ollama is unreachable or the required llama3.2:3b model is not installed."""


class ModelResponseError(CommitCraftError):
    """Raised when the model returns an HTTP error, malformed output, or invalid schema."""


class PlanValidationError(CommitCraftError):
    """Raised when a proposed plan fails semantic assignment, commit message, or dependency rules."""


class DependencyError(CommitCraftError):
    """Base error for dependency resolution."""


class DependencyCycleError(DependencyError):
    """Raised when proposed commit groups contain circular dependencies."""


class InvalidDependencyError(DependencyError):
    """Raised when a group references a non-existent or self dependency."""


class ExecutionError(CommitCraftError):
    """Raised during preflight, commit creation, or branch update."""


class BranchMovementError(ExecutionError):
    """Raised when the branch moved concurrently before guarded update."""


class StaleSnapshotError(ExecutionError):
    """Raised when working tree changes were detected after snapshot capture."""


class IndexSyncError(ExecutionError):
    """Raised when the branch updated but index synchronization failed."""


class ConfigurationError(CommitCraftError):
    """Raised when application configuration is invalid."""


class HookError(CommitCraftError):
    """Raised when Git hook installation or removal fails."""
