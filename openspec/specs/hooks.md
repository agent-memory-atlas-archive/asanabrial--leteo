# Hooks

## Purpose

The unattended surface. An agent runs `leteo hook <event>` at points in its own
lifecycle and Leteo answers on stdout — with the opening context, with a nudge,
or with nothing. Nobody is watching, and the agent kills the process on a
deadline, so every promise here is a promise about time as much as content.

## Behaviour

1. **Five events.** `session-start`, `post-compaction`, `user-prompt-submit`,
   `subagent-stop`, `session-stop`. The five names exist once, in the parser
   that reads them, and the installer writes what the parser accepts — they were
   spelled out in three places before, none of them bound to the one that
   decides. An agent may subscribe to fewer of them than exist: ZCode takes
   three because its client has no `SubagentStop` and no `SessionEnd`
   ([`cli.md`](cli.md) §5), and the subscriptions are pointed at this list,
   never restated beside an agent.

2. **Leteo gives up before its agent does.** Each event knows how long its agent
   waits — 10 s for `session-start`, `post-compaction` and `subagent-stop`, 5 s
   for `user-prompt-submit`, 3 s for `session-stop`, which Codex clamps — and
   waits for a locked store for nine tenths of what is left after a flat second
   of that. A killed hook tells nobody anything; one that answers carries a
   warning saying what it could not do.

   `session-start` also asks whether this directory's sessions were recorded
   under a project other than the one it now resolves to — the drift the write
   path's silent pick refuses on, asked where nobody is there to answer a
   prompt. When one
   differs it pushes a warning naming both and `leteo projects consolidate`,
   and it asks after `migrate_directory_project`, so the one drift already
   folded on its own — a repository that took its directory's name — is not
   warned about as a split it has just repaired. The lookup is one scan of
   `sessions` with the directory folded in Rust, paid once at session start
   rather than on every prompt. Measured through this crate in a release build
   against a temporary store: 500 sessions, a real store held 483, cost
   **235 µs**, and 5,000 cost **2.24 ms**, against this event's ten-second
   patience. The write path's half of the same fact is
   [`mcp-tools.md`](mcp-tools.md) §5.

3. **The payload is read before the store is opened, and a hook answers even
   when the store cannot be opened.** The store is opened on the way into the
   hook path, and an open that fails prints `{}` and exits 0 rather than
   blocking the agent. Reading the payload first is what lets a `subagent-stop`
   whose open fails busy still keep its capture (§22), and it means a malformed
   payload warns without touching the store. The promise that a hook never
   blocks was once written in `hooks` and broken in `cli`, which opened the
   database before the payload and exited 1 on the open error.

4. **`session-start` returns the opening context.** Recent sessions with their
   last activity, recent prompts, and the memories most worth having in front of
   you, sized by the configured context size (`slim`, `full`, `deep`) — the
   same size every other surface that opens a context uses, which `leteo
   context` did not ([`cli.md`](cli.md) §13). The block is bounded in bytes as
   well as in entries: the size's budget from `ContextSize::bytes()` is applied
   at an entry boundary, and the block says how many memories, prompts and
   sessions it left out ([`mcp-tools.md`](mcp-tools.md) §3). A project
   with nothing in it returns one line saying so — and only when some other
   project holds something, because a store that is genuinely empty has nothing
   to explain. It is the same sentence the two tools use
   ([`mcp-tools.md`](mcp-tools.md) §7), asked at the earliest moment: an empty
   block is the first thing an agent learns about the store, and a directory
   that resolved somewhere quiet reads exactly like a fresh install.

