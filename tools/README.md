# Development tools

Not part of the binary. Nothing here ships.

Two small crates, each its own workspace, and one Python harness. `mutate`
depends on nothing from `leteo` on purpose: it edits `src/` and then runs `cargo test` on it, and built
as part of the crate it mutates it would be rebuilt *from the mutated source*
before the suite could run. `retrieval` does depend on `leteo`, and that is
equally deliberate — it measures the ranking statement the product issues
rather than a copy of it.

## `mutate` — does the guard actually guard?

A test that passes is not evidence. A test that **fails when you break the
thing it is about** is. This breaks each invariant in `guards.json` on purpose,
runs the whole suite, and reports which tests noticed.

```bash
cargo run --release --manifest-path tools/mutate/Cargo.toml -- tools/guards.json
```

It exists because doing this by hand failed three times in one session, each
time looking like success:

- `cargo fmt` had reformatted the line the patch was matching on, so the edit
  silently did nothing and the *unmodified* code passed.
- A `cargo test "one two"` filter matched no tests at all. Zero ran; it said
  `ok`.
- A guard passed with its subject broken, because a fallback quietly supplied
  the right answer and the fast path had become dead code.

So it asserts the mutation landed, runs the full suite rather than a filter,
and treats a surviving mutation as a failure. A guard that survives its own
invariant being removed is not a guard.

Add a case when you add a guard:

```json
{"name": "what is being broken", "file": "src/…", "old": "exact text", "new": "replacement"}
```

`old` must match the file **after** `cargo fmt`, or the run reports
`NOT APPLIED` rather than pretending.

### Cost

One full suite run per case, so a sweep of 27 takes roughly ten minutes. This
is a pre-release check, not something to run per edit — narrow `guards.json` to
the cases near what you changed while iterating, and run the whole file before
shipping.

Progress prints as it goes, one line per case with its elapsed time.

### It breaks the working tree on purpose

While a case runs, the repository really is broken — that is the whole method.
Two things follow, and both cost real time before they were handled:

**Do not run anything else against the repo while a sweep is going.** A
`cargo test` racing a background sweep reported four failures that were not
real, and the obvious next move is to go and "fix" a bug that does not exist.

**A run that is killed leaves a mutation applied.** `tools/.mutate-in-flight.json`
holds the file being edited and its original bytes, so an interrupted run leaves
something the next one repairs on startup, saying so:

```
repaired src/store/search.rs: a previous run was interrupted mid-mutation
```

If that file exists, the tree is not what it looks like. Run the tool again — or
restore from the `original` it holds — before believing any test result.

### SURVIVED is not the same as unguarded

Some tests carry `#[ignore = "requires TEST_DATABASE_URL …"]`, including the
one that proves a tenant cannot reach another tenant's project. They do not run
locally; CI runs them against a real PostgreSQL service.

So a local sweep reports SURVIVED for anything only those tests cover. Five
isolation mutations did exactly that — allow every project grant, accept any
auth scheme — and the boundary was fine. The tool now prints the ignored count
before the verdicts for that reason. Read SURVIVED as **"nothing that ran
noticed"**, and check whether an ignored test covers it before concluding
anything.

### An ambiguous pattern is not a case

`old` must match exactly once. `.replace(..., 1)` takes the first occurrence,
so a pattern appearing twice mutates whichever copy comes first — silently, and
usually not the one meant. Five queries in `store/relations.rs` share a join
clause; a case aimed at the caveat query hit an unrelated one and reported
SURVIVED, which meant nothing.

The tool now refuses those as `AMBIGUOUS` and says how many matches it found.
Add surrounding lines until the pattern is unique.

### A mutation that hangs

Some mutations make a test loop instead of fail — removing the progress check
from the repository import leaves every round retrying the same unappliable
chunk. `cargo test` then never returns and the sweep stops dead, with no
verdict for that case or any after it.

Each run is bounded (`SUITE_TIMEOUT`, five minutes). A run that does not finish
counts as caught and says so: a hang is a test noticing, not a reason to wait.

## `retrieval` — can the store find what it holds?

Every question is built from a memory the store already has, so the answer that
should come back is known without anybody labelling anything.

```bash
cargo run --release --manifest-path tools/retrieval/Cargo.toml -- ~/.leteo/leteo.db
cargo run --release --manifest-path tools/retrieval/Cargo.toml -- copy.db \n  --weights "20.0, 0.3, 0.0, 0.0, 0.0, 6.0"
cargo run --release --manifest-path tools/retrieval/Cargo.toml -- copy.db --rerank
```

