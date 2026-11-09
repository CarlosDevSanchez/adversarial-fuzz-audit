# Writing tests when the skill itself is the author

Sometimes there are no tests yet and the user asks this skill to write them. The moment you
do, you become the **author** of the tests, with every bias that implies. These rules make
the tests you write worth attacking rather than worthless, and they set up the adversary
that will attack them next.

## Declare it

Write at the top of `adversarial/01-provenance.json`:
`"test_authors": ["<your model/vendor>"], "source": "this session wrote the tests"`.
The adversary in Phase 2 must then be a different vendor. You may not grade your own tests.

## Derive expected values independently of the implementation

- Compute every expected value **by hand, from the specification**, and write the
  derivation in a comment (`# 5 items, size 2 -> pages: [1,2] [3,4] [5]; page 3 is [5]`).
- Never obtain an expected value by running the implementation and copying the output.
  That is a snapshot, not a test.
- Never re-implement the function inside the test to produce the expected value. If the
  only way to state the answer is the formula, you have found a property, not an example:
  write a property-based test instead and pick a *different* formulation (e.g. check
  `sum(len(p) for p in pages) == len(items)` rather than `len(pages) == ceil(n/size)`).

## Cover equivalence classes, not just happy paths

For each parameter, include at least one case from each class the spec distinguishes, plus
the boundaries between classes: empty, one, many; zero, negative, maximum; valid, invalid,
borderline; ASCII, Unicode, control characters where strings are involved. Add an explicit
negative test for every documented error, asserting the **specific** error type and, if
the spec fixes it, the message.

## Make tests that can fail

Before committing a test, ask: which realistic bug would make this test fail? If you cannot
name one, delete or strengthen it. Avoid `is not None`, `len(x) > 0`, `raises(Exception)`,
and assertions on mocks. Prefer exact equality on small, hand-derived values and
property assertions on generated values.

## Keep them independent and deterministic

No shared mutable state, no wall-clock, no network, no ordering assumptions. Seed any
randomness and print the seed on failure.

## Then hand them over

Write `adversarial/03-claim-audit.md` honestly about your own suite (tautology index, which
classes you could not cover, assumptions you made about the spec), and route the adversary.
Treat the adversary's findings against your tests exactly as you would treat findings
against the coding agent's tests: as evidence, not as an insult.