5. **A line is cut at a bound somebody measured.** Every budget in the block is
   named and argued: a title past the p99 of a real store's titles, a session
   line past the p99 of its summaries, a prompt line deliberately below both
   because a prompt is whatever somebody typed and people paste. The session
   line was the same literal as the prompt line, three times over, and 200 sits
   just above the *median* of a summary — so 37% of the lines whose whole job is
   to say what a session was for lost their end.

   And one summary per session, chosen where the choosing is cheap. "A session
   has at most one summary" is what the lookup assumed, and clients disagree: an
   agent that reuses a session id writes one every time it finishes something,
   so a real store holds 71 under one id, 39 under another, 37 under a third —
   101 session ids with more than one, each summary genuinely different text
   rather than the same one saved twice. The fold takes the newest and drops the
   rest, so the rest were read for nothing, with their bodies, which is most of
   what a summary is: the recent sessions of one project brought back 19
   summaries and 58.8 KB to render two lines worth 6.3 KB. Choosing in SQL makes
   that 2 rows and 5.5 KB, at every session opening and on every `mem_context`.

6. **One question is listed once.** The recent-prompts section deduplicates
   twice, because one comparison cannot see both shapes: by the text exactly,
   which catches a question genuinely retyped, and by
   `normalize::prompt_core` — leading slash command dropped, whitespace
   collapsed, case ignored — which catches the same question with `/loop` or
   `$task-board` in front of it. `mem_context` reads the same list. The second
   pass costs 0.2 ms.

7. **A session is dated by its last activity, not its start.** A session can stay
   open for a week; ordering the list by `started_at` buries the one being
   worked in right now.

8. **The save reminder is about this conversation, not about the calendar.**
   It fires when the session has gone a while without keeping anything, counted
   from whichever came later — the last thing saved, or the moment the session
   began. Counting from the project's last memory alone said something true and
   useless: opening a project untouched for a week and typing one sentence
   announced 7,504 minutes, which is five days in which nothing had yet
   happened. The span is said in the largest unit that still reads as one —
   minutes, then hours, then days — in every language.

9. **`user-prompt-submit` nudges, and never twice.** The prompt is matched
   against the store and any memory worth naming is named — but a memory already
   shown in this session is not shown again. The set of what has been shown is
   session state on disk, capped, read once and written once per event.

   The list is capped, because it is written on every prompt — and the cap has
   to cover a whole conversation or the promise stops holding. It was 128,
   sized against sessions of 45 prompts, which was the longest the store held
   when it was written; that store now holds one of 351, so the oldest ids fell
   off and the hint could offer them again in the same conversation. It is
   derived now rather than chosen: at most `RECALL_LIMIT` new memories a prompt
   across the longest conversation measured, which is 1,200 ids, a 7.2 KB file
   and 0.07 ms to read and write against the 13 ms the hook costs end to end.

   What was measured is written down beside what was chosen, and the guard
   holds the second to the first. Without that the sizing can be lowered back
   to what it was with every test still green, because the fixture is derived
   from the same number — the blind spot the capture ceiling found, one level
   up.

   "Worth naming" is a bar relative to the other candidates *this query* found,
   not a promise about how often the hint speaks. The margins were chosen at a
   measured 80.9%, explicitly declining a looser pair that spoke nine times in
   ten; re-measured on the same store 4,013 memories later the chosen pair
   speaks 92% of the time. It is a ranking rule and it drifts with what the
   store holds. Re-tuning it needs a relevance label that works on today's
   filing — see the note in `Store::prompt_matches`, which says why the old one
   does not.

10. **`subagent-stop` keeps what a subagent learned, in any language Leteo
   speaks.** The skill asks a subagent to end with `## Key Learnings:` and the
   opening context tells the agent which language to write memories in, so one
   working in Portuguese ends with `## Aprendizados-chave` — the instruction
   followed rather than ignored. Only English and Spanish were recognised, and
   a miss is not a poorer capture: the subagent finishes, its context is
   discarded, and what it found is gone. The headings are a table keyed by
   language code, walked against the thirteen so a fourteenth cannot be added
   without one, and the accents are optional in the match because a heading
   loses them before a heading loses its words. `mem_capture_passive` says the
   same: a description that named two of the thirteen told an agent not to send
   the other eleven, which is the same silence one layer up.

11. **`post-compaction` clears what was shown.** Compaction is exactly the moment
   the agent forgot; continuing to suppress those memories would suppress them
   from a context that no longer holds them.

