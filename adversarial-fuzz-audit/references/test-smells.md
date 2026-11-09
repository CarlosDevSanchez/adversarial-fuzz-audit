# Test smells: how to recognize a test that proves nothing

A test is only as strong as its oracle. This catalog lists the shapes that LLM-written
suites (and tired humans) produce when they optimize for "green" instead of "correct", with
a detection heuristic for each and the question to ask. `scripts/test_smells.py` flags the
mechanical ones; the judgment ones are yours.

## Table of contents

1. Tautological assertion
2. Implementation echo
3. Existence-only assertion
4. No-assertion test
5. Mock verifies mock
6. Snapshot regenerated from the code
7. Hard-coded expected value from a single run
8. Happy-path monoculture
9. Exception swallowed or over-broad
10. Skipped, disabled, or conditional tests
11. Special-cased input
12. Shared mutable fixture
13. Ordering-dependent suite
14. Trivial parametrization
15. Assertion on the wrong thing
16. Over-tight assertion on incidental detail
17. The tautology index

---

### 1. Tautological assertion
The expected value is computed by the same logic the code uses.
```python
assert total(items) == sum(i.price for i in items)   # same formula as the implementation
```
*Detect:* expected side contains a call to the function under test, or re-implements it.
*Ask:* what independent fact about the result is asserted? If the answer is "none", the
test can never fail unless the language breaks.

### 2. Implementation echo
Test names, cases, and branches map one-to-one onto the code's `if` statements. The test
documents what the code does, not what it must do.
*Detect:* every literal in the test also appears in the implementation; test added in the
same commit as the code with identical structure.
*Ask:* if the spec changed, which test would fail first? If none, the suite is a mirror.

### 3. Existence-only assertion
```python
assert result is not None
assert len(result) > 0
expect(res).toBeDefined()
assert.NoError(t, err)
```
*Detect:* assertion predicates in {not None, truthy, defined, no error, isinstance}.
*Ask:* which wrong value would still pass? Usually all of them.

### 4. No-assertion test
The test calls the code and ends. It only proves "did not throw".
*Detect:* test body without `assert`, `expect`, `should`, `t.Error*`, `require.*`.
*Ask:* is "did not throw" the actual contract? Rarely.

### 5. Mock verifies mock
Every dependency is mocked and the assertion checks the mock was called with what the test
passed in. Real code paths are never executed.
*Detect:* ratio of mock setup lines to assertion lines > 3; assertions on `.called_with`
only; no assertion on the return value.
*Ask:* what would break if the real dependency changed its contract? Nothing here would
notice.

### 6. Snapshot regenerated from the code
`toMatchSnapshot()`, golden files, `--update-snapshots` in the commit. The snapshot *is* the
implementation output; the test pins the present, not the spec.
*Detect:* snapshot files updated in the same commit as the code; no hand-written expected
values.
*Ask:* who reviewed the snapshot diff against the spec? If nobody, treat it as no test.

### 7. Hard-coded expected value from a single run
A magic literal (`assert hash(x) == 0x3af1...`, `expect(ids).toEqual([7, 12, 31])`) with no
derivation. Correct only if the first run was correct.
*Detect:* long literals, floats to many digits, hashes, timestamps as expected values.
*Ask:* can the expected value be derived independently? If not, cross-check it by hand or
with a reference implementation during the informed pass.

### 8. Happy-path monoculture
All inputs are small, positive, ASCII, well-formed, and present.
*Detect:* no test uses empty, zero, negative, max/min, unicode, None/null, duplicate,
unsorted, huge, or malformed input; no test expects an error.
*Ask:* which attack class from `attack-playbook.md` has zero tests? Each one is a fuzz
target.

### 9. Exception swallowed or over-broad
```python
with pytest.raises(Exception): ...
try: f() except: pass
```
*Detect:* `raises(Exception)`, `raises(BaseException)`, `expect(...).toThrow()` with no
matcher, bare `except`, `catch (e) {}`.
*Ask:* would the test pass if the code threw the *wrong* exception, e.g. `TypeError` from a
bug instead of `ValidationError` from a check? Yes. Finding.

### 10. Skipped, disabled, or conditional tests
`@skip`, `xit`, `t.Skip()`, `#[ignore]`, `if CI: return`, commented-out assertions.
*Detect:* skip decorators, `xit`/`xdescribe`/`test.skip`, `it.todo`, commented `assert`.
*Ask:* when was it disabled and why? A test disabled in the feature commit is a confession.

### 11. Special-cased input
The implementation contains a literal that also appears as a test input, with a branch that
returns the test's expected value.
```python
if user_id == 42: return "alice"   # test_lookup uses 42
```
*Detect:* `grep` test literals in the implementation; branches that compare to constants
present only in tests. This is the ImpossibleBench/EvilGenie pattern.
*Ask:* does the same test pass with input 43 and an updated expectation? Try it. If the
code has to be changed, it is special-casing: a `security`/`spec-violation` finding.

### 12. Shared mutable fixture
Module-level objects mutated across tests; passes only in a specific order.
*Detect:* fixtures without teardown, global lists/dicts, singletons.
*Ask:* run the suite in random order (`pytest -p randomly`, `jest --randomize`,
`go test -shuffle on`). Failures are findings against the tests.

### 13. Ordering-dependent suite
Same as 12 at the suite level; also tests that depend on wall-clock, locale, or timezone.
*Detect:* run with `TZ=Pacific/Kiritimati`, `LC_ALL=tr_TR.UTF-8`, and at a faked date.

### 14. Trivial parametrization
`@pytest.mark.parametrize("x", [1, 2, 3])` where all cases exercise the same branch.
*Detect:* parametrized values of one class (all small positive ints).
*Ask:* does the parameter list include a value from each equivalence class and each
boundary? Usually not.

### 15. Assertion on the wrong thing
Checks the log message, the return type, or a side channel instead of the result.
*Detect:* assertions on `caplog`, `console.log` spies, `typeof`, status code only without
body.
*Ask:* can the result be wrong while the asserted side channel is right?

### 16. Over-tight assertion on incidental detail
Asserts exact whitespace, key order, or error-message wording that the spec does not fix.
These tests fail on harmless changes and get "fixed" by copying the new output back in,
turning them into smell 6.
*Detect:* `assertEqual` on whole serialized blobs; string equality on messages.
*Ask:* which of these details does the spec promise? Assert only those.

### 17. The tautology index
For the suite as a whole, estimate how many tests would still pass if the implementation
were replaced by `return <the constant the test expects>` or `return input`. Count them.
Report the fraction. A suite where a third of tests survive a constant-returning stub is
not protecting anything; the mutation check in Phase 6 confirms this empirically.

## Using the scan

```bash
python3 scripts/test_smells.py tests/ --json adversarial/03-smells.json
```

Output per file: counts per smell, the offending lines, and a heuristic **oracle strength**
score (0–100) that is a starting point, not a verdict. Read every file the scan rates below
60 in full before writing the Phase 3 audit. Read at least one file it rates above 80 too:
the scan cannot see smell 2 or smell 11, which are the ones that matter most.
