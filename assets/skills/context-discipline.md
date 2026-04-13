---
name: context-discipline
description: Strict rules for loading only the context needed for the current phase. Applies to every phase.
---

# Context Discipline

**Context is the single biggest lever for agent quality and cost. Load what you
need, nothing more. Every unnecessary tool call wastes the user's money and
dilutes your focus.**

## Hard rules — no exceptions

### 1. The plan is your contract

The planner phase produces an explicit plan listing affected files. **That list
IS the scope.** Read only what the plan names, plus what's strictly required
to edit those files safely:

- The file you're about to edit (always read before modifying)
- Tests for that file (to match conventions)
- Files directly imported by what you edit (for type signatures)

That's it. If a file isn't in this list, you don't need it.

### 2. Forbidden operations

These operations are **never justified** during a phase:

- **Reading `.devflow/state.json`** — this is devflow's internal state, not
  source code. It tells you nothing about how to implement a feature.
- **Running `python3 -c "..."` to parse files or inspect state** — if you need
  to understand code, read it. Ad-hoc one-liners are token sinks.
- **`cat`-ing large files via Bash** — use the Read tool with line ranges.
- **`find` / `ls` on the whole project** — use Glob with a specific pattern.
- **Reading README / CLAUDE.md mid-phase** — rules files are loaded at the
  start. Don't re-read them.

### 3. Targeted reads

When reading a file, think about scope:

```
Big file, specific need  →  Read with offset + limit
Small file (<200 lines)  →  Read the whole thing
Just need a symbol       →  Grep first, then Read the matching range
Just checking existence  →  Glob, not Read
```

### 4. Filter every Bash command

Every Bash invocation should minimize output:

```bash
# ✓ Good
pytest tests/test_foo.py -q --tb=line
ruff check src/devflow/foo.py
git diff --stat HEAD~1
git log --oneline -5

# ✗ Bad (scans / prints too much)
pytest                      # runs everything verbose
ruff check                  # scans entire tree
git diff                    # full text diff
git log                     # full log
```

### 5. Skip known-good

After you write a file, you know what's in it. Don't re-read it to verify.
After a passing test run, don't re-run for a non-Python edit. After a clean
ruff, don't re-ruff the same untouched file.

## Before every tool call — the 3-question smell test

1. **Could I skip this entirely?** If yes, skip.
2. **Could I narrow the scope?** If yes, narrow.
3. **Will the result change my next action?** If no, skip.

If you can't answer "yes, this is necessary" for all three, don't make the call.

## Budget awareness

A small feature (1-2 files, <50 lines changed) should cost **under 10 tool
calls total** for the implementing phase. If you're past 10 tools and haven't
finished, you over-explored. Stop, reassess, and write code.

A medium feature (3-5 files, <200 lines changed) caps around 20 tool calls.

If the plan is genuinely too complex for these budgets, the plan is wrong —
flag it and stop rather than burning tokens.