Read-only, against the database you name. It reports title-shaped and
body-shaped questions separately, each against two independent draws, because
the gap between those four numbers is the only thing that makes a weight change
believable.

`--rerank` prints the shipped ordering beside the same statement with the Engram
pin/recency/stability factor as its sort key, over the same draws. The factor is
not adopted; the measurement that rejected it is in
[`openspec/specs/search.md`](../openspec/specs/search.md) §2.

### The trap, which has now caught two attempts

Questions drawn from titles reward weighting titles. Sweeping the bm25 vector
against a title-drawn set found `(title 20, content 0.3, topic 6)` worth +3.3
MRR points — **entirely fake**, and only visible by asking the same vector
questions drawn from bodies, where it lost.

Then it caught the fix for it. Body questions taken from the *top* of a body are
title questions wearing another hat: memories are written lead-sentence first
and that sentence restates the title. Measured on a real store, the same vector:

| | shipped | title-tuned |
|---|---|---|
| bodies, from the top | 0.9557 | 0.9673 (+0.012) |
| bodies, past the lead | **0.9778** | 0.9718 (−0.006) |
| bodies, past the lead, held out | **0.9708** | 0.9659 (−0.005) |

The first row says change the weights. The other two say the shipped vector is
the Pareto point, which is what the earlier sweep concluded. `BODY_SKIP` steps
past the lead for that reason; a harness without it produces the first row and
sounds convincing.

### What it cannot tell you

Whether recall surfaces the memory somebody *actually wanted*. Self-retrieval
measures the index, not the judgement — a question nobody asked, answered by the
memory it was copied from. The ranking gap it does show is real and bounded:
title-shaped questions sit lower than body-shaped ones, and no reweighting has
closed it, because the same idea in different words is a semantic problem rather
than a lexical one.

### It cannot compare ways of choosing query words

A prompt longer than twelve words is cut to its first twelve, so nearly half of
real prompts are searched by their opening — the courtesy — and not by what
they ask. Choosing the twelve *rarest* words instead measures better here, and
keeps measuring better with the recall gate applied:

| | speaks | right when it speaks | hits overall |
|---|---|---|---|
| first twelve (shipped) | 83.3% | 79.2% | 66.0% |
| twelve rarest | 84.0% | 82.5% | 69.3% |

Do not believe it. Every question this harness asks is copied out of the memory
it expects back, so the rare words in that question are by construction the
words that identify that memory and no other. Ranking by rarity is then close
to sorting by "how nearly is this an id" — the instrument rewards the variable
under test, whatever the gate does afterwards.

The shipped choice was made against a hundred and twenty hand-labelled
prompt-to-memory pairs, where rarest-six raised top-three hits from 28% to 34%
and *lost* on precision, 20% against 23%. That is the right instrument for this
question and this is not it. Settling it needs questions somebody actually
asked, which is why `mem_save` now records the prompt a memory answers.

## `engram-bench` — a floor under search quality, and the same data on both engines

The corpus is 170 synthetic memories in two projects and 117 queries of seven
kinds — paraphrase, short, Spanish, partial word, typo, several words, a long
natural-language question — each with the one memory it should find. Two things
use it.

`ratchet.py` needs nothing but Leteo and stock `python3`. It saves the corpus
into a fresh store in a temporary directory through `mem_save`, runs every query
through `mem_search` at limit 20, and compares mean reciprocal rank per kind and
overall, and the bytes of twenty-result searches and of `mem_context`,
against `floors.json`. CI runs it as the `search-quality` job.

```bash
cargo build --release
LETEO_BIN=target/release/leteo python3 tools/engram-bench/ratchet.py
```

`LETEO_BIN` has no default here, because `leteo` on `PATH` is usually an
installed release and not the build under test.

It exits 1 and names every breach with its measured value and its floor. It
exits 2 if it could not run at all — a missing binary, a tool error, a save that
did not insert, fewer queries evaluated than the corpus defines — because a
suite that can pass having executed nothing guards nothing. Time is printed and
not gated: it does not transfer between SQLite builds, ranking does.

`floors.json` is the only place the numbers live. Floors are the measured MRR
rounded down to three decimals; ceilings are the measured bytes rounded up to
the next hundred, and the one ceiling on empty answers is the measured count,
which can only fall. Since the semantic stage the kinds it can help — `spanish`,
`paraphrase`, `multiword` — are measured with it on. When a run prints `RAISE?` a kind is two points or more above
its floor. To raise floors after an improvement, or to move them on purpose,
run `python3 tools/engram-bench/ratchet.py --propose`, which prints a
replacement file under those two rules, and commit it with the change that
moved the numbers. A floor is never lowered to make a red run green without a
sentence in the commit saying what was given up and why.