12. **A hook writes nothing an agent reads without folding it to one line.** See
   [`mcp-tools.md`](mcp-tools.md), Invariants.

   And no fold ever splits a character. Every bound this crate publishes is a
   place a slice could land inside a `ñ` or an emoji, which in Rust is a panic
   rather than a mojibake — in a process an agent is talking to, over a store
   that is mostly Spanish. Driven at every position rather than beside each
   bound, because these functions subtract their own marker before they cut and
   a sweep around the nominal number misses the real one.

13. **A session opening hands the agent its waiting verdicts, and tells the
   person only what is theirs.** Both are said at a session opening and nowhere
   else, because at every prompt they would nag.

   Memories due for a reread are the person's: the greeting counts them and
   `mem_review` hands them over. Waiting verdicts are not. The opening block
   carries the five oldest pairs to the *agent*, each with its `judgment_id`
   and, for both memories, the id, the category and the topic key — under a
   heading that says to rule on them now — and the greeting says nothing about
   them at all.

   It said so once, in twelve languages, and the sentence was removed. Judging a
   pair is Leteo's own bookkeeping; the agent settles it in the opening turn
   without asking anybody, so a count in the greeting described work already
   being done for the reader, in a line they could not act on and were never
   meant to.

   Counting alone was half a fix in the other direction too. `mem_judge` takes a
   `judgment_id` that only `mem_save` ever returned, so an agent told "1 pair
   waiting" had no way to reach that pair without leaving the session for
   `leteo conflicts list` — a number to act on and nothing to act with. The pairs come oldest first, and
   that ordering is what makes the queue drain rather than churn: a pair not
   ruled on today is nearer the front tomorrow, so none can starve behind newer
   ones. That is how the oldest on a real store reached eight weeks.

   The block states what it expects: all six verdicts settled by the agent, none
   put to the user, and the section itself never mentioned in a reply — the same
   rule as [`mcp-tools.md`](mcp-tools.md) §7, restated where the pairs are
   because an agent reaching one through this block may never have read the
   other route. It carries the category and the topic key rather than the bodies,
   which is what keeps it affordable to send unasked: two 300-character previews
   cost about four times the rest of a pair's entry, and a topic key decides most
   pairs on its own — two memories under one key are revisions of each other, two
   under different keys rarely conflict. `mem_get_observation` is one call away
   for the rest. Measured on a real store, a pair costs 281 bytes where it cost
   about 1,050 with previews, and the whole block is 2,190 of a 12,719-byte
   opening at five pairs.

   How many are handed over follows from that measurement rather than from
   taste. The 782-byte header is paid once per session that has a queue at all,
   so a smaller batch does not spend less — it spends the same header more
   times. Draining seventy pairs costs fourteen headers at five a session and
   twenty-four at three, 10.9 KB against 18.8. Five is the number, and the
   ceiling on it is shape rather than cost: past a handful an opening reads as a
   worklist, and an agent that skims one judges nothing.

   **Only pairs `mem_judge` will accept are offered, and the rest are named in
   one sentence.** `judge_relation` refuses two shapes: a memory absent from the
   table, and two ends carrying different projects. Those can never be settled,
   and offered in a queue ordered by age one of them takes the head and keeps
   it — so they are filtered out of the work and counted separately, with the
   command that inspects them. Folding them into the "more waiting" number would
   leave a count that never reaches zero however diligent anybody is.

   A **soft**-deleted memory is not one of those, and the first version of this
   said it was. The row survives a soft delete, so the guard finds the memory
   and the verdict records; the pair is handed over with that side marked
   `(deleted since this pair was proposed)`, because `not_conflict` closes it in
   one call. Told it could not be ruled on, an agent parked forever a pair that
   one call clears — and the test asserting the claim made it permanent. Both
   shapes are now decided by asking the store, not by reading the guard.

   When the only pending pairs are ones nothing can settle, the block still
   appears and says so under a heading that promises no work. Silence there
   would be the disease this block was written for: seventy pairs and no surface
   that named them.

   The handover is not governed by the voice setting. Silencing Sardi silences
   what Sardi says about itself; the block is protocol handed to a model, and a
   quiet Leteo still has to be a correct one.

   The review queue had no reader at all. A decision, a policy or a preference
   is saved with a date to look at it again, migration 15 rewrote every one of
   those dates, and migration 14 built a partial index for the exact query that
   finds them: on a real store 269 memories carry a date and the first falls due
   in 34 days, at which point nothing would have said so. `mem_review` reads the
   queue, the skill listed that tool without ever saying when to reach for it,
   and the command line has no equivalent. A window nothing opens is the defect
   `policy` had when its own window could never fire.

   The count costs four microseconds and shares its `WHERE` with the list, so
   the number said and the queue handed over cannot come to mean different
   things.

