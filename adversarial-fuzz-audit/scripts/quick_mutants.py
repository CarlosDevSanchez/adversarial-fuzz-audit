#!/usr/bin/env python3
"""Dependency-free mutation check for Python source files.

Applies a small, fixed set of semantic mutations to one Python module using the `ast`
module, runs the test command once per mutant with the mutated module shadowing the
original on PYTHONPATH, and reports which mutants SURVIVED (tests still passed). Each
survivor is a concrete bug the suite does not detect. Standard library only (Python 3.9+).

This is a fallback for when mutmut/cosmic-ray are not installed. It produces dozens of
mutants, not thousands: enough for undeniable report examples, not a full score.

Usage:
    quick_mutants.py src/pagination.py --test-cmd "python3 -m pytest -q -x tests/" \
        [--timeout 60] [--max-mutants 80] [--json adversarial/06-mutants.json] [--seed 0]

How shadowing works: the mutated file is written to a temp dir under the same relative
path as the original, and that temp dir is prepended to PYTHONPATH. Works when the tests
import the module by name (e.g. `from pagination import paginate` with `src/` on the path,
or `import pkg.module` with the project root on the path). Use --package-root to tell the
script which directory is the import root (default: the file's parent directory).
"""
from __future__ import annotations

import argparse
import ast
import copy
import difflib
import json
import os
import random
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
            ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
ARITH_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult, ast.Div: ast.Mult, ast.Mod: ast.FloorDiv}
BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


class MutantCollector(ast.NodeVisitor):
    """Enumerate (description, mutate_fn) pairs; mutate_fn edits a *copy* of the tree in place."""

    def __init__(self):
        self.sites: list[tuple[str, int, str, callable]] = []  # (kind, lineno, desc, apply)

    def _add(self, kind, node, desc, apply):
        self.sites.append((kind, getattr(node, "lineno", 0), desc, apply))

    def visit_Compare(self, node: ast.Compare):
        for i, op in enumerate(node.ops):
            new = CMP_SWAP.get(type(op))
            if new:
                path = _path_to(node)
                def apply(tree, i=i, new=new, path=path):
                    n = _resolve(tree, path); n.ops[i] = new()
                self._add("relational", node, f"{type(op).__name__} -> {new.__name__}", apply)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        new = ARITH_SWAP.get(type(node.op))
        if new:
            path = _path_to(node)
            def apply(tree, new=new, path=path):
                n = _resolve(tree, path); n.op = new()
            self._add("arithmetic", node, f"{type(node.op).__name__} -> {new.__name__}", apply)
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp):
        new = BOOL_SWAP.get(type(node.op))
        if new:
            path = _path_to(node)
            def apply(tree, new=new, path=path):
                n = _resolve(tree, path); n.op = new()
            self._add("boolean", node, f"{type(node.op).__name__} -> {new.__name__}", apply)
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            path = _path_to(node)
            def apply(tree, path=path):
                parent, attr, idx = _parent_of(tree, path)
                target = _resolve(tree, path)
                _replace(parent, attr, idx, target.operand)
            self._add("negation", node, "remove `not`", apply)
        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        path = _path_to(node)
        def apply(tree, path=path):
            n = _resolve(tree, path); n.test = ast.UnaryOp(op=ast.Not(), operand=n.test)
        self._add("condition", node, "negate if-condition", apply)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        v = node.value
        path = _path_to(node)
        if isinstance(v, bool):
            def apply(tree, path=path, v=v):
                _resolve(tree, path).value = (not v)
            self._add("constant", node, f"{v} -> {not v}", apply)
        elif isinstance(v, int) and not isinstance(v, bool):
            for delta in (1, -1):
                def apply(tree, path=path, v=v, delta=delta):
                    _resolve(tree, path).value = v + delta
                self._add("constant", node, f"{v} -> {v + delta}", apply)
        elif isinstance(v, str) and v and len(v) < 40 and not (node.col_offset == 0 and v.strip() == v and len(v) > 20):
            def apply(tree, path=path):
                _resolve(tree, path).value = ""
            self._add("constant", node, f"{v!r} -> ''", apply)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return):
        if node.value is not None and not isinstance(node.value, ast.Constant):
            path = _path_to(node)
            def apply(tree, path=path):
                _resolve(tree, path).value = ast.Constant(value=None)
            self._add("return", node, "return value -> None", apply)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        path = _path_to(node)
        def apply(tree, path=path):
            parent, attr, idx = _parent_of(tree, path)
            _replace(parent, attr, idx, ast.Pass())
        self._add("raise", node, "remove raise", apply)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            for which in ("lower", "upper"):
                bound = getattr(node.slice, which)
                if bound is not None:
                    path = _path_to(node)
                    def apply(tree, path=path, which=which):
                        n = _resolve(tree, path)
                        setattr(n.slice, which, ast.BinOp(left=getattr(n.slice, which), op=ast.Add(), right=ast.Constant(value=1)))
                    self._add("boundary", node, f"slice {which} + 1", apply)
        self.generic_visit(node)


# --- tree addressing: record a path of (field, index) from root so the same node can be found in a deep copy
def _annotate(tree):
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for i, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        child._parent = node; child._field = field; child._idx = i
            elif isinstance(value, ast.AST):
                value._parent = node; value._field = field; value._idx = None


