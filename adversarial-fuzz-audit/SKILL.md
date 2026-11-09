---
name: adversarial-fuzz-audit
description: Independent adversarial verification of code produced by an AI coding agent (Claude Code, Codex, Gemini CLI, Copilot, Aider, Cursor, OpenCode). Establishes who wrote the code and who wrote its tests, assigns a DIFFERENT model as adversary, audits the existing tests for weak oracles, then attacks the implementation with malformed and fuzzed inputs, property-based and metamorphic checks, and mutation analysis to break the agent's "it works" claim, and delivers a report of every failure and why the claim fell. Use whenever the user wants to verify, challenge, red-team, stress, fuzz, break, audit, cross-check, or "really test" code or tests written by an agent; mentions adversarial tests, fuzzing, malformed/hostile/random input, mutation testing, edge cases, or a second opinion from another model; or distrusts tests an agent wrote for its own code, even without saying "adversarial" or "fuzz". Never let the model that wrote the code grade it unless the user explicitly decides so.
license: MIT
metadata:
  version: "1.0.0"
  author: "Carlos Sánchez (CarlosDevSanchez)"
  language: "en"
  readme: "Spanish README at repository root"
---

# Adversarial Fuzz Audit

An agent that writes code and then writes the tests for that code is grading its own
homework. It shares the same blind spots in both places, it tends to assert what the
implementation already does rather than what the specification demands, and research on
LLM evaluators shows a measurable self-preference bias when a model judges its own output.
Coding-agent benchmarks (ImpossibleBench, EvilGenie, GSO HackDetector, 2025) caught both
Codex and Claude Code special-casing inputs, hard-coding expected values, and editing test
files so that a suite goes green. A green suite written by the author is therefore a
**claim**, not **evidence**.

This skill turns that claim into something that can be falsified. It separates the roles of
*author* and *adversary*, routes the adversary to a different model whenever one is
available, and gives the adversary a disciplined toolkit (test-smell audit, malformed input
corpus, fuzzing, property and metamorphic checks, mutation analysis) whose only goal is to
make the author's assertion fall. The output is a report that says exactly what broke, how
to reproduce it, and why the original claim did not hold.

## Non-negotiable principles

1. **Separation of duties.** Whoever authored the code or the tests under audit must not be
   the adversary. "Different model" means a different model family or vendor when possible,
   never merely a fresh session of the same model. Running everything with one model is only
   acceptable when the user explicitly decides so after being told the risk, and the report
   must then carry a visible independence warning.
2. **Specification over implementation.** Derive expected behavior from the task, the docs,
   the type signatures, and domain invariants. Reading the implementation first anchors you
   to its assumptions. Attack blind first, then read the code and tests to find what they
   left uncovered.
3. **Break, do not fix.** The adversary never edits production code or the author's tests.
   Fixing collapses the roles again and hides the evidence. Record, reproduce, report, and
   hand back to the author (or to the user).
4. **Evidence over assertion.** A finding exists only when it reproduces from a saved input
   with a stated expected-vs-actual. "Looks suspicious" goes in an observations section, not
   in findings.
5. **Honest scope.** State what was attacked, for how long, with which tools, and what was
   not attacked. Zero findings never means "correct", it means "not broken within this
   budget".

## Workflow

