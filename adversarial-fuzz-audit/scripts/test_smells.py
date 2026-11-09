#!/usr/bin/env python3
"""Heuristic scan of test files for weak oracles ("test smells").

Finds the mechanical shapes described in references/test-smells.md across Python,
JavaScript/TypeScript, Go, Java/Kotlin, Rust, C#, Ruby and PHP test files, and computes a
rough oracle-strength score per file. It is a starting point for the Phase 3 claim audit,
not a verdict: it cannot see implementation echoes or special-cased inputs. Standard
library only.

Usage:
    test_smells.py <path ...> [--json OUT] [--min-score N] [--impl PATH ...]

With --impl, literals used in tests are cross-checked against the implementation files to
flag possible special-casing (a literal that appears in both a test and an `if`/`==`/`case`
line of the implementation).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".rs", ".cs", ".rb", ".php", ".swift"}
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|test)/|test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(java|kt|cs|swift)$|_spec\.rb$|Test\.php$")

# test function / block starts
TEST_START = re.compile(
    r"^\s*(async\s+)?def\s+test\w*\s*\(|^\s*(it|test|specify)(\.only|\.skip|\.todo|\.each\([^)]*\))?\s*\(|^\s*func\s+(Test|Fuzz|Example)\w*\s*\(|"
    r"^\s*@(Test|ParameterizedTest|RepeatedTest|Fact|Theory|TestCase)\b|^\s*#\[(test|tokio::test|rstest|proptest|quickcheck)\]|^\s*\[(Fact|Theory|Test|TestMethod)\]|"
    r"^\s*(it|specify|scenario)\s+['\"]|^\s*public function test\w*\s*\(|^\s*func test\w*\s*\(", re.M)

ASSERT = re.compile(
    r"\bassert\w*\s*[\(\s]|\bexpect\s*\(|\bshould\b|\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b|\brequire\.\w+\(|\bassert\.\w+\(|"
    r"\bassert_(eq|ne|matches)!|\bassert!|\bAssert\.\w+\(|\bAssertions\.\w+\(|\bassertThat\(|\b\w+\.Should\(|\bexpect\(.*\)\.to|\bself\.assert\w+\(|\bthis\.assert\w+\(|\bprop_assert", re.I)

SMELLS = {
    "existence_only": re.compile(
        r"assert\s+\w[\w\.\[\]]*\s+is\s+not\s+None\s*$|assertIsNotNone\(|assertTrue\(\s*\w+\s*\)|assert\s+\w[\w\.\[\]]*\s*$|"
        r"toBeDefined\(\)|toBeTruthy\(\)|not\.toBeNull\(\)|toBeInstanceOf\(|assertNotNull\(|\.Should\(\)\.NotBeNull\(\)|assert\.NotNil\(|require\.NotNil\(|"
        r"assert\.NoError\(|require\.NoError\(|\.is_ok\(\)\)|\.is_some\(\)\)|assert_ok!|assertIsInstance\(|toHaveLength\(\s*[1-9]\d*\s*\)\s*;?\s*$|"
        r"assert\s+len\(\w+\)\s*>\s*0\s*$|assertGreater\(len\(\w+\),\s*0\)", re.M),
    "broad_exception": re.compile(
        r"pytest\.raises\(\s*(Exception|BaseException)\s*\)|assertRaises\(\s*(Exception|BaseException)\s*[,)]|\.toThrow\(\s*\)|\.toThrowError\(\s*\)|"
        r"rejects\.toThrow\(\s*\)|assertThrows\(\s*(Exception|Throwable|RuntimeException)\.class|Assert\.Throws<(Exception|SystemException)>|"
        r"expect_err\(\)|\.is_err\(\)\)|\bexcept\s*:\s*(pass|return|continue)|\bexcept\s+Exception\s*(as \w+)?\s*:\s*(pass|return)|catch\s*\(\s*\w*\s*\)\s*\{\s*\}|"
        r"expect\s*\{\s*.*\}\.to raise_error\s*$|assert_raises\(\s*(Exception|StandardError)\s*\)", re.M),
    "skipped": re.compile(
        r"@pytest\.mark\.skip\b|@unittest\.skip\b|pytest\.skip\(|^\s*(x|f)?(it|describe|test)\.(skip|todo|only)\(|^\s*x(it|describe|test)\s*\(|t\.Skip\(|t\.SkipNow\(|"
        r"#\[ignore\]|@Disabled\b|@Ignore\b|\[Ignore\]|\[Fact\(Skip|skip:\s*true|pending\s*\(|^\s*skip\s+['\"]|markTestSkipped\(|^\s*//\s*(it|test)\(|^\s*#\s*(def test_|assert)", re.M),
    "snapshot": re.compile(r"toMatchSnapshot\(|toMatchInlineSnapshot\(|toMatchFileSnapshot\(|assert_snapshot!|insta::|snapshot\.assert_match|\.snap['\"]|golden\b.*(update|\-update)|snapshots?/", re.I),
    "mock_heavy": re.compile(r"\bmock\w*\s*\(|\bMock\w*\(|\bpatch\s*\(|@patch\b|@mock\.|jest\.(fn|mock|spyOn)\(|vi\.(fn|mock|spyOn)\(|sinon\.|Mockito\.|when\(.*\)\.thenReturn|\bmockk\b|Substitute\.For|\bstub\w*\s*\(|double\(|\.returns\(|mockResolvedValue|mockReturnValue", re.I),
    "mock_verify_only": re.compile(r"assert_called(_once)?(_with)?\(|assert_any_call\(|toHaveBeenCalled(Times|With)?\(|verify\(\s*\w+\s*(,\s*times\(\d+\))?\s*\)\.|\.Received\(|calledWith|calledOnce|expect\(\w+\.mock\.calls", re.I),
    "magic_literal": re.compile(r"(?<![\w.])(0x[0-9a-f]{8,}|[0-9a-f]{32,}|\d{13,}|\d+\.\d{7,})(?![\w.])", re.I),
    "sleep": re.compile(r"\btime\.sleep\(|\bsleep\(\d|setTimeout\(|await new Promise\(r(esolve)?\s*=>\s*setTimeout|Thread\.sleep\(|time\.Sleep\(|tokio::time::sleep|Task\.Delay\(", re.I),
    "print_debug": re.compile(r"^\s*(print\(|console\.log\(|fmt\.Println\(|System\.out\.println\(|println!\(|Console\.WriteLine\()", re.M),
    "conditional_assert": re.compile(r"^\s*if\b[^\n]*:\s*\n\s+(assert|expect)|^\s*if\s*\([^\n]*\)\s*\{?\s*\n?\s*(expect|assert|t\.Error)", re.M),
    "tautology_shape": re.compile(r"assert\s+(\w+)\s*==\s*\1\s*$|expect\((\w+)\)\.toBe\(\2\)|assert(Equal|Equals)\((\w+),\s*\4\)|assert_eq!\((\w+),\s*\5\)|assertEqual\(\s*(\w+\([^)]*\))\s*,\s*\6\s*\)", re.M),
    "catch_all_try": re.compile(r"^\s*try\s*:\s*\n(?:.*\n)*?\s*except\b.*:\s*\n\s*(pass|return|continue)\b|try\s*\{[^}]*\}\s*catch\s*\([^)]*\)\s*\{\s*\}", re.M),
}

NEGATIVE_INPUT = re.compile(r"\b(None|null|nil|undefined|NaN|Infinity|-1|0|\"\"|''|\[\]|\{\}|empty|invalid|malformed|negative|overflow|huge|unicode|boundary|edge|max|min|raises|throws|error|fail)\b", re.I)

WEIGHTS = {  # points subtracted from 100 per occurrence (capped per smell)
    "no_assert_tests": (25, 60), "existence_only": (6, 30), "broad_exception": (8, 30), "skipped": (5, 25), "snapshot": (4, 20),
    "mock_verify_only": (4, 20), "magic_literal": (2, 10), "sleep": (3, 10), "conditional_assert": (6, 20), "tautology_shape": (15, 45),
    "catch_all_try": (10, 30), "possible_special_case": (15, 45), "no_negative_tests": (20, 20),
}


def split_tests(text: str) -> list[tuple[str, str]]:
    """Return (name, body) for each test block, by start markers; body runs to next start."""
    starts = [m.start() for m in TEST_START.finditer(text)]
    blocks = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[s:e].lstrip("\r\n")
        first = chunk.splitlines()[0].strip() if chunk.strip() else ""
        m = re.search(r"(test\w*|Test\w*|['\"][^'\"]+['\"])", first)
        blocks.append((m.group(1) if m else first[:60], chunk))
    return blocks


def literals_in(text: str) -> set[str]:
    lits = set(re.findall(r"""(?<![\w])(?:"([^"\\\n]{2,40})"|'([^'\\\n]{2,40})')""", text))
    out = {a or b for a, b in lits}
    out |= {n for n in re.findall(r"(?<![\w.])(\d{2,})(?![\w.])", text) if n not in {"00", "10", "100", "1000"}}
    return {l for l in out if not re.fullmatch(r"[\s\W]*", l)}