def _path_to(node):
    path = []
    while getattr(node, "_parent", None) is not None:
        path.append((node._field, node._idx)); node = node._parent
    return list(reversed(path))


def _resolve(tree, path):
    n = tree
    for field, idx in path:
        v = getattr(n, field)
        n = v[idx] if idx is not None else v
    return n


def _parent_of(tree, path):
    parent = _resolve(tree, path[:-1]); field, idx = path[-1]
    return parent, field, idx


def _replace(parent, field, idx, new):
    if idx is None:
        setattr(parent, field, new)
    else:
        getattr(parent, field)[idx] = new


def run_tests(cmd: str, env: dict, timeout: int, cwd: str) -> tuple[str, float, str]:
    t0 = time.time()
    try:
        p = subprocess.run(shlex.split(cmd), env=env, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        status = "pass" if p.returncode == 0 else "fail"
        tail = (p.stdout + p.stderr)[-600:]
    except subprocess.TimeoutExpired:
        status, tail = "timeout", ""
    return status, time.time() - t0, tail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="Python file to mutate")
    ap.add_argument("--test-cmd", required=True, help="command that runs the suite; exit 0 = pass")
    ap.add_argument("--timeout", type=int, default=120, help="seconds per mutant")
    ap.add_argument("--max-mutants", type=int, default=80)
    ap.add_argument("--package-root", help="import root to shadow (default: source file's directory)")
    ap.add_argument("--cwd", default=".", help="working directory for the test command")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--seed", type=int, default=0, help="shuffle seed when sampling down to --max-mutants")
    ap.add_argument("--kinds", help="comma list to restrict: relational,arithmetic,boolean,negation,condition,constant,return,raise,boundary")
    args = ap.parse_args()

    src = Path(args.source).resolve()
    root = Path(args.package_root).resolve() if args.package_root else src.parent
    rel = src.relative_to(root)
    original = src.read_text()
    tree = ast.parse(original)
    _annotate(tree)
    coll = MutantCollector(); coll.visit(tree)
    sites = coll.sites
    if args.kinds:
        keep = {k.strip() for k in args.kinds.split(",")}
        sites = [s for s in sites if s[0] in keep]
    if len(sites) > args.max_mutants:
        random.Random(args.seed).shuffle(sites); sites = sorted(sites[:args.max_mutants], key=lambda s: s[1])

    env = dict(os.environ)
    print(f"baseline: running `{args.test_cmd}` on the unmodified code ...")
    base_status, base_t, base_tail = run_tests(args.test_cmd, env, args.timeout, args.cwd)
    if base_status != "pass":
        print(f"baseline {base_status}; the suite must pass before mutation testing makes sense.\n{base_tail}")
        return 2
    print(f"baseline passed in {base_t:.1f}s; {len(sites)} mutants to try (timeout {args.timeout}s each)\n")

    results = []
    with tempfile.TemporaryDirectory(prefix="quick-mutants-") as tmp:
        shadow_root = Path(tmp) / "shadow"
        for n, (kind, lineno, desc, apply) in enumerate(sites, 1):
            mutated = copy.deepcopy(tree)
            try:
                apply(mutated)
                ast.fix_missing_locations(mutated)
                code = ast.unparse(mutated)
            except Exception as e:  # mutation not applicable after copy; skip
                results.append({"id": n, "kind": kind, "line": lineno, "desc": desc, "status": "skipped", "error": str(e)}); continue
            if code.strip() == ast.unparse(tree).strip():
                results.append({"id": n, "kind": kind, "line": lineno, "desc": desc, "status": "equivalent-text"}); continue
            target = shadow_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # make intermediate packages importable
            for parent in list(rel.parents)[:-1]:
                (shadow_root / parent / "__init__.py").touch()
            target.write_text(code)
            menv = dict(env); menv["PYTHONPATH"] = str(shadow_root) + os.pathsep + env.get("PYTHONPATH", ""); menv["PYTHONDONTWRITEBYTECODE"] = "1"
            status, dt, tail = run_tests(args.test_cmd, menv, args.timeout, args.cwd)
            verdict = {"pass": "SURVIVED", "fail": "killed", "timeout": "timeout"}[status]
            diff = "".join(difflib.unified_diff((ast.unparse(tree) + "\n").splitlines(True), (code + "\n").splitlines(True), "original", "mutant", n=0))
            results.append({"id": n, "kind": kind, "line": lineno, "desc": desc, "status": verdict, "seconds": round(dt, 1), "diff": diff[:1200]})
            mark = "!!" if verdict == "SURVIVED" else "  "
            print(f"{mark} [{n:>3}/{len(sites)}] line {lineno:<4} {kind:<10} {desc:<32} {verdict}")

    tried = [r for r in results if r["status"] in ("SURVIVED", "killed", "timeout")]
    survived = [r for r in results if r["status"] == "SURVIVED"]
    killed = len([r for r in tried if r["status"] in ("killed", "timeout")])
    score = (killed / len(tried) * 100) if tried else 0
    print(f"\nmutation score: {killed}/{len(tried)} killed = {score:.0f}%   survivors: {len(survived)}")
    for r in survived:
        print(f"\n--- SURVIVED  {src.name}:{r['line']}  {r['desc']}\n{r['diff']}")
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps({"source": str(src), "test_cmd": args.test_cmd, "score": round(score, 1),
                                                   "tried": len(tried), "killed": killed, "survived": len(survived), "mutants": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
