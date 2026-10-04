#!/usr/bin/env python3
"""One command reproduces every number on docs/comparison-with-engram.md.

This is the single entry point for the head-to-head: it loads the corpus into a
fresh Engram store, adopts a copy into Leteo, runs each engine's own MCP
`mem_search` over the same queries, and rewrites the generated block in the page
from the harness output. The versions and the date are measured here too, so a
re-run on a different Engram or a new Leteo commit regenerates the page with the
numbers it actually saw rather than the ones somebody typed.

A step that cannot run is skipped and named, never faked: the page must not
carry a number this script did not produce. `bench_cost.py` is the standing
example -- its Engram session-start hook is a script in Engram's source tree,
not its binary, so it needs ENGRAM_SRC and is skipped without one.

    LETEO_BIN=target/release/leteo python3 tools/engram-bench/compare.py

Why the page is generated rather than written: the previous comparison lived in
`tools/README.md` as prose with a date and a commit in it, and drifted from the
harness the moment either moved. A generated block has one source of truth.
"""

import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAGE = ROOT / "docs" / "comparison-with-engram.md"
BEGIN = "<!-- BEGIN GENERATED: compare.py -->"
END = "<!-- END GENERATED: compare.py -->"

sys.path.insert(0, str(HERE))
from corpus import corpus, queries  # noqa: E402  (path must be set first)

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


def which(name, explicit):
    path = explicit or shutil.which(name)
    if not path:
        sys.exit(f"{name} not found: set {name.upper()}_BIN or put it on PATH")
    return path


def engram_version(binary):
    r = sh([binary, "--version"], dict(os.environ))
    text = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"engram\s+v?(\d+\.\d+\.\d+)", text)
    return m.group(1) if m else "unknown"


def leteo_version(binary):
    r = sh([binary, "--version"], dict(os.environ))
    text = ((r.stdout or "") + (r.stderr or "")).strip()
    m = re.search(r"(\d+\.\d+\.\d+)", text)
    return m.group(1) if m else "unknown"


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
    """The limit bench_search.py asks at, read from it rather than retyped.

    The page states the limit as method; reading it here is what keeps that
    sentence true when somebody changes the harness's own number.
    """
    src = (HERE / "bench_search.py").read_text()
    m = re.search(r'"limit":\s*(\d+)', src)
    return m.group(1) if m else "?"


def summarise(rows):
    n = len(rows)
    hit1 = sum(r["rank"] == 1 for r in rows) / n
    hit5 = sum(bool(r["rank"]) and r["rank"] <= 5 for r in rows) / n
    mrr = sum(1 / r["rank"] for r in rows if r["rank"]) / n
    return dict(n=n, hit1=hit1, hit5=hit5, mrr=mrr)


