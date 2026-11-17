"""Failure-mode probe (M1 evidence): turn ON exactly one bug switch of lab9.variant_agent on top of
`fixed` and see which eval items break, under which grader. This is how docs/failure_taxonomy.md
links every FM to a concrete claim@seed, and how eval_set_v1 got its failure_modes tags.

    python -m lab9.fm_probe                                  # every switch, seeds 11 and 55
    python -m lab9.fm_probe --bug misreport --trace C-014    # one switch, print one trace

Runs on fresh temp stores like lab9.eval; never touches lab8/ or reports/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import variants
from lab9.eval import SPEC, load_spec, run_eval

BUG_TO_FM = {
    "leaky_trace": "FM-01", "ignore_denied": "FM-02", "ticket_trust": "FM-03", "sum_parts": "FM-04",
    "round_down": "FM-04", "pre_deducted": "FM-05", "stale_clause": "FM-06", "sibling_refund": "FM-07",
    "misreport": "FM-08",
}
SAFETY = ("approval_bypass", "secret_leak")


def register_probes() -> list[str]:
    from lab8.shapes import SHAPES
    from lab9.variant_agent import make_shape
    variants.register()
    for bug in BUG_TO_FM:
        SHAPES.setdefault(f"probe_{bug}", make_shape(f"probe_{bug}", {"no_override", bug}))
    return [f"probe_{b}" for b in BUG_TO_FM]


def failing(report: dict) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for r in report["rows"]:
        bad = [k for k, v in r.items() if (k in SAFETY and v is True)
               or (k not in SAFETY and k not in ("item_id", "seed", "slices", "cost") and v is False)]
        for k in bad:
            out.setdefault(r["item_id"], set()).add(f"{k}@{r['seed']}")
    return {k: sorted(v) for k, v in sorted(out.items())}


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.fm_probe")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--seeds", default="11,55")
    ap.add_argument("--bug", choices=sorted(BUG_TO_FM), help="probe one switch only")
    ap.add_argument("--trace", metavar="CLAIM", help="with --bug: print that claim's trace (first seed)")
    args = ap.parse_args(argv)
    register_probes()
    seeds = [int(s) for s in args.seeds.split(",")]
    if args.trace:
        from lab9.trace_case import main as trace_main
        return trace_main(["--shape", f"probe_{args.bug or 'misreport'}", "--claim", args.trace, "--seed", str(seeds[0])])
    spec = load_spec(Path(args.spec))
    bugs = [args.bug] if args.bug else list(BUG_TO_FM)
    for shape, fm in [("swarm", "baseline")] + [(f"probe_{b}", BUG_TO_FM[b]) for b in bugs]:
        print(f"{shape:<22} {fm:<8} {json.dumps(failing(run_eval(shape, spec, seeds)), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
