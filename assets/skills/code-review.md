---
name: code-review
description: Review discipline — catches bugs, patches-masquerading-as-features, and quality issues before the quality gate. For the reviewing phase.
---

# Code Review

**Your job is to block code that makes the codebase worse, even if it "works".
Reviewing is not rubber-stamping; it's the last defense against patches,
regressions, and drift.**

## Five passes, in order

### Pass 0 — Patch detection (non-negotiable, comes first)

**This is the most important pass. Spend 30%+ of your effort here.** Skipping
or rushing Pass 0 means shipping technical debt. Read every changed file's
**full content**, not just the diff — patches often hide in surrounding code
that didn't change but should have.

Scan for these patch smells:

- **Module-level mutation / import-order hacks** — code that defines a constant
  then mutates it later because something "wasn't defined yet". Look for
  comments like "patch this in later", "see below", "done after X is defined".
  These are automatic critical. The fix is always trivial: reorder definitions.

- **Copy-paste with small tweaks** across the diff → critical, demand refactor.

- **Special-case flags** (`if feature_x: do_this_differently`) → critical,
  wrong abstraction.

- **Parameter threading** (same new arg in 3+ signatures) → critical.

- **Anonymous tuples with 4+ fields** in registries or data structures →
  critical, suggest NamedTuple/dataclass. They invite silent breakage when
  growing.

- **Overly defensive try/except** — bare `except Exception` (often with
  `noqa: BLE001`) catching errors from functions that don't raise. Critical
  when it duplicates logic that should be a helper. Warning otherwise.

- **God modules growing** (file passes 500 lines) → critical.

- **Inconsistent patterns** (one file uses Path, another string) → warning.

- **Dead code** (unused vars, commented blocks) → warning.

For every flagged smell, **propose the concrete refactor**. Don't just say
"this is a patch" — show the before/after code, name the helper to extract,
explain how the feature becomes shorter on top of cleaner code.

If the PR is fundamentally a patch when a refactor was the right answer,
block with REQUEST_CHANGES.

**Self-check before declaring Pass 0 done**: did you find at least one thing
to flag? Most diffs have something. If you found nothing, you probably read
too fast — re-read the largest file in the diff before moving on.

### Pass 1 — Plan compliance

Compare the diff against the plan:

- Every planned step implemented?
- No unplanned changes?
- File structure matches the plan?
- All planned tests written?

Unplanned changes are either good refactors (merge them, note them) or scope
creep (flag them, demand they move to a separate PR).

### Pass 2 — Correctness

- Does the logic do what the plan says?
- Edge cases covered: empty inputs, None, missing keys, max values?
- State machine transitions valid (if state.py touched)?
- Crash safety (state persisted before risky operations)?
- Race conditions in file ops (tmp + rename pattern used)?

### Pass 3 — Security

Scan for common vulnerabilities:

- No secrets hardcoded (API keys, tokens, passwords)?
- Subprocess calls use list args, not `shell=True`?
- User input never interpolated into file paths?
- YAML uses `safe_load`, not `load`?
- No `eval` / `exec` on user data?

Any hit here is critical. No exceptions.

### Pass 4 — Conventions

Does the code match project style?

- Type hints on all public functions?
- Docstrings on public functions?
- f-strings (not `.format()` or `%`)?
- `pathlib.Path` (not `os.path`)?
- `datetime.now(UTC)` (not `utcnow()`)?
- `Field(default_factory=...)` for mutable defaults?
- Two blank lines between top-level classes?
- Lines ≤ 99 characters?

Convention violations are warnings, not blockers — unless they indicate a
deeper misunderstanding (e.g. using `os.path` everywhere suggests the agent
didn't read CLAUDE.md).

### Pass 5 — Tests

- Tests exist for every new public function?
- Tests are independent (no shared mutable state)?
- Tests use `tmp_path` for filesystem operations?
- Tests cover happy path AND error paths?
- Test names describe behavior, not implementation?
- No assertions on internal implementation details?

Missing tests for new behavior is a warning. Missing tests for new state
machine transitions or security-sensitive code is critical.

## Output shape

```markdown
## Review: [feature-id]

### Verdict: [APPROVE | REQUEST_CHANGES | BLOCK]

### Critical (must fix)
1. **[file:line]** — [description]
   Current:
   ```[lang]
   [problematic code]
   ```
   Suggested:
   ```[lang]
   [fixed code]
   ```

### Warnings (should fix)
1. **[file:line]** — [description]

### Nitpicks (optional)
1. **[file:line]** — [description]

### What looks good
- [positive observations — reinforces good patterns]
```

## Severity calibration

- **Critical** — bug, security issue, data loss risk, patch-when-refactor-needed.
  Blocks merge.
- **Warning** — convention violation, missing test case, code smell. Should
  be fixed but doesn't block.
- **Nitpick** — style preference, naming suggestion. Optional.

## Rules of engagement

- **Be specific.** Always include file:line, never "somewhere in the code".
- **Show, don't tell.** Include code snippets for every suggested fix.
- **No false positives.** If you're unsure, say "verify this" not "this is wrong".
- **Acknowledge what's good.** Note patterns done well, not just problems.
- **APPROVE if no criticals.** Warnings get a follow-up comment, not a block.
- **Cap at 3 criticals.** If you find more than 3 critical issues, the
  implementation phase failed. Recommend re-planning.
