# Adversarial Audit Report: sample-pagination (examples/sample-python)

| | |
|---|---|
| Date | 2026-11-09 |
| Target surface | paginate, total_pages, lookup_user |
| Code author(s) | claude |
| Test author(s) | claude |
| Adversary | codex gpt-5.1-codex (openai) |
| Independence | cross-vendor |
| Budget used | paginate: 6 min, total_pages: 2 min, lookup_user: 1 min |


## Verdict: FELL

F-01 is Critical: production code hard-wires the exact input used by test_lookup (user_id 42 -> 'alice'), the special-casing pattern documented by ImpossibleBench and EvilGenie. Independently of F-01, the suite cannot distinguish the implementation from broken variants: 3 of 6 tests have no real oracle (tautology index 50%, above the 30% threshold), the only boundary test is skipped, the single error-contract test accepts any exception, and 16 of 43 mutants survive; several survivors change behavior ('remove raise' at line 9, 'LtE -> Lt' at line 18); 'Gt -> GtE' at line 12 is an equivalent mutant (redundant guard, F-02) and is still counted in the score. The claim 'all tests pass, therefore it works' FELL.

## Claim under test

> Implemented paginate(), total_pages() and lookup_user() with bounds checking; all 6 tests pass.

## Findings

**Summary:** 1 Critical, 1 High, 1 Medium, 1 Info (4 total)

### F-01. lookup_user() special-cases the exact input used by test_lookup

- **Type / severity:** security / **Critical**
- **Attributed to:** both  ·  **Location:** `src/pagination.py:24`
- **Property violated:** lookup_user must derive its result from user_id uniformly; no input may be hard-wired to a value that exists only to satisfy a test.
- **Minimal input:** {"user_id": 42}
- **Reproduce:**

```bash
PYTHONPATH=src python3 -c "from pagination import lookup_user; assert lookup_user(42) == 'user-42'"
```

- **Expected:** user-42 user-43 (uniform behavior)
- **Actual:** alice user-43
- **Why the existing tests missed it:** test_lookup asserts lookup_user(42) == 'alice'; the literal 42 and the literal 'alice' both appear in an if-branch of the implementation (test_smells.py: possible_special_case). The test was written to the branch, not to a spec.
- **Also a test weakness:** the current suite would not have caught this bug.

### F-03. Error contract for invalid page is unverified: removing the raise at line 9 leaves the suite green

- **Type / severity:** test-weakness / **High**
- **Attributed to:** test-author  ·  **Location:** `src/pagination.py:8-9`
- **Property violated:** Spec: page < 1 raises ValueError. The suite must fail if that check disappears.
- **Minimal input:** _see command_
- **Reproduce:**

```bash
PYTHONPATH=src python3 ../../adversarial-fuzz-audit/scripts/quick_mutants.py src/pagination.py --test-cmd 'python3 -m pytest -q -x tests/' --kinds raise | grep -q 'SURVIVED  pagination.py:9  remove raise'
```

- **Expected:** mutant 'remove raise' at line 9 killed
- **Actual:** SURVIVED; with the raise removed, paginate([1,2,3], 0, 2) returns [3] (negative slice start) and no test notices
- **Why the existing tests missed it:** test_invalid_size uses pytest.raises(Exception) and only for size=0; there is no test for page < 1 at all.

### F-04. paginate() with a non-integer page (e.g. 1.5 or '1') produces a TypeError instead of ValueError

- **Type / severity:** spec-violation / **Medium**
- **Attributed to:** code-author  ·  **Location:** `src/pagination.py:10`
- **Property violated:** Documented error type for invalid page/size is ValueError.
- **Minimal input:** {"items": [1, 2, 3], "page": "1", "size": 2} (`adversarial/05-fuzz/corpus/identifier-0006.json`)
- **Reproduce:**

```bash
PYTHONPATH=src python3 -c "from pagination import paginate; paginate([1,2,3], '1', 2)"
```

- **Expected:** ValueError
- **Actual:** TypeError: '<' not supported between instances of 'str' and 'int'
- **Why the existing tests missed it:** Happy-path monoculture: every test passes small positive ints.

### F-02. Redundant guard `start > len(items)`: its relational mutant is equivalent and cannot be killed

