# I measured whether my memory tool saves tokens, and it buys something else instead

When I put this project in front of people, I ended the post with the one thing I could not test on my own: *does the recall help, or does it just add noise to your context?* Nobody answered it, and neither did I. This is the answer, and it is not the one I was hoping to write.

The short version: **on questions the code already answers, the saving is not distinguishable from noise. On questions the code cannot answer, the agent without memory spends more and still answers something else, confidently.** What you buy is not tokens — the token figures are too noisy to sell. It is not being wrong.

## The setup

Somebody replying to that post gave me the protocol, and it was better than mine. *Same repo, same task, run it twice, memory on and memory off. Don't score the answers, they're too easy to read charitably. Count operations instead.*

So: two question archetypes, two arms, three repetitions each — four in one cell, for a reason I explain below. **Thirteen runs in total.** Both arms run the same read-only agent, with the same tool grant and the same shell — so both pay the same fixed cost, including the tool schemas below. What differs is that one arm was given the command that queries the store and told to use it, and the other was told not to.

- **B1** — a question the repository answers: *was ranking by literal, unstemmed match ever tried on its own, what was measured, and why was that route not taken?* The answer is in a doc comment in `src/store/search.rs`.
- **B2** — a question only the store answers: *what measurement mistake once made the search look four times worse than it is?* The answer is in one memory and nowhere in the tree.

Correctness was graded by hand against ground truth written down **before** anything ran. That turned out to matter more than I expected, and I come back to it.

## The runs

Tokens per run, and whether the answer was right.

**B1 — the repository has the answer**

```
                     runs                          median    correct
  no memory     31,701 · 37,537 · 47,802           37,537      3/3
  with memory   22,892 · 32,409 · 82,920           32,409      3/3
```

**B2 — only the store has the answer**

```
                     runs                                    median    correct
  no memory     27,394 · 85,950 · 98,733                     85,950      0/3
  with memory   29,996* · 55,189 · 71,037 · 100,417          63,113      4/4

  * off-protocol: its prompt asked for one field the others did not
```

## Three numbers, one dataset

Here is the part I want to be blunt about, because it is the whole reason this document exists.

```
  best with memory vs worst without      -70%*  (B2)     -52%   (B1)
  median vs median                       -27%*  (B2)     -14%   (B1)
  worst with memory vs best without      costs 3.7x as much  (B2)

  * depends on the off-protocol run; without it, -44% and -17%
```

All three come out of the runs above. I can write "saves 70%", "saves 14%" or "costs three times as much" and every one of them is true of some pair. The spread inside a single cell reaches 3.6x — as wide as the widest gap between the arms, which is the 3.7x on the line above it. **On B1 the median difference is 14% and I would not defend it: it is smaller than the noise it sits in.**

The 70% is real and it has a cause worth naming, which is why I am keeping it rather than hiding it: that run made **one** query, opened **zero** files, and finished in seventeen seconds, because the first search it tried landed on the right memory. That is the tool working exactly as designed. What varies between runs is not whether memory helps — it is whether the agent's first query is well aimed. When it is, one call is enough. When it is not, the agent chains up to nine and the saving evaporates.

That run used a prompt marginally different from the other three in its cell — it asked for one extra field — so it is off-protocol and I say so wherever its numbers appear. I counted it as a fourth repetition and I counted it **at both ends**: with it, the B2 best case is 70% and the median is 27%. **Without it, on the strict protocol, the best case is 44% and the median is 17%.** Both pairs are in this document; the strict pair is the conservative one and a reader who trusts only it loses nothing I would argue with.

## What actually separates the arms

Not the tokens. The correctness.

On B2, the arm without memory went **0 for 3** — and all three declared themselves satisfied. Each one found a real, documented mistake that was not the one being asked about: a tokenizer that treated `ª` and `º` as separators, a hand-copied SQL statement that drifted from the product's, a warning about comparing two experiments. Three plausible neighbours, three confident wrong answers.

**The cheapest of the seven runs in B2 — 27,394 tokens, no memory — is one of the wrong ones.** It was cheap *because* it stopped early at something that looked right. (The cheapest run of the whole thirteen is 22,892, in B1, and it *had* memory and was right — which is the opposite lesson and belongs on the same page.) The honest form of the warning is narrower than I first wrote it: **on a question the code cannot answer, measuring tokens alone rewards the arm that gets it wrong fastest.**

## What it costs to have it at all

A session pays this before anyone asks anything, and some of it again every time the context is compacted. Everything here is what the model is sent, measured by running the shipped hooks and the MCP server over a copy of a store and counting the text they return, with tiktoken's `cl100k_base` as a proxy for the model's tokenizer. It is a proxy: the real count differs, and what it is good for is setting two engines side by side under the same ruler.

