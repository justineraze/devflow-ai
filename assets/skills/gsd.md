# Skill: GSD (Get Stuff Done)

Rules for maintaining fresh context and avoiding context rot.

## Principles

1. **Fresh context per phase** — Don't carry stale information between phases.
   Each phase should load only what it needs.

2. **Read before modify** — Always read a file's current state before editing.
   Don't assume you know what's in it from a previous phase.

3. **Atomic commits** — One logical change per commit. Don't batch unrelated
   changes.

4. **Verify after change** — Run tests after every code change, not just at
   the end.

5. **State first** — Persist state to .devflow/state.json before starting
   any potentially failing operation.

## Anti-patterns to avoid

- Loading the entire codebase into context
- Carrying implementation details from plan phase to review phase
- Making multiple changes before verifying any of them
- Relying on memory instead of reading current file state