A guard is checked by breaking what it protects. Disabling a relaxed search
stage failed the ratchet on the kinds that depend on it, and raising
`PREVIEW_BYTES` failed it on the byte ceilings; both were put back and the diff
of the file came back empty.

`--propose` also prints the empty-answer ceiling. A run prints how many questions
each kind came back empty for, beside its MRR: a question answered wrongly and a
question not answered both score zero, and an agent is told different things by the
two.

The second use is the comparison with Engram, on identical data: the corpus is
saved into a fresh Engram store through Engram's own CLI, a copy of that store
is adopted with `leteo import --from-engram`, and both engines are asked the
same queries through their own MCP `mem_search`. Ids survive adoption, so one
answer key serves both.

One command runs the load and both benchmarks and rewrites the comparison page
from what it measured:

```bash
cargo build --release
LETEO_BIN=target/release/leteo python3 tools/engram-bench/compare.py
```

It regenerates [`docs/comparison-with-engram.md`](../docs/comparison-with-engram.md),
which carries the measured Engram version, the Leteo commit and the per-kind
numbers. The numbers live there rather than here, where they were dated prose
and drifted; the individual scripts (`load_engram.py`, `load_leteo.sh`,
`bench_search.py`, `bench_any.py`, `bench_cost.py`) still run on their own, and
`compare.py` skips a step it cannot run and says so.

`bench_cost.py` needs an Engram source checkout because Engram's
session-start hook is a shell script in its tree, not part of its binary.
`bench_any.py` reruns Engram with its opt-in `match_mode: "any"`, which agents
only get if they ask for it.

Two limits to keep in view before quoting any of it. The corpus and queries are
synthetic and were written knowing how both engines search, so paraphrases
deliberately avoid the memories' words — exactly where Leteo's relaxed stages
help; questions real agents asked would be the stronger test. And precision is
barely measured: there is no set of queries that should find nothing.

## `semantic` — where the shipped model comes from, and whether it earns its keep

`tools/semantic/` rebuilds the embedding model under `assets/model/` from the model
it is derived from (`build_model.py`, with `fetch_corpus.py` for the text the
vocabulary is pruned against), checks the result against `checksums.json`, and
carries the two things that keep the stage honest:

```bash
# The model is a file the binary loads, so the ones that exercise the stage say where.
export LETEO_MODEL_DIR=assets/model
python3 tools/semantic/hardset/evaluate.py target/release/leteo
python3 tools/semantic/hardset/check_sets.py
python3 tools/semantic/check_binary_size.py target/release/leteo
cargo run --release --manifest-path tools/retrieval/Cargo.toml -- copy.db --pipeline
```

- **`hardset/evaluate.py`** asks 2,028 questions that do not use their target's words,
  once with the `semantic_search` setting off and once with it on, through one binary,
  and reports the paired difference with a bootstrap 95% interval. It fails when the
  whole set's interval does not exclude zero, or any kind falls by more than 0.02. The
  questions are LLM-generated; `hardset/README.md` says by what and how they were
  checked. The `search-quality` CI job runs it.
- **`check_binary_size.py`** fails above its byte budget (the binary is about 21 MB on Linux, and the model is a file beside it). Prove it by lowering the
  constant under the binary's size, running it, and restoring the file.
- **`check_install.sh`** builds an archive laid out as `release.yml` packs one, installs it
  with `scripts/install.sh` over `file://` into temporary directories, asks the installed
  binary's `doctor` whether the model is verified, and removes Leteo three ways
  (`leteo uninstall --yes`, `uninstall.sh` with and without the binary), failing if any
  model file or directory is left or `share/` is taken. It then runs the npm wrapper against the
  same archive over a local HTTPS endpoint: a cold install, a cache whose binary was deleted, and
  two runs at once of each. Every command runs under `env -i`, so no variable of the caller's
  (`LETEO_DATABASE` included) reaches the binary. It needs `node`, `openssl` and `python3`.
  The `search-quality` CI job runs it. Prove it by pointing `install.sh` at a different model
  directory and running it, or by taking the heal out of `npm/bin/leteo.js`.
- **`retrieval --pipeline`** asks the whole search over a *copy* of a store, with and
  without the stage. It cannot show the stage helping — those questions are built from
  their targets' words — only that it does no harm where it has nothing to do.

See [`semantic/README.md`](semantic/README.md).
