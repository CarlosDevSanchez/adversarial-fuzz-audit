#!/usr/bin/env python3
"""Generate a deterministic corpus of malformed / hostile inputs for fuzzing an agent's code.

Each case is written as its own JSON file {"id", "kind", "category", "note", "value"} so a
harness in any language can replay it. Binary payloads are base64-encoded with
"encoding": "base64". The corpus is seeded, so two runs with the same --seed produce the
same files and a finding can be reproduced by file name. Standard library only.

Usage:
    gen_malformed.py --kind all --out adversarial/05-fuzz/corpus [--seed 1337] [--max-size 1048576]

Kinds: string number json bytes csv url path datetime identifier all
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from pathlib import Path

# ----------------------------------------------------------------------------- strings
CONTROL = [chr(i) for i in range(0, 32)] + ["\x7f"]
ZERO_WIDTH = ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u180e"]
BIDI = ["\u202a", "\u202b", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069", "\u200f", "\u200e"]
NORMALIZATION = ["e\u0301", "\u00e9", "\ufb01", "\uff21", "\u0130", "\u0131", "\u00df", "\u1e9e", "\u212b", "\u00c5"]
HOMOGLYPHS = ["\u0430dmin", "p\u0430ypal", "\u03bfk", "\U0001d5ee", "\u0410\u0412\u0421", "rn" , "\u2170"]
EMOJI = ["\U0001f600", "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466", "\U0001f44d\U0001f3fd", "\U0001f1fa\U0001f1f8", "\u2764\ufe0f"]
WHITESPACE = [" ", "  ", "\t", "\n", "\r\n", "\r", "\u00a0", "\u2003", "\u3000", " leading", "trailing ", "\u000b", "\u000c"]
INJECTION = [
    "' OR 1=1 --", "'; DROP TABLE users; --", "\" OR \"\"=\"", "1; SELECT * FROM users",
    "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "\"><svg/onload=alert(1)>", "javascript:alert(1)",
    "{{7*7}}", "${7*7}", "<%= 7*7 %>", "#{7*7}", "{{constructor.constructor('return this')()}}",
    "$(id)", "`id`", "; id", "| id", "&& id", "\nid\n", "-rf /", "--help", "-",
    "%s%s%s%s%n", "%x%x%x%x", "{0}{1}{2}",
    "=1+1", "+1+1", "-1+1", "@SUM(1+1)", "=cmd|' /C calc'!A0",
    "../../../../etc/passwd", "..\\..\\..\\windows\\win.ini", "%2e%2e%2f%2e%2e%2f", "....//....//",
    "\x1b[2J\x1b[H", "\x1b]0;pwned\x07", "line1\nFAKE LOG ENTRY: admin logged in",
    "__proto__", "constructor", "prototype", "$where", "$gt", "{\"$ne\": null}",
    "<!DOCTYPE x [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><x>&xxe;</x>",
    "%00", "\x00", "a\x00b", "NUL", "CON", "AUX", "COM1", "LPT1",
]
RESERVED_WORDS = ["null", "NULL", "None", "nil", "undefined", "NaN", "Infinity", "-Infinity", "true", "false", "True",
                  "FALSE", "yes", "no", "on", "off", "0", "1", "-1", "0x0", "0e0", "1e309", "[]", "{}", "()", "\"\"", "''"]


def strings(rng: random.Random, max_size: int):
    out = []
    def add(cat, note, v): out.append((cat, note, v))
    add("empty", "empty string", "")
    for c in CONTROL: add("control", f"U+{ord(c):04X}", c); add("control", f"embedded U+{ord(c):04X}", f"ab{c}cd")
    for z in ZERO_WIDTH: add("zero-width", f"U+{ord(z):04X}", f"ad{z}min")
    for b in BIDI: add("bidi", f"U+{ord(b):04X} override", f"abc{b}fed")
    for n in NORMALIZATION: add("normalization", repr(n), n)
    for h in HOMOGLYPHS: add("homoglyph", repr(h), h)
    for e in EMOJI: add("emoji", "grapheme != codepoint != byte", e)
    for w in WHITESPACE: add("whitespace", repr(w), w)
    for i in INJECTION: add("injection", i[:30], i)
    for r in RESERVED_WORDS: add("reserved-word", r, r)
    add("surrogate", "lone high surrogate (invalid in UTF-8)", "\ud800")
    add("surrogate", "lone low surrogate", "\udfff")
    add("max-codepoint", "U+10FFFF", "\U0010ffff")
    add("noncharacter", "U+FFFE", "\ufffe"); add("noncharacter", "U+FFFF", "\uffff")
    add("zalgo", "100 combining marks", "a" + "\u0301" * 100)
    add("zalgo", "1000 combining marks", "a" + "\u0300" * 1000)
    add("long", "255 a", "a" * 255); add("long", "256 a", "a" * 256); add("long", "65535 a", "a" * 65535)
    add("long", "65536 a", "a" * 65536); add("long", f"{max_size} a", "a" * max_size)
    add("long", "10k unicode", "\u00e9" * 10000); add("long", "10k emoji", "\U0001f600" * 10000)
    add("repeat", "regex catastrophic", "a" * 30000 + "!")
    add("repeat", "many newlines", "\n" * 10000)
    add("repeat", "many spaces", " " * 10000)
    add("case", "mixed case true", "TrUe"); add("case", "upper TRUE", "TRUE"); add("case", "padded true", " true \n")
    add("numeric-string", "leading zeros", "007"); add("numeric-string", "plus sign", "+1"); add("numeric-string", "underscore", "1_000")
    add("numeric-string", "hex", "0x10"); add("numeric-string", "exp", "1e3"); add("numeric-string", "arabic-indic digits", "\u0661\u0662\u0663")
    add("numeric-string", "fullwidth digits", "\uff11\uff12\uff13"); add("numeric-string", "trailing dot", "1."); add("numeric-string", "leading dot", ".5")
    add("numeric-string", "comma decimal", "1,5"); add("numeric-string", "thousands", "1,000"); add("numeric-string", "negative zero", "-0")
    add("email-like", "quoted local part", '"a b"@example.com'); add("email-like", "unicode domain", "user@bücher.example")
    add("email-like", "no tld", "user@localhost"); add("email-like", "double at", "a@b@c.com"); add("email-like", "ip literal", "user@[127.0.0.1]")
    # random strings
    alphabet = [chr(i) for i in range(32, 127)] + CONTROL + ZERO_WIDTH + BIDI + EMOJI + ["\u00e9", "\u4e2d", "\u0416", "\u0627"]
    for i in range(40):
        n = rng.choice([1, 2, 3, 7, 16, 64, 255, 1024])
        add("random", f"random mixed #{i}", "".join(rng.choice(alphabet) for _ in range(n)))
    return out


# ----------------------------------------------------------------------------- numbers
def numbers(rng: random.Random, max_size: int):
    out = []
    def add(cat, note, v): out.append((cat, note, v))
    for n in [0, -0.0, 1, -1, 2, -2, 7, 10, 42, 100, 255, 256, 1000, 65535, 65536]:
        add("small", repr(n), n)
    for p in [7, 8, 15, 16, 31, 32, 52, 53, 63, 64, 127, 128]:
        for d in (-1, 0, 1):
            add("power-of-two-boundary", f"2^{p}{d:+d}", 2 ** p + d)
            add("power-of-two-boundary", f"-(2^{p}){d:+d}", -(2 ** p) + d)
    add("float", "0.1+0.2", 0.1 + 0.2); add("float", "1/3", 1 / 3); add("float", "min positive subnormal", 5e-324)
    add("float", "max double", 1.7976931348623157e308); add("float", "min normal", 2.2250738585072014e-308)
    add("float", "half-even tie 2.5", 2.5); add("float", "half-even tie 0.125", 0.125); add("float", "1e16+1", 1e16 + 1)
    add("float", "9007199254740993 (2^53+1 as float)", float(9007199254740993))
    add("float-string", "NaN", "NaN"); add("float-string", "inf", "Infinity"); add("float-string", "-inf", "-Infinity"); add("float-string", "nan lower", "nan")
    add("huge", "10^100", 10 ** 100); add("huge", "-10^100", -(10 ** 100)); add("huge-string", "1e400", "1e400"); add("huge-string", "4000 digits", "9" * 4000)
    add("money", "0.30 as float", 0.3); add("money", "19.99*3", 19.99 * 3); add("money", "negative cents", -0.01); add("money", "sub-cent", 0.001)
    add("percent", "100", 100); add("percent", "101", 101); add("percent", "-1", -1); add("percent", "1.0 vs 100", 1.0)
    add("time-ish", "epoch ms 13 digits", 1700000000000); add("time-ish", "epoch s", 1700000000); add("time-ish", "2038 overflow", 2147483648); add("time-ish", "negative epoch", -1)
    for i in range(30):
        kind = rng.choice(["int", "float", "big"])
        if kind == "int": v = rng.randint(-2**63, 2**63)
        elif kind == "float": v = rng.uniform(-1e18, 1e18)
        else: v = rng.randint(-10**40, 10**40)
        add("random", f"random {kind} #{i}", v)
    return out


# ----------------------------------------------------------------------------- json
def json_docs(rng: random.Random, max_size: int):
    out = []
    def add(cat, note, v): out.append((cat, note, v))
    add("empty", "empty document", "")
    add("scalar-top", "top-level null", "null"); add("scalar-top", "top-level number", "1"); add("scalar-top", "top-level string", '"x"')
    add("whitespace", "only whitespace", " \n\t ")
    add("bom", "UTF-8 BOM prefix", "\ufeff{}")
    add("dup-keys", "duplicate keys", '{"a": 1, "a": 2}')
    add("dup-keys", "duplicate keys nested", '{"user": {"role": "user", "role": "admin"}}')
    add("proto", "__proto__ key", '{"__proto__": {"admin": true}}'); add("proto", "constructor.prototype", '{"constructor": {"prototype": {"admin": true}}}')
    add("nosql", "$gt operator", '{"password": {"$gt": ""}}'); add("nosql", "$where", '{"$where": "1==1"}')
    add("numbers", "huge exponent", '{"n": 1e400}'); add("numbers", "negative zero", '{"n": -0}'); add("numbers", "leading zero", '{"n": 01}')
    add("numbers", "2^53+1", '{"n": 9007199254740993}'); add("numbers", "huge int", '{"n": ' + "9" * 400 + '}'); add("numbers", "hex", '{"n": 0x10}')
    add("literals", "NaN literal", '{"n": NaN}'); add("literals", "Infinity literal", '{"n": Infinity}'); add("literals", "undefined", '{"n": undefined}')
    add("syntax", "trailing comma obj", '{"a": 1,}'); add("syntax", "trailing comma arr", '[1,2,]'); add("syntax", "single quotes", "{'a': 1}")
    add("syntax", "comment", '{"a": 1 /* c */}'); add("syntax", "unquoted key", '{a: 1}'); add("syntax", "unterminated", '{"a": "b'); add("syntax", "extra brace", '{"a": 1}}')
    add("syntax", "two documents", '{"a":1}{"b":2}'); add("syntax", "ndjson", '{"a":1}\n{"b":2}\n')
    add("strings", "lone surrogate escape", '{"s": "\\ud800"}'); add("strings", "null byte escape", '{"s": "a\\u0000b"}'); add("strings", "raw newline in string", '{"s": "a\nb"}')
    add("strings", "invalid escape", '{"s": "\\x41"}'); add("strings", "bidi override", '{"name": "abc\\u202eexe.txt"}'); add("strings", "1MB string", '{"s": "' + "a" * max_size + '"}')
    deep = 100000
    add("nesting", "100k nested arrays", "[" * deep + "]" * deep); add("nesting", "10k nested objects", '{"a":' * 10000 + "1" + "}" * 10000)
    add("nesting", "unbalanced deep", "[" * 10000)
    add("types", "string where number expected", '{"count": "10"}'); add("types", "number where string expected", '{"name": 10}'); add("types", "array where object", '[{"a":1}]')
    add("types", "bool as string", '{"active": "false"}'); add("types", "null for required", '{"id": null}'); add("types", "missing required", '{}')
    add("types", "object where scalar", '{"id": {"$oid": "x"}}'); add("types", "empty array", '{"items": []}'); add("types", "array of nulls", '{"items": [null, null]}')
    add("size", "100k keys", "{" + ",".join(f'"k{i}": {i}' for i in range(100000)) + "}")
    add("size", "100k-element array", "[" + ",".join("0" for _ in range(100000)) + "]")
    add("keys", "empty key", '{"": 1}'); add("keys", "whitespace key", '{" ": 1}'); add("keys", "very long key", '{"' + "k" * 10000 + '": 1}')
    add("keys", "unicode key", '{"ключ": 1}'); add("keys", "case-variant keys", '{"Id": 1, "id": 2, "ID": 3}')
    for i in range(25):
        add("random-valid", f"random valid doc #{i}", json.dumps(_rand_json(rng, 0), ensure_ascii=False))
    for i in range(25):
        s = json.dumps(_rand_json(rng, 0))
        if len(s) > 3:
            k = rng.randrange(len(s)); s = s[:k] + rng.choice(['"', "{", "}", "[", "]", ",", ":", "\\", "\x00", "é"]) + s[k + 1:]
        add("random-mutated", f"random mutated doc #{i}", s)
    return out


def _rand_json(rng: random.Random, depth: int):
    if depth > 4:
        return rng.choice([None, True, 0, "", "x"])
    t = rng.random()
    if t < 0.2: return rng.choice([None, True, False])
    if t < 0.4: return rng.choice([0, -1, 1, 2**31, -2**63, 0.5, 1e-7, 1e21])
    if t < 0.6: return rng.choice(["", " ", "a", "\u00e9", "\u202e", "null", "0", "a" * 100])
    if t < 0.8: return [_rand_json(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    return {rng.choice(["a", "id", "", "__proto__", "name", "k"]): _rand_json(rng, depth + 1) for _ in range(rng.randint(0, 5))}


# ----------------------------------------------------------------------------- bytes
def byte_blobs(rng: random.Random, max_size: int):
    out = []
    def add(cat, note, v: bytes): out.append((cat, note, v))
    add("empty", "zero bytes", b"")
    add("nul", "single NUL", b"\x00"); add("nul", "NUL-padded", b"abc\x00\x00\x00")
    add("utf8-invalid", "lone continuation", b"\x80"); add("utf8-invalid", "truncated 3-byte", b"\xe2\x82"); add("utf8-invalid", "0xFF 0xFE", b"\xff\xfe")
    add("utf8-invalid", "overlong slash C0 AF", b"\xc0\xaf"); add("utf8-invalid", "overlong NUL C0 80", b"\xc0\x80"); add("utf8-invalid", "surrogate ED A0 80", b"\xed\xa0\x80")
    add("utf8-invalid", "5-byte sequence", b"\xf8\x88\x80\x80\x80"); add("utf8-invalid", "> U+10FFFF", b"\xf4\x90\x80\x80")
    add("bom", "UTF-8 BOM", b"\xef\xbb\xbf"); add("bom", "UTF-16 LE BOM", b"\xff\xfe"); add("bom", "UTF-16 BE BOM", b"\xfe\xff"); add("bom", "UTF-32 LE BOM", b"\xff\xfe\x00\x00")
    add("magic", "PNG header only", b"\x89PNG\r\n\x1a\n"); add("magic", "gzip header only", b"\x1f\x8b\x08\x00"); add("magic", "zip EOCD only", b"PK\x05\x06" + b"\x00" * 18)
    add("magic", "PDF header only", b"%PDF-1.7\n"); add("magic", "ELF header", b"\x7fELF"); add("magic", "JPEG SOI only", b"\xff\xd8\xff")
    add("magic", "mismatched: PNG magic, text body", b"\x89PNG\r\n\x1a\nhello world")
    add("crlf", "CRLF only", b"\r\n" * 1000); add("crlf", "mixed line endings", b"a\nb\r\nc\rd")
    add("all-same", "1MB zeros", b"\x00" * max_size); add("all-same", "1MB 0xFF", b"\xff" * max_size)
    add("pattern", "0..255 repeated", bytes(range(256)) * 64)
    for i in range(30):
        n = rng.choice([1, 2, 3, 4, 7, 8, 15, 16, 17, 64, 255, 256, 1023, 4096])
        add("random", f"random bytes #{i} len {n}", bytes(rng.getrandbits(8) for _ in range(n)))
    return out


# ----------------------------------------------------------------------------- csv / url / path / datetime / identifier
def csv_docs(rng: random.Random, max_size: int):
    rows = [
        ("formula", "formula injection =", 'name,amount\n=1+1,10\n'), ("formula", "formula injection @", 'name,amount\n@SUM(A1),10\n'),
        ("formula", "formula via cmd", 'name\n=cmd|\' /C calc\'!A0\n'), ("formula", "leading plus/minus", 'a,b\n+1,-1\n'),
        ("quoting", "embedded newline", 'name,note\n"a","line1\nline2"\n'), ("quoting", "embedded quote", 'name\n"a""b"\n'), ("quoting", "unbalanced quote", 'name\n"abc\n'),
        ("columns", "ragged rows", 'a,b,c\n1,2\n1,2,3,4\n'), ("columns", "header only", 'a,b,c\n'), ("columns", "no header", '1,2,3\n'), ("columns", "duplicate headers", 'id,id,id\n1,2,3\n'),
        ("delimiter", "semicolons", 'a;b;c\n1;2;3\n'), ("delimiter", "tabs", 'a\tb\tc\n1\t2\t3\n'), ("delimiter", "mixed", 'a,b;c\n1;2,3\n'),
        ("encoding", "BOM + CRLF", '\ufeffa,b\r\n1,2\r\n'), ("encoding", "latin-1 bytes as text", 'name\ncaf\u00e9\n'),
        ("empty", "empty", ""), ("empty", "only newlines", "\n\n\n"), ("empty", "blank fields", 'a,b\n,\n,,\n'),
        ("size", "100k rows", 'a,b\n' + "1,2\n" * 100000), ("size", "one huge field", 'a\n' + "x" * max_size + "\n"),
        ("types", "numbers with thousands sep", 'amount\n"1,000"\n'), ("types", "dates mixed formats", 'd\n2024-01-02\n01/02/2024\n2 Jan 2024\n'),
        ("injection", "null byte", 'a\nx\x00y\n'), ("injection", "html in field", 'a\n<script>alert(1)</script>\n'),
    ]
    return rows


def urls(rng: random.Random, max_size: int):
    base = [
        ("scheme", "javascript scheme", "javascript:alert(1)"), ("scheme", "data scheme", "data:text/html,<script>alert(1)</script>"),
        ("scheme", "file scheme", "file:///etc/passwd"), ("scheme", "no scheme", "example.com/path"), ("scheme", "uppercase scheme", "HTTP://EXAMPLE.COM"),
        ("scheme", "scheme with whitespace", "java\tscript:alert(1)"), ("scheme", "gopher", "gopher://localhost:25/"),
        ("host", "userinfo spoof", "http://good.com@evil.com/"), ("host", "ip decimal", "http://2130706433/"), ("host", "ip hex", "http://0x7f000001/"),
        ("host", "ip short", "http://127.1/"), ("host", "ipv6 loopback", "http://[::1]/"), ("host", "ipv6 mapped", "http://[::ffff:127.0.0.1]/"),
        ("host", "localhost", "http://localhost/"), ("host", "metadata endpoint", "http://169.254.169.254/latest/meta-data/"), ("host", "idn homograph", "http://\u0430pple.com/"),
        ("host", "punycode", "http://xn--80ak6aa92e.com/"), ("host", "trailing dot", "http://example.com./"), ("host", "port 0", "http://example.com:0/"), ("host", "port 65536", "http://example.com:65536/"),
        ("host", "empty host", "http:///path"), ("host", "backslash", "http://example.com\\@evil.com/"),
        ("path", "traversal", "http://example.com/../../etc/passwd"), ("path", "encoded traversal", "http://example.com/%2e%2e/%2e%2e/"), ("path", "double encoded", "http://example.com/%252e%252e/"),
        ("path", "null byte", "http://example.com/a%00.jpg"), ("path", "unicode slash", "http://example.com/a\u2215b"), ("path", "very long", "http://example.com/" + "a" * 5000),
        ("query", "duplicate params", "http://example.com/?a=1&a=2"), ("query", "array params", "http://example.com/?a[]=1&a[]=2"), ("query", "empty key", "http://example.com/?=1"),
        ("query", "semicolon separator", "http://example.com/?a=1;b=2"), ("query", "encoded ampersand", "http://example.com/?a=1%26b=2"), ("query", "plus vs space", "http://example.com/?q=a+b%20c"),
        ("fragment", "fragment with script", "http://example.com/#<script>"), ("fragment", "only fragment", "#top"),
        ("relative", "protocol-relative", "//evil.com/"), ("relative", "dot segment", "./a/../b"), ("relative", "triple slash", "http:///evil.com"),
        ("empty", "empty", ""), ("whitespace", "spaces", "http://example .com/"), ("whitespace", "leading space", " http://example.com/"),
        ("size", "2083 chars", "http://example.com/" + "a" * 2064), ("size", "64k", "http://example.com/" + "a" * 65536),
    ]
    return base


def paths(rng: random.Random, max_size: int):
    return [
        ("traversal", "dotdot unix", "../../../etc/passwd"), ("traversal", "dotdot windows", "..\\..\\..\\windows\\win.ini"), ("traversal", "mixed", "..\\../..\\../etc/passwd"),
        ("traversal", "encoded", "%2e%2e%2f%2e%2e%2fetc%2fpasswd"), ("traversal", "double encoded", "%252e%252e%252f"), ("traversal", "overlong utf8", "\xc0\xae\xc0\xae/"), ("traversal", "quad dot", "....//....//etc/passwd"),
        ("absolute", "unix root", "/etc/passwd"), ("absolute", "windows drive", "C:\\Windows\\System32"), ("absolute", "UNC", "\\\\server\\share\\file"), ("absolute", "file url", "file:///etc/passwd"),
        ("special", "null byte", "safe.txt\x00.exe"), ("special", "trailing space", "file.txt "), ("special", "trailing dot", "file.txt."), ("special", "reserved CON", "CON"), ("special", "reserved NUL.txt", "NUL.txt"),
        ("special", "dot", "."), ("special", "dotdot", ".."), ("special", "hidden", ".env"), ("special", "git dir", ".git/config"), ("special", "tilde", "~/.ssh/id_rsa"), ("special", "dev", "/dev/zero"), ("special", "proc", "/proc/self/environ"),
        ("case", "case variant", "FILE.TXT"), ("unicode", "rtl override", "file\u202etxt.exe"), ("unicode", "zero width", "fi\u200ble.txt"), ("unicode", "nfd", "cafe\u0301.txt"), ("unicode", "fullwidth slash", "a\uff0fb"),
        ("length", "255 chars name", "a" * 255), ("length", "256 chars name", "a" * 256), ("length", "4096 path", "/".join(["d"] * 2048)), ("length", "deep", "/".join(["x"] * 500)),
        ("empty", "empty", ""), ("empty", "whitespace", "   "), ("glob", "star", "*"), ("glob", "brace", "{a,b}"), ("glob", "question", "?"), ("shell", "dash prefix", "-rf"), ("shell", "semicolon", "a;rm -rf x"),
        ("symlink", "symlink name hint", "link -> /etc/passwd"),
    ]


def datetimes(rng: random.Random, max_size: int):
    return [
        ("epoch", "unix epoch", "1970-01-01T00:00:00Z"), ("epoch", "before epoch", "1969-12-31T23:59:59Z"), ("epoch", "2038 problem", "2038-01-19T03:14:08Z"), ("epoch", "2038 minus 1s", "2038-01-19T03:14:07Z"),
        ("range", "year 0001", "0001-01-01T00:00:00Z"), ("range", "year 9999", "9999-12-31T23:59:59Z"), ("range", "year 10000", "10000-01-01T00:00:00Z"), ("range", "year 0000", "0000-01-01"), ("range", "negative year", "-0001-01-01"),
        ("leap", "feb 29 leap", "2024-02-29"), ("leap", "feb 29 non-leap", "2023-02-29"), ("leap", "feb 29 century non-leap", "1900-02-29"), ("leap", "feb 29 400-year leap", "2000-02-29"), ("leap", "leap second", "2016-12-31T23:59:60Z"),
        ("invalid", "month 13", "2024-13-01"), ("invalid", "month 0", "2024-00-10"), ("invalid", "day 0", "2024-01-00"), ("invalid", "day 32", "2024-01-32"), ("invalid", "hour 24", "2024-01-01T24:00:00Z"), ("invalid", "hour 25", "2024-01-01T25:00:00Z"), ("invalid", "minute 60", "2024-01-01T00:60:00Z"),
        ("dst", "nonexistent local time NY", "2026-03-08T02:30:00 America/New_York"), ("dst", "ambiguous local time NY", "2026-11-01T01:30:00 America/New_York"),
        ("offset", "+14:00", "2024-01-01T00:00:00+14:00"), ("offset", "-12:00", "2024-01-01T00:00:00-12:00"), ("offset", "+00:00 vs Z", "2024-01-01T00:00:00+00:00"), ("offset", "half-hour", "2024-01-01T00:00:00+05:30"), ("offset", "45 minutes", "2024-01-01T00:00:00+05:45"), ("offset", "invalid +25:00", "2024-01-01T00:00:00+25:00"),
        ("format", "date only", "2024-01-01"), ("format", "no separators", "20240101T000000Z"), ("format", "space separator", "2024-01-01 00:00:00"), ("format", "US order", "01/02/2024"), ("format", "EU order", "02/01/2024"), ("format", "two-digit year", "01/02/24"),
        ("format", "RFC 2822", "Mon, 01 Jan 2024 00:00:00 +0000"), ("format", "fractional 9 digits", "2024-01-01T00:00:00.123456789Z"), ("format", "fractional comma", "2024-01-01T00:00:00,123Z"), ("format", "lowercase t z", "2024-01-01t00:00:00z"), ("format", "week date", "2024-W01-1"), ("format", "ordinal date", "2024-366"),
        ("numeric", "epoch seconds", "1700000000"), ("numeric", "epoch millis", "1700000000000"), ("numeric", "epoch micros", "1700000000000000"), ("numeric", "negative epoch", "-1"), ("numeric", "float epoch", "1700000000.5"),
        ("naive", "no timezone", "2024-06-15T12:00:00"), ("relative", "now", "now"), ("relative", "tomorrow", "tomorrow"), ("relative", "yesterday", "yesterday"), ("relative", "+1 day", "+1 day"),
        ("empty", "empty", ""), ("garbage", "text", "not a date"), ("garbage", "null", "null"), ("garbage", "unicode digits", "\u0662\u0660\u0662\u0664-\u0660\u0661-\u0660\u0661"),
    ]


def identifiers(rng: random.Random, max_size: int):
    return [
        ("int", "zero", 0), ("int", "negative", -1), ("int", "max int32", 2147483647), ("int", "int32 overflow", 2147483648), ("int", "max int64", 9223372036854775807), ("int", "int64 overflow", 9223372036854775808),
        ("int-string", "numeric string", "42"), ("int-string", "leading zeros", "0042"), ("int-string", "plus", "+42"), ("int-string", "float string", "42.0"), ("int-string", "exp", "4.2e1"),
        ("uuid", "nil uuid", "00000000-0000-0000-0000-000000000000"), ("uuid", "max uuid", "ffffffff-ffff-ffff-ffff-ffffffffffff"), ("uuid", "uppercase", "123E4567-E89B-12D3-A456-426614174000"),
        ("uuid", "braces", "{123e4567-e89b-12d3-a456-426614174000}"), ("uuid", "urn prefix", "urn:uuid:123e4567-e89b-12d3-a456-426614174000"), ("uuid", "no dashes", "123e4567e89b12d3a456426614174000"), ("uuid", "invalid version digit", "123e4567-e89b-02d3-a456-426614174000"), ("uuid", "one char short", "123e4567-e89b-12d3-a456-42661417400"),
        ("string", "empty", ""), ("string", "whitespace", " "), ("string", "sql", "1 OR 1=1"), ("string", "path", "../admin"), ("string", "unicode", "\u0438\u0434"), ("string", "null word", "null"), ("string", "undefined", "undefined"),
        ("string", "very long", "a" * 10000), ("string", "other tenant hint", "tenant-B/user-1"), ("string", "case variant", "USER-1"), ("string", "trailing newline", "user-1\n"),
        ("bool", "true as id", True), ("null", "null id", None), ("array", "array of ids", [1, 2]), ("object", "object id", {"$oid": "x"}), ("float", "float id", 1.0), ("float", "nan", "NaN"),
    ]


GENERATORS = {
    "string": strings, "number": numbers, "json": json_docs, "bytes": byte_blobs,
    "csv": csv_docs, "url": urls, "path": paths, "datetime": datetimes, "identifier": identifiers,
}


def write_case(out: Path, kind: str, idx: int, cat: str, note: str, value) -> str:
    case_id = f"{kind}-{idx:04d}"
    rec = {"id": case_id, "kind": kind, "category": cat, "note": note}
    if isinstance(value, (bytes, bytearray)):
        rec["encoding"] = "base64"; rec["value"] = base64.b64encode(bytes(value)).decode("ascii"); rec["length"] = len(value)
    else:
        rec["value"] = value
        if isinstance(value, str):
            rec["length"] = len(value)
    try:
        text = json.dumps(rec, ensure_ascii=False, indent=0)
        text.encode("utf-8")              # lone surrogates cannot be written raw
    except UnicodeEncodeError:
        text = json.dumps(rec, ensure_ascii=True, indent=0)   # escaped as \udXXX, still valid JSON
    (out / f"{case_id}.json").write_text(text, encoding="utf-8")
    return case_id


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", default="all", help="comma list of kinds or 'all'")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--max-size", type=int, default=1_048_576, help="size of the largest payloads (default 1 MiB)")
    ap.add_argument("--list-kinds", action="store_true")
    args = ap.parse_args()
    if args.list_kinds:
        print("\n".join(GENERATORS)); return 0
    kinds = list(GENERATORS) if args.kind == "all" else [k.strip() for k in args.kind.split(",")]
    unknown = [k for k in kinds if k not in GENERATORS]
    if unknown:
        print("unknown kinds:", unknown, file=sys.stderr); return 2
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    index = []
    for kind in kinds:
        rng = random.Random(f"{args.seed}:{kind}")
        for i, (cat, note, value) in enumerate(GENERATORS[kind](rng, args.max_size)):
            index.append({"id": write_case(out, kind, i, cat, note, value), "kind": kind, "category": cat, "note": note})
    (out / "INDEX.json").write_text(json.dumps({"seed": args.seed, "max_size": args.max_size, "count": len(index), "cases": index}, indent=1, ensure_ascii=False))
    by_kind = {}
    for rec in index:
        by_kind[rec["kind"]] = by_kind.get(rec["kind"], 0) + 1
    print(f"wrote {len(index)} cases to {out} (seed={args.seed}): " + ", ".join(f"{k}={v}" for k, v in by_kind.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