14. **A hook that loses to another writer keeps a `subagent-stop` capture
   instead of only warning.** A failure inside a hook is otherwise a warning: on
   stderr, in the outcome, where `--verbose` shows it. The agent gets `{}`. That
   is right almost everywhere — a prompt that was not recorded or a session that
   was not closed is nothing the agent can put back, and a workflow finishing
   dozens of subagents cannot afford a line each.

   `subagent-stop` is the exception, for the reason §10 already gives: the
   learnings live in the text this hook was handed and nowhere else, because the
   subagent finishes and its context is discarded. Since #202 a busy store does
   not lose them: the capture is written to the spool beside the database (§22)
   and a later open replays it, so the line the agent reads says it was kept for
   later and asks for nothing. The spool write happens only when the store error
   is `is_busy()` — every other refusal would fail again on replay, and that
   line names its cause instead of sending the identical write to fail a second
   time. A capture that stopped part way has already committed the learnings
   before the one that failed, so the line says what was kept rather than
   claiming the whole text is gone. Timed under a genuinely held write lock,
   this event spends 8.93 s of its agent's 10, so the spooling is the last thing
   that happens before it answers.

15. **A snippet inside a learnings section is neither a boundary nor a
   learning.** The section `subagent-stop` reads ends at the next line opening
   with hashes and a space, and that is exactly how a shell comment is written.
   A subagent that followed §10's instruction and put a code block between its
   second and third learning had the section cut at the comment: three numbered
   items were captured as one, and the hook reported one kept, which reads as
   having worked. The other way round, a numbered line *inside* a block was
   captured, so `1. export the variable first` was filed as something a
   subagent had learned rather than as the command it is.

   Fenced blocks are blanked before the section is found or read, which fixes
   both. `mem_session_summary` takes its title by the same kind of scan and had
   the same hole one level over — a summary opening with a snippet titled
   `cargo test --all --release`, a title weighted 5.0 in the ranking and saying
   nothing about the session. Not one of the 900 summaries in a real store is
   titled differently by the fix; it is there because the shape is one line
   away from the defect above, not because anything was found broken.

16. **A payload that parsed and carried nothing says so.** Every field of the
   hook payload defaults and unknown ones are ignored, which is deliberate: a
   client adds a field to its own schema and a hook that refused it would stop
   working for a change that was none of its business. What that costs is that
   a payload whose fields are *named* differently — the same JSON in camelCase,
   or a schema that moved — parses perfectly into an empty input, and every
   hook then reports success having done nothing: a session invented under
   `manual-save-<project>`, the prompt never saved, and not a word anywhere.

   That is the shape a `serde` alias once gave Codex's ordinary payload, and
   the warning written afterwards catches a body that is not JSON, which is the
   half that announces itself. The other half is now named too, by a test that
   needs no list of field names to keep in step: the body was an object with
   something in it, and what came out is indistinguishable from an empty
   payload. An empty payload is not that and stays quiet — every event is
   driven that way by clients carrying no fields for it — and a payload that
   Leteo reads plus fields it does not is read, not complained about.

   The warning names the four fields to check against. It also spent its whole
   life with fourteen spaces in the middle of that sentence, which is the
   general rule below.

