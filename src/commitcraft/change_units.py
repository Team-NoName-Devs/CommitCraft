"""Change unit definitions and representations."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ChangeUnit:
    """An independently addressable unit of change (a whole file or a single hunk)."""

    id: str
    path: str
    kind: str  # 'add', 'delete', 'modify', 'binary', 'mode_change'
    summary: str
    hunk_header: Optional[str]
    added_lines: int
    removed_lines: int
    is_binary: bool
    is_splittable: bool
    excerpt: str
    patch_text: str  # Immutable native unified diff patch
    scope_hint: Optional[str] = None
    context_info: Optional[str] = None

    def to_prompt_dict(self) -> dict:
        """Compact dictionary representation formatted for LLM prompt context."""
        data = {
            "id": self.id,
            "path": self.path,
            "kind": self.kind,
            "summary": self.summary,
            "hunk_header": self.hunk_header or "",
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "is_binary": self.is_binary,
            "excerpt": self.excerpt,
        }
        if self.scope_hint:
            data["scope_hint"] = self.scope_hint
        if self.context_info:
            data["context_info"] = self.context_info
        return data
