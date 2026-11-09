# Attack playbook: input classes and concrete payloads

For each public input in scope, walk every section that applies. Each bullet is a payload
or a transformation; the question after it is the oracle. Write the chosen attacks into
`adversarial/04-attack-plan.md` with the property each one tests.

## Table of contents

1. Boundaries and cardinality
2. Numeric edge cases
3. Strings, encoding, and Unicode
4. Structured data (JSON, XML, YAML, CSV)
5. Paths, URLs, and identifiers
6. Time, dates, locale
7. Size and resource exhaustion
8. Ordering, duplicates, and collections
9. State, lifecycle, idempotency
10. Concurrency and reentrancy
11. Injection surfaces
12. Serialization round-trips
13. Error-path behavior
14. Agent-specific patterns

---

### 1. Boundaries and cardinality
- Empty: `""`, `[]`, `{}`, `None`/`null`/`undefined`, zero-byte file, empty stream.
- One element; exactly the limit; limit ± 1; the type's max and min.
- Off-by-one on pagination: page 0, page -1, page size 0, page beyond last, offset == total.
- Oracle: documented behavior at the edge, or the same behavior as the nearest valid input.

### 2. Numeric edge cases
- `0`, `-0`, `-1`, `1`, `2^31-1`, `2^31`, `2^32`, `2^53` (JS integer precision), `2^63-1`,
  `2^64`, `-2^63`, `10^308`, `1e-324`.
- `NaN`, `+inf`, `-inf`, denormals (`5e-324`), `0.1 + 0.2`, values whose rounding differs
  between banker's and half-up.
- Integer passed where float expected and the reverse; numeric strings `"1e3"`, `"0x10"`,
  `"١٢٣"` (Arabic-Indic digits), `"1_000"`, `" 1 "`, `"+1"`, `"1."`, `".5"`.
- Decimal currency: `0.10 + 0.20 == 0.30` in floats? Totals that must sum exactly.
- Oracle: no silent overflow or wraparound; errors for non-finite where the spec implies
  finite; totals equal the sum of parts within the documented precision.

### 3. Strings, encoding, and Unicode
- Control characters `\x00`–`\x1f`, `\x7f`; `\r\n` vs `\n`; tabs; BOM `﻿` at start and
  mid-string.
- Zero-width: `​`, `‌`, `‍`, `⁠`, `﻿`. Bidi overrides `‮`,
  `⁦`–`⁩` (can reverse rendered text; classic spoofing).
- Normalization: `é` as `é` vs `é`; Turkish dotless `ı` and `İ` under
  `.lower()`/`.upper()`; `ß` → `SS`; ligatures `ﬁ`; full-width `Ａ`.
- Homoglyphs: Cyrillic `а` for Latin `a`, Greek `ο`, `𝗮` mathematical bold.
- Emoji with ZWJ sequences and skin tones (grapheme count != code point count != byte count);
  surrogate halves `\ud800` unpaired; overlong UTF-8 `C0 80`; invalid bytes `FF FE`.
- Very long single grapheme cluster; 10 000 combining marks on one base ("zalgo").
- Case and whitespace variants of enumerations: `"TRUE"`, `" true"`, `"True\n"`.
- Oracle: lengths and truncation counted in the unit the spec names; comparisons normalized
  if the spec says equivalent; no crash on invalid UTF-8; output does not change meaning
  under bidi.

### 4. Structured data
- JSON: duplicate keys (which wins?), nesting 10 000 deep (stack), huge numbers (`1e400`),
  `-0`, lone surrogates in strings, trailing commas, comments, `NaN` literals, top-level
  scalar, 1 MB string value, keys like `__proto__`, `constructor`, `prototype` (prototype
  pollution in JS), `$where` and `$gt` (NoSQL operators).
- YAML: `yes`/`no`/`on`/`off` as booleans, `1e3` as string vs float, anchors and aliases
  (billion laughs), tags `!!python/object`.
- XML: entity expansion, external entities (XXE), CDATA with `]]>`, namespace confusion.
- CSV: fields starting with `=`, `+`, `-`, `@` (formula injection), embedded newlines in
  quoted fields, inconsistent column counts, BOM, mixed delimiters, 1 million rows.
- Oracle: schema-violating input rejected with the documented error, never a 500 or a
  partial write.

### 5. Paths, URLs, and identifiers
- `../../etc/passwd`, `..\\`, `%2e%2e%2f`, `....//`, absolute paths, UNC `\\\\server\\share`,
  `file:///`, null byte `a.txt\x00.jpg`, trailing dot or space (Windows), reserved names
  `CON`, `NUL`, case-only differences on case-insensitive filesystems, symlinks.
- URLs: `javascript:`, `data:`, userinfo `http://evil@good.com`, IDN homographs,
  `http://127.1`, `http://[::1]`, `http://0x7f000001`, port 0, 65536, fragments, double
  encoding `%252e`, missing scheme, 2 083+ chars.