17. **A sentence never carries the indentation of the source it was written
   in.** A backslash at the end of a Rust source line eats the line break *and*
   every space after it; without one, both stay in the string. So a sentence
   broken across two source lines to fit the width reaches whoever reads it with
   a hole in it. The tool descriptions have had a guard since three of them
   shipped that way; it is now checked over every string in the tree, in both
   forms, on files with either line ending.

   Two lines a person reads were wrong: the warning above, and the Polish line
   that says how many memories are due for a reread. The exemptions are stated
   rather than assumed — `src/i18n` holds the wizard's key legends, where the
   runs of spaces are the columns, and SQL and markdown fixtures are laid out
   the way they are read.

18. **One subagent's turn may leave eighty learnings behind, and is told what
   did not fit.** There was no bound. Every item of a numbered list became a
   memory - one row and three full-text triggers each - inside a hook the agent
   kills after ten seconds. Measured against a copy of a real store of 4,121
   memories: ten items 121 ms, a hundred 261, five hundred 867, two thousand
   4,226. Somewhere past four and a half thousand the hook is killed part way
   through, having written some unknown number of them; each insert is its own
   transaction, so there is nothing to roll back and nothing anywhere that says
   what happened.

   Eighty, which is what `mem_context` opens with at its deepest. Past that a
   turn is not leaving learnings behind, it is filing a list, and the next
   session's whole opening would be one subagent's afternoon.

   The rest are counted, not swallowed: `observations_dropped` beside the
   extracted and duplicate counts, and a line telling the agent to save what
   matters with `mem_save` while it still has the text - the same reasoning as a
   capture the store refused, which is that the subagent's context is gone and
   the agent's is not.

   `mem_capture_passive` says it too. The ceiling went on the store underneath
   both doors and only the hook was taught to report it, so the tool answered
   `extracted: 500, saved: 80, duplicates: 0` - three numbers that do not add
   up, with four hundred and twenty memories gone and nothing said.

   Held by counting rather than by matching names: the two doors name the same
   facts differently - `saved` against `observations_captured` - and a table
   mapping one to the other would be the second copy this codebase keeps paying
   for. A count cannot say which number was forgotten, and cannot be satisfied
   by remembering to update it either: a fifth number added to the result fails
   both sides until both carry it.

   What holds the number is not a test that asserts it. A guard sizing its
   fixture from the ceiling - which it must, or it never reaches it - cannot see
   the ceiling change: raised to a hundred thousand, that test writes a hundred
   thousand memories and passes, in thirty-three minutes. The assertion that
   bites is the relationship the number exists for: what a capture may cost is
   what the event's deadline has left after `store_wait`, and at three
   milliseconds a learning eighty fits inside it with room. That one fails in
   microseconds and says why.

19. **The plugin bundles register what the installer writes, matcher
   included.** Leteo installs two ways — `leteo setup`, and the plugin bundles
   under `plugin/`, which for Codex is the only route to hooks at all — and the
   two have to arrive at the same events, on the same triggers, with the same
   deadlines.

   The list that decides is the *agent's*, not the global one:
   `AgentAdapter::hook_registrations`, which is also what the installer writes
   from. Held against `HOOK_EVENTS` instead, ZCode's honest three-event bundle
   would fail and a bundle carrying all five — two of them events its client
   cannot fire — would pass. A guard reads every bundle against its own agent's
   field.

   The matcher is part of that and was not always. Compared on event, subcommand
   and timeout alone, the field that carries meaning by itself went unwatched:
   `session-start` and `post-compaction` both sit on `SessionStart` and the
   matcher is the whole of what separates them. Widening the guard to hold it
   found the Codex bundle already drifted on two — `startup|resume|clear` where
   the installer writes `startup|clear`, so a resumed session was handed an
   opening block it already had, and a `.*` on `SubagentStop` that the installer
   leaves empty. Neither was written down anywhere as a decision, and no version
   of this test could see either.

