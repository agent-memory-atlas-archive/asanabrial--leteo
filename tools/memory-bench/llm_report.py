"""The LLM tier's section of the comparison page, from `results_llm.json`.

A model that extracts facts or builds a graph does not give the same store twice,
so one number per engine would hide the variance that is most of what these
engines need to be judged on. Every figure here is shown as the mean over the
engine's passes with the lowest and highest pass beside it, and the pass count is
a column of its own: a row measured on one pass says so in the table, not in a
footnote.
"""

import statistics

from scoring import summarise

CAVEAT = (
    "**These engines may score lower here than in their vendor-default configuration.** "
    "Every model call goes to a small local model (named in the table above) in place of the hosted model each "
    "project is built and tuned around, and the extraction prompts, entity types and defaults were left as shipped. "
    "A low row says how the engine behaves on this local model, not how it behaves with its recommended one."
)


def spread(values):
    """`(mean, lowest, highest)` over the passes."""
    return statistics.mean(values), min(values), max(values)


def cell(values, digits=3):
    mean, lo, hi = spread(values)
    if lo == hi:
        return f"{mean:.{digits}f} (every pass)"
    return f"{mean:.{digits}f} ({lo:.{digits}f}–{hi:.{digits}f})"


def each_pass(engine, fn):
    return [fn(p) for p in engine["passes"]]


def models_cell(engine):
    if not engine["models"]:
        return "none called"
    parts = []
    for role in ("llm", "embed"):
        m = engine["models"].get(role)
        if m:
            parts.append(f"{m['name']} ({m['size']}, {m['quantization']}, `{m['digest']}`)")
    return "; ".join(parts)


def passes_cell(engine):
    done, planned = len(engine["passes"]), engine["planned"]
    return f"{done}" if done == planned else f"{done} of {planned}"


def engines_table(engines):
    lines = ["| engine | version | models and digests | run date | passes | status |", "|---|---|---|---|---:|---|"]
    for e in engines:
        if e["status"] == "measured":
            status = "measured"
            if e.get("failed"):
                status += f"; **stopped:** {e['failed']}"
            lines.append(f"| {e['label']} | {e['version']} | {models_cell(e)} | {e['date']} | {passes_cell(e)} | {status} |")
        else:
            lines.append(f"| {e['label']} | {e['version'] or '—'} | — | {e['date']} | — | **not measured:** {e['reason']} |")
    return "\n".join(lines)


def results_table(measured):
    """One row per engine; each figure is mean (lowest–highest pass)."""
    lines = [
        "| engine | passes | h@1 | h@5 | MRR | returned nothing, of the answerable queries | unmappable hits | no-answer questions answered | write time per pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for e in measured:
        stats = each_pass(e, lambda p: summarise(p["rows"]))
        # Both "of N" denominators are this engine's own: a row must not carry the
        # first engine's totals when it was asked fewer answerable or unanswerable
        # queries.
        n = stats[0]["n"]
        no_answer = len(e["passes"][0]["no_answer"])
        lines.append(
            f"| {e['label']} | {passes_cell(e)} | {cell([s['hit1'] for s in stats], 2)} | {cell([s['hit5'] for s in stats], 2)} "
            f"| {cell([s['mrr'] for s in stats])} "
            f"| {cell(each_pass(e, lambda p: sum(r['n'] == 0 for r in p['rows'])), 1)} of {n} "
            f"| {cell(each_pass(e, lambda p: sum(r['unmappable'] for r in p['rows'])), 1)} "
            f"| {cell(each_pass(e, lambda p: sum(r['n'] > 0 for r in p['no_answer'])), 1)} of {no_answer} "
            f"| {cell(each_pass(e, lambda p: p['load_seconds']), 0)} s |"
        )
    return "\n".join(lines)


def kind_table(measured):
    """Mean MRR per query kind. A kind has a handful of queries, so its spread
    across passes would mostly be one query moving; the mean is shown alone."""
    kinds = sorted({r["kind"] for e in measured for r in e["passes"][0]["rows"]})
    lines = ["| query kind | n | " + " | ".join(f"{e['label']} MRR" for e in measured) + " |",
             "|---|---:|" + "---:|" * len(measured)]
    for kind in kinds + ["ALL"]:
        cells, n = [], 0
        for e in measured:
            per = [summarise([r for r in p["rows"] if kind == "ALL" or r["kind"] == kind]) for p in e["passes"]]
            n = per[0]["n"]
            cells.append(f"{statistics.mean(s['mrr'] for s in per):.3f}")
        lines.append(f"| {'**overall**' if kind == 'ALL' else kind} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def notes(engines):
    out = []
    for e in engines:
        if e["status"] != "measured":
            continue
        seen = []
        for p in e["passes"]:
            for note in p["notes"]:
                if note not in seen:
                    seen.append(note)
        out += [f"- **{e['label']}:** {note}." for note in seen]
    return "\n".join(out)
