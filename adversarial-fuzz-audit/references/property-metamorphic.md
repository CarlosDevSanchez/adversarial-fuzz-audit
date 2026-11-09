# Property-based, metamorphic, and differential oracles

The hard part of adversarial testing is not generating inputs, it is knowing when an output
is wrong without an example to compare against. These three techniques give you oracles
that do not depend on the author's examples.

## 1. Deriving properties from a spec, not from code

Work from the intake document. For each operation, ask the questions below and write each
answer as a predicate over arbitrary inputs. Do this **before** reading the implementation;
the implementation will tempt you to write properties it already satisfies.

| Question | Property shape | Example |
|---|---|---|
| What must never change? | Invariant: `inv(state)` after every op | balance ≥ 0; tree is sorted; `len(pages) == ceil(n/size)` |
| Is there an inverse? | Round-trip: `dec(enc(x)) == x` | `parse(format(d)) == d`; `decompress(compress(b)) == b` |
| Does doing it twice equal once? | Idempotence: `f(f(x)) == f(x)` | normalize, dedupe, `PUT` |
| Does order matter? | Commutativity / permutation invariance: `f(shuffle(xs)) == f(xs)` | sum, set union, "top N by score" (modulo ties) |
| Does more input give more output? | Monotonicity: `x ≤ y ⇒ f(x) ≤ f(y)` | price with quantity; search results with looser filter ⊇ stricter |
| What is the size relationship? | Cardinality: `len(f(xs)) ≤ len(xs)`; `sum(len(p) for p in pages) == len(xs)` | filter, paginate, chunk |
| Is there a simpler reference? | Oracle: `f(x) == slow_obvious(x)` | optimized sort vs `sorted`; cached vs uncached |
| What does the error contract say? | Error property: `invalid(x) ⇒ raises(E)` and `valid(x) ⇒ not raises` | `size ≤ 0 ⇒ ValueError`; anything else must not raise `TypeError` |
| Are there algebraic laws? | Associativity, identity, distributivity | `merge(a, merge(b, c)) == merge(merge(a, b), c)`; `merge(a, empty) == a` |
| What must hold about the output shape? | Structural: schema validity, no `None` in required fields, unique IDs | every row has `id`; IDs are unique |

Write 3–8 properties per operation. A property that the author's tests already imply is
still worth having: with random inputs it covers input classes the author never typed.

## 2. Metamorphic relations

When you cannot compute the expected output for *one* input, you can often say how the
output must change when you change the input in a known way. Run the program twice; the
oracle compares the two results.

Common relations:

| Transformation of input | Expected effect on output | Domains |
|---|---|---|
| Permute items | Unchanged (or permuted identically) | aggregations, search ranking by score |
| Add an element that cannot match | Unchanged | filters, search, dedupe |
| Add an element that must match | Grows by exactly one / includes it | search, filters |
| Scale all numbers by k | Output scales by k (or k², or unchanged for ratios) | pricing, statistics, geometry |
| Translate / shift all values | Shift by same amount | timestamps, coordinates |
| Negate | Negated / reversed | sorting direction, sign-sensitive math |
| Reverse the sequence | Reversed result or same set | path finding (reverse edges → same distance), diffs |
| Concatenate inputs | `f(a ++ b)` relates to `f(a)`, `f(b)` | hashing (not equal), counting (sum), max (max) |
| Re-encode (UTF-8 ↔ UTF-16, NFC ↔ NFD) | Unchanged semantics | text processing |
| Change timezone representation of the same instant | Unchanged instant-based results | scheduling, billing periods |
| Rename identifiers consistently | Unchanged structure | compilers, parsers, templating |
| Add whitespace / comments where the grammar allows | Unchanged parse tree | parsers, config loaders |
| Increase precision of inputs | Output within tolerance | numeric code |
| Run with a different but equivalent configuration | Same result | caches on/off, parallel vs serial, batch size |

Metamorphic testing is the fastest way to attack ML inference wrappers, search, ranking,
pricing engines, and anything with "it depends" semantics.

## 3. Differential testing (pseudo-oracles)

Compare the target with an independent implementation on identical inputs:

- The **previous version** (`git worktree add /tmp/prev HEAD~1`) when the claim is "refactor
  with no behavior change" or "optimized". Diff on thousands of random inputs; every
  difference is either a bug or an undocumented behavior change (a `spec-gap` finding).
- A **trusted library** (stdlib `json`, `datetime`, `decimal`; `moment`/`luxon` vs hand
  parsing; `sorted`).
- A **deliberately naive reimplementation** you write in 10 lines in `adversarial/`. Slow
  and obvious beats fast and clever as an oracle.
