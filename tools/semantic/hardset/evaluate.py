"""Does the semantic stage find what the words cannot? Asked of the binary, with a CI.

The engram-bench ratchet measures questions drawn from a memory's own vocabulary,
and the lexical stages answer those. This set is the opposite: questions that do
not use the target's words, in English, in the other twelve languages, and against
memories that are themselves translated. It is LLM-generated (see README.md) and
is labelled as such wherever its numbers are quoted.

One binary, two passes over the same stores: the `semantic_search` setting is
written off, every question is asked, the setting is removed, every question is
asked again. The difference is the stage and nothing else, and the setting is the
very switch a user has, read by the very server being measured. The server is
`leteo mcp` and the question goes through `mem_search`, so the reply parsed is the
reply an agent gets and the time is the time it waits.

The statistic is the per-question reciprocal rank at depth 20, paired between the
two passes, with a percentile bootstrap over questions (4,000 resamples, a fixed
seed). A kind regresses when its mean difference is below -0.02, the rule the issue
sets for every kind.

    usage: evaluate.py <leteo-binary> [--resamples N] [--json out.json]

Exits 0 when the whole hard set improves with a 95% interval that excludes zero and
no kind falls by more than 0.02; 1 otherwise; 2 when it could not run.
"""

import argparse
import gzip
import importlib
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "engram-bench"))
import corpus as C  # noqa: E402

DATA = os.path.join(HERE, "data")
PROJECTS = ("alpha-api", "beta-web")
OTHER = {"alpha-api": "beta-web", "beta-web": "alpha-api"}
LANGS = "ca de es eu fr gl it nl pl pt ro sv".split()
TRANSLATED = "de es eu gl".split()
DEPTH = 20
REGRESSION = 0.02


class CannotRun(Exception):
    pass


def load(name):
    """A data file by its JSON name; it is stored as deterministic gzip."""
    with gzip.open(os.path.join(DATA, name + ".gz"), "rb") as handle:
        return json.load(handle)


class Store:
    """The engram-bench corpus, or its translation, saved through `mem_save`."""

    def __init__(self, root, name, members, binary):
        self.root = os.path.join(root, name)
        os.makedirs(self.root)
        # mcpclient reads BENCH_STATE and LETEO_BIN once, when it is imported, and
        # `importlib.reload` runs that again in the same module object -- there is
        # no second copy. What holds is the order: the servers below are spawned
        # before the next store reloads it, and a spawned server has its directory
        # in its own environment, so each store's servers keep pointing at its own.
        os.environ["BENCH_STATE"] = self.root
        os.environ["LETEO_BIN"] = binary
        import mcpclient

        importlib.reload(mcpclient)
        self.home = os.path.join(self.root, "lhome")
        self.servers = {p: mcpclient.MCP("leteo", p) for p in PROJECTS}
        self.ids = {}
        for m in members:
            args = dict(title=m["title"], content=m["content"], type=m["type"])
            if m["topic"]:
                args["topic_key"] = m["topic"]
            reply = self.call(m["project"], "mem_save", args)
            if reply.get("status") != "inserted" or reply.get("project") != m["project"]:
                raise CannotRun(f"{m['key']} was not inserted into {m['project']}: {json.dumps(reply)[:200]}")
            self.ids[m["key"]] = reply["observation"]["id"]
        if len(set(self.ids.values())) != len(members):
            raise CannotRun("two memories were given the same id")

    def call(self, project, tool, args):
        text, dt, raw = self.servers[project].call(tool, args)
        if "error" in raw or (raw.get("result") or {}).get("isError"):
            raise CannotRun(f"{tool} failed: {text[:300] or raw}")
        self.last_ms = dt * 1000
        return json.loads(text)

    def semantic(self, on):
        path = os.path.join(self.home, "settings.json")
        if on:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w") as handle:
                handle.write('{"semantic_search": false}\n')

    def ask(self, project, query):
        reply = self.call(project, "mem_search", {"query": query, "limit": DEPTH})
        results = reply.get("results") or []
        return [r["id"] for r in results], [bool(r.get("semantic")) for r in results], self.last_ms

    def close(self):
        for server in self.servers.values():
            try:
                server.close()
            except Exception:
                server.p.kill()