Run the phases in order. Each phase writes to `adversarial/` inside the project (never into
the author's source or test directories). Read the linked reference before a phase the first
time you perform it in a session.

| Phase | Goal | Reference |
|---|---|---|
| 0. Intake | Pin down the claim under test and the budget | this file |
| 1. Provenance | Who wrote the code, who wrote the tests | `references/provenance.md` |
| 2. Adversary routing | Pick a model that is not the author | `references/adversary-routing.md` |
| 3. Claim audit | Rate the existing tests' oracle strength | `references/test-smells.md` |
| 4. Attack plan | Blind, spec-derived attack vectors | `references/attack-playbook.md`, `references/property-metamorphic.md` |
| 5. Fuzz campaign | Malformed, random, and coverage-guided input | `references/fuzzing.md` |
| 6. Mutation check | Prove whether the suite detects injected bugs | `references/mutation-testing.md` |
| 7. Triage | Dedupe, minimize, classify, confirm | `references/fuzzing.md` (triage section) |
| 8. Report | Deliver the verdict and the evidence | `references/report-format.md` |

### Phase 0. Intake

Write `adversarial/00-intake.md` answering:

- **Claim.** In one sentence, what does the author assert works? Quote the agent's own
  summary or commit message when available ("implemented pagination with bounds checking,
  all 14 tests pass"). The report will later state whether this sentence survived.
- **Surface.** Which functions, endpoints, CLIs, or modules are in scope, and their input
  types. Every input type becomes a fuzz target.
- **Specification sources.** Ticket, README, docstrings, type hints, OpenAPI, domain rules.
  If there is no spec, write the implied one from the task description and mark it as
  inferred.
- **Budget.** Wall-clock for fuzzing (default 10 minutes per target, more if the user asks),
  and whether the adversary may spend external model calls.
- **Runtime facts.** Language, test runner, how to run the suite, how to run one test.

Ask the user only when the claim or the surface is genuinely ambiguous. Everything else has
a sensible default.

### Phase 1. Provenance

Run `scripts/provenance.py <repo> [paths...]`. It reads git history for commit trailers such
as `Co-Authored-By: Claude`, `Co-Authored-By: Codex`, `Claude-Session:`, agent markers in
commit bodies, and author e-mails, and emits a responsibility matrix: for each source file
and each test file, the most likely author (human, claude, codex, gemini, copilot, unknown).

Interpret with judgment. If git is unavailable or uninformative, ask the user one direct
question: "Who wrote the code, and who wrote the tests?" Record the answer and its source
(git, user statement, or inferred) in `adversarial/01-provenance.json`. The responsibility
matrix decides who is accountable for each falsified claim in the final report.

### Phase 2. Adversary routing

Run `scripts/detect_agents.py`. It lists agent CLIs on PATH (`claude`, `codex`, `gemini`,
`opencode`, `aider`, `copilot`, `cursor-agent`, `goose`), provider API keys present in the
environment, and the model powering the current session when it can tell. Then apply the
routing table in `references/adversary-routing.md`. The short version:

| Code author | Test author | Adversary must be |
|---|---|---|
| Model A | Model A | Any model that is not A (prefer another vendor) |
| Model A | Model B | A model that is not B (A is acceptable, a third model is better) |
| Human | Model A | Not A |
| Model A | Human | Not A; the human's tests are still audited for weak oracles |
| Nobody yet (we write tests) | Us (Model X) | Not X. We author the tests, then a different model attacks both the code and our tests |
| Any | Any, but no other model is reachable | Stop and ask the user. Proceed same-model only on explicit decision, with the warning in the report |

Running the adversary on another model is done through that agent's non-interactive mode
(`claude -p`, `codex exec`, `gemini -p`, `opencode run`). `scripts/run_adversary.sh` wraps
these calls, injects `assets/prompts/adversary_prompt.md`, refuses to run when the chosen
adversary equals the recorded author unless `--allow-same-model` is passed, and stores the
transcript in `adversarial/02-adversary/`. Record the decision (author vendors, adversary
agent and model, independence tier, user override) in `adversarial/02-routing.json`. When
the current session itself is the non-author model, the current session is the adversary
and no external call is needed.

When the user asks the skill to write the tests too, the session becomes the *author* of the
tests. Say so explicitly, write the tests under `assets/prompts/author_prompt.md`
discipline (spec-derived, no peeking at implementation internals for expected values), then
route a different model as adversary against both the code and the new tests. Do not skip
this: tests the skill wrote are no more trustworthy than tests the coding agent wrote.

### Phase 3. Claim audit

Run `scripts/test_smells.py <test paths>` to get a heuristic scan for weak oracles:
tautological assertions, assertions that only check "not null" or "no exception", tests
with zero assertions, snapshot tests regenerated from the implementation, mock-everything
tests that verify the mock, hard-coded expected values copied from a single run, disabled
or skipped tests, happy-path-only input sets, and branches with no negative test. Then read
the tests yourself and answer, per test file, in `adversarial/03-claim-audit.md`:

- What property of the *specification* does each test actually pin down?
- Which inputs can never reach this test (empty, negative, huge, unicode, concurrent, …)?
- If the implementation were replaced with `return <the constant the test expects>`, how
  many tests would still pass? That count is the suite's tautology index.

Do not stop at the scan. The scan finds shapes, you find meaning.

### Phase 4. Attack plan

Two passes, in this order, written to `adversarial/04-attack-plan.md`:

**Blind pass.** Using only the intake spec, list the properties the code must hold
(invariants, round-trips, idempotency, monotonicity, commutativity, bounds, error
contracts) and the metamorphic relations that follow from them. For each public input,
enumerate the attack classes from `references/attack-playbook.md` that apply: boundaries,
type confusion, encoding and Unicode, numeric edge cases, time and locale, size and
resource exhaustion, ordering and concurrency, state and lifecycle, injection, serialization
round-trips, error-path behavior.

**Informed pass.** Now read the implementation and the existing tests. Add attacks aimed at
what you see: every `if` without a test on the other side, every parsed-but-unvalidated
field, every catch block that swallows, every TODO, every assumption in a comment, every
place a test used a literal that the code also contains.

Prioritize: spec violations and data corruption first, crashes second, performance third.

### Phase 5. Fuzz campaign

Build inputs in three layers, cheapest first, under `adversarial/05-fuzz/`:

1. **Malformed corpus.** `scripts/gen_malformed.py --kind <json|string|number|bytes|csv|url|path|datetime|all> --out <dir>`
   writes a deterministic, seeded corpus of hostile values (naughty strings, control
   characters, bidi overrides, homoglyphs, overlong UTF-8, NaN and ±inf, 2^31 and 2^63
   boundaries, -0, denormals, deeply nested JSON, duplicate keys, BOMs, CRLF, null bytes,
   path traversal, 1 MB payloads). Feed every value to every input in scope through a small
   harness you write in the project's language. Record any exception that is not the
   documented error type, any hang over the timeout, and any output that violates a Phase 4
   property.
2. **Property-based and metamorphic.** Use the project's PBT library (Hypothesis,
   fast-check, jqwik, proptest, rapid, FsCheck, QuickCheck; see
   `references/property-metamorphic.md`). Encode the Phase 4 properties. Let shrinking give
   you minimal counterexamples.
3. **Coverage-guided fuzzing** when a harness is cheap to write and the surface parses
   untrusted bytes or strings (Atheris, Jazzer, cargo-fuzz, `go test -fuzz`, libFuzzer,
   AFL++; see `references/fuzzing.md`). Time-box it to the Phase 0 budget.

Always run fuzzers under resource limits (`ulimit -v`, `timeout`, a temp working directory,
no network). Fuzz only code the user owns and only in a sandbox, never a live service.

### Phase 6. Mutation check

The sharpest proof that a suite is weak is a bug it does not notice. Run the project's
mutation tool if present (mutmut, Stryker, PIT, cargo-mutants, Infection, go-mutesting; see
`references/mutation-testing.md`). Without one, `scripts/quick_mutants.py <source.py>
--test-cmd "<command>"` applies a small set of semantic mutants to a Python file (flipped
comparisons, negated conditions, off-by-one constants, dropped return, swapped boolean
operators) and reports which ones the suite fails to kill. Each surviving mutant is a
concrete, reportable statement: "the suite passes even when `<=` becomes `<` at line N".
Limit the run to the files in scope and keep the per-mutant timeout small.

### Phase 7. Triage

For every candidate failure:

- **Reproduce** from the saved input, twice. Flaky results go to observations with the flake
  rate.
- **Minimize** the input (shrinking output, delta-debugging, or by hand) until removing
  anything more makes the failure disappear.
- **Deduplicate** by root cause (same stack frame, same violated property), not by input.
- **Classify** as one of: `spec-violation`, `crash`, `hang-or-resource`, `data-corruption`,
  `security`, `test-weakness` (the suite would not catch a real bug), `spec-gap` (the spec
  is silent, behavior is arguable). Assign severity with the rubric in
  `references/report-format.md`.
- **Attribute** to the responsible party from Phase 1: code author, test author, or both.

Use `scripts/report_builder.py` to validate `adversarial/findings.json` against
`assets/findings_schema.json` and to render the report.

### Phase 8. Report

Write `adversarial/REPORT.md` using `assets/report_template.md` exactly. The report must
open with a verdict on the Phase 0 claim sentence (`HELD`, `PARTIALLY HELD`, `FELL`), then
list findings with reproduction, then the test-weakness analysis (tautology index,
surviving mutants), then scope and budget, then an independence statement naming the author
model(s) and the adversary model and whether the user overrode the separation rule. Close
with a hand-back list for the author. Do not include fixes. Do not soften a `FELL` verdict
because the fix looks easy.

## Rules of engagement

- Work in `adversarial/` and the fuzzer's own directories. Treat the author's source and
  tests as read-only. If a harness needs a shim, put the shim in `adversarial/`.
- Never disable, delete, skip, or edit an existing test to make something run. If a test is
  wrong, that is a finding.
- Never fuzz production endpoints, third-party APIs, or shared databases. Use local fakes.
- Keep every input that produced a finding; the report links to it.
- Respect the user's budget. Prefer ten minutes of well-targeted fuzzing over an hour of
  random bytes.
- If the only adversary available is the author model, stop and ask. The user decides, and
  the report says so.

## Scripts

| Script | Use |
|---|---|
| `scripts/detect_agents.py` | List agent CLIs, API keys, current model; JSON output |
| `scripts/provenance.py` | Git-based author/test responsibility matrix |
| `scripts/run_adversary.sh` | Invoke a different model's CLI with the adversary prompt and independence guard |
| `scripts/test_smells.py` | Heuristic weak-oracle scan across Python, JS/TS, Go, Java, Rust, C# tests |
| `scripts/gen_malformed.py` | Deterministic malformed-input corpus generator |
| `scripts/quick_mutants.py` | Dependency-free mutation check for Python sources |
| `scripts/report_builder.py` | Validate findings JSON and render REPORT.md |

All scripts are standard-library only (Python 3.9+, bash) and print `--help`.

## References

- `references/principles.md`: the why, with sources (self-preference bias, oracle problem, reward hacking in coding agents, Goodhart).
- `references/provenance.md`: reading agent fingerprints from git and the responsibility matrix.
- `references/adversary-routing.md`: detection, routing table, exact CLI invocations per agent, user-override protocol.
- `references/test-smells.md`: catalog of weak oracles with detection heuristics and examples.
- `references/attack-playbook.md`: attack classes per input type with concrete payloads.
- `references/fuzzing.md`: strategies, per-language tool matrix, harness templates, sandboxing, triage and minimization.
- `references/property-metamorphic.md`: deriving properties and metamorphic relations from a spec, differential testing, library cheat sheets.
- `references/mutation-testing.md`: tool matrix, interpreting survivors, equivalent mutants.
- `references/report-format.md`: severity rubric, verdict rules, template field guide.
