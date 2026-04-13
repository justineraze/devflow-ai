---
name: planning-rigor
description: Produces rigorous implementation plans with concrete steps, quality audit, and risk assessment. For the planning and architecture phases.
---

# Planning Rigor

A good plan is executable. A bad plan is vague encouragement. Your job is to
produce a plan so specific that a developer agent can execute it without
asking a single follow-up question.

## What makes a plan rigorous

### 1. Named files with named actions

```
✓ "src/devflow/detect.py — create. Add detect_stack(path: Path) -> str | None
  that counts source files by extension and returns the language with most files."

✗ "Add detection logic somewhere in the codebase."
```

Every step must name:
- The exact file path
- The exact action (create / modify / delete / rename)
- The exact change (function names, class names, imports)

### 2. Tests live in the plan

Every step that changes behavior must name a test:
- What fixture or setup is needed
- What assertion proves the change works
- Edge case that will be covered

If you can't name the test, you don't understand the step well enough.

### 3. Quality audit before the feature

Before proposing feature steps, audit the code you'll touch:

- **Duplication** — similar code elsewhere that should be consolidated first?
- **God modules** — file over 300 lines mixing concerns? Plan a split.
- **Leaky abstractions** — callers reaching into internals? Plan a cleaner API.
- **Dead code** — unused functions, flags, branches? Plan a cleanup.
- **Inconsistency** — similar code using different conventions? Plan unification.

If any of these apply, **the refactor steps come FIRST, before the feature steps**.
A good plan leaves the codebase cleaner than it found it. Shipping a patch now
and refactoring "later" means never refactoring.

### 4. Risk flagging

For every plan, flag what could go wrong:

- Breaking API changes → which callers need updating?
- State machine changes → which transitions are now invalid?
- Heavily-imported files → high blast radius, more tests needed
- External dependencies → version compatibility, new install steps

Each risk gets a mitigation line. "Risk: X could break. Mitigation: Y."

### 5. Step count is a signal

- **1-3 steps** — trivial. Maybe too trivial for a full workflow.
- **4-8 steps** — healthy. Usual sweet spot.
- **9-15 steps** — borderline. Consider splitting.
- **16+ steps** — too big. This is two features, split them.

If you find yourself padding to hit a count, stop. Fewer honest steps beat more
padded ones.

## Output shape (always this structure)

```markdown
## Plan: [feature-id] — [one-line summary]

### Scope
- Type: [new-feature | extension | refactor | bugfix]
- Complexity: [low | medium | high]
- Estimated steps: N

### Affected files
| File | Action | What changes |
|------|--------|-------------|

### Quality audit
(what needs refactoring before we add to these files, if anything)

### Implementation steps
1. **[file]** — [what]. Test: [test name + assertion]
2. ...

### Risks
- [risk] → [mitigation]

### Open questions
- [only if truly blocking; otherwise omit this section]
```

## When to ask vs when to decide

If the spec is ambiguous, you have two options:

- **Decide** — make a reasonable choice and note it in the plan as a decision.
  Preferred when the choice is reversible and doesn't affect scope.
- **Ask** — list it in "Open questions" and STOP the planning phase. The
  feature will be blocked until the user answers. Preferred when the choice
  affects scope, breaks API, or touches security.

Never guess silently. Either decide-and-document or ask-and-block.