def translated(lang):
    by_key = {t["key"]: t for t in load(f"mem_{lang}.json")}
    return [dict(m, title=by_key[m["key"]]["title"], content=by_key[m["key"]]["content"]) if m["key"] in by_key else m
            for m in C.corpus()]


def questions(base, translations):
    """Every question, the store it is asked of, and what it should find (or nothing)."""
    out = []
    projects = {t["key"]: t["project"] for t in C.TARGETS}

    def add(store, group, kind, q, project, key):
        out.append(dict(store=store, group=group, kind=kind, q=q, project=project,
                        target=store_ids(store).get(key) if key else None))

    stores = {"base": base, **translations}
    store_ids = lambda name: stores[name].ids  # noqa: E731

    for q in load("para_en.json"):
        add("base", "english paraphrase", "para_en", q["q"], projects[q["key"]], q["key"])
    for lang in LANGS:
        for q in load(f"xl_{lang}.json"):
            add("base", "query in another language", f"xl_{lang}", q["q"], projects[q["key"]], q["key"])
    for lang in TRANSLATED:
        for q in C.queries():
            add(f"mem_{lang}", "translated memories", f"mem_{lang}", q["q"], q["project"], q["target"])
        for q in load("para_en.json"):
            add(f"mem_{lang}", "translated memories", f"mem_{lang}_para", q["q"], projects[q["key"]], q["key"])
    # Questions whose answer is not in the store: the other project's, and ones
    # nothing in either project is about. Silence is the right answer to these.
    for q in C.queries():
        add("base", "control", "ctrl_foreign", q["q"], OTHER[q["project"]], None)
    for q in load("absent.json"):
        for project in PROJECTS:
            add("base", "control", "ctrl_absent", q, project, None)
    return out


def reciprocal_rank(found, target):
    if target is None or target not in found:
        return 0.0
    return 1.0 / (found.index(target) + 1)


