#!/usr/bin/env python3
"""One command reproduces every number on docs/comparison.md.

This is the single entry point for the comparison: `bench_engines.py` starts each
engine of the tier through its adapter, writes the held-out corpus through the
engine's own write path, asks every engine the same queries at the same limit
through its own search path, and this script rewrites the generated block in the
page from that output. The versions and the date are measured here too, so a
re-run on a different engine or a new Leteo commit regenerates the page with the
numbers it actually saw rather than the ones somebody typed.

A step that cannot run is skipped and named, never faked: the page must not
carry a number this script did not produce, and an engine that could not be
measured is listed with its reason rather than as a row of zeros. `bench_cost.py`
is the standing example -- its Engram session-start hook is a script in Engram's
source tree, not its binary, so it needs ENGRAM_SRC and is skipped without one.

    LETEO_BIN=target/release/leteo python3 tools/engram-bench/compare.py

`--tier llm` is the one opt-in flag for the engines that need a local language
model (mem0, claude-mem, Letta, Graphiti on Ollama). It runs only that tier, each
engine for `--passes` independent loads (three by default), and rewrites only the
LLM section of the page, which has generated markers of its own; the default run
leaves that section alone. It is never part of CI: it needs Ollama, Docker and
hours.

Why the page is generated rather than written: the previous comparison lived in
`tools/README.md` as prose with a date and a commit in it, and drifted from the
harness the moment either moved. A generated block has one source of truth.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAGE = ROOT / "docs" / "comparison.md"
BEGIN = "<!-- BEGIN GENERATED: compare.py -->"
END = "<!-- END GENERATED: compare.py -->"
LLM_BEGIN = "<!-- BEGIN GENERATED: compare.py --tier llm -->"
LLM_END = "<!-- END GENERATED: compare.py --tier llm -->"

sys.path.insert(0, str(HERE))
from comparison_corpus import corpus, queries  # noqa: E402  (path must be set first)
from scoring import summarise  # noqa: E402
import llm_report  # noqa: E402

PROJECTS = ("alpha-api", "beta-web")


def sh(cmd, env, cwd=HERE, capture=True):
    print(f"$ {' '.join(str(c) for c in cmd)}", file=sys.stderr)
    return subprocess.run(
        [str(c) for c in cmd],
        env=env,
        cwd=str(cwd),
        capture_output=capture,
        text=True,
    )


def git_head():
    r = sh(["git", "-C", str(ROOT), "rev-parse", "HEAD"], dict(os.environ))
    head = r.stdout.strip()
    # Only the inputs the binary is built from matter here: a page regenerated
    # against a modified `docs/` or `tools/` is not a modified Leteo, and calling
    # that "dirty" would put a false warning on every generated commit.
    src = sh(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "src", "migrations", "Cargo.toml", "Cargo.lock", "build.rs"],
        dict(os.environ),
    ).stdout.strip()
    return head, bool(src)


def search_limit():
    """The limit bench_engines.py asks at, read from it rather than retyped.

    The page states the limit as method; reading it here is what keeps that
    sentence true when somebody changes the harness's own number.
    """
    src = (HERE / "bench_engines.py").read_text()
    m = re.search(r"^LIMIT\s*=\s*(\d+)", src, re.M)
    return m.group(1) if m else "?"


def kinds_of(engines):
    return sorted({r["kind"] for e in engines for r in e["rows"]})


def of_kind(engine, kind):
    return [r for r in engine["rows"] if kind == "ALL" or r["kind"] == kind]


def engines_table(engines):
    """Every engine of the tier, measured or not, with the reason when not.

    A skipped engine appears here and nowhere below: the tables that carry
    numbers hold only engines that produced some.
    """
    lines = ["| engine | version | run date | status |", "|---|---|---|---|"]
    for e in engines:
        if e["status"] == "measured":
            lines.append(f"| {e['label']} | {e['version']} | {e['date']} | measured |")
        else:
            lines.append(f"| {e['label']} | {e['version'] or '—'} | {e['date']} | **not measured:** {e['reason']} |")
    return "\n".join(lines)


def overall_table(measured):
    """One row per engine on the whole query set.

    `returned nothing` counts answerable queries the engine replied to with no
    hit at all, and `unmappable` counts returned hits that are none of the corpus
    memories: both score zero, and they are different faults. `answered` is how
    many of the unanswerable questions got any hit.
    """
    lines = [
        "| engine | version | run date | h@1 | h@5 | MRR | returned nothing | hits returned | unmappable hits | no-answer questions answered |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for e in measured:
        s = summarise(e["rows"])
        empty = sum(r["n"] == 0 for r in e["rows"])
        hits = sum(r["n"] for r in e["rows"])
        unmappable = sum(r["unmappable"] for r in e["rows"])
        answered = sum(r["n"] > 0 for r in e["no_answer"])
        lines.append(
            f"| {e['label']} | {e['version']} | {e['date']} | {s['hit1']:.2f} | {s['hit5']:.2f} | {s['mrr']:.3f} "
            f"| {empty} of {s['n']} | {hits} | {unmappable} | {answered} of {len(e['no_answer'])} |"
        )
    return "\n".join(lines)


def kind_table(measured):
    lines = [
        "| query kind | n | " + " | ".join(f"{e['label']} h@1 / h@5 / MRR" for e in measured) + " |",
        "|---|---:|" + "---:|" * len(measured),
    ]
    for kind in kinds_of(measured) + ["ALL"]:
        name = "**overall**" if kind == "ALL" else kind
        cells = []
        for e in measured:
            s = summarise(of_kind(e, kind))
            cells.append(f"{s['hit1']:.2f} / {s['hit5']:.2f} / {s['mrr']:.3f}")
        lines.append(f"| {name} | {len(of_kind(measured[0], kind))} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def timing_block(results):
    lines = [
        "| engine | warm search median | p90 | mean reply bytes | mean results | zero-result queries | 20-result replies | mean bytes at 20 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in ("engram", "leteo"):
        rows = results[engine]
        ms = sorted(r["ms"] for r in rows)
        p90 = ms[int(0.9 * len(ms))]
        full = [r["bytes"] for r in rows if r["n"] == 20]
        lines.append(
            f"| {engine} | {statistics.median(ms):.1f} ms | {p90:.1f} ms "
            f"| {statistics.mean(r['bytes'] for r in rows):.0f} "
            f"| {statistics.mean(r['n'] for r in rows):.1f} "
            f"| {sum(r['n'] == 0 for r in rows)} "
            f"| {len(full)} | {statistics.mean(full) if full else 0:.0f} |"
        )
    return "\n".join(lines)


def parse_any(stdout):
    """bench_any.py prints one `kind h@1 .. h@5 .. MRR ..` line per kind.

    The harness is left as it is rather than taught a second output format: a
    JSON sidecar would be a second place the numbers live.
    """
    out = {}
    for line in stdout.splitlines():
        m = re.match(r"^(\w+)\s+h@1\s+([\d.]+)\s+h@5\s+([\d.]+)\s+MRR\s+([\d.]+)$", line.strip())
        if m:
            out[m.group(1)] = dict(hit1=float(m.group(2)), hit5=float(m.group(3)), mrr=float(m.group(4)))
    return out


def no_answer_table(results):
    """What each engine does with a question its store cannot answer.

    `with no caveat` is the number that matters: an empty reply and one that
    carries a sentence saying the match is weak both tell the agent not to rely
    on it, and only a reply that does neither is a confident wrong answer. The
    no-answer precision is the share of these questions the engine handled
    correctly, which is every reply that was empty or carried a caveat.
    """
    lines = [
        "| engine | answered | with no caveat | no-answer precision | mean reply bytes |",
        "|---|---:|---:|---:|---:|",
    ]
    for engine in ("engram", "leteo"):
        rows = results.get("no_answer_" + engine, [])
        # No rows at all is not a zero: the run has no measurement of this
        # engine's no-answer behaviour, and a `0.00` there reads as a measured
        # failure. The dash says the number was not taken.
        if not rows:
            lines.append(f"| {engine} | — | — | — | — |")
            continue
        answered = [r for r in rows if r["n"]]
        confident = sum(1 for r in answered if not r["caveat"])
        precision = (len(rows) - confident) / len(rows)
        bytes_cell = f"{statistics.mean(r['bytes'] for r in answered):.0f}" if answered else "—"
        lines.append(
            f"| {engine} | {len(answered)} of {len(rows)} "
            f"| {confident} "
            f"| {precision:.2f} "
            f"| {bytes_cell} |"
        )
    return "\n".join(lines)


def any_table(engram, leteo, any_stats):
    """Per-kind rows for Engram's opt-in `match_mode: "any"`, against Leteo.

    Leteo is not rerun under the mode — it has no such switch — so its columns
    are its defaults, which the header names.
    """
    lines = [
        "| query kind | n | Engram `any` h@1 | Engram `any` h@5 | Engram `any` MRR | Leteo h@1 | Leteo h@5 | Leteo MRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for kind in kinds_of([engram]) + ["ALL"]:
        e = any_stats.get(kind)
        l = summarise(of_kind(leteo, kind))
        name = "**overall**" if kind == "ALL" else kind
        if e is None:
            lines.append(f"| {name} | {l['n']} | — | — | — | {l['hit1']:.2f} | {l['hit5']:.2f} | {l['mrr']:.3f} |")
        else:
            lines.append(
                f"| {name} | {l['n']} | {e['hit1']:.2f} | {e['hit5']:.2f} | {e['mrr']:.3f} "
                f"| {l['hit1']:.2f} | {l['hit5']:.2f} | {l['mrr']:.3f} |"
            )
    return "\n".join(lines)


def leads_table(measured, any_stats):
    """Who has the higher MRR on each kind, computed from the tables above.

    A tie is an exact equality rather than a closeness test, and every engine
    that shares the top is named. A per-kind lead of one query is noise, and the
    page says so beside the table. With Engram's `any` run available the last
    column ranks it in place of Engram's defaults.
    """

    def leader(scores):
        best = max(v for _, v in scores)
        names = [n for n, v in scores if v == best]
        return ("tie " if len(names) > 1 else "") + ", ".join(names) + f" {best:.3f}"

    lines = [
        "| query kind | " + " | ".join(f"{e['label']} MRR" for e in measured) + " | Engram `any` MRR | leader, defaults | leader, `any` |",
        "|---|" + "---:|" * (len(measured) + 1) + "---|---|",
    ]
    for kind in kinds_of(measured) + ["ALL"]:
        scores = [(e["label"], summarise(of_kind(e, kind))["mrr"]) for e in measured]
        a = any_stats.get(kind, {}).get("mrr")
        name = "**overall**" if kind == "ALL" else kind
        a_lead = "—"
        if a is not None:
            a_lead = leader([(n, a if n == "Engram" else v) for n, v in scores])
        lines.append(
            f"| {name} | " + " | ".join(f"{v:.3f}" for _, v in scores)
            + f" | {f'{a:.3f}' if a is not None else '—'} | {leader(scores)} | {a_lead} |"
        )
    return "\n".join(lines)


def run_optional(cmd, env, cwd=HERE):
    """Run a benchmark that may be impossible on this machine.

    Returns (ok, stdout, reason). A missing dependency is a skip with a sentence
    naming it, not a failure and not a silent zero.
    """
    try:
        r = sh(cmd, env, cwd=cwd)
    except OSError as e:
        return False, "", f"could not start `{cmd[0]}`: {e}"
    if r.returncode != 0:
        first = (r.stderr or r.stdout or "").strip().splitlines()
        return False, r.stdout or "", (
            f"`{' '.join(str(c) for c in cmd)}` exited {r.returncode}: {first[0] if first else 'no output'}"
        )
    return True, r.stdout, ""


def replace_block(begin, end, text):
    page = PAGE.read_text()
    if begin not in page or end not in page:
        sys.exit(f"{PAGE} does not carry the generated-block markers {begin}")
    before, rest = page.split(begin, 1)
    _, after = rest.split(end, 1)
    PAGE.write_text(before + begin + "\n" + text + "\n" + end + after)


def llm_block(engines, harness_date, head):
    measured = [e for e in engines if e["status"] == "measured"]
    members = corpus()
    qs = queries()
    ollama = next((e["ollama"] for e in measured if e.get("ollama")), "—")
    out = [f"*Generated by `tools/engram-bench/compare.py --tier llm` on {harness_date}.*", "",
           "| measured | value |", "|---|---|",
           "| tier | llm (opt-in, local Ollama only) |",
           f"| harness | `tools/engram-bench` at Leteo commit `{head}` |",
           f"| Ollama | {ollama} |",
           f"| search limit | {search_limit()} |",
           f"| corpus | {len(members)} memories, the same as the table above |",
           f"| queries | {len(qs)}, the same as the table above |",
           f"| passes requested | {', '.join(sorted({str(e['planned']) for e in measured})) or '—'} per engine, each from an empty store |",
           "", "### Engines", "", llm_report.engines_table(engines), "", llm_report.CAVEAT, ""]
    if measured:
        out += ["### Head to head, LLM tier, limit " + search_limit(), "",
                "Each figure is the mean over the engine's passes, with the lowest and the highest pass in "
                "parentheses. Compare with the deterministic table above: it is the same corpus, the same queries "
                "and the same limit.", "", llm_report.results_table(measured), "", llm_report.kind_table(measured), "",
                llm_report.notes(measured), ""]
    return "\n".join(out)


def llm_main(args):
    state = os.environ.get("BENCH_STATE") or tempfile.mkdtemp(prefix="leteo-engram-compare-")
    os.makedirs(state, exist_ok=True)
    env = dict(os.environ, BENCH_STATE=state)
    harness_date = datetime.date.today().isoformat()
    head, _ = git_head()
    cmd = [sys.executable, "bench_engines.py", "--tier", "llm"]
    if args.passes:
        cmd += ["--passes", str(args.passes)]
    if args.only:
        cmd += ["--only", args.only]
    try:
        r = sh(cmd, env, capture=False)
        if r.returncode:
            sys.exit(f"bench_engines.py failed ({r.returncode}); the page was not rewritten")
        with open(os.path.join(state, "results_llm.json")) as f:
            engines = json.load(f)["engines"]
        replace_block(LLM_BEGIN, LLM_END, llm_block(engines, harness_date, head))
        print(f"\nwrote the LLM section of {PAGE.relative_to(ROOT)}", file=sys.stderr)
    finally:
        if not os.environ.get("BENCH_STATE"):
            shutil.rmtree(state, ignore_errors=True)


def main(argv):
    ap = argparse.ArgumentParser(description="Regenerate the comparison page from one run.")
    ap.add_argument("--tier", default="deterministic", choices=("deterministic", "llm"),
                    help="deterministic is the default; llm is the opt-in tier of engines that need a local LLM")
    ap.add_argument("--passes", type=int, help="llm tier only: independent loads per engine (three by default)")
    ap.add_argument("--only", help="llm tier only: comma-separated engine names, for resuming a long run")
    args = ap.parse_args(argv)
    if args.tier == "llm":
        return llm_main(args)

    leteo_bin = os.environ.get("LETEO_BIN")
    if not leteo_bin:
        sys.exit("LETEO_BIN is not set; name the binary under test")
    leteo_bin = str(Path(leteo_bin).resolve())

    state = os.environ.get("BENCH_STATE") or tempfile.mkdtemp(prefix="leteo-engram-compare-")
    os.makedirs(state, exist_ok=True)
    env = dict(os.environ, BENCH_STATE=state, LETEO_BIN=leteo_bin)

    harness_date = datetime.date.today().isoformat()
    head, source_dirty = git_head()

    try:
        r = sh([sys.executable, "bench_engines.py", "--tier", args.tier], env)
        print(r.stderr, file=sys.stderr)
        if r.returncode:
            sys.exit(f"bench_engines.py failed ({r.returncode}); the page was not rewritten")

        with open(os.path.join(state, "results_engines.json")) as f:
            engines = json.load(f)["engines"]
        measured = [e for e in engines if e["status"] == "measured"]
        by_name = {e["name"]: e for e in measured}
        both = "engram" in by_name and "leteo" in by_name

        # The latency, reply-size and no-answer figures come from scripts that
        # read the Engram and Leteo stores the adapters just loaded, so they run
        # only when both engines were measured.
        search_ok, search_reason, results = False, "", {}
        any_ok, any_out, any_reason = False, "", ""
        if both:
            search_ok, search_out, search_reason = run_optional([sys.executable, "bench_search.py"], env)
            print(search_out, file=sys.stderr)
            if search_ok:
                with open(os.path.join(state, "results_search.json")) as f:
                    results = json.load(f)
            any_ok, any_out, any_reason = run_optional([sys.executable, "bench_any.py"], env)
        else:
            search_reason = any_reason = "Engram and Leteo were not both measured, and this reads their stores"
        any_stats = parse_any(any_out) if any_ok else {}

        cost_ok, cost_out, cost_reason = (False, "", "")
        engram_src = os.environ.get("ENGRAM_SRC")
        if not engram_src:
            cost_reason = (
                "`ENGRAM_SRC` is not set, and Engram's session-start hook is a script in its "
                "source tree rather than part of its binary"
            )
        else:
            hook = Path(engram_src) / "plugin" / "claude-code" / "scripts" / "session-start.sh"
            if not hook.exists():
                cost_reason = f"`ENGRAM_SRC={engram_src}` does not hold `plugin/claude-code/scripts/session-start.sh`"
            elif not both:
                cost_reason = "Engram and Leteo were not both measured, and this reads their stores"
            else:
                cost_ok, cost_out, cost_reason = run_optional([sys.executable, "bench_cost.py"], env)

        members = corpus()
        qs = queries()
        per_project = {p: sum(1 for m in members if m["project"] == p) for p in PROJECTS}
        per_kind = {}
        for q in qs:
            per_kind[q["kind"]] = per_kind.get(q["kind"], 0) + 1

        out = []
        out.append(f"*Generated by `tools/engram-bench/compare.py` on {harness_date}.*")
        out.append("")
        out.append("| measured | value |")
        out.append("|---|---|")
        out.append(f"| tier | {args.tier} |")
        out.append(f"| Leteo commit | `{head}`{' — source tree dirty' if source_dirty else ''} |")
        out.append("| harness | `tools/engram-bench`, run by `compare.py` at this commit |")
        out.append(f"| search limit | {search_limit()} |")
        out.append(f"| corpus | {len(members)} memories ({', '.join(f'{p} {per_project[p]}' for p in PROJECTS)}) |")
        out.append(
            f"| queries | {len(qs)} across {len(per_kind)} kinds ("
            + ", ".join(f"{k} {per_kind[k]}" for k in sorted(per_kind))
            + ") |"
        )
        out.append("")
        out.append("### Engines")
        out.append("")
        out.append(engines_table(engines))
        out.append("")
        out.append("The LLM tier (engines that need a local model) is opt-in and not part of this run: "
                   "its engines have no row here, which is different from a row of zeros.")
        out.append("")
        out.append(f"### Head to head, each engine's own search, limit {search_limit()}, defaults")
        out.append("")
        out.append(overall_table(measured))
        out.append("")
        out.append(kind_table(measured))
        out.append("")
        out.append("### Warm-search latency and reply size")
        out.append("")
        out.append(timing_block(results) if search_ok else f"Skipped: {search_reason}.")
        out.append("")
        out.append("### Questions the corpus cannot answer")
        out.append("")
        out.append(no_answer_table(results) if search_ok else f"Skipped: {search_reason}.")
        out.append("")
        out.append("### Engram with its opt-in `match_mode: \"any\"`")
        out.append("")
        if any_ok and any_stats:
            out.append(any_table(by_name["engram"], by_name["leteo"], any_stats))
        elif any_ok:
            out.append("Skipped: `bench_any.py` ran but printed no per-kind rows to parse.")
        else:
            out.append(f"Skipped: {any_reason}.")
        out.append("")
        out.append("### Who leads, per query kind")
        out.append("")
        out.append(leads_table(measured, any_stats))
        out.append("")
        out.append("### Reply bytes, session-start hook latency, cold CLI search")
        out.append("")
        if cost_ok:
            out.append("```text")
            out.append(cost_out.strip())
            out.append("```")
        else:
            out.append(f"Skipped: {cost_reason}.")
        out.append("")
        block = "\n".join(out)

        page = PAGE.read_text()
        if BEGIN not in page or END not in page:
            sys.exit(f"{PAGE} does not carry the generated-block markers")
        before, rest = page.split(BEGIN, 1)
        _, after = rest.split(END, 1)
        PAGE.write_text(before + BEGIN + "\n" + block + "\n" + END + after)

        print(f"\nwrote {PAGE.relative_to(ROOT)}", file=sys.stderr)
        print(f"{', '.join(e['label'] + ' ' + e['version'] for e in measured)}; {len(qs)} queries", file=sys.stderr)
    finally:
        if not os.environ.get("BENCH_STATE"):
            shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
