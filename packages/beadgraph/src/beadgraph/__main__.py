"""python -m beadgraph selftest [--json] [--quick] -> conformance report on the frozen fixtures (exit 0 = pass).
python -m beadgraph version"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m beadgraph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("selftest", help="run the conformance checks (V-BG-1..6, 14 package part)")
    st.add_argument("--json", action="store_true", help="print the report as JSON")
    st.add_argument("--quick", action="store_true", help="skip the H6 invariance and some H6 morph recipes")
    sub.add_parser("version")
    a = ap.parse_args(argv)
    from . import MORPH_RULES, RULES, SCHEMA, __version__
    if a.cmd == "version":
        print(json.dumps({"version": __version__, "schema": SCHEMA, "rules": RULES, "morph_rules": MORPH_RULES}))
        return 0
    from .testing.conformance import selftest
    rep = selftest(full=not a.quick)
    if a.json:
        print(json.dumps(rep, indent=1, sort_keys=True, default=str))
    else:
        print(f"beadgraph {rep['beadgraph_version']} (rules {rep['rules']}) selftest:")
        for k, v in rep["checks"].items():
            print(f"  [{'ok' if v['ok'] else 'FAIL'}] {k}")
            for p in v["problems"][:20]:
                print(f"        - {p}")
        print("PASS" if rep["ok"] else "FAIL")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