- A **second model's implementation** of the same spec: when the user allows it, ask the
  adversary model to write its own version blind and diff. Where the two disagree, read the
  spec; one of them is wrong and often it is the author.

Independence of the oracle matters more than its quality. An oracle that shares the
author's assumptions (copied from the author's code, or generated by the author model from
the author's code) is not an oracle.

## 4. Library cheat sheet

**Hypothesis (Python)**
```python
from hypothesis import given, assume, settings, example, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, initialize, Bundle

st.text()                             # any unicode, includes surrogates-free weirdness
st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1)
st.binary(), st.integers(), st.floats(allow_nan=False, allow_infinity=False)
st.decimals(), st.fractions(), st.datetimes(timezones=st.timezones()), st.timedeltas()
st.lists(st.integers(), unique=True), st.dictionaries(st.text(), st.integers())
st.from_regex(r"^[a-z]{1,8}@[a-z]+\.[a-z]{2,3}$", fullmatch=True)
st.builds(MyModel, name=st.text(), age=st.integers(0, 150))
st.recursive(st.none() | st.booleans() | st.floats() | st.text(),
             lambda c: st.lists(c) | st.dictionaries(st.text(), c), max_leaves=50)  # JSON
st.sampled_from([...]), st.one_of(...), st.just(x), st.data()  # draw interactively

@settings(max_examples=5000, deadline=None, derandomize=False)   # derandomize=True for CI
@example(items=[], size=1)                                       # pin known edge cases
```
Stateful:
```python
class CacheMachine(RuleBasedStateMachine):
    keys = Bundle("keys")
    def __init__(self): super().__init__(); self.cache = LRU(3); self.model = {}
    @rule(target=keys, k=st.text(min_size=1), v=st.integers())
    def put(self, k, v): self.cache.put(k, v); self.model[k] = v; return k
    @rule(k=keys)
    def get(self, k): assert self.cache.get(k) in (self.model.get(k), None)
    @invariant()
    def size_bounded(self): assert len(self.cache) <= 3
TestCache = CacheMachine.TestCase
```
Reproduce: Hypothesis prints `@reproduce_failure(...)` or `Falsifying example`; the
`.hypothesis/` directory caches failures so re-runs replay them.

**fast-check (JS/TS)**
```ts
import fc from 'fast-check';
fc.string(), fc.string({ unit: 'grapheme' }), fc.fullUnicodeString(), fc.base64String()
fc.integer({ min, max }), fc.double({ noNaN: true }), fc.bigInt(), fc.date()
fc.array(fc.integer(), { minLength: 0, maxLength: 100 }), fc.uniqueArray(...)
fc.record({ id: fc.uuid(), tags: fc.array(fc.string()) }), fc.dictionary(fc.string(), fc.jsonValue())
fc.jsonValue(), fc.json(), fc.webUrl(), fc.emailAddress(), fc.ipV4(), fc.ipV6()
fc.oneof(...), fc.constantFrom(...), fc.letrec(...)  // recursive
fc.assert(fc.property(...), { numRuns: 5000, seed: 42, path: "3:1:0", endOnFailure: true })
fc.assert(fc.asyncProperty(...))                       // async
// Stateful: fc.commands([...]) with fc.modelRun(() => ({ model, real }), cmds)
```

**proptest (Rust)**
```rust
proptest! {
    #![proptest_config(ProptestConfig::with_cases(5000))]
    #[test]
    fn roundtrip(s in "\\PC*") { prop_assert_eq!(decode(&encode(&s)).unwrap(), s); }
    #[test]
    fn pages_partition(v in prop::collection::vec(any::<i64>(), 0..1000), n in 1usize..100) {
        let pages = paginate(&v, n);
        prop_assert_eq!(pages.concat(), v);
    }
}
```

**rapid (Go)**
```go
rapid.Check(t, func(t *rapid.T) {
    xs := rapid.SliceOf(rapid.Int()).Draw(t, "xs")
    n := rapid.IntRange(1, 100).Draw(t, "n")
    pages := Paginate(xs, n)
    if !reflect.DeepEqual(flatten(pages), xs) { t.Fatalf("lost items") }
})
```

**jqwik (Java)**
```java
@Property(tries = 5000)
void roundTrip(@ForAll String s) { assertThat(decode(encode(s))).isEqualTo(s); }
@Provide Arbitrary<String> weird() { return Arbitraries.strings().withCharRange('\u0000', '￿'); }
```

## 5. Turning counterexamples into findings

Shrunk counterexamples are the best evidence you can put in a report: small, deterministic,
and obviously wrong. For each one record the property as a sentence ("flattening the pages
must give back the original list"), the minimal input, expected vs actual, and the
reproduction command including the seed.
