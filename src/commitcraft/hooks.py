"""Optional, reversible Git hook integration."""

import os
from pathlib import Path
import shutil
from typing import Optional

from commitcraft.errors import HookError


HOOK_MARKER = "# CommitCraft pre-commit advisory hook"

HOOK_SCRIPT_TEMPLATE = f"""#!/bin/sh
{HOOK_MARKER}
# This hook checks if there are many staged changes and reminds the developer
# that CommitCraft is available to split them into cohesive, reviewable commits.

STAGED_COUNT=$(git diff --cached --name-only | wc -l)
if [ "$STAGED_COUNT" -gt 3 ]; then
    echo "\\033[1;36m[CommitCraft]\\033[0m Notice: You have $STAGED_COUNT staged files."
    echo "\\033[1;36m[CommitCraft]\\033[0m Tip: Run 'commitcraft split' to organize them into logical Conventional Commits."
fi
exit 0
"""


class HookManager:
    """Manages installation and clean removal of Git pre-commit hooks."""

    def __init__(self, git_dir: Path):
        self.git_dir = Path(git_dir).resolve()
        self.hooks_dir = self.git_dir / "hooks"
        self.hook_file = self.hooks_dir / "pre-commit"
        self.backup_file = self.hooks_dir / "pre-commit.commitcraft.bak"

    def is_installed(self) -> bool:
        """Check if CommitCraft hook is currently installed."""
        if not self.hook_file.is_file():
            return False
        try:
            content = self.hook_file.read_text(encoding="utf-8")
            return HOOK_MARKER in content
        except Exception:
            return False

    def install(self) -> Path:
        """Install CommitCraft advisory pre-commit hook safely."""
        self.hooks_dir.mkdir(parents=True, exist_ok=True)

        if self.is_installed():
            return self.hook_file

        # Preserve existing non-commitcraft hook
        if self.hook_file.is_file():
            shutil.copy2(self.hook_file, self.backup_file)

        try:
            with open(self.hook_file, "w", encoding="utf-8") as f:
                f.write(HOOK_SCRIPT_TEMPLATE)
            # Make executable
            self.hook_file.chmod(self.hook_file.stat().st_mode | 0o755)
        except Exception as e:
            raise HookError(
                f"Failed to install Git hook: {e}",
                resolution="Check file permissions in .git/hooks directory.",
            ) from e

        return self.hook_file

    def remove(self) -> bool:
        """Remove CommitCraft hook and restore any previous backup."""
        if not self.hook_file.exists():
            return False

        if not self.is_installed():
            raise HookError(
                "Active pre-commit hook was not installed by CommitCraft.",
                resolution="Inspect .git/hooks/pre-commit manually before modifying.",
            )

        self.hook_file.unlink()

        # Restore backup if available
        if self.backup_file.is_file():
            shutil.move(str(self.backup_file), str(self.hook_file))

        return True
