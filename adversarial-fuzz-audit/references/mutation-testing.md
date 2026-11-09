# Mutation testing: proving the suite is weak with injected bugs

Coverage says a line executed. Mutation testing says whether the suite *notices* when that
line is wrong. For an adversarial audit this is the single most persuasive form of evidence
against a test suite, because every surviving mutant is a concrete bug the suite would
ship.

## How it works

The tool makes one small semantic change (a *mutant*) to the source, runs the suite, and
records whether any test failed (*killed*) or all passed (*survived*). Repeat for hundreds
of mutants. Mutation score = killed / (total − equivalent). Typical operators:

| Operator | Example |
|---|---|
| Relational | `<` ↔ `<=`, `==` ↔ `!=` |
| Arithmetic | `+` ↔ `-`, `*` ↔ `/`, `%` dropped |
| Boolean | `and` ↔ `or`, `not` removed |
| Constant | `0` → `1`, `n` → `n+1`, `""` → `"x"`, `True` ↔ `False` |
| Statement | return value replaced, statement deleted, `break` ↔ `continue` |
| Call | argument swapped, call removed |
| Boundary | `range(n)` → `range(n+1)`, slice indices shifted |

## Tool matrix

| Language | Tool | Invocation | Notes |
|---|---|---|---|
| Python | **mutmut** 3.x | `mutmut run --paths-to-mutate src/x.py; mutmut results; mutmut show <id>` | pytest; config in `setup.cfg`/`pyproject.toml` |
| Python | cosmic-ray | `cosmic-ray init cr.toml s.sqlite; cosmic-ray exec cr.toml s.sqlite; cr-report s.sqlite` | distributed, slower |
| Python (fallback) | `scripts/quick_mutants.py` | `quick_mutants.py src/x.py --test-cmd "pytest -q tests/test_x.py"` | stdlib only, AST-based |
| JS / TS | **Stryker** | `npx stryker run` (needs `stryker.config.mjs`, `mutate: ["src/x.ts"]`) | jest/vitest/mocha; HTML report |
| Go | go-mutesting, gremlins | `gremlins unleash ./pkg/...` | pre-1.0 tools; keep scope small |
| Rust | **cargo-mutants** | `cargo mutants -f src/x.rs --timeout 60` | only the current crate; incremental builds |
| Java / Kotlin | **PIT** | `mvn org.pitest:pitest-maven:mutationCoverage -DtargetClasses=com.x.Y` | bytecode-level, fast |
| C# | **Stryker.NET** | `dotnet stryker --mutate "**/X.cs"` | |
| PHP | **Infection** | `vendor/bin/infection --filter=src/X.php` | |
| Ruby | mutant | `bundle exec mutant run --use rspec 'X*'` | |
| Swift | muter | `muter` | |
| C / C++ | Mull | `mull-runner` with clang plugin | |

Scope the run to the files in the intake surface and set a per-mutant timeout of 2–5× the
suite's normal runtime. A full-project mutation run on a large codebase can take hours and
is not what an audit needs.

## Reading the results

- **Survived** mutant at a line the author's tests cover: the oracle is weak there. This is
  a `test-weakness` finding attributed to the test author. Write it as a sentence a
  reviewer can verify: "Changing `page_size <= 0` to `page_size < 0` at
  `pagination.py:27` leaves all 14 tests green; a page size of 0 is then accepted and
  divides by zero downstream."
- **Survived** mutant that is genuinely **equivalent** (same behavior, e.g. `i += 1` vs
  `i = i + 1`, or a mutation in dead code): exclude it from the score and say so. Do not
  pad the findings with equivalents.
- **Timeout** mutants: usually an infinite loop introduced by the mutant, counted as detected
  by most tools (`quick_mutants.py` reports `killed`, `timeout` and `detected` = both; since 1.1.0 `killed` excludes timeouts, so use `detected` for the score);
  mention the count.
- **Killed only by a smelly test**: if the killing test is itself a tautology (see
  `test-smells.md`), the kill is accidental. Note it.

## Connecting to the other phases

- Every surviving mutant suggests an input class: find a concrete input whose output
  differs between original and mutant, add it to the fuzz corpus, and check whether the
  original code also mishandles a nearby input. Surviving mutants cluster where real bugs
  live.
- Report the mutation score alongside the tautology index from Phase 3. When both are poor,
  the verdict on "tests prove it works" is `FELL` regardless of whether you found a
  runtime bug.

## quick_mutants.py

For Python targets without mutmut, the bundled script applies a fixed set of operators via
the `ast` module, writes each mutant to a temp copy, runs `--test-cmd` with the mutated
module shadowing the original on `PYTHONPATH`, and prints survivors with line numbers and
the diff. It is deliberately small (dozens of mutants, not thousands): its purpose is to
produce a handful of undeniable examples for the report, not a full score. Use a real
mutation tool when one is available.

```bash
python3 scripts/quick_mutants.py src/pagination.py \
    --test-cmd "python3 -m pytest -q -x tests/test_pagination.py" \
    --timeout 60 --json adversarial/06-mutants.json
```