def bootstrap(deltas, resamples, seed):
    rng = random.Random(seed)
    n = len(deltas)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return sum(deltas) / n, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("--resamples", type=int, default=4000)
    parser.add_argument("--json")
    args = parser.parse_args()
    binary = os.path.abspath(args.binary)
    if not os.path.exists(binary):
        raise CannotRun(f"{binary} does not exist")

    root = tempfile.mkdtemp(prefix="leteo-hardset-")
    stores = {}
    try:
        stores["base"] = Store(root, "base", C.corpus(), binary)
        for lang in TRANSLATED:
            stores[f"mem_{lang}"] = Store(root, f"mem_{lang}", translated(lang), binary)
        asked = questions(stores["base"], {k: v for k, v in stores.items() if k != "base"})

        # Lexical first and semantic second, in that order, so that the second
        # pass is the one that pays for making the vectors, as a user's does.
        passes = {}
        for name, on in (("lexical", False), ("semantic", True)):
            for store in stores.values():
                store.semantic(on)
            answers = []
            for q in asked:
                found, marked, ms = stores[q["store"]].ask(q["project"], q["q"])
                answers.append(dict(found=found, marked=marked, ms=ms))
            passes[name] = answers
    finally:
        for store in stores.values():
            store.close()
        shutil.rmtree(root, ignore_errors=True)

    lexical, semantic = passes["lexical"], passes["semantic"]
    rows = []
    for q, lex, sem in zip(asked, lexical, semantic):
        rows.append(dict(q, lex_rr=reciprocal_rank(lex["found"], q["target"]),
                         sem_rr=reciprocal_rank(sem["found"], q["target"]),
                         lex_empty=not lex["found"], sem_empty=not sem["found"],
                         added=sum(sem["marked"]), sem_ms=sem["ms"], lex_ms=lex["ms"]))

    if not any(r["added"] for r in rows):
        # Without the model the stage is off and the second pass is the first
        # again, which this would report as the stage failing to help. That is a
        # fact about the environment and not about the stage.
        raise CannotRun("the semantic stage never ran: no answer in the semantic pass carries a result "
                        "found by meaning. Either the model was not found or did not verify (point "
                        "LETEO_MODEL_DIR at a directory holding it, e.g. assets/model), or "
                        "`semantic_search` is off")

    groups = defaultdict(list)
    for r in rows:
        if r["group"] == "control":
            continue
        groups[r["kind"]].append(r)
        groups[r["group"]].append(r)
        groups["HARD SET"].append(r)

    report = {}
    print(f"{'':34} {'n':>5} {'lexical':>8} {'+stage':>8}   delta [95% CI]            empty->")
    worst = (0.0, "")
    order = ["HARD SET", "english paraphrase", "query in another language", "translated memories"]
    order += sorted(k for k in groups if k not in order)
    for name in order:
        g = groups[name]
        deltas = [r["sem_rr"] - r["lex_rr"] for r in g]
        mean, low, high = bootstrap(deltas, args.resamples, 124)
        lex = sum(r["lex_rr"] for r in g) / len(g)
        sem = sum(r["sem_rr"] for r in g) / len(g)
        empties = (sum(r["lex_empty"] for r in g), sum(r["sem_empty"] for r in g))
        report[name] = dict(n=len(g), lexical=lex, semantic=sem, delta=mean, low=low, high=high, empty=empties)
        print(f"{name:34} {len(g):5} {lex:8.3f} {sem:8.3f}   {mean:+.3f} [{low:+.3f}, {high:+.3f}]   {empties[0]} -> {empties[1]}")
        if name not in ("HARD SET", "english paraphrase", "query in another language", "translated memories"):
            worst = min(worst, (mean, name))

    controls = [r for r in rows if r["group"] == "control"]
    print()
    for kind in sorted({r["kind"] for r in controls}):
        c = [r for r in controls if r["kind"] == kind]
        answered = (sum(not r["lex_empty"] for r in c), sum(not r["sem_empty"] for r in c))
        report[kind] = dict(n=len(c), answered_lexical=answered[0], answered_semantic=answered[1])
        print(f"control {kind:14} n={len(c):4}  answered by the words {answered[0]:4}  with the stage {answered[1]:4}"
              f"  (silence is correct here)")

    p = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(q * len(xs)))]  # noqa: E731
    lex_ms, sem_ms = [r["lex_ms"] for r in rows], [r["sem_ms"] for r in rows]
    report["latency_ms"] = dict(lexical_p50=statistics.median(lex_ms), lexical_p90=p(lex_ms, 0.9),
                                semantic_p50=statistics.median(sem_ms), semantic_p90=p(sem_ms, 0.9),
                                semantic_max=max(sem_ms))
    print(f"\nmem_search over MCP, ms:  p50 {report['latency_ms']['lexical_p50']:.1f} -> {report['latency_ms']['semantic_p50']:.1f}"
          f"   p90 {report['latency_ms']['lexical_p90']:.1f} -> {report['latency_ms']['semantic_p90']:.1f}"
          f"   max with the stage {report['latency_ms']['semantic_max']:.0f}")
    if args.json:
        json.dump(report, open(args.json, "w"), indent=1)

    hard = report["HARD SET"]
    failures = []
    if not hard["low"] > 0:
        failures.append(f"the hard set's interval [{hard['low']:+.3f}, {hard['high']:+.3f}] does not exclude zero")
    if worst[0] < -REGRESSION:
        failures.append(f"{worst[1]} falls by {-worst[0]:.3f}, more than {REGRESSION}")
    for line in failures:
        print("FAIL", line)
    if not failures:
        print("PASS: the stage improves the hard set (LLM-generated) with a 95% CI above zero, and no kind falls by more than 0.02")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CannotRun, OSError, RuntimeError, KeyError, ValueError) as error:
        print(f"hard-set evaluation could not run: {type(error).__name__}: {error}")
        sys.exit(2)
