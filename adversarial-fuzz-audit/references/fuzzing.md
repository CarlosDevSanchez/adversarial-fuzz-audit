# Fuzzing: strategies, tools, harnesses, sandboxing, triage

## Table of contents

1. Which strategy when
2. Tool matrix by language
3. Writing a harness
4. Oracles for fuzzers
5. Sandboxing and budgets
6. Triage: reproduce, minimize, deduplicate
7. Reporting fuzz results honestly

---

## 1. Which strategy when

| Strategy | What it does | Best for | Cost |
|---|---|---|---|
| **Malformed corpus** (`gen_malformed.py`) | Replays a fixed list of hostile values | Every input, first 5 minutes, deterministic | Trivial |
| **Mutational** | Mutates seed inputs (bit flips, splices, dictionary tokens) | Parsers, binary formats, anything with valid examples | Low |
| **Generative / grammar** | Builds inputs from a grammar or schema | Structured input (JSON API bodies, SQL, config) where random bytes never get past validation | Medium |
| **Property-based** | Random typed values + predicate oracle + shrinking | Pure functions, data structures, business rules | Low, highest signal per minute |
| **Stateful / model-based** | Random operation sequences against a model | Caches, stores, state machines, connection pools | Medium |
| **Coverage-guided** | Instruments code, keeps inputs that reach new edges | Deep parsers, decoders, anything with branches on input bytes | Setup cost, then runs itself |
| **Differential** | Same input to two implementations, diff outputs | Rewrites, ports, "faster version of", wrappers around a reference | Low if a reference exists |

Start at the top. Coverage-guided fuzzing is the most powerful and the most expensive to
set up; only reach for it when the surface parses untrusted bytes or strings and a harness
is under 30 lines.

## 2. Tool matrix by language

| Language | Property-based | Coverage-guided | Mutation | Notes |
|---|---|---|---|---|
| Python | **Hypothesis** (`@given`, `RuleBasedStateMachine`, `hypothesis.extra.lark`) | **Atheris** (libFuzzer; `atheris.Setup`, `FuzzedDataProvider`) | mutmut, cosmic-ray, `quick_mutants.py` | Atheris slow on pure Python; instrument only the target module |
| JS / TS | **fast-check** (`fc.assert(fc.property(...))`, `fc.commands` for stateful) | jsfuzz, Jazzer.js | **Stryker** | fast-check prints seed + path; replay with `{ seed, path }` |
| Go | **rapid**, gopter, testing/quick | **native `go test -fuzz=FuzzX`** (Go ≥ 1.18, corpus in `testdata/fuzz`) | go-mutesting, gremlins | Always add `-race` |
| Rust | **proptest**, quickcheck | **cargo-fuzz** (nightly, libFuzzer), afl.rs | **cargo-mutants** | `arbitrary` crate for structured input |
| Java / Kotlin | **jqwik**, QuickTheories | **Jazzer** (`@FuzzTest`, `JAZZER_FUZZ=1`) | **PIT** | Jazzer also finds injection via sanitizers |
| C# / .NET | **FsCheck**, CsCheck | SharpFuzz | **Stryker.NET** | |
| C / C++ | RapidCheck | **libFuzzer**, **AFL++**, honggfuzz, with ASan/UBSan | Mull | Sanitizers are the oracle |
| Ruby | rantly, PropCheck | Ruzzy | mutant | |
| PHP | eris | – | **Infection** | |
| Swift | SwiftCheck | libFuzzer via `-sanitize=fuzzer` | muter | |
| Elixir / Erlang | StreamData, PropEr | – | – | |
| Haskell | QuickCheck, Hedgehog | – | MuCheck | |
| Any HTTP API | Schemathesis (OpenAPI/GraphQL, built on Hypothesis), RESTler | – | – | Only against a local instance |
| Any CLI | `gen_malformed.py` + shell loop, AFL++ in QEMU mode | AFL++ | – | Capture exit code, stderr, time |

Check what the project already depends on first; adding a dev dependency is fine inside
`adversarial/`, never in the project's manifest without asking.

## 3. Writing a harness

A harness maps bytes or generated values to one call of the target and lets exceptions
propagate except the ones the contract allows. Keep it in `adversarial/05-fuzz/`.

**Corpus replay (any language, Python shown):**
```python
# adversarial/05-fuzz/replay_corpus.py
import json, sys, time, traceback
from pathlib import Path
sys.path.insert(0, "src")
from pagination import paginate          # target

ALLOWED = (ValueError,)                  # documented error types ONLY
TIMEOUT = 2.0

results = []
for p in sorted(Path(sys.argv[1]).glob("*.json")):
    case = json.loads(p.read_text())
    t0 = time.perf_counter()
    try:
        out = paginate(case["value"], page=1, size=10)
        status, detail = "ok", repr(out)[:200]
        # property oracles go here, e.g.:
        assert len(out) <= 10, "page larger than size"
    except ALLOWED as e:
        status, detail = "rejected", f"{type(e).__name__}: {e}"
    except AssertionError as e:
        status, detail = "PROPERTY_VIOLATION", str(e)
    except Exception as e:
        status, detail = "CRASH", traceback.format_exc(limit=3)
    dt = time.perf_counter() - t0
    if dt > TIMEOUT: status = "HANG"
    results.append({"input": p.name, "status": status, "detail": detail, "seconds": round(dt, 3)})
Path("adversarial/05-fuzz/replay_results.json").write_text(json.dumps(results, indent=2))
bad = [r for r in results if r["status"] in ("CRASH", "HANG", "PROPERTY_VIOLATION")]
print(f"{len(bad)} / {len(results)} inputs broke something")
```

