---
name: devflow-debug
description: Methodical fix discipline — reproduce, isolate, fix minimally, verify. For the fixing phase. Prevents symptomatic patches and regression blindness.
---

# Debug Discipline

**Never patch what you haven't reproduced. Never ship a fix you haven't verified.**

## The fix cycle

```
  1. Reproduce     Run the exact failing check or test. Confirm it fails.
                   If you can't reproduce it, do not touch the code.
        ↓
  2. Isolate       Find the root cause, not the symptom.
                   Binary-search: comment out code, add logs, narrow the scope.
                   Stop when you can name exactly one line or logic path causing the failure.
        ↓
  3. Fix           Write the smallest change that resolves the isolated cause.
                   Do not fix adjacent code. Do not refactor while fixing.
                   If the fix needs a refactor first, do it as a separate commit.
        ↓
  4. Verify        Re-run the originally failing check. It must pass.
                   Run the full test suite. Zero new failures.
                   Write a regression test that would have caught this bug.
                   Commit: fix + regression test in the same commit.
```

## On reproducing first

If the gate report names a specific file and line, run that check against only
that file before touching anything. If it names a test, run that test in
isolation (`pytest path/to/test.py::TestClass::test_name`).

A fix that passes without reproducing first is guesswork.

## On isolating root cause

Symptoms and causes are different things:

| Symptom | Possible root cause |
|---------|-------------------|
| `ruff E501` on line 80 | Logic was added inline instead of extracted |
| `AssertionError` in test | Wrong return value, not a missing import |
| `KeyError` at runtime | Missing default, not a wrong key name |

Fix the cause. Patching the symptom produces the same failure in a different place.

## On minimal fixes

The fix commit must be the smallest possible diff. If you find yourself:

- Touching files not named in the error → stop, you've drifted
- Rewriting logic that works → stop, that's a refactor, not a fix
- Adding new features while fixing → stop, open a separate feature

A large fix diff is a signal that you're patching symptoms or mixing concerns.

## On regression tests

Every fix ships with a test that encodes the exact scenario that broke.
The test name should describe the bug: `test_does_not_raise_on_empty_input`,
not `test_fix_123`.

If a regression test already exists and was failing, explain in the commit
message why it was failing and what changed.

## Anti-patterns to avoid

- ❌ "The error message says X so I'll change X" — without running the check
- ❌ "I'll fix this and also clean up nearby code while I'm here"
- ❌ "Tests pass locally, I'll skip the regression test"
- ❌ Fixing three issues in one commit without isolating each one first
