# Report format, severity rubric, verdict rules

The report is the deliverable. Someone will decide whether to ship based on it, and someone
else (the author, often an agent) will be asked to act on it. Write for both.

## Verdict on the claim

Phase 0 recorded the author's claim as one sentence. The report opens with a verdict on
that sentence:

| Verdict | Rule |
|---|---|
| **FELL** | At least one finding of severity High or Critical in `spec-violation`, `crash`, `data-corruption`, or `security`; **or** the test-weakness evidence shows the suite cannot distinguish the implementation from a broken one (tautology index ≥ 30 % or mutation score < 60 % on the files in scope) when the claim was about the tests ("fully tested", "all tests pass therefore it works") |
| **PARTIALLY HELD** | Only Medium/Low findings, or High findings confined to `spec-gap`, or test weaknesses below the thresholds above but non-trivial |
| **HELD** | No findings above Low after the full budget, and test weaknesses are minor. State the budget prominently; HELD is "not falsified within scope", never "proven correct" |

Do not soften a FELL because the fix is a one-liner. The size of the fix is irrelevant to
whether the claim was true.

## Severity rubric

| Severity | Meaning | Examples |
|---|---|---|
| **Critical** | Data loss or corruption, security boundary crossed, silent wrong answer in the core function on realistic input | wrong total on a currency rounding path; traversal reads outside root; special-cased test input in production code |
| **High** | Spec violated on plausible input; crash or hang on input the spec accepts; suite would not detect a core-logic bug | `IndexError` on empty list; `page_size=0` accepted; 40 % of mutants survive in the main function |
| **Medium** | Wrong behavior on edge input the spec is quiet about but a user would plausibly send; undocumented exception type; resource use superlinear within documented limits | unicode normalization mismatch; `TypeError` where `ValueError` documented; 2 s for a 1 MB input that should be linear |
| **Low** | Cosmetic, message wording, over-tight tests, minor smells | error message leaks a path; snapshot tests without review |
| **Info** | Observations, flaky behavior below reporting threshold, things to watch | 1/10 flake under heavy parallelism |

Classification (`type`) and severity are independent: a `spec-gap` can be High if the gap
matters, a `crash` can be Low if it requires an input the system can never receive.

## Template field guide

Use `assets/report_template.md` verbatim as the skeleton. Field by field:

- **Header**: project, target surface, date, author model(s), adversary model, independence
  tier, budget used. If the user overrode separation, the header carries
  `INDEPENDENCE WARNING` on its own line.
- **Verdict**: one of the three words, then one paragraph: which findings or which
  weaknesses decided it.
- **Claim under test**: the Phase 0 sentence, quoted.
- **Findings**: one block per deduplicated finding, numbered `F-01`…:
  - title (one line, states the wrong behavior, not the input)
  - type, severity, attributed to (code author / test author / both)
  - property or contract violated, in a sentence
  - minimal reproducer: input (inline or path), command, observed output, expected output
  - why the existing tests did not catch it (name the test file and the smell)
  - independence note if same-model
- **Test-weakness analysis**: tautology index (count / total, list), smells table from
  `test_smells.py` summarized, mutation score and the surviving mutants that matter, with
  line numbers.
- **What was attacked**: per target, strategies, tools, seeds, examples/executions,
  wall-clock, coverage plateau.
- **Not attacked / out of scope**: explicit list, with reasons (budget, no harness,
  requires live service, user excluded).
- **Observations**: non-reproducible, flaky, or judgment calls that are not findings.
- **Hand-back to author**: a numbered list of what the author must address, in severity
  order, without proposed fixes. The adversary does not fix.
- **Artifacts**: paths to `findings.json`, corpora, harnesses, raw logs, adversary transcript.

## findings.json

`scripts/report_builder.py` validates against `assets/findings_schema.json` and renders the
Findings and Test-weakness sections from it, so write the JSON first and let the script
produce the Markdown. Hand-edit the prose sections afterwards.

```bash
python3 scripts/report_builder.py adversarial/findings.json \
    --template assets/report_template.md --out adversarial/REPORT.md
```

## Tone

Plain, specific, verifiable. No adjectives about the author ("sloppy"), only facts about
the artifact ("`test_lookup` passes with the implementation replaced by `return 'alice'`").
A finding the reader can reproduce in under a minute is worth ten they must trust.
