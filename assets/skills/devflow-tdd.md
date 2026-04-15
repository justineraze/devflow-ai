---
name: devflow-tdd
description: Test-driven mindset — tests are written as part of each implementation step, not after. Proves behavior, not implementation. For the implementing and gate phases.
---

# TDD Discipline

**Tests are how you prove a change works. Not an afterthought, not a "later"
task. Every implementation step names its test, and the test is written as part
of that step.**

## The shape of a good test

```python
def test_<subject>_<behavior>(<fixtures>) -> None:
    """One-line description of what the test proves."""
    # Arrange: set up inputs and state
    feature = Feature(id="f-001", description="test")

    # Act: call the thing under test
    feature.transition_to(FeatureStatus.PLANNING)

    # Assert: check the observable outcome
    assert feature.status == FeatureStatus.PLANNING
```

- **Name describes behavior**, not implementation.
  ✓ `test_transition_to_planning_updates_status`
  ✗ `test_transition_to_calls_setattr`
- **Three phases**: arrange, act, assert. Keep them visible.
- **One assertion per test** when possible. Multiple asserts are OK for
  related checks on the same outcome.

## What to test

### New public function or method

Always write at least:

- **Happy path** — typical input, expected output.
- **Edge case** — empty input, boundary value, None where Optional.
- **Error path** — invalid input raises the expected exception.

### State machine transitions

Every new allowed transition gets a test. Every invalid transition gets a test
that asserts it raises `InvalidTransition`.

### Filesystem operations

Always use `tmp_path`. Test both the success case and a crash-safe case (e.g.
verify no `.tmp` files are left behind).

### Subprocess calls

Mock `subprocess.run` / `subprocess.Popen`. Test:

- Return code 0 → success path
- Return code non-zero → failure path
- `FileNotFoundError` → CLI missing path
- Timeout → timeout handling

## What NOT to test

- **Internal implementation details.** Don't assert on private attributes or
  call counts of private helpers.
- **Third-party behavior.** Don't test that `pathlib.Path` works.
- **Trivial getters.** A one-line property returning `self._x` doesn't need a
  test.

## Fixtures over repetition

If three tests set up the same state, extract a fixture:

```python
@pytest.fixture
def sample_feature() -> Feature:
    return Feature(id="f-001", description="test feature")

def test_transition(sample_feature: Feature) -> None:
    sample_feature.transition_to(FeatureStatus.PLANNING)
    assert sample_feature.status == FeatureStatus.PLANNING
```

## Parametrize instead of copy-paste

When testing the same logic across inputs, use `pytest.parametrize`:

```python
@pytest.mark.parametrize("status", [FeatureStatus.DONE, FeatureStatus.FAILED])
def test_terminal_states(status: FeatureStatus) -> None:
    feature = Feature(id="f-001", description="test", status=status)
    assert feature.is_terminal
```

## Test file structure

One test file per source file, matching the name:

```
src/devflow/foo.py       →  tests/test_foo.py
```

Group tests in classes by subject:

```python
class TestTransitions:
    def test_valid_transition(self) -> None: ...
    def test_invalid_raises(self) -> None: ...

class TestSerialization:
    def test_roundtrip(self) -> None: ...
```

## During implementing phase

Every step in the plan names a test. The step is not done until:

1. The production code is written.
2. The test is written.
3. `pytest` passes (all tests, not just yours).
4. `ruff check` is clean.
5. The step is committed.

If the test is hard to write, the code is probably hard to use. Refactor the
code to be testable before moving on.

## During the gate phase

The gate is not a suggestion. It is binary: pass or fail.

- `ruff check` — zero errors required.
- `pytest` — all tests pass.
- Secrets scan — no leaks.

If any of these fail, the feature cannot merge. No "I'll fix it later". Fix
now or mark the feature failed.

## Coverage is not the goal

Don't write tests to hit a coverage number. Write tests that prove behavior.
A project with 60% coverage of meaningful tests beats one with 95% coverage
of setter/getter tests.

That said: new public functions without any test are a red flag. The reviewer
will block on those.
