# Contributing to CommitCraft

Thank you for your interest in contributing to **CommitCraft**! We welcome contributions that align with our core engineering principles and architectural invariants.

---

## 1. Core Principles

1. **Local AI Only**: CommitCraft's core planning workflow requires Ollama running `llama3.2:3b`. There is no paid API dependency and no deterministic fallback planner.
2. **Git Mathematical Invariants**: The final Git tree of the created commit sequence must match the exact reviewed target snapshot tree.
3. **Safety First**: CommitCraft must never silently discard or mutate the user's working tree changes.
4. **Isolated Replay**: All preflight simulations and patch applications must use isolated Git indexes (`GIT_INDEX_FILE`), leaving the user's real `.git/index` pristine until execution.
5. **No Blind Trust in LLMs**: Python strictly validates all AI-generated proposals for identifier completeness, dependency cycles, commit syntax, and patch applicability.

---

## 2. Development Setup

### Prerequisites

- **Python**: `>= 3.11` (Python 3.12 recommended)
- **Git**: `>= 2.30`
- **uv**: Recommended fast package installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Ollama**: [Download Ollama](https://ollama.com) and pull `llama3.2:3b`

### Installation

```bash
# Clone the repository
git clone https://github.com/Team-NoName-Devs/CommitCraft.git
cd CommitCraft

# Create virtual environment with Python 3.12
uv venv --python 3.12
source .venv/bin/activate

# Install editable package with development dependencies
uv pip install -e ".[dev]"
```

---

## 3. Running Tests

All unit, integration, and end-to-end tests run with test fixtures and mocks. **No live Ollama instance or model download is required to run the test suite.**

```bash
# Run complete test suite
pytest

# Run tests with verbose output
pytest -v

# Run a specific test module
pytest tests/test_executor.py
```

---

## 4. Conventional Commit Messages

Every commit in CommitCraft must adhere to the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <short description>
```

### Supported Types:
- `feat`: New user-facing feature or CLI capability
- `fix`: Bug fix
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding or correcting tests
- `docs`: Documentation updates
- `chore`: Build system, packaging, or dependency maintenance
- `perf`: Performance improvements

### Examples:
- `feat(snapshot): support executable mode tracking in isolated index`
- `fix(executor): prevent race condition during guarded update-ref`
- `test(planner): add test case for bounded correction loops`

---

## 5. Pull Request Guidelines

1. Ensure all 50+ unit and integration tests pass cleanly (`pytest`).
2. Verify that `commitcraft inspect` runs without errors on a test repo.
3. Ensure no model-generated patch strings replace Git-native unified diffs.
4. Document any new CLI options or configuration parameters in `README.md`.