Conditions, because the figures are meaningless without them: **2026-10-13**, Leteo 0.3.0 at the head of this branch (`394d997`) and Engram 3.4.0, each over a copy of the same 1,048-memory store (1,017 of them in the project the session runs in), `--tools=agent` for both servers, a 20-prompt session, and a fixed mix of one `mem_context`, six `mem_search` and three `mem_save` calls. The prompts, queries and saves came from the project the store was copied from, so they are not published; the committed ones are synthetic and give different absolute numbers.

```
                                   Leteo    Engram     Leteo vs Engram
  session start                    1,586     1,300     +22.0%
  per-prompt hook, 20 prompts      1,410       421     +234.9%   (Leteo spoke on 17 prompts, Engram on 1)
  post-compaction                  1,266     1,629     -22.3%
  mem_context                      2,670     2,594     +2.9%
  mem_save (median of 5)             299       395     -24.3%
  mem_search (mean of 20)            726       909     -20.1%
  tools/list (input schemas)       5,195     5,028     +3.3%     (20 tools against 19)
  server instructions                411       412     -0.2%
                                  ------    ------
  one session, schemas upfront    17,791    18,023     -1.3%
  one session, schemas deferred   12,185    12,583     -3.2%
```

*Upfront* pays every tool's schema in every session. *Deferred* is for a client that loads schemas only when a tool is first used, so they cost nothing until then; it is the same sum without the `tools/list` and `server instructions` lines. Engram's per-prompt figure is one 387-token reminder on the first prompt plus 34 for the save nudge it fires once in a session, which the harness triggers by ageing the session in the copy.

The same session that morning, before the changes between then and this page, was 22,565 upfront and 16,959 deferred for Leteo (at `78bc173`) against 17,734 and 12,294 for Engram, a gap of +27% and +38%. Engram's own figure moved by 1.6% between the two runs with no Engram change, mostly in `mem_context`; I did not isolate why, and it is the size of the difference to treat as noise when reading the rest.

**The per-prompt hook is the row where Leteo is worst, and it is not fixed.** On this store it speaks on 17 of 20 prompts, including "continue", "yes, go with that" and "looks good, commit it", each time with three memories chosen on the words of the prompt. Against a hand-labelled sample of 150 prompts over a real store the hint is now silent on 54 of the 90 that need nothing, where it was silent on 21 before the single relevance bar, and it names a right memory on 20 of the 60 that have one, where it named 21. On the imported copy used here that bar buys nothing yet: it is silent on 2 of 10 neutral prompts, before and after.

### The tool list, corrected

An earlier version of this page put the `tools/list` array at 19 tools, 47,781 bytes and about 12,000 tokens, and called it 78% of the fixed cost. Two things were wrong. The count: the agent profile has **20** tools (the default profile has 23). And the measure: the array holds more than the model is sent. A client shows the model each tool's name, description and input schema. The **output schema** of each tool is in the array too, and the model is not sent it. Counted properly:

```
  tools/list, as the server sends it        65,621 B   (20 tools)
    of which outputSchema                   40,617 B   not model-visible
    name + description + inputSchema        21,801 B   5,195 tokens
      of which descriptions                  3,564 B
      of which input schemas                16,971 B
```

The 47.8 KB figure was mostly output schemas, which is why it was far too large to be the cost of the tools. Engram publishes no output schemas, and that is the whole of the difference between the two engines' `tools/list` bytes; in the tokens the model reads they are within 3% of each other. This count takes the name, description and input schema as the model-visible part and leaves out `annotations`; that is an assumption about the client, and the one to check first if the totals look off.

Each input schema starts with the JSON-Schema dialect declaration, 57 bytes times 20 tools, 1,140 bytes: the only pure ceremony in it. The rest is mine, the descriptions I wrote and the shape of my own tools. With the output schemas out, the tool list is 29% of a session's upfront total, not 78%, and under a client that defers schemas it is none of it.

What I take from this is narrower than what I wrote before. The cost I had been trimming, the memory block, is 1,586 tokens at the start and 1,266 after each compaction, and the tool list next to it is about three times that on an upfront client. Neither is the largest line. The replies to the tools in that mix are 7,923 tokens, 44% of the session upfront and 65% deferred, and they grow with use.

### Re-running it

```bash
cargo build --release
python3 tools/memory-bench/session_cost.py \
    --leteo-bin target/release/leteo --leteo-store copy-of-leteo.db \
    --engram-bin "$(command -v engram)" --engram-store copy-of-engram.db \
    --engram-plugin-root path/to/engram/plugin/claude-code \
    --project the-project --workdir /tmp
```

