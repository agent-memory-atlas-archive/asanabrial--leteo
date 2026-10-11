#!/usr/bin/env python3
"""Ask every engine of a tier the same held-out queries, through its own adapter.

Writes `results_engines.json` under BENCH_STATE for `compare.py`. An engine that
cannot be measured is recorded with the reason and no rows: the page lists it as
not measured, never as a row of zeros.

    BENCH_STATE=/tmp/state LETEO_BIN=target/release/leteo python3 bench_engines.py [--tier deterministic] [--only engram,leteo]
"""

import argparse
import datetime
import json
import os
import sys

from adapters import TIERS, Skipped
from comparison_corpus import corpus, no_answer, queries
from mcpclient import BENCH

# The limit every engine is asked at. An engine with no limit parameter returns
# what it returns and the harness keeps the first LIMIT, so no engine is scored
# on more than the others were.
LIMIT = 20


def measure(adapter, members):
    rows, na = [], []
    for q in queries():
        hits = adapter.search(q["project"], q["q"], LIMIT)[:LIMIT]
        mapped = [adapter.map_hit(h, [m for m in members if m["project"] == q["project"]]) for h in hits]
        rank = mapped.index(q["target"]) + 1 if q["target"] in mapped else None
        rows.append(dict(q, rank=rank, n=len(hits), unmappable=sum(k is None for k in mapped)))
    for q in no_answer():
        hits = adapter.search(q["project"], q["q"], LIMIT)[:LIMIT]
        na.append(dict(q, n=len(hits)))
    return rows, na


def run_one(cls, state, members, date):
    adapter = cls(state)
    entry = dict(name=adapter.name, label=adapter.label, date=date, required=adapter.required,
                 status="measured", reason="", version="", rows=[], no_answer=[])
    try:
        adapter.check()
        entry["version"] = adapter.version()
        adapter.load(members)
        entry["rows"], entry["no_answer"] = measure(adapter, members)
    except Skipped as e:
        entry.update(status="skipped", reason=str(e), rows=[], no_answer=[])
    except Exception as e:  # noqa: BLE001 - any engine fault is named, never scored
        entry.update(status="skipped", reason=f"could not run: {type(e).__name__}: {e}", rows=[], no_answer=[])
    finally:
        adapter.close()
    return entry


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="deterministic", choices=sorted(TIERS))
    ap.add_argument("--only", help="comma-separated engine names, for working on one adapter")
    args = ap.parse_args(argv)
    adapters = TIERS[args.tier]
    if not adapters:
        print(f"the {args.tier} tier has no adapters yet", file=sys.stderr)
        return 2
    only = set(args.only.split(",")) if args.only else None
    members = corpus()
    date = datetime.date.today().isoformat()
    out = []
    for cls in adapters:
        if only and cls.name not in only:
            continue
        entry = run_one(cls, BENCH, members, date)
        print(f"{entry['label']}: {entry['status']}{' - ' + entry['reason'] if entry['reason'] else ''}", file=sys.stderr)
        out.append(entry)
    json.dump(dict(tier=args.tier, engines=out), open(os.path.join(BENCH, "results_engines.json"), "w"),
              ensure_ascii=False, indent=1)
    missing = [e["label"] for e in out if e["required"] and e["status"] != "measured"]
    if missing:
        print(f"required engine not measured: {', '.join(missing)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
