# Skill: Check

Run the quality gate checklist before completing a phase.

## Automated checks (via devflow check)

- [ ] Ruff lint passes with zero errors
- [ ] All pytest tests pass
- [ ] No secrets detected in source files

## Manual checks (agent behavior)

- [ ] Type hints on all new/changed functions
- [ ] Docstrings on public functions
- [ ] No business logic in cli.py
- [ ] State persisted before phase transitions
- [ ] Commit messages follow conventional format
