# Contributing to devflow-ai

Thanks for your interest! Here's how to get started.

## Setup

```bash
git clone https://github.com/JustineRaze/devflow-ai.git
cd devflow-ai
uv sync          # install dependencies
uv run pytest    # verify tests pass
```

## Development workflow

1. Create a branch: `git checkout -b feat/your-feature`
2. Make your changes
3. Run the quality gate: `uv run devflow check`
4. Commit with conventional format: `feat: description` / `fix: description`
5. Open a PR against `main`

## Code standards

- **Python 3.11+** — use modern syntax (`X | None`, `match`, built-in generics)
- **Type hints everywhere** — parameters and return types
- **Docstrings on public functions** — one-line summary, then details if needed
- **f-strings** — not `.format()`
- **pathlib.Path** — not `os.path`
- **`datetime.now(UTC)`** — not `datetime.utcnow()`

## Architecture rules

- `cli.py` — Typer commands only, zero business logic
- One file = one responsibility
- Data flows downward in the dependency graph
- State changes must be crash-safe (tmp + rename)

## Testing

- Write tests alongside code, not after
- Use `tmp_path` for all filesystem operations
- Test behavior, not implementation
- Class-based grouping: `TestFeatureTransitions`, `TestStatePersistence`

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new workflow definition
fix: handle empty description in build
refactor: extract phase transition logic
docs: update README quickstart
test: add edge cases for state machine
```

## Questions?

Open an issue — we'll figure it out together.
