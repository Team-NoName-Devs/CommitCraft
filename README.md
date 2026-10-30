# CommitCraft

Turn a messy Git working tree into logical, reviewable commits with local AI, user-controlled grouping, and automatic pull-request description generation.

## Overview

Developers routinely modify several files and implement multiple unrelated changes while working on one task. Their working tree gradually accumulates bug fixes, refactors, tests, documentation edits, and formatting adjustments. Eventually, they create one large commit containing all those changes, which is difficult to review, cherry-pick, or revert.

**CommitCraft** solves this by:
1. Analyzing the repository's intended changes (tracked modifications, staged changes, and untracked files).
2. Extracting independently addressable change units—including splitting independent hunks from the same text file.
3. Using a locally running language model (`llama3.2:3b` via Ollama) to propose cohesive, semantically grouped commits with Conventional Commit messages.
4. Enabling developers to interactively inspect and revise commit proposals (moving units, editing messages, reordering, managing dependencies).
5. Validating all proposals and replaying patches in an isolated Git index to mathematically prove **target tree equality**.
6. Creating real Git commit objects safely with explicit user approval and generating an editable PR description.

## Prerequisites

- **Python**: `>= 3.11` (Python 3.12 recommended)
- **Git**: installed and accessible in `PATH`
- **Ollama**: running locally at `http://localhost:11434` with model `llama3.2:3b`

### Setting up Ollama

```bash
# Start Ollama service (if not already running)
ollama serve

# Pull the required model
ollama pull llama3.2:3b

# Verify model availability
curl -s http://localhost:11434/api/tags | grep llama3.2:3b
```

## Installation

```bash
uv pip install -e ".[dev]"
# Or with standard pip:
python -m pip install -e ".[dev]"
```

## Quick Start

```bash
# Inspect repository and Ollama status
commitcraft inspect

# Run interactive commit splitting
commitcraft split
```

## License

MIT
