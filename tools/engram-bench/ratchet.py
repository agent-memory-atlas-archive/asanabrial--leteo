import json, math, os, shutil, statistics, sys, tempfile
from collections import defaultdict

# A fresh store every run, and set before mcpclient is imported because it reads
# the directory at import: a ratchet that reused a store would be measuring
# whatever the last run left in it.
STATE = tempfile.mkdtemp(prefix="leteo-ratchet-")
os.environ["BENCH_STATE"] = STATE

from corpus import corpus, queries
from mcpclient import MCP

HERE = os.path.dirname(os.path.abspath(__file__))
FLOORS = os.path.join(HERE, "floors.json")
PROJECTS = ("alpha-api", "beta-web")
SEARCH_LIMIT = 20
# The first two match many short bodies; the third is a disjunction over words
# that sit in the long ones, because the preview is the thing most likely to
# change a reply's size and short bodies never reach it.
BYTE_QUERIES = {
    "search_service": {"query": "service"},
    "search_latency": {"query": "latency"},
    "search_long_bodies": {"query": "regression test commit", "match_mode": "any"},
}


class CannotRun(Exception):
    pass


def call(m, tool, args):
    text, dt, raw = m.call(tool, args)
    if "error" in raw or (raw.get("result") or {}).get("isError"):
        raise CannotRun(f"{tool} failed: {text[:300] or raw}")
    try:
        return json.loads(text), text, dt
    except ValueError:
        raise CannotRun(f"{tool} answered something that is not JSON: {text[:300]}")


def measure():
    members = corpus()
    wanted = queries()
    servers = {p: MCP("leteo", p) for p in PROJECTS}
    try:
        ids = {}
        for mem in members:
            args = dict(title=mem["title"], content=mem["content"], type=mem["type"])
            if mem["topic"]:
                args["topic_key"] = mem["topic"]
            reply, _, _ = call(servers[mem["project"]], "mem_save", args)
            # A save that merged into an earlier memory would leave a target
            # without an id of its own, and every query for it would then be
            # scored against the wrong row.
            if reply.get("status") != "inserted" or reply.get("project") != mem["project"]:
                raise CannotRun(f"{mem['key']} was not inserted into {mem['project']}: {json.dumps(reply)[:300]}")
            ids[mem["key"]] = reply["observation"]["id"]
        if len(set(ids.values())) != len(members):
            raise CannotRun("two corpus memories were given the same id")

        ranks = defaultdict(list)
        # How many questions came back with nothing at all. MRR alone cannot
        # say it: a question answered wrongly and a question not answered both
        # score zero, and an agent is told very different things by the two.
        empty = defaultdict(int)
        millis = []
        for q in wanted:
            reply, _, dt = call(servers[q["project"]], "mem_search", {"query": q["q"], "limit": SEARCH_LIMIT})
            found = [r["id"] for r in reply.get("results") or []]
            target = ids[q["target"]]
            rank = found.index(target) + 1 if target in found else None
            ranks[q["kind"]].append(rank)
            ranks["ALL"].append(rank)
            if not found:
                empty[q["kind"]] += 1
                empty["ALL"] += 1
            millis.append(dt * 1000)
        if len(ranks["ALL"]) != len(wanted) or len(wanted) == 0:
            raise CannotRun(f"{len(ranks['ALL'])} queries were evaluated and the corpus defines {len(wanted)}")

        alpha = servers["alpha-api"]
        sizes = {}
        for name, extra in BYTE_QUERIES.items():
            reply, text, _ = call(alpha, "mem_search", dict(extra, limit=SEARCH_LIMIT))
            # Fewer than the limit would measure a smaller reply than the
            # ceiling is meant to bound, and pass.
            if len(reply.get("results") or []) != SEARCH_LIMIT:
                raise CannotRun(f"{name} returned {len(reply.get('results') or [])} results, not {SEARCH_LIMIT}")
            sizes[name] = len(text.encode())
        _, text, _ = call(alpha, "mem_context", {})
        sizes["context"] = len(text.encode())
    finally:
        for m in servers.values():
            try:
                m.close()
            except Exception:
                m.p.kill()

    mrr = {k: sum(1 / r for r in rs if r) / len(rs) for k, rs in ranks.items()}
    hit1 = {k: sum(r == 1 for r in rs) / len(rs) for k, rs in ranks.items()}
    return dict(mrr=mrr, hit1=hit1, counts={k: len(v) for k, v in ranks.items()}, bytes=sizes,
                empty={k: empty[k] for k in ranks}, median_ms=statistics.median(millis))


