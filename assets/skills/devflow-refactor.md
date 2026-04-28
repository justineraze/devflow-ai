---
name: devflow-refactor
description: Quality-first discipline — refactor when code is dirty, don't ship patches. Applies to planning, implementing, and reviewing phases.
---

# Refactor First

**Every change is an opportunity to leave the codebase cleaner than you found
it. Never ship a patch when a refactor is the honest answer.**

## The core principle

Before you write code, ask:

1. Does this change fit cleanly in the current structure?
2. Am I adding a special case, a flag, or a workaround?
3. Would a reader understand this in six months without explanation?

If any answer is "no", stop and refactor.

## Signals that demand a refactor

These are not stylistic preferences — they are concrete signals that the
existing structure can't host the new change cleanly. When you see them,
refactor **before** adding the new code.

### 1. The new branch duplicates existing logic

```python
# Before
def process_order(order):
    if order.type == "standard":
        # 20 lines
    elif order.type == "express":
        # 20 lines (90% the same as standard)

# You're about to add:
    elif order.type == "subscription":
        # 20 lines (90% the same)
```

**Refactor**: extract the common logic, parameterize the differences.

### 2. A new parameter threads through 3+ functions

```python
# A new flag appears in the top-level API
def build(..., new_flag: bool):
    _step_a(..., new_flag=new_flag)

def _step_a(..., new_flag):
    _step_b(..., new_flag=new_flag)

def _step_b(..., new_flag):
    if new_flag:
        ...
```

**Refactor**: either put the flag in a context/state object, or push the
behavior change up to the caller.

### 3. The file already mixes concerns

If you're about to add to a 400-line module that already handles parsing,
validation, I/O, and rendering, **don't add a fifth concern**. Split first.

### 4. You can't name your function cleanly

If the best name you can come up with is `process_and_validate_and_save()`,
the function does too much. Split it before writing.

### 5. You're adding a special case

`if feature_x: do_this_differently` is a sign the abstraction is wrong. The
shape should be general; the special case should be a data-driven config, not
a hard-coded branch.

### 6. Copy-paste with small tweaks

If you're about to copy-paste code from elsewhere with 2-3 small tweaks,
**don't**. Extract the shared part, parameterize the differences.

## Include the refactor in the step

When a step needs a refactor, **include the refactor in that step**, not in
a "cleanup PR later". The cleanup PR never comes. Your step becomes:

```
Step 3 (revised):
  3a. Extract `_validate_*` methods into a Validator class.
  3b. Implement the new validation on top of the cleaner interface.
  3c. Test: ...
```

Each becomes a commit. The feature lands with clean code, not on top of mess.

## When the refactor is too big

If including the refactor would blow up the step beyond reasonable size,
**pause the phase**. Output:

```
BLOCKED: Step 3 requires refactoring X, which is beyond this step's scope.
Suggested approach:
  - First: a dedicated refactor feature for X (estimate: N steps)
  - Then: this feature on top of the cleaner code
```

The build flow will surface this to the user, who decides whether to approve
the larger scope or split into two features.

## What this is NOT

- **Not gold-plating.** "Refactor first" means refactor what blocks the change
  you're making, not a tour of "cleanup opportunities" around the codebase.
- **Not an excuse to rewrite.** The refactor should be minimal — the smallest
  change that lets the feature land cleanly.
- **Not infinite.** If you find yourself 5 refactors deep, stop. The scope has
  drifted. Commit what's clean, flag what's left, pause.

## The test

A good refactor-first PR reads like:

> "I made the codebase slightly better, then added my feature."

A patch-style PR reads like:

> "I made the codebase slightly worse, but at least it works."

Always aim for the first.