20. **A client whose hook runner can be switched off costs the person their
   hooks, never their memory.** ZCode is the one such client today: its
   configuration hooks run only while `hooks.enabled` is true, which starts off
   ([`cli.md`](cli.md) §5). Setup turns it on. What matters is the person who
   deliberately turned it back off, and the answer differs by who is asking.

   `leteo setup zcode --hooks` refuses, because somebody typed the word `hooks`
   and writing registrations into a block the client will never read is a setup
   reporting success over files nothing opens. The wizard does not refuse: it
   asks the same question first, drops the hooks half, and installs the server
   and the instructions — the refusal lands before the server is written, so
   refusing there cost a ticked ZCode its memory entirely over a preference that
   was never about it. This is the shape already used for a plugin bundle that
   registers the hooks itself, and the same predicate answers both callers.

   `doctor` reports the state that check cannot prevent: hooks installed, runner
   switched off afterwards, nothing firing, and a file that still names every
   command. Read for the command alone, that reports healthy — the same way
   Codex's untrusted hooks did before they got their own line.

21. **The OpenCode plugin serves both majors from one file.** OpenCode 1.x loads
   a plugin's `server` factory; 2.x loads `setup`, binds hooks through per-domain
   registrations, and carries sessions on an event stream. The plugin at
   `plugin/opencode/leteo.ts` exports both over the same four handlers —
   `event`, `chat.message`, `tool.execute.after` and
   `experimental.chat.system.transform` — so a 2.x host is not left with a plugin
   that never loads and never says so. It spawns the binary through
   `node:child_process` rather than `Bun.spawn`, because 2.x runs plugins on Node
   where `Bun` is undefined. `plugin/opencode/leteo.test.ts` holds the plugin to
   each major's contract: the default export carries `server` and `setup`, the
   1.x factory binds its four hooks, the 2.x setup registers `session.context`
   and `tool.execute.after` and subscribes to events, and no code path calls
   `Bun`. Unlike the bundles in §19 this is not a `BUNDLES` entry — `leteo setup`
   writes OpenCode's MCP config and instructions but not its hooks
   (`hooks_path: None`) — so the plugin is the only route to lifecycle capture.
   Two guards hold it: its own contract test, which runs the entry points and the
   hook path, and a Rust guard that reads the file so `cargo test` watches the
   export too.

22. **A capture a busy store refused is kept beside the database and replayed
   by the next open.** One JSON file per capture, under
   `<database parent>/hooks/spool/` — the same `hooks/` the reminder state uses
   — written to a temporary name that ends `.tmp` and renamed into place, so a
   drain running at the same time never reads half a turn and never mistakes
   the in-flight temporary for an entry. The entry records the event, an ISO
   timestamp, the `PassiveCapture` fields and the session's directory; the
   content is passed through
   `normalize::strip_private` before it reaches the disk, so the `<private>`
   promise holds for a file that outlives the process that wrote it
   ([`project.md`](../project.md) §3).

   A drain claims an entry by renaming it to a `.claimed-<pid>` name, which is
   atomic, so two drainers take different entries rather than both replaying
   one. It replays oldest first, and before `Store::passive_capture` it ensures
   the session from the entry's own session id, project and directory — the
   busy-open path spools before `ensure_session` could run, so an entry can name
   a session no store ever created, and replaying it without that would fail
   `SessionNotFound` and delete the subagent's only copy. On success the entry
   goes, on the first busy error the drain stops and puts the entry back,
   and any other error counts the entry dropped and removes it — a retry cannot
   mend it, and keeping it would make `doctor` report a spool that can never
   drain. The drain is bounded by what is left of the caller's budget, so it
   cannot outlast the agent waiting for the answer. It runs at the end of every
   hook, at `leteo mcp` startup, and in `doctor --repair`.

   The spool holds at most `SPOOL_CAP` (1,000) entries and drops the oldest past
   that, and an entry older than `SPOOL_RETENTION_DAYS` (7) is dropped on the
   next spool write or drain without being replayed — a subagent's learnings
   belong to the conversation that produced them. Both numbers are one constant
   each, read by the behaviour and the tests, and named here so the limit that
   is published is the limit that is applied. `doctor` reports what is waiting
   as `hook_spool` ([`store-and-schema.md`](store-and-schema.md) §4), and
   `doctor --repair` drains it.

