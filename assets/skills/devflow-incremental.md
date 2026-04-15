---
name: devflow-incremental
description: Execution discipline for building features incrementally — thin vertical slices, commit per step, verify before continuing. For the implementing and fixing phases.
---

# Incremental Build

**Build in thin vertical slices. Each slice leaves the system in a working,
testable, committed state. Don't batch, don't race ahead, don't "finish it all
and commit at the end".**

## The increment cycle

For every step in the plan:

```
  1. Read          Read the target file before editing.
        ↓
  2. Implement     Write the smallest complete piece from the step.
        ↓
  3. Test          Run the test(s) this step names.
        ↓
  4. Verify        ruff passes on the file. All tests green.
                 Re-read the plan step: does the code actually do what was asked?
                 If not, fix before committing — green tests ≠ correct behaviour.
        ↓
  5. Commit        git add -A && git commit -m "..."
        ↓
  6. Next slice    Move to the next step. Don't loop back.
```

**Never skip a step in the cycle.** If verify fails, fix it before committing.
If tests fail, fix them before the next slice. The system must stay green.

## One step = one commit

Each plan step gets its own commit. Do not:

- Batch multiple steps into one commit ("save time for later").
- Split one step into multiple commits ("this is a big step").
- Amend previous commits ("I forgot something").

A clean linear history of one-step-one-commit makes review, revert, and squash
trivial. Batching destroys that.

### Commit message format

Use Conventional Commits:

```
feat: add <what> in <file>
fix: handle <case> in <file>
test: cover <scenario>
refactor: extract <function> from <module>
```

Short, imperative, present tense. One line. No body unless the "why" is
non-obvious.

## Refactor within the step, not around it

If the current step requires touching code that isn't clean, **refactor first,
then do the step, both in the same commit**. A step called "Add foo() to bar.py"
becomes two commits if bar.py needs a split first:

```
Commit A:  refactor: split bar.py into bar/core.py and bar/helpers.py
Commit B:  feat: add foo() in bar/core.py
```

That's fine — it's two conceptual changes. Just don't ship A as dead code; make
sure each commit leaves the system green.

## Size signals

You should feel tension when a slice gets too big:

- **~100 lines changed** — normal slice, commit it.
- **200+ lines changed** — check your scope. Probably 2 slices merged.
- **Multiple files in one commit when the plan said one file** — you drifted.

If you drifted from the plan, stop. Either:
- Revert to the plan and commit only that slice.
- Update the plan in your output, justifying the drift.

## When to escape the cycle

The cycle assumes tests can prove correctness. When they can't (UI polish,
perf tuning, external integration), substitute with the strongest verification
you have:

- Run the dev server and take a screenshot (UI)
- Run a benchmark (perf)
- Hit the real endpoint with curl (external API)

But still commit per slice. The verify step is non-negotiable.

## Anti-patterns to avoid

- ❌ "Let me write all the code first, then test at the end"
- ❌ "I'll commit everything once the feature is done"
- ❌ "Tests are failing but unrelated to my change, I'll push anyway"
- ❌ "I'll just fix this other thing while I'm here"
- ❌ Writing 3 files simultaneously, hoping they fit together

Each of these costs time and produces lower-quality output. The cycle is
slower per iteration but faster end-to-end because you don't debug five
intertwined mistakes at once.