def kind_table(results):
    kinds = sorted({r["kind"] for r in results["engram"]})
    lines = [
        "| query kind | n | Engram h@1 | Engram h@5 | Engram MRR | Leteo h@1 | Leteo h@5 | Leteo MRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for kind in kinds + ["ALL"]:
        e = summarise([r for r in results["engram"] if kind == "ALL" or r["kind"] == kind])
        l = summarise([r for r in results["leteo"] if kind == "ALL" or r["kind"] == kind])
        name = "**overall**" if kind == "ALL" else kind
        lines.append(
            f"| {name} | {e['n']} | {e['hit1']:.2f} | {e['hit5']:.2f} | {e['mrr']:.3f} "
            f"| {l['hit1']:.2f} | {l['hit5']:.2f} | {l['mrr']:.3f} |"
        )
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
            out[m.group(1)] = float(m.group(4))
    return out


def leads_sentence(results, any_mrr):
    kinds = sorted({r["kind"] for r in results["engram"]})
    default = [
        (
            kind,
            summarise([r for r in results["engram"] if r["kind"] == kind])["mrr"],
            summarise([r for r in results["leteo"] if r["kind"] == kind])["mrr"],
        )
        for kind in kinds
    ]
    e_all = summarise(results["engram"])
    l_all = summarise(results["leteo"])

    engram_wins = [f"{k} (Engram {e:.3f}, Leteo {l:.3f})" for k, e, l in default if e > l]
    leteo_wins = [k for k, e, l in default if l > e]
    ties = [k for k, e, l in default if e == l]

    parts = []
    if engram_wins:
        parts.append("With each engine's own defaults, **Engram leads on " + ", ".join(engram_wins) + "**.")
    else:
        parts.append("With each engine's own defaults, **Engram does not lead on any query kind in this run**.")
    if ties:
        parts.append("The two tie on " + ", ".join(ties) + ".")
    if leteo_wins:
        parts.append("Leteo leads on " + ", ".join(leteo_wins) + ".")
    parts.append(
        f"Overall MRR is {e_all['mrr']:.3f} for Engram against {l_all['mrr']:.3f} for Leteo "
        f"(hit@1 {e_all['hit1']:.2f} against {l_all['hit1']:.2f})."
    )

    partial = next((f"Engram {e:.3f} against Leteo {l:.3f}" for k, e, l in default if k == "partial"), None)
    if partial:
        parts.append(f"Partial words — the axis this comparison was built around — is {partial} in this run.")

    if any_mrr:
        any_leads = [
            f"{k} (Engram {any_mrr[k]:.3f}, Leteo {l:.3f})"
            for k, _, l in default
            if k in any_mrr and any_mrr[k] > l
        ]
        if any_leads:
            parts.append(
                "With Engram's opt-in `match_mode: \"any\"` — not the default an agent gets — "
                "Engram leads on " + ", ".join(any_leads) + "."
            )
        else:
            parts.append(
                "With Engram's opt-in `match_mode: \"any\"` — not the default an agent gets — "
                "Engram still leads on no query kind."
            )
    return " ".join(parts)


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


def main():
    leteo_bin = os.environ.get("LETEO_BIN")
    if not leteo_bin:
        sys.exit("LETEO_BIN is not set; name the binary under test")
    leteo_bin = str(Path(leteo_bin).resolve())
    engram_bin = which("engram", os.environ.get("ENGRAM_BIN"))

    state = os.environ.get("BENCH_STATE") or tempfile.mkdtemp(prefix="leteo-engram-compare-")
    os.makedirs(state, exist_ok=True)
    env = dict(os.environ, BENCH_STATE=state, ENGRAM_BIN=engram_bin, LETEO_BIN=leteo_bin)

    harness_date = datetime.date.today().isoformat()
    e_version = engram_version(engram_bin)
    l_version = leteo_version(leteo_bin)
    head, source_dirty = git_head()

    try:
        # The corpus is saved through Engram's own CLI first: its index is built
        # by its own write path, not by SQL this harness composed.
        r = sh([sys.executable, "load_engram.py"], env)
        if r.returncode:
            sys.exit(f"load_engram.py failed:\n{r.stderr}")
        print(r.stdout.strip(), file=sys.stderr)

        r = sh(["sh", "load_leteo.sh"], env)
        if r.returncode:
            sys.exit(f"load_leteo.sh failed:\n{r.stderr}")
        print(r.stdout.strip(), file=sys.stderr)

        r = sh([sys.executable, "bench_search.py"], env)
        if r.returncode:
            sys.exit(f"bench_search.py failed:\n{r.stderr}")
        print(r.stdout, file=sys.stderr)

        with open(os.path.join(state, "results_search.json")) as f:
            results = json.load(f)

        any_ok, any_out, any_reason = run_optional([sys.executable, "bench_any.py"], env)
        any_mrr = parse_any(any_out) if any_ok else {}

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
        out.append(f"| Engram version | {e_version} |")
        out.append(f"| Leteo version | {l_version} |")
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
        out.append(f"### Head to head, each engine's own MCP `mem_search`, limit {search_limit()}, defaults")
        out.append("")
        out.append(kind_table(results))
        out.append("")
        out.append("### Warm-search latency and reply size")
        out.append("")
        out.append(timing_block(results))
        out.append("")
        out.append("### Engram with its opt-in `match_mode: \"any\"`")
        out.append("")
        out.append(
            textwrap.fill(
                "`match_mode: any` is opt-in, so this is not the answer an agent gets by default; "
                "it is included because it is the closest Engram comes to Leteo's relaxed stages.",
                width=88,
            )
        )
        out.append("")
        if any_ok and any_mrr:
            out.append("```text")
            out.append(any_out.strip())
            out.append("```")
        elif any_ok:
            out.append("Skipped: `bench_any.py` ran but printed no per-kind rows to parse.")
        else:
            out.append(f"Skipped: {any_reason}.")
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
        out.append("### Where Engram leads")
        out.append("")
        out.append(textwrap.fill(leads_sentence(results, any_mrr), width=88))
        out.append("")
        block = "\n".join(out)

        page = PAGE.read_text()
        if BEGIN not in page or END not in page:
            sys.exit(f"{PAGE} does not carry the generated-block markers")
        before, rest = page.split(BEGIN, 1)
        _, after = rest.split(END, 1)
        PAGE.write_text(before + BEGIN + "\n" + block + "\n" + END + after)

        print(f"\nwrote {PAGE.relative_to(ROOT)}", file=sys.stderr)
        print(f"Engram {e_version} vs Leteo {l_version} ({head[:12]}), {len(qs)} queries", file=sys.stderr)
    finally:
        if not os.environ.get("BENCH_STATE"):
            shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    main()