- IDs: negative, zero, UUID with uppercase/braces/urn prefix, UUID nil, sequential guessing,
  IDs belonging to another tenant (authorization), strings where ints expected.
- Oracle: traversal and scheme confusion rejected; tenant isolation holds.

### 6. Time, dates, locale
- `1970-01-01`, `1969-12-31`, `2038-01-19T03:14:08Z`, `9999-12-31`, `0001-01-01`,
  Feb 29 in leap and non-leap years, `24:00:00`, leap second `23:59:60`, DST gap
  (`2026-03-08T02:30` in America/New_York does not exist) and overlap, offsets `+14:00`
  and `-12:00`, `Z` vs `+00:00`, naive vs aware datetimes, epoch in seconds vs
  milliseconds (13 digits), negative epoch, month 13, day 0, ISO week dates.
- Run the suite with `TZ=Pacific/Kiritimati`, `TZ=America/St_Johns` (half-hour), `LC_ALL=tr_TR.UTF-8`,
  `LANG=C`, and with the clock faked to Dec 31 23:59:59.
- Oracle: round-trip `parse(format(t)) == t`; ordering preserved across zones; no
  locale-dependent parsing of machine formats.

### 7. Size and resource exhaustion
- Input 100× and 10 000× larger than any test uses; 1 MB string; 10 MB JSON; 10⁶ list items;
  deeply recursive structures; regex inputs crafted for catastrophic backtracking
  (`"a" * 50_000 + "!"` against `(a+)+$`); zip bombs; many small requests.
- Measure time and memory; compare against a linear expectation from two smaller sizes.
- Oracle: documented limits enforced; complexity does not explode; no unbounded buffering.

### 8. Ordering, duplicates, and collections
- Unsorted input where sorted assumed; reverse-sorted; all-equal elements; duplicates;
  stability of sort on ties; set vs list semantics; dictionary iteration order assumptions;
  input that is a generator consumed twice.
- Oracle: result independent of input order when the spec says so (metamorphic:
  `f(shuffle(x)) == f(x)`); duplicates handled per spec.

### 9. State, lifecycle, idempotency
- Call twice; call after close; close twice; use before init; retry after partial failure;
  same request ID twice (idempotency key); concurrent create with same natural key.
- Oracle: `f(f(x)) == f(x)` where idempotent; no resource leak after N open/close cycles;
  invariants hold after every step of a random operation sequence (stateful PBT).

### 10. Concurrency and reentrancy
- Two writers, one reader; `N` threads incrementing; cancellation mid-operation; a callback
  that re-enters the API; timeouts shorter than the operation.
- Tools: `go test -race`, ThreadSanitizer, `pytest-xdist` with shared state, `loom` for Rust.
- Oracle: final state equals a serial execution; no torn writes; no deadlock within timeout.

### 11. Injection surfaces
Only against local fakes, never live systems.
- SQL: `' OR 1=1 --`, `'; DROP TABLE x; --`, unicode quotes, comments `/**/`, stacked queries.
- Shell: `; id`, `$(id)`, `` `id` ``, `| id`, `&&`, newlines, `-rf` as a filename argument.
- Templates: `{{7*7}}`, `${7*7}`, `<%= 7*7 %>`.
- HTML/JS: `<img src=x onerror=alert(1)>`, `"><svg/onload=alert(1)>`, `javascript:`.
- Headers: `\r\n` in values (response splitting), oversized headers.
- Log injection: newlines and ANSI escape sequences `\x1b[2J` in user-controlled strings.
- Oracle: input is data, never code; output is escaped for its context.

### 12. Serialization round-trips
- `decode(encode(x)) == x` for every generated `x`; `encode(decode(s))` canonical for valid
  `s`; cross-version (old serialized blob read by new code); unknown fields preserved or
  rejected per spec; enum value added after serialization.
- Oracle: round-trip identity; forward and backward compatibility as documented.

### 13. Error-path behavior
- Every documented error: is it raised with the documented type and at the documented
  moment (eager vs lazy)? Every undocumented error path found by fuzzing: is a `TypeError`
  or `KeyError` leaking where a domain error belongs?
- Partial failure: write 3 of 5 items then fail. Is the state consistent?
- Error messages: do they leak internals (paths, SQL, stack traces, secrets)?
- Oracle: error type and message match the contract; no partial state; no leak.

### 14. Agent-specific patterns
Things coding agents do disproportionately often. Check each explicitly.
- Validation added at one entry point but not at the others that reach the same code.
- A helper duplicated with a subtle difference (one copy fixed, the other not).
- `try/except Exception: return None` or `return []` that converts bugs into empty results.
- Default arguments that are mutable (`def f(x, acc=[])`).
- Off-by-one in slicing after "fixing" an index error.
- Case-insensitive comparison done with `.lower()` on one side only.
- Timezone handling that works only in UTC (the agent's sandbox).
- Regex that matches the test string and little else, or far too much (`.*`).
- Hard-coded test values inside the implementation (special-casing; see `test-smells.md` 11).
- "Comprehensive tests" that import the function and assert the happy path N times with
  different variable names.
