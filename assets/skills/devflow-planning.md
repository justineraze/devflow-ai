---
name: devflow-planning
description: Planning principles — when to audit, when to refactor, when to block. Injected alongside the planner agent.
---

# Planning Principles

This skill defines the decision principles for the planning phase. The planner
agent defines the process and output format. This skill tells you WHEN and WHY
to make certain choices — the agent tells you HOW to structure the output.

## Principle 1 — Audit before you plan

Never plan on top of code you haven't read. The quality audit (duplication,
file size, abstraction threshold, test coverage) is not a nice-to-have — it's
the foundation of the plan. If you skip the audit, you're planning blind.

**When to apply**: every planning phase, no exceptions.

## Principle 2 — Refactor-first, not refactor-later

If the audit finds problems (duplication, god modules, missing tests), the
refactoring steps come FIRST in the plan, before the feature. "Ship the
feature now, refactor later" means never refactoring. The plan must leave the
codebase cleaner than it found it.

**When to apply**: whenever the audit finds issues in files you'll touch.

**Exception**: if the refactor is large enough to be its own feature (>5 steps),
propose splitting it out as a separate `devflow build` instead of front-loading
it. Flag this to the user.

## Principle 3 — The rule of three

Two similar cases = inline is fine. Three similar cases = abstraction is
mandatory. When your feature adds a 3rd handler, backend, format, or similar
construct, the plan must include extracting the common pattern before adding
the new case.

**When to apply**: whenever you notice you're adding "another one of those."

## Principle 4 — Characterization tests before modification

If a file has no tests (or no tests covering the area you'll change), writing
characterization tests is step 1. These tests capture current behavior so you
can prove the refactor or feature doesn't break anything.

**When to apply**: whenever you modify untested code.

## Principle 5 — Every step has a "why"

A plan step that says "add X to Y" without explaining why is a plan step you
haven't thought through. The "why" is what lets the developer agent make
judgment calls when the plan meets reality. Without it, the developer follows
instructions blindly and makes bad decisions at the edges.

**When to apply**: every step, no exceptions.

## Principle 6 — Ask or decide, never guess silently

When the spec is ambiguous:
- **Decide** if the choice is reversible and doesn't affect scope. Document
  the decision in the plan so the user can override it.
- **Ask** if the choice affects scope, breaks API, or touches security. The
  feature will be blocked until the user answers.

Never guess silently. A plan built on silent assumptions will be wrong in
exactly the ways that are hardest to debug.

**When to apply**: whenever you face ambiguity.

## Principle 7 — Step count is a complexity signal

| Steps | Signal |
|-------|--------|
| 1-3 | Trivial — maybe too trivial for a full workflow |
| 4-8 | Healthy sweet spot |
| 9-15 | Borderline — consider splitting |
| 16+ | Too big — this is two features, split them |

Don't pad to hit a count. Don't compress to hide complexity. The step count
should honestly reflect the work.

**When to apply**: during plan review, before finalizing.