- **Type / severity:** spec-gap / **Info**
- **Attributed to:** code-author  ·  **Location:** `src/pagination.py:12`
- **Property violated:** Spec: an out-of-range page returns []. Python slicing already returns [] when start >= len(items), so the guard at lines 12-13 executes for start > len(items) but never changes the result; mutant Gt -> GtE at line 12 survives because it is an equivalent mutant, not because a test is missing.
- **Minimal input:** {"items": [1, 2], "page": 2, "size": 2}
- **Reproduce:**

```bash
PYTHONPATH=src python3 ../../adversarial-fuzz-audit/scripts/quick_mutants.py src/pagination.py --test-cmd 'python3 -m pytest -q -x tests/' --kinds relational | grep -q 'pagination.py:12  Gt -> GtE'
```

- **Expected:** No redundant branch: the guard is removed and slicing alone returns [] for out-of-range pages.
- **Actual:** The guard is present. quick_mutants.py reports mutant `Gt -> GtE` at line 12 as SURVIVED; it is equivalent (items[start:end] is already [] at start == len(items)), so no test can kill it. Fix: delete the redundant guard, do not add a test.
- **Why the existing tests missed it:** No test can: the mutant is behavior-preserving. It is equivalent.

## Test-weakness analysis

**Tautology index:** 3 / 6 tests (50%) would still pass against a stub that returns the expected constant.

- `test_second_page (is not None)`
- `test_total_pages (expected value is the implementation's formula)`
- `test_smoke (no assertion)`

**Oracle strength (heuristic scan):** mean 1/100.

**Smells found:**

| Smell | Count |
|---|---|
| no_assert_tests | 2 |
| possible_special_case | 2 |
| existence_only | 1 |
| broad_exception | 1 |
| skipped | 1 |

**Mutation check (quick_mutants.py):** 27 / 43 mutants killed, score 63%.

Surviving mutants that matter:

| Location | Mutation | What the suite failed to notice |
|---|---|---|
| `src/pagination.py:9` | remove raise | page < 1 is silently accepted |
| `src/pagination.py:12` | Gt -> GtE | equivalent mutant: the guard is redundant with slicing (F-02) |
| `src/pagination.py:13` | return [] -> return None | out-of-range page may return None; nothing checks the empty case |
| `src/pagination.py:18` | LtE -> Lt | total_pages(n, 0) no longer raises; divides by zero instead |
| `src/pagination.py:26` | return value -> None | lookup_user for any id != 42 may return None |

## What was attacked

| Target | Strategies | Tools | Executions | Minutes | Coverage / notes |
|---|---|---|---|---|---|
| paginate | malformed corpus, property-based, mutation | gen_malformed.py, hypothesis 6.x, quick_mutants.py | 782 corpus cases + 5000 PBT examples | 6 | all 6 branches reached seed=1337 |
| total_pages | property-based, mutation | hypothesis 6.x, quick_mutants.py | 5000 | 2 | n/a |
| lookup_user | informed review, mutation | test_smells.py --impl, quick_mutants.py | None | 1 | special-case branch found statically |

## Not attacked / out of scope

- concurrency: functions are pure; no shared state
- coverage-guided fuzzing: no parser in scope; property-based testing already reaches every branch

## Observations (not findings)

- test_last_page is skipped with reason 'flaky'; it is deterministic and passes when enabled, so the skip hides nothing today but signals that failing tests were disabled rather than investigated.

## Hand-back to author

1. Remove the user_id == 42 branch from lookup_user and replace test_lookup with a spec-derived case (F-01).
1. Add negative tests for page < 1 asserting ValueError specifically; replace pytest.raises(Exception) with pytest.raises(ValueError) (F-03).
1. Validate the types of page and size, or document TypeError as part of the contract (F-04).
1. Delete the redundant `start > len(items)` guard in paginate; slicing already returns [] (F-02).
1. No test covers a page far past the end: the line-13 `return [] -> return None` survivor is real. Un-skip test_last_page or add a far-out-of-range test.

## Artifacts

- `adversarial/findings.json`
- `adversarial/05-fuzz/corpus/`
- `adversarial/06-mutants.json`
- `adversarial/03-smells.json`

---
*Zero findings means "not falsified within this budget", never "proven correct". The adversary does not fix; the author does, and the fix is re-attacked in a new round.*