**Property-based (Hypothesis):**
```python
from hypothesis import given, settings, strategies as st, HealthCheck
@settings(max_examples=2000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(items=st.lists(st.integers()), size=st.integers(min_value=1, max_value=1000))
def test_pages_partition_items(items, size):
    pages = list(paginate_all(items, size))
    assert [x for page in pages for x in page] == items        # nothing lost or reordered
    assert all(len(p) == size for p in pages[:-1])             # all full except last
    assert not pages or 0 < len(pages[-1]) <= size             # last non-empty
```

**Coverage-guided (Atheris):**
```python
import atheris, sys
with atheris.instrument_imports():
    from mymodule import parse
def TestOneInput(data):
    fdp = atheris.FuzzedDataProvider(data)
    s = fdp.ConsumeUnicodeNoSurrogates(4096)
    try:
        parse(s)
    except ValueError:
        pass            # documented; anything else is a crash
atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
```
Run: `timeout 600 python3 fuzz_parse.py corpus/ -max_len=4096 -rss_limit_mb=1024`.

**Go native:**
```go
func FuzzParse(f *testing.F) {
    f.Add("valid seed")
    f.Fuzz(func(t *testing.T, s string) {
        out, err := Parse(s)
        if err != nil { return }                       // documented rejection
        if back := Format(out); back != s && !Equivalent(back, s) {
            t.Fatalf("round-trip mismatch: %q -> %q", s, back)
        }
    })
}
```
Run: `go test -run=^$ -fuzz=FuzzParse -fuzztime=10m -race ./...`.

**fast-check (TS):**
```ts
fc.assert(fc.property(fc.string({ unit: 'binary' }), fc.integer({min: 0, max: 100}), (s, n) => {
  const out = truncate(s, n);
  return [...out].length <= n && s.startsWith(out);
}), { numRuns: 5000 });
```

## 4. Oracles for fuzzers

A fuzzer without an oracle only finds crashes. Add at least one of:

- **Contract exceptions**: anything other than the documented error types is a bug.
- **Properties** from the attack plan (invariants, bounds, round-trips).
- **Metamorphic relations**: run twice with related inputs, compare (see
  `property-metamorphic.md`).
- **Differential**: a reference implementation, the previous git revision checked out in a
  worktree, or a trusted library.
- **Sanitizers**: ASan/UBSan/TSan for native code; `-race` for Go; `PYTHONDEVMODE=1`,
  `PYTHONWARNINGS=error` for Python; Node `--pending-deprecation --throw-deprecation`.
- **Resource ceilings**: time and memory per input; exceeding them is a `hang-or-resource`
  finding.

## 5. Sandboxing and budgets

- Run in a scratch copy or a git worktree; never where the author's uncommitted work is.
- `ulimit -v 2000000` (2 GB virtual), `ulimit -f 1000000` (1 GB files), `timeout <budget>`.
- Disable network for the harness process when the platform allows (`unshare -n`,
  firejail, Docker `--network none`), or stub the network layer. Fuzzers must never reach
  third-party services or production.
- Write only under `adversarial/` and the system temp directory; set `TMPDIR` to a fresh
  folder and delete it afterwards.
- Budget: default 10 minutes per target for coverage-guided, 2 000–10 000 examples for
  PBT, full corpus replay always. Stop early when the fuzzer reports no new coverage for
  three consecutive minutes; note that in the report.

## 6. Triage: reproduce, minimize, deduplicate

1. **Reproduce.** Re-run the single saved input in a clean process. Twice. If it does not
   reproduce, record as flaky with the rate (e.g. 2/10) under observations.
2. **Minimize.** Use the tool's shrinker (`hypothesis` does it automatically; `cargo fuzz
   tmin`, `go test -run=FuzzX/<id>` on the saved corpus entry, libFuzzer `-minimize_crash=1`,
   fast-check reports the shrunk value). Without a shrinker, delta-debug by hand: halve the
   input, keep the half that still fails, repeat.
3. **Deduplicate** by root cause: top non-library stack frame + exception type, or the
   violated property. Twenty inputs that hit the same `IndexError` at line 41 are one
   finding with twenty reproducers.
4. **Classify** (`spec-violation`, `crash`, `hang-or-resource`, `data-corruption`,
   `security`, `test-weakness`, `spec-gap`) and assign severity with
   `report-format.md`.
5. **Confirm against the suite.** Add the minimized input to a throwaway test in
   `adversarial/`; if the *existing* suite would not have caught it, the finding gets a
   second tag `test-weakness` and is attributed to the test author too.
6. **Save** the reproducer under `adversarial/findings/<id>/` with the input file, the
   command, and the observed output.

## 7. Reporting fuzz results honestly

State per target: strategy, tool and version, seed, wall-clock, executions (or examples),
coverage reached if the tool reports it, and whether coverage had plateaued. "Fuzzed for 10
minutes, 1.2 M execs, coverage plateaued at minute 4, 0 crashes" is a useful sentence.
"Fuzzed it, found nothing" is not.