def propose(got):
    return {
        "raise_margin": 0.02,
        "mrr": {k: math.floor(got["mrr"][k] * 1000 + 1e-9) / 1000 for k in sorted(got["mrr"])},
        "bytes": {k: (v // 100 + 1) * 100 for k, v in sorted(got["bytes"].items())},
        "empty": {"ALL": got["empty"]["ALL"]},
    }


def judge(got, floors):
    breaches, raisable = [], []
    if set(floors["mrr"]) != set(got["mrr"]):
        breaches.append(f"kinds differ: floors name {sorted(floors['mrr'])}, the corpus has {sorted(got['mrr'])}")
    if set(floors["bytes"]) != set(got["bytes"]):
        breaches.append(f"byte measurements differ: floors name {sorted(floors['bytes'])}, measured {sorted(got['bytes'])}")
    for kind, floor in floors["mrr"].items():
        value = got["mrr"].get(kind)
        if value is None:
            continue
        if value < floor:
            breaches.append(f"MRR {kind}: measured {value:.3f}, floor {floor:.3f}")
        elif value - floor >= floors["raise_margin"]:
            raisable.append(f"MRR {kind}: measured {value:.3f} is {value - floor:.3f} above its floor {floor:.3f}")
    # A ceiling and not a floor: the count of questions answered with nothing
    # can only be allowed to fall. Only the total is gated; the per-kind
    # counts are printed, because a kind of eight questions moves by one.
    for kind, ceiling in floors.get("empty", {}).items():
        value = got["empty"].get(kind)
        if value is None:
            # A ceiling on something that was not measured would pass for ever.
            raise CannotRun(f"floors.json bounds empty answers for {kind!r}, which was not measured "
                            f"(measured: {sorted(got['empty'])})")
        if value > ceiling:
            breaches.append(f"empty answers {kind}: measured {value}, ceiling {ceiling}")
        elif value < ceiling:
            raisable.append(f"empty answers {kind}: measured {value} is below its ceiling {ceiling}")
    for name, ceiling in floors["bytes"].items():
        value = got["bytes"].get(name)
        if value is not None and value > ceiling:
            breaches.append(f"bytes {name}: measured {value}, ceiling {ceiling}")
    return breaches, raisable


def main():
    # mcpclient falls back to `leteo` on PATH, which on a developer machine is
    # an installed release, and a ratchet that quietly measured that binary
    # instead of the build under test passed against the wrong code once.
    binary = os.environ.get("LETEO_BIN")
    if not binary:
        raise CannotRun("LETEO_BIN is not set; name the binary under test")
    print(f"binary under test: {binary}", file=sys.stderr)
    if "--propose" in sys.argv:
        print(json.dumps(propose(measure()), indent=2))
        return 0
    floors = json.load(open(FLOORS))
    got = measure()
    n = got["counts"]["ALL"]
    print(f"{n} queries evaluated, median warm search {got['median_ms']:.1f} ms (printed, not gated)")
    for k in sorted(got["mrr"]):
        print(f"  {k:10} n={got['counts'][k]:3}  hit@1 {got['hit1'][k]:.3f}  MRR {got['mrr'][k]:.3f}  floor {floors['mrr'].get(k, float('nan')):.3f}  empty {got['empty'][k]:3}")
    for k, v in sorted(got["bytes"].items()):
        print(f"  {k:15} {v:6} bytes  ceiling {floors['bytes'].get(k, 0)}")
    breaches, raisable = judge(got, floors)
    for line in raisable:
        print("RAISE?", line)
    for line in breaches:
        print("BREACH", line)
    if breaches:
        print(f"ratchet FAILED: {len(breaches)} breach(es)")
        return 1
    print("ratchet passed")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except (CannotRun, OSError, RuntimeError, KeyError, ValueError) as e:
        print(f"ratchet could not run: {type(e).__name__}: {e}")
        code = 2
    finally:
        shutil.rmtree(STATE, ignore_errors=True)
    sys.exit(code)