## Invariants

- Every event finishes inside its agent's patience even when the wait overruns.
  The margin is asserted against the worst overshoot measured on Windows (15%)
  plus the cost of starting and answering, not against the nominal wait — see
  [`store-and-schema.md`](store-and-schema.md) §8.
- No hook can panic. Fifteen `unwrap`/`expect` calls exist in production code
  and nine of them are regexes over constant patterns, where a mistype fails the
  build. The one that is built at run time — the learning headings a subagent is
   captured by — is fed a hostile table by a guard, because the thirteen headings
   there today are letters and spaces and prove nothing about the fourteenth.
- A hook that cannot do its work still answers, with a warning. Silence is the
  one outcome that teaches nobody anything, and the warning is in words rather
  than in SQLite's: a busy store is the one failure with a next step, so it says
  the write did not happen and can be done again. Hooks are the surface a person
  actually reads — their warnings land on stderr in front of them — and
  `database is locked` is the prose of a corrupt file about a store that was
  merely in use.

## Where it lives

- `src/hooks/mod.rs` — the events, the budgets, the dispatch
- `src/hooks/context.rs` — what a session opening is built from
- `src/hooks/nudge.rs` — the per-session record of what has been shown
- `src/hooks/session.rs` — `drifted_directory_projects`, §2's drift warning, held
  by `a_session_start_warns_when_the_directorys_history_is_under_another_name`,
  its agreeing half by
  `a_session_start_in_an_agreeing_directory_says_nothing_about_projects`, and
  the lookup's error half by
  `a_session_start_says_when_it_could_not_check_the_directorys_history`
- `src/hooks/spool.rs` — §22's spool: the directory, the entry format, the cap
  and retention, and the drain. Held by
  `a_capture_that_meets_a_held_store_is_kept_once_it_is_free`,
  `a_spooled_capture_drained_twice_is_stored_once`,
  `a_spooled_capture_without_a_session_is_stored_when_drained`,
  `a_temporary_file_is_not_a_spool_entry`,
  `two_drainers_claim_each_entry_once`,
  `a_drain_with_no_budget_left_writes_nothing`,
  `the_spool_drops_the_oldest_past_its_cap`,
  `the_spool_drops_entries_past_their_retention`, and, from `tests/`,
  `a_capture_hook_spools_over_a_store_it_cannot_open`
- `src/recall.rs` — the sizes and the rendering shared with the CLI. §5 is
  held by `a_session_line_and_a_prompt_line_are_cut_for_opposite_reasons` and,
  for the two sections that also carry a content preview, by
  `the_two_sections_that_carry_a_preview_cut_their_title_like_every_other_line`
- `src/setup/mod.rs` — `HOOK_EVENTS`, the one list of events, matchers and
  deadlines that both install routes are held to, and `ZCODE_HOOK_REGISTRATIONS`,
  the subset one client can fire
- `plugin/claude-code/hooks/hooks.json`, `plugin/codex/hooks/hooks.json`,
  `plugin/zcode/hooks/hooks.json` — the bundles, each guarded against its own
  agent's registrations by
  `the_plugin_bundles_register_the_hooks_the_binary_writes`
- `plugin/opencode/leteo.ts` — the OpenCode plugin, 1.x and 2.x from one file,
  held to each contract by `plugin/opencode/leteo.test.ts` (`node --test`) and to
  its export shape by `the_opencode_plugin_serves_both_majors_without_bun`
- `src/hooks/tests.rs`

## Related

- [`search.md`](search.md) — the nudge is a search nobody asked for
- [`mcp-tools.md`](mcp-tools.md) — the same store, when somebody did ask
- [`store-and-schema.md`](store-and-schema.md) — the lock these budgets wait on
- [`cli.md`](cli.md) — `leteo setup`, which installs these hooks
