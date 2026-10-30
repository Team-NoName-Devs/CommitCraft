# CommitCraft

> Turn a messy Git working tree into logical, reviewable commits with local AI, user-controlled grouping, and automatic pull-request description generation.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: >=3.11](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Model: llama3.2:3b](https://img.shields.io/badge/Ollama-llama3.2%3A3b-orange)](https://ollama.com/library/llama3.2)
[![Tests: 133 passed](https://img.shields.io/badge/tests-133%20passed-brightgreen)](tests/)

---

## 1. The Problem

Developers routinely modify several files and implement multiple unrelated changes while working on one task. Their working tree gradually accumulates bug fixes, refactors, tests, documentation edits, and formatting adjustments.

Eventually, they create **one monolithic commit** containing all those changes. Such commits are difficult to review, cherry-pick, bisect, and revert. While Git allows manually staging hunks via `git add -p`, it provides no semantic understanding of relationships between code, tests, and documentation.

## 2. The Solution

**CommitCraft** analyzes a repository's intended changes, extracts independently addressable change units (including splitting independent text hunks from the same file), and uses a local language model (**Llama 3.2 3B Instruct** running on **Ollama**) to propose logically related commit groups.

Developers inspect, reorder, and refine the proposal before CommitCraft constructs actual Git commits using isolated Git indexes, strictly proving **final-tree equality** before moving any branch pointer. Once verified, CommitCraft automatically creates dedicated Git branches and individual, editable Markdown pull-request descriptions for each group—following idiomatic open-source contribution practices.

---

## 3. Architecture Pipeline

```mermaid
flowchart TD
    A[User CLI: commitcraft split] --> B[Repository State Validation]
    B --> C[Isolated-Index Snapshot Capture]
    C --> D[Diff Extraction & Change-Unit Construction]
    D --> E[Mandatory Ollama / Llama 3.2 3B Planner]
    E --> F[Pydantic Schema & Invariant Validation]
    F --> G[Interactive Terminal Review & Editing]
    G --> H[Dependency Ordering via TopologicalSorter]
    H --> I[Isolated-Index Patch Replay & Preflight]
    I --> J[Target Tree Equality Verification]
    J --> K[Explicit User Approval Prompt]
    K --> L[Git commit-tree Construction]
    L --> M[Dedicated Branch Creation per Group]
    M --> N[Guarded update-ref Branch Installation]
    N --> O[Real Index Synchronization: read-tree HEAD]
    O --> P[Individual PR Descriptions: .commit_craft/prs/PR_*.md]
```

---

## 4. Engineering Principles & Invariants

1. **Mandatory Local AI Runtime**: Ollama running `llama3.2:3b` is a mandatory dependency for the core planning workflow. There is **no fallback planner**, no one-commit-per-file substitute, and no silent model substitution. If Ollama is unavailable, CommitCraft reports an actionable error and safely halts.
2. **Same-File Hunk Splitting**: Independent hunks from the same text file can be placed into separate commits (e.g. an authentication bug fix on line 2 and a formatting refactor on line 40).
3. **Mathematical Final-Tree Equality**: The final commit tree SHA must match the exact target snapshot tree SHA captured prior to planning.
4. **Pristine Real Index During Planning**: Isolated indexes (`GIT_INDEX_FILE`) are used for snapshot capture and patch replay. The user's actual `.git/index` and working files are never mutated during planning or preflight.
5. **No Blind Trust in LLMs**: Python code independently validates all unit assignments, unknown IDs, commit messages, and dependency graphs before any patch is replayed.

---

## 5. Prerequisites & System Requirements

- **Operating System**: Linux, macOS, or Windows (WSL recommended on Windows).
- **Python**: `>= 3.11` (Python 3.12 recommended).
- **Git**: Installed and accessible in system `PATH`.
- **Ollama**: Local AI runner.
- **Model**: `llama3.2:3b`.

---

## 6. Ollama Setup

Install and launch Ollama, then pull the mandatory model:

```bash
# 1. Start Ollama service (if not already running)
ollama serve

# 2. Pull the required Llama 3.2 3B Instruct model
ollama pull llama3.2:3b

# 3. Verify availability
curl -s http://localhost:11434/api/tags | grep llama3.2:3b
```

---

## 7. Installation

Install CommitCraft using `uv` or `pip`:

```bash
# Clone the repository
git clone https://github.com/Team-NoName-Devs/CommitCraft.git
cd CommitCraft

# Create and activate virtual environment
uv venv --python 3.12
source .venv/bin/activate

# Install in editable mode with development dependencies
uv pip install -e ".[dev]"
```

Verify installation:
```bash
commitcraft --help
```

---

## 8. CLI Usage Guide

### 8.1 Diagnostic Inspection (`commitcraft inspect`)

Displays repository health, active branch, HEAD commit, modified files, and Ollama model status:

```bash
commitcraft inspect
```

*Example Output:*
```text
CommitCraft Diagnostic Inspection

✔ Repository Root: /home/user/project
✔ Active Branch:   main (refs/heads/main)
✔ HEAD Commit:     8fbf780e
          Working Tree Changes          
 Category   Files                       
 Staged     0: None                     
 Unstaged   2: app.py, math_utils.py    
 Untracked  1: tests/test_auth.py       

Ollama Runtime Status
✔ Endpoint: http://localhost:11434 (Connected)
✔ Required Model: llama3.2:3b (Available)
```

### 8.2 Interactive Splitting (`commitcraft split`)

Analyzes working changes, requests semantic grouping from Ollama, enables interactive review, verifies tree equality, and installs real Git commits:

```bash
# Interactive mode with rich proposal review
commitcraft split

# Dry-run mode: verify plan & preflight without altering Git history
commitcraft split --dry-run

# Split with unified diffs displayed alongside plan
commitcraft split --diff
```

#### Interactive Review Options & Shortcuts:
- **[1 / a] Approve & Execute**: Runs preflight, verifies tree equality, and prompts for explicit confirmation.
- **[2 / m] Move a unit**: Reassign a change unit between groups with auto-detected source group.
- **[3 / g] Merge groups**: Combine two groups into one cohesive commit.
- **[4 / s] Split group**: Carve out specific change units into a new commit group with auto-suggested IDs.
- **[5 / e] Edit message/title**: Revise Conventional Commit message or title with prefilled current defaults.
- **[6 / d] Edit dependencies**: Add or update prerequisite dependencies between groups.
- **[7 / r] Request fresh AI proposal**: Re-prompt Ollama for an alternative grouping.
- **[8 / v] View Diff**: Inspect syntax-highlighted unified diff of any unit, group, or all changes.
- **[0 / q] Abort**: Cancel the operation safely without touching Git state.

### 8.3 Configuration (`commitcraft config`)

View or modify Ollama endpoint and timeout settings:

```bash
# View configuration
commitcraft config

# Update endpoint and read timeout
commitcraft config --url http://localhost:11434 --timeout 180.0
```

Environment variable overrides are also supported:
- `COMMITCRAFT_OLLAMA_URL`: Override Ollama base URL.
- `COMMITCRAFT_READ_TIMEOUT`: Override inference timeout (seconds).

### 8.4 Optional Advisory Git Hook (`commitcraft hook`)

Install an optional advisory pre-commit hook that alerts you when staging many files:

```bash
# Install hook
commitcraft hook install

# Remove hook (cleanly restores any previous backup)
commitcraft hook remove
```

---

## 9. Failure Handling & Recovery

- **Ollama Offline**: If Ollama is unreachable or `llama3.2:3b` is missing, CommitCraft provides the exact `ollama pull` command and cleanly halts.
- **Invalid Model Proposals**: If the model proposes missing units or invalid messages, CommitCraft feeds the exact validation errors back into Ollama for bounded correction attempts (up to 3 times). If exhausted, it aborts safely.
- **Concurrent Branch Movement**: If another process moves the branch during review, `git update-ref` aborts immediately to prevent overwriting newer history.
- **Index Synchronization Failure**: If the branch pointer updates but index synchronization fails, CommitCraft preserves full recovery state in `.git/COMMITCRAFT_RECOVERY.json` and provides the exact safe command to refresh your index:
  ```bash
  git read-tree HEAD
  ```

---

## 10. Running Automated Tests

All 128 unit, integration, and end-to-end tests run in complete isolation with mock transports:

```bash
pytest
```

---

## 11. License & AI Usage Disclosure

- **License**: Released under the [MIT License](LICENSE).
- **AI Usage**: Uses local **Llama 3.2 3B Instruct** via Ollama for semantic planning. No cloud APIs, proprietary models, or external services are used.
