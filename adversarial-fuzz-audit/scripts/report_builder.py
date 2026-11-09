#!/usr/bin/env python3
"""Validate adversarial/findings.json and render REPORT.md from the template.

Validation is a focused structural check (required keys, enums, id format) implemented
without third-party libraries so it runs anywhere; it mirrors assets/findings_schema.json.
Rendering fills the {{placeholders}} in assets/report_template.md. Prose sections you want
to hand-edit afterwards are left in place.

Usage:
    report_builder.py adversarial/findings.json [--template assets/report_template.md] [--out adversarial/REPORT.md] [--validate-only]
                          [--verify [--verify-timeout 60]]

--verify re-runs every finding's reproduction.command (shell, cwd = current directory) and
records the exit code and an output tail in the report. Convention: the command must exit
NON-ZERO while the defect is present (like a failing test). Exit 0 is reported as
"NOT REPRODUCED" and this script exits 3. If a command legitimately signals the defect
with another exit code, set reproduction.expect_exit (integer) and that exact code is
required instead. A timeout counts as reproduced only for type hang-or-resource.
Commands run with your permissions: only verify findings you trust.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"

VERDICTS = {"HELD", "PARTIALLY HELD", "FELL"}
TYPES = {"spec-violation", "crash", "hang-or-resource", "data-corruption", "security", "test-weakness", "spec-gap"}
SEVERITIES = ["Critical", "High", "Medium", "Low", "Info"]
ATTRIB = {"code-author", "test-author", "both"}
INDEP = {"cross-vendor", "same-vendor-different-model", "same-model-user-override", "api-oracle-only", "unverified-provider"}


def validate(doc: dict) -> list[str]:
    errs = []
    for k in ("claim", "verdict", "authors", "adversary", "findings", "scope"):
        if k not in doc:
            errs.append(f"missing top-level key: {k}")
    if doc.get("verdict") not in VERDICTS:
        errs.append(f"verdict must be one of {sorted(VERDICTS)}")
    a = doc.get("authors", {})
    for k in ("code", "tests"):
        if not isinstance(a.get(k), list):
            errs.append(f"authors.{k} must be a list")
    adv = doc.get("adversary", {})
    for k in ("model", "vendor", "independence"):
        if not adv.get(k):
            errs.append(f"adversary.{k} is required")
    if adv.get("independence") and adv["independence"] not in INDEP:
        errs.append(f"adversary.independence must be one of {sorted(INDEP)}")
    if adv.get("independence") == "same-model-user-override" and not adv.get("user_override"):
        errs.append("same-model-user-override requires adversary.user_override: true (the user must have decided this)")
    ids = set()
    for i, f in enumerate(doc.get("findings", [])):
        where = f"findings[{i}]"
        for k in ("id", "title", "type", "severity", "attributed_to", "property", "reproduction", "expected", "actual"):
            if k not in f:
                errs.append(f"{where} missing {k}")
        if not re.fullmatch(r"F-\d{2,}", str(f.get("id", ""))):
            errs.append(f"{where}.id must look like F-01")
        if f.get("id") in ids:
            errs.append(f"{where}.id duplicate {f.get('id')}")
        ids.add(f.get("id"))
        if f.get("type") not in TYPES:
            errs.append(f"{where}.type must be one of {sorted(TYPES)}")
        if f.get("severity") not in SEVERITIES:
            errs.append(f"{where}.severity must be one of {SEVERITIES}")
        if f.get("attributed_to") not in ATTRIB:
            errs.append(f"{where}.attributed_to must be one of {sorted(ATTRIB)}")
        if not isinstance(f.get("reproduction"), dict) or not f["reproduction"].get("command"):
            errs.append(f"{where}.reproduction.command is required (a finding must be reproducible)")
        elif "expect_exit" in f["reproduction"] and type(f["reproduction"]["expect_exit"]) is not int:
            errs.append(f"{where}.reproduction.expect_exit must be an integer")
    sc = doc.get("scope", {})
    for k in ("attacked", "not_attacked"):
        if not isinstance(sc.get(k), list):
            errs.append(f"scope.{k} must be a list")
    # consistency: verdict vs findings
    sev = [f.get("severity") for f in doc.get("findings", []) if f.get("type") in {"spec-violation", "crash", "data-corruption", "security"}]
    if doc.get("verdict") == "HELD" and any(s in ("Critical", "High") for s in sev):
        errs.append("verdict HELD is inconsistent with a Critical/High spec-violation/crash/data-corruption/security finding")
    if doc.get("verdict") == "FELL" and not doc.get("findings") and not doc.get("test_weakness"):
        errs.append("verdict FELL needs at least one finding or a test_weakness section that justifies it")
    return errs


def verify_finding(f: dict, timeout: int) -> dict:
    rep = f["reproduction"]
    want = rep.get("expect_exit")
    try:
        p = subprocess.run(rep["command"], shell=True, capture_output=True, text=True, timeout=timeout)
        code, tail, timed_out = p.returncode, (p.stdout + p.stderr)[-400:].strip(), False
    except subprocess.TimeoutExpired:
        code, tail, timed_out = None, f"(timed out after {timeout}s)", True
    if timed_out:
        ok = f.get("type") == "hang-or-resource"
    else:
        ok = (code == want) if want is not None else code != 0
    return {"exit": code, "tail": tail, "timed_out": timed_out, "expect_exit": want, "reproduced": ok}


def md_verify(v: dict) -> list[str]:
    label = "REPRODUCED" if v["reproduced"] else "NOT REPRODUCED"
    code = "timeout" if v["timed_out"] else f"exit {v['exit']}"
    want = f"expected exit {v['expect_exit']}" if v["expect_exit"] is not None else "non-zero expected"
    return [f"- **Verification ({label}):** {code} ({want})", "", "```text", v["tail"] or "(no output)", "```", ""]


def md_findings(findings: list[dict]) -> str:
    if not findings:
        return "_No findings within the stated budget and scope._"
    order = {s: i for i, s in enumerate(SEVERITIES)}
    out = []
    for f in sorted(findings, key=lambda x: order.get(x.get("severity"), 9)):
        rep = f.get("reproduction", {})
        inp = rep.get("input")
        inp_s = json.dumps(inp, ensure_ascii=False) if inp is not None and not isinstance(inp, str) else (inp or "")
        if rep.get("input_path"):
            inp_s = (inp_s + " " if inp_s else "") + f"(`{rep['input_path']}`)"
        lines = [
            f"### {f['id']}. {f['title']}",
            "",
            f"- **Type / severity:** {f['type']} / **{f['severity']}**",
            f"- **Attributed to:** {f['attributed_to']}" + (f"  ·  **Location:** `{f['location']}`" if f.get("location") else ""),
            f"- **Property violated:** {f['property']}",
            f"- **Minimal input:** {inp_s or '_see command_'}",
            f"- **Reproduce:**",
            "", "```bash", rep.get("command", ""), "```", "",
            f"- **Expected:** {f['expected']}",
            f"- **Actual:** {f['actual']}",
        ]
        if f.get("_verify"):
            lines += [""] + md_verify(f["_verify"])
        if f.get("why_tests_missed_it"):
            lines.append(f"- **Why the existing tests missed it:** {f['why_tests_missed_it']}")
        if f.get("also_test_weakness"):
            lines.append("- **Also a test weakness:** the current suite would not have caught this bug.")
        if f.get("independence_note"):
            lines.append(f"- **Independence note:** {f['independence_note']}")
        out.append("\n".join(lines))
    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    summary = "**Summary:** " + ", ".join(f"{counts[s]} {s}" for s in SEVERITIES if s in counts) + f" ({len(findings)} total)\n\n"
    return summary + "\n\n".join(out)


def md_test_weakness(tw: dict | None) -> str:
    if not tw:
        return "_Not assessed._"
    parts = []
    ti = tw.get("tautology_index")
    if ti:
        pct = (ti.get("count", 0) / ti["total"] * 100) if ti.get("total") else 0
        parts.append(f"**Tautology index:** {ti.get('count', 0)} / {ti.get('total', '?')} tests ({pct:.0f}%) would still pass against a stub that returns the expected constant.")
        if ti.get("tests"):
            parts.append("\n".join(f"- `{t}`" for t in ti["tests"]))
    if tw.get("oracle_strength_mean") is not None:
        parts.append(f"**Oracle strength (heuristic scan):** mean {tw['oracle_strength_mean']:.0f}/100.")
    if tw.get("smells"):
        parts.append("**Smells found:**\n\n| Smell | Count |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in sorted(tw["smells"].items(), key=lambda kv: -kv[1])))
    mu = tw.get("mutation")
    if mu:
        parts.append(f"**Mutation check ({mu.get('tool', 'unknown tool')}):** {mu.get('killed', '?')} / {mu.get('tried', '?')} mutants killed, score {mu.get('score', '?')}%.")
        if mu.get("survivors"):
            parts.append("Surviving mutants that matter:\n\n| Location | Mutation | What the suite failed to notice |\n|---|---|---|\n" +
                         "\n".join(f"| `{s.get('location','')}` | {s.get('mutation','')} | {s.get('meaning','')} |" for s in mu["survivors"]))
    return "\n\n".join(parts) if parts else "_Not assessed._"


def md_attacked(items: list[dict]) -> str:
    if not items:
        return "_Nothing recorded._"
    rows = ["| Target | Strategies | Tools | Executions | Minutes | Coverage / notes |", "|---|---|---|---|---|---|"]
    for a in items:
        rows.append(f"| {a.get('target','')} | {', '.join(a.get('strategies', []))} | {', '.join(a.get('tools', []))} | {a.get('executions', '')} | {a.get('wall_clock_minutes', '')} | {a.get('coverage_note', '')}{' seed=' + str(a['seed']) if a.get('seed') is not None else ''} |")
    return "\n".join(rows)


def md_list(items, empty="_None._", fmt="- {}"):
    if not items:
        return empty
    return "\n".join(fmt.format(x if isinstance(x, str) else f"{x.get('target','')}: {x.get('reason','')}") for x in items)


def render(doc: dict, template: str) -> str:
    adv = doc.get("adversary", {})
    warn = ""
    if adv.get("independence") == "same-model-user-override":
        warn = "\n> **INDEPENDENCE WARNING:** the adversary is the same model that authored the code/tests, by explicit user decision. Findings may be incomplete; absence of findings carries little weight.\n"
    elif adv.get("independence") == "unverified-provider":
        warn = "\n> **Note:** the adversary CLI routes to a configurable provider that was not verified against the author vendor.\n"
    targets = ", ".join(a.get("target", "") for a in doc.get("scope", {}).get("attacked", [])) or "see scope"
    budget = ", ".join(f"{a.get('target','')}: {a.get('wall_clock_minutes','?')} min" for a in doc.get("scope", {}).get("attacked", []) if a.get("wall_clock_minutes") is not None) or "not recorded"
    fill = {
        "project": doc.get("project", "(project)"),
        "date": doc.get("date") or date.today().isoformat(),
        "targets": targets,
        "code_authors": ", ".join(doc.get("authors", {}).get("code", [])) or "unknown",
        "test_authors": ", ".join(doc.get("authors", {}).get("tests", [])) or "unknown",
        "adversary": f"{adv.get('agent', '')} {adv.get('model', '')} ({adv.get('vendor', '')})".strip(),
        "independence": adv.get("independence", ""),
        "budget": budget,
        "independence_warning": warn,
        "verdict": doc.get("verdict", ""),
        "verdict_reason": doc.get("verdict_reason", "_(write one paragraph: which findings or weaknesses decided the verdict)_"),
        "claim": doc.get("claim", ""),
        "findings": md_findings(doc.get("findings", [])),
        "test_weakness": md_test_weakness(doc.get("test_weakness")),
        "attacked": md_attacked(doc.get("scope", {}).get("attacked", [])),
        "not_attacked": md_list(doc.get("scope", {}).get("not_attacked", [])),
        "observations": md_list(doc.get("observations", [])),
        "handback": md_list(doc.get("handback", []), fmt="1. {}"),
        "artifacts": md_list(doc.get("artifacts", []), fmt="- `{}`"),
    }
    out = template
    for k, v in fill.items():
        out = out.replace("{{" + k + "}}", str(v))
    leftovers = re.findall(r"{{\w+}}", out)
    if leftovers:
        print("warning: unfilled placeholders:", leftovers, file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings")
    ap.add_argument("--template", default=str(ASSETS / "report_template.md"))
    ap.add_argument("--out", default=None, help="default: REPORT.md next to findings.json")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--verify", action="store_true", help="re-run each reproduction.command and record the evidence")
    ap.add_argument("--verify-timeout", type=int, default=60, help="seconds per reproduction command (default 60)")
    args = ap.parse_args()
    doc = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    errs = validate(doc)
    if errs:
        print("findings.json is invalid:"); [print("  -", e) for e in errs]
        return 1
    print(f"findings.json valid: {len(doc.get('findings', []))} findings, verdict {doc['verdict']}")
    if args.validate_only:
        return 0
    failed = []
    if args.verify:
        for f in doc.get("findings", []):
            f["_verify"] = verify_finding(f, args.verify_timeout)
            print(f"verify {f['id']}: {'REPRODUCED' if f['_verify']['reproduced'] else 'NOT REPRODUCED'} ({'timeout' if f['_verify']['timed_out'] else 'exit ' + str(f['_verify']['exit'])})")
            if not f["_verify"]["reproduced"]:
                failed.append(f["id"])
    out = Path(args.out) if args.out else Path(args.findings).parent / "REPORT.md"
    out.write_text(render(doc, Path(args.template).read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {out}")
    if failed:
        print(f"NOT REPRODUCED: {', '.join(failed)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