Run it with a Python that has `tiktoken` for the figures above; without it the output says `~tokens (bytes/4)` and must not be compared with them. The stores are copied with SQLite's backup API into a temporary directory and each engine runs there with its own `HOME`, data directory and port, so neither the originals nor a store in use are written. `--prompts`, `--queries` and `--saves` take your own inputs. To replay the per-prompt hook over a labelled sample instead, add `--labels labels.tsv`; the committed `session_cost_data/labels.example.tsv` shows the columns and is run against `--build-fixture`'s synthetic store. `tools/memory-bench/bench_cost.py` prints the same hook costs beside its byte counts.

## Why the saving is small here, and where it would not be

I sampled twelve of the fifty memories the block delivers and asked, one agent per memory, whether the repository could recover it — source, comments, tests, README, **and the full git history**.

```
  FULL       7 of 12      the substance is recoverable
  PARTIAL    4 of 12      the outcome is there, the road to it is not
  NONE       1 of 12      the code contradicts it outright
```

One of those FULLs is circular — I wrote that memory the same day by reading the code — so the figure I would quote is **6 of 11**.

The pattern in the PARTIALs is the same every time: **the repository keeps the result and the store keeps the road.** What was tried and rejected does not get committed. The clearest case was a memory recording that I had proposed a set of guards, been told they were unwanted, and reverted them: the guard that survived is in the tree since the first commit, and the proposal, the refusal and the reversal appear nowhere — not in the log, not in dangling commits, not in the reflog. What you said no to exists in one place only.

That is also why the number here is a floor rather than an average. This repository is 22.8% comments, keeps its specs current, and writes its reasons into commit messages. The store is competing against an author who already writes down what it would have remembered. In a codebase that does not do that, the FULL share drops and the memory wins more — **but I have not measured that, so I am not claiming it.**

## The liability I was not looking for

Recoverability and staleness are different axes, and the second one is worse. Only one of the twelve is contradicted so thoroughly that the repository is a better source than the memory — that is the NONE above. But **two** of the twelve assert something the code contradicts *today*, and both ride in the block that opens every session; the second is recoverable enough to grade PARTIAL and wrong anyway.

One says a partial index was reverted as useless, that it belonged on an expression rather than a raw column, and that the raw column would not work. The migration says the opposite in all three respects, in a comment that ends *"only this one is used by the statement the code prepares"*. The other names a Windows configuration path that the code records as a bug already fixed.

Three of the twelve also cite commit hashes that resolve to nothing.

None of that is caught by anything. Review windows are a calendar, and the calendar was never what made these wrong — the world moved underneath them. Contradiction judging only fires when another *memory* disagrees, and here the thing that disagrees is the code. The cheap half of the fix is obvious in hindsight and does not exist yet: check that the paths, constants and commit hashes a memory cites still resolve. On this sample that alone would have raised its hand four times out of twelve — three dead hashes and one stale path.

## Where this is weak

**n = 3**, thirteen runs, two question archetypes, one repository, one model. This is a direction, not a magnitude, and the variance is large enough that I would not defend any single percentage as *the* number.

**"The repository has the answer" is a proxy** for what a real working day looks like, and I do not know the real mix. That mix is what decides whether this pays for itself, and it is the one thing I have not measured.

**The grader was me.** I wrote the ground truth before running, which is the part that matters, but I also built the questions, and one of them turned out to be answerable from the code when I had predicted it would not be. I found that by running it rather than by thinking about it, which is the argument for running things.

## What I am doing about it

Publishing this, and not adjusting the number. What I will say out loud is **four right answers out of four where the same agent without memory got none out of three** — three out of three against none out of three if you drop the off-protocol run, which is the same answer in a smaller sample. That is the finding that survives the variance. Beside it, and only beside it: up to 70% fewer tokens when the first search lands, 27% median on B2, 44% and 17% if you keep only the strict protocol, and *costs 3.7x as much* if you pick the opposite pair from the same thirteen runs.

If a memory tool tells you it saves you half your tokens and does not show you its runs, its baseline and its error bars, that number came from choosing a pair. Mine did too. The difference is that this page shows you which pair.

---

*The tool is [Leteo](https://github.com/asanabrial/leteo) — MIT, `cargo install leteo`. Everything above was measured against a copy of a real store of 4,756 memories across 27 projects; the real one was never opened. The companion write-up is [*there was nothing worth tuning*](nothing-worth-tuning.md), about the retrieval floor that produces the searches counted here.*
