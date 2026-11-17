"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    man = pr.get("manifest") or {}
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. Metric values must be finite numbers (NaN < min is False: a naive gate passes it).
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (not a finite number)")
    for m in spec.get("metrics", []):
        mid = m["id"]
        if (base.get("metrics") or {}).get(mid) is not None and (pr.get("metrics") or {}).get(mid) is None:
            problems.append(f"metric {mid} missing/None in PR but present on main")

    # 2. Graders must not have crashed, and no graded cell may be empty.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    base_cols = set(base_rows[0]) if base_rows else set()
    none_cells = [(r.get("item_id"), r.get("seed"), mid) for r in rows for mid in graded
                  if mid in base_cols and (r.get(mid) is None
                                           or (isinstance(r[mid], float) and not math.isfinite(r[mid])))]
    if none_cells:
        problems.append(f"{len(none_cells)} graded cell(s) are None/NaN, first {none_cells[0]}")

    # 3. Row count = items x seeds, no duplicates, and the same (item, seed) grid as main.
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows but manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    if len(set(keys)) != len(keys):
        problems.append(f"{len(keys) - len(set(keys))} duplicated (item, seed) row(s)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = base_keys - set(keys), set(keys) - base_keys
        problems.append(f"(item, seed) grid differs from main: {len(miss)} missing, {len(extra)} extra")
    bman = base.get("manifest") or {}
    if man.get("items") != bman.get("items") or sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
        problems.append(f"manifest items/seeds {man.get('items')}/{man.get('seeds')} != main "
                        f"{bman.get('items')}/{bman.get('seeds')}")

    # 4. Headline metrics must be what the rows say (catches a hand-edited number).
    if rows and not problems:
        ids = [mid for mid in graded if mid in rows[0]]
        try:
            recomputed = aggregate(rows, ids, k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ValueError):
            recomputed = {}         # rows without cost etc. (hand-built test reports): nothing to compare
        for k, v in recomputed.items():
            if k in (pr.get("metrics") or {}) and not _close(pr["metrics"][k], v):
                problems.append(f"metric {k}={pr['metrics'][k]} but the rows give {v}")

    # 5. Slice tags per item must match main (relabelling an item out of a slice hides it).
    def tags(rs: list[dict]) -> dict:
        out: dict = {}
        for r in rs:
            out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
        return out
    pt, bt = tags(rows), tags(base_rows)
    relabelled = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if relabelled:
        problems.append(f"slice tags differ from main on {len(relabelled)} item(s), first {relabelled[0]}")

    # 6. Ratchet: same eval-set version => thresholds may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= 1e-6
    except (TypeError, ValueError):
        return a == b


def _looser(old: dict, new: dict) -> list[str]:
    """Which parts of threshold `new` are looser than `old`."""
    out = []
    for k in ("max", "max_increase"):
        if k in old and (k not in new or new[k] > old[k]):
            out.append(f"{k} {old[k]} -> {new.get(k, 'removed')}")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"min {old['min']} -> {new.get('min', 'removed')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => a spec may only get stricter than the one on main."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []          # new eval-set version: thresholds restart (and need a new baseline)
    problems = []
    for k in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(k) != spec.get(k):
            problems.append(f"RATCHET {k} changed {base_spec.get(k)!r} -> {spec.get(k)!r} on the same eval-set version")
    if sorted(base_spec.get("seeds") or []) != sorted(spec.get("seeds") or []):
        problems.append(f"RATCHET seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        problems.append(f"RATCHET pass_k {base_spec.get('pass_k')} -> {spec.get('pass_k')}")
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if nb.get("confidence", 0.95) > ob.get("confidence", 0.95):
        problems.append(f"RATCHET bootstrap confidence {ob.get('confidence')} -> {nb.get('confidence')} (wider CI)")
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        n = new_m.get(m["id"])
        if n is None:
            problems.append(f"RATCHET metric {m['id']} removed")
            continue
        if m.get("blocking") and not n.get("blocking"):
            problems.append(f"RATCHET metric {m['id']} no longer blocking")
        problems += [f"RATCHET metric {m['id']} {x}" for x in _looser(m.get("threshold") or {}, n.get("threshold") or {})]
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        n = new_s.get((s["name"], s["metric"]))
        sid = f"slice:{s['name']}/{s['metric']}"
        if n is None:
            problems.append(f"RATCHET {sid} removed")
            continue
        if s.get("blocking") and not n.get("blocking"):
            problems.append(f"RATCHET {sid} no longer blocking")
        problems += [f"RATCHET {sid} {x}" for x in _looser(s, n)]
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # A slice that is empty in the PR but not on main was relabelled or dropped: never "ok".
            verdict = "missing" if b else "empty"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict in ("fail", "missing") and s.get("blocking"):
            blocked.append(sid)
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        label = {"ok": "ok", "missing": "MISSING", "empty": "empty"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