def impl_special_case_lines(impl_texts: dict[str, str]) -> dict[str, list[tuple[str, int, str]]]:
    """Map literal -> [(file, line, text)] for literals that appear in comparison/branch lines of implementation code."""
    idx: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for path, text in impl_texts.items():
        for ln, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b(if|elif|else if|case|when|match|switch|return)\b|==|===|\.equals\(|strcmp|\bin\s*[\(\[\{]", line):
                for lit in literals_in(line):
                    idx[lit].append((path, ln, line.strip()[:100]))
    return idx


def analyze_file(path: Path, impl_idx: dict | None) -> dict:
    text = path.read_text(errors="ignore")
    tests = split_tests(text)
    findings: dict[str, list] = defaultdict(list)
    for name, body in tests:
        if not ASSERT.search(body):
            findings["no_assert_tests"].append(name)
    for smell, rx in SMELLS.items():
        if smell == "mock_heavy":
            continue
        for m in rx.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            findings[smell].append({"line": ln, "text": text.splitlines()[ln - 1].strip()[:120]})
    mock_lines = len(SMELLS["mock_heavy"].findall(text))
    assert_lines = len(ASSERT.findall(text))
    if mock_lines and assert_lines and mock_lines / assert_lines >= 2:
        findings["mock_heavy_ratio"].append({"mocks": mock_lines, "asserts": assert_lines})
    negative = bool(NEGATIVE_INPUT.search(text))
    if tests and not negative:
        findings["no_negative_tests"].append("no test mentions empty/null/invalid/boundary/error inputs")
    if impl_idx:
        for lit in literals_in(text):
            if lit in impl_idx:
                findings["possible_special_case"].append({"literal": lit, "implementation": impl_idx[lit][:3]})
    score = 100
    for smell, items in findings.items():
        per, cap = WEIGHTS.get(smell, (2, 10))
        score -= min(cap, per * len(items))
    score = max(0, score)
    return {
        "file": str(path), "tests": len(tests), "assert_lines": assert_lines, "mock_lines": mock_lines,
        "oracle_strength": score, "smells": {k: v for k, v in findings.items()},
        "counts": {k: len(v) for k, v in findings.items()},
    }


def collect(paths: list[str], want_tests: bool) -> list[Path]:
    out = []
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            out.append(pp)
        elif pp.is_dir():
            for f in pp.rglob("*"):
                if f.suffix in EXTS and f.is_file() and not any(s in f.parts for s in ("node_modules", ".git", "vendor", "dist", "build", "__pycache__", "target")):
                    if want_tests == bool(TEST_PATH.search(str(f).replace("\\", "/"))):
                        out.append(f)
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="test files or directories")
    ap.add_argument("--impl", nargs="*", default=[], help="implementation files/dirs to cross-check literals for special-casing")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--min-score", type=int, default=101, help="only print files scoring below this")
    args = ap.parse_args()

    files = collect(args.paths, want_tests=True) or [Path(p) for p in args.paths if Path(p).is_file()]
    impl_idx = None
    if args.impl:
        impl_files = collect(args.impl, want_tests=False)
        impl_idx = impl_special_case_lines({str(f): f.read_text(errors="ignore") for f in impl_files})
    results = [analyze_file(f, impl_idx) for f in files]
    total = Counter()
    for r in results:
        total.update(r["counts"])

    print(f"{'file':<58} {'tests':>5} {'score':>5}  top smells")
    for r in results:
        if r["oracle_strength"] < args.min_score:
            top = ", ".join(f"{k}={v}" for k, v in sorted(r["counts"].items(), key=lambda kv: -kv[1])[:4])
            print(f"{r['file'][-57:]:<58} {r['tests']:>5} {r['oracle_strength']:>5}  {top}")
    if results:
        avg = sum(r["oracle_strength"] for r in results) / len(results)
        print(f"\n{len(results)} files, {sum(r['tests'] for r in results)} tests, mean oracle strength {avg:.0f}/100")
        print("totals: " + ", ".join(f"{k}={v}" for k, v in total.most_common()))
        print("Read every file below 60 in full. The scan cannot see implementation echoes or hand-picked happy paths.")
    else:
        print("no test files found; pass files explicitly or check the path patterns in --help")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps({"files": results, "totals": dict(total)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
