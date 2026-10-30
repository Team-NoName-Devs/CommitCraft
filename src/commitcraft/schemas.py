"""Pydantic data schemas for CommitCraft plans and proposals."""

import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


COMMIT_TYPES = (
    "feat",
    "fix",
    "refactor",
    "perf",
    "test",
    "docs",
    "build",
    "ci",
    "chore",
    "style",
    "revert",
)
CommitType = Literal[
    "feat",
    "fix",
    "refactor",
    "perf",
    "test",
    "docs",
    "build",
    "ci",
    "chore",
    "style",
    "revert",
]

CONVENTIONAL_COMMIT_REGEX = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|build|ci|chore|style|revert)(\([a-zA-Z0-9_\-\./]+\))?!?: .+$"
)


class CommitGroupProposal(BaseModel):
    """A proposed logical commit group containing one or more ChangeUnits."""

    id: str = Field(description="Group ID, e.g. G01, G02")
    unit_ids: list[str] = Field(description="List of assigned ChangeUnit IDs, e.g. ['U001', 'U002']")
    title: str = Field(description="Short title for this group")
    explanation: str = Field(description="Evidence-based rationale for grouping these units together")
    commit_type: str = Field(description="Conventional commit type (feat, fix, refactor, test, docs, etc.)")
    scope: Optional[str] = Field(default=None, description="Optional commit scope, e.g. auth, parser")
    message: str = Field(description="Full conventional commit message, e.g. feat(auth): add login route")
    depends_on: list[str] = Field(
        default_factory=list,
        description="IDs of prerequisite groups that must be committed before this group",
    )

    @field_validator("commit_type")
    @classmethod
    def validate_commit_type(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if "(" in v_clean:
            base_type = v_clean.split("(")[0].strip()
            if base_type in COMMIT_TYPES:
                return base_type
        if v_clean.endswith(":"):
            base_type = v_clean[:-1].strip()
            if base_type in COMMIT_TYPES:
                return base_type

        if v_clean not in COMMIT_TYPES:
            raise ValueError(f"Invalid commit type '{v}'. Must be one of: {', '.join(COMMIT_TYPES)}")
        return v_clean

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("Commit message cannot be empty.")
        first_line = v_clean.splitlines()[0].strip()
        if not CONVENTIONAL_COMMIT_REGEX.match(first_line):
            raise ValueError(
                f"Commit message '{v_clean}' does not match Conventional Commits format "
                "(e.g. 'feat(scope): concise description')."
            )
        return v_clean


class PlanProposal(BaseModel):
    """Complete semantic commit grouping plan proposed by AI or edited by user."""

    version: str = Field(default="1.0", description="Plan schema version")
    groups: list[CommitGroupProposal] = Field(description="List of proposed commit groups")
    summary: Optional[str] = Field(default=None, description="Overview of the changes")

    @field_validator("groups")
    @classmethod
    def validate_groups_non_empty(cls, v: list[CommitGroupProposal]) -> list[CommitGroupProposal]:
        if not v:
            raise ValueError("Plan must contain at least one commit group.")
        return v
