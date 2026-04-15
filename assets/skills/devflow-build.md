# Skill: Build

Orchestrate a feature build through the devflow state machine.

## Workflow

1. **Plan** — Use the planner agent to break down the feature
2. **Review plan** — Validate the plan makes sense
3. **Implement** — Use the developer agent to write code
4. **Review** — Use the reviewer agent to check quality
5. **Fix** — Address any review feedback
6. **Gate** — Run devflow check for automated quality verification
7. **Done** — Feature complete

## State machine rules

- Each phase updates `.devflow/state.json` before starting the next
- If a phase fails, the feature can be resumed with `--resume`
- The gate phase must pass before marking done
- Blocked features can be unblocked from any previous state

## Context management

- Load only the files relevant to the current phase
- Don't carry implementation details into the review phase
- Each phase gets a fresh context with just what it needs
