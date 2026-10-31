"""Pydantic data schemas for CommitCraft plans and proposals."""

import re
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


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


def parse_conventional_commit(message: str) -> tuple[Optional[str], Optional[str], bool, str]:
    """Extract (commit_type, scope, is_breaking, description) from a conventional commit message.

    Returns (None, None, False, message) if message does not match.
    """
    if not message:
        return None, None, False, ""
    first_line = message.splitlines()[0].strip()
    match = CONVENTIONAL_COMMIT_REGEX.match(first_line)
    if not match:
        return None, None, False, first_line

    commit_type = match.group(1).lower()
    raw_scope = match.group(2)
    scope = None
    if raw_scope:
        scope = raw_scope.strip("()").strip().lower()

    header_prefix = first_line.split(":", 1)[0]
    is_breaking = "!" in header_prefix
    description = first_line.split(":", 1)[1].strip()
    return commit_type, scope, is_breaking, description


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

    @model_validator(mode="before")
    @classmethod
    def reconcile_raw_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_type = data.get("commit_type")
            raw_scope = data.get("scope")
            raw_msg = data.get("message")

            # Extract scope from commit_type if embedded e.g. "feat(auth)"
            if isinstance(raw_type, str) and "(" in raw_type and ")" in raw_type:
                parts = raw_type.split("(", 1)
                extracted_t = parts[0].strip().lower()
                extracted_s = parts[1].split(")", 1)[0].strip().lower()
                if extracted_t in COMMIT_TYPES:
                    data["commit_type"] = extracted_t
                    if not raw_scope:
                        data["scope"] = extracted_s

            # Strip redundant scope equal to commit_type (e.g. test(test) -> test)
            if isinstance(data.get("commit_type"), str) and isinstance(data.get("scope"), str):
                c_type = data["commit_type"].strip().lower()
                c_scope = data["scope"].strip().lower()
                if c_scope == c_type:
                    data["scope"] = None

            # Reconcile from message if present
            if isinstance(raw_msg, str) and raw_msg.strip():
                m_type, m_scope, is_breaking, desc = parse_conventional_commit(raw_msg)
                if m_type:
                    curr_type = str(data.get("commit_type", "")).strip().lower()
                    if not curr_type or (curr_type not in COMMIT_TYPES and m_type in COMMIT_TYPES):
                        data["commit_type"] = m_type
                    if not data.get("scope") and m_scope:
                        data["scope"] = m_scope

        return data

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

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_clean = v.strip().lower()
        if not v_clean:
            return None
        if v_clean.startswith("(") and v_clean.endswith(")"):
            v_clean = v_clean[1:-1].strip()
        v_clean = v_clean.replace(" ", "-").replace("_", "-")
        return v_clean or None

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

    @model_validator(mode="after")
    def ensure_coherence(self) -> "CommitGroupProposal":
        # Disallow redundant scope matching type
        if self.scope and self.scope.lower() == self.commit_type.lower():
            self.scope = None

        if self.message:
            m_type, m_scope, is_breaking, desc = parse_conventional_commit(self.message)
            if m_type:
                # Synchronize commit_type to match message type if message is valid conventional commit
                if m_type in COMMIT_TYPES and m_type != self.commit_type:
                    self.commit_type = m_type

                # Synchronize scope and message
                bang = "!" if is_breaking else ""
                lines = self.message.splitlines()
                rest = ("\n" + "\n".join(lines[1:])) if len(lines) > 1 else ""

                if self.scope and not m_scope:
                    # Message is missing scope, add it
                    self.message = f"{self.commit_type}({self.scope}){bang}: {desc}{rest}"
                elif m_scope and not self.scope:
                    # Group model missing scope, take from message
                    self.scope = m_scope
                elif self.scope and m_scope and self.scope != m_scope:
                    # Scope normalized/cleaned
                    self.message = f"{self.commit_type}({self.scope}){bang}: {desc}{rest}"

        return self


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
