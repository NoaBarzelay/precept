# Context management: keep the window small, keep the state on disk

A design for how Precept keeps a long session from degrading into a lossy
auto-compaction that drops important detail and hurts model quality.

## The governing principle

**The transcript is not the source of truth.** Claude Code owns the context
window and will, when it fills, run its own compaction: a generic
summarize-and-truncate that decides on its own what to keep. That summary is
lossy by construction, and Precept does not control what it keeps. So Precept
does not rely on the window at all. It externalizes durable state to disk every
turn, so the window can stay small and be *rehydrated* from disk rather than
*relied upon*.

Two consequences follow, and the rest of this doc is just their mechanics:

1. Anything that scrolls out of the window is already on disk (rules, knowledge,
   decisions, a session ledger), so it is recoverable, not lost.
2. Because the durable state is on disk, Precept can advocate for a *small*
   window: retrieve what is relevant instead of holding everything, and turn the
   limit from a cliff (lossy auto-compaction) into a deliberate checkpoint+resume.

This is an honest boundary up front: **Claude Code owns the window; Precept does
not edit, truncate, or compact it.** Precept's only levers are the ones the hook
contract actually gives us: what we *inject* (`additionalContext` at
SessionStart / UserPromptSubmit / PreCompact / Stop), what we *write to disk*
every turn, and what we *advise* the user to do (checkpoint, resume). Every
mechanism below lives inside that boundary. We never claim to control the
transcript; we claim to make the transcript not matter.

## How this maps onto Precept's existing spine

Precept already runs a per-turn `DETECT -> COMPILE -> REVIEW -> COMMIT ->
ENFORCE` loop off the Stop / SessionEnd hooks, with markdown cards as the source
of truth (`~/.precept/catalog`, `~/.precept/notes`) and a derived, local-only
state dir (`~/.local/state/precept`) for the disposable index and policy cache.
Context management is **not a tenth artifact type.** It is an *operational layer*
that reuses the stores and seams already built:

- The **catalog** (rules) and **notes / vault knowledge** (entities) are the
  durable stores that make externalization free (capture already writes them).
- The **`additionalContext` injection seam** (already wired and verified for
  UserPromptSubmit, already specced for SessionStart retrieval in BACKLOG #7) is
  the rehydration channel.
- The **local state dir** (`paths.state_dir()`, already the home of the policy
  cache, the FTS index, the detect cursor, the permissions manifest) is where the
  one new artifact (a per-session **ledger**) lives.

So the only genuinely new store is the session ledger, and it is small,
derived-ish, and local. Everything else is an extension of capture (write durable
facts every turn) and retrieval (inject relevant facts on demand).

---

## 1. Externalize-as-you-go

**Mechanism.** Every turn, the Stop hook already runs DETECT, which mines genuine
user corrections into PENDING rule cards on disk, and the knowledge-capture pass
(BACKLOG #7) routes durable facts into the vault. The point worth stating plainly
for context management: *this is already a memory-externalization engine.* The
durable content of a session (the rules learned, the facts established, the
decisions made) is committed to markdown the turn it happens. When that content
later scrolls out of the window (or is dropped by a compaction), it is not lost,
because it was never only in the window.

**Hook.** Stop (`precept-hook-stop` -> `hooks.stop_main` -> `_spawn_detect`),
SessionEnd (`precept-hook-sessionend` -> `hooks.detect_main`).

**Writes.** Rule cards to `paths.catalog_dir()`; knowledge to the notes dir /
vault; both are markdown source-of-truth, sync-safe, git-logged.

**Reads.** Nothing in the hot path; this mechanism only writes. Recovery is the
job of mechanisms 2 and 3.

**Why it preserves quality.** The transcript can shrink to nothing and the
*durable* state survives at full fidelity on disk. Compaction loses prose; it does
not lose a committed rule card or a knowledge note, because those live outside the
window. This is the foundation: it is what makes a small window safe.

---

## 2. Session ledger

The one new artifact. A small, structured, continuously-updated file that holds
the *working state* of the current session: the part of the transcript that is
load-bearing for continuing the task, distilled to a page.

**What it holds (kept compact, hard-capped):**

- `current_task`: the goal in one or two sentences.
- `decisions`: durable choices made this session (what, and one line of why).
- `open_threads`: what is unfinished, what is next.
- `key_paths`: the handful of files/dirs in play.
- `active_rules`: the ids (and one-line triggers) of Precept rules in force for
  this cwd, so the model is reminded of the guardrails it is operating under.
- `knowledge_refs`: ids/titles of the knowledge cards already pulled in, so a
  resume does not re-retrieve or re-derive them.

**Hook that maintains it.** Stop, each turn. The same `stop_main` that already
fires DETECT writes/updates the ledger. It is cheap: the ledger is a structured
upsert, not an LLM essay. Where a turn clearly changed the working state (a new
decision, a finished thread), an optional small Haiku pass distills the delta;
otherwise it is a deterministic patch (append a decision, flip a thread to done,
add a touched path). Bias to deterministic; only summarize when the structured
patch cannot capture it.

**Hook that reads it.** SessionStart, injected via `additionalContext`. And
critically, **SessionStart fires on a post-compaction resume too** (the
`source` field distinguishes `startup` / `resume` / `compact`). So immediately
after Claude Code compacts, Precept re-injects the full structured ledger. The
model rehydrates the essentials (task, decisions, open threads, paths, rules)
from a clean page instead of from whatever the generic summary happened to keep.

**Writes.** `paths.state_dir()/sessions/<session_id>/ledger.json` (and a
human-readable `ledger.md` mirror for `precept` inspection). Local, derived,
disposable, keyed by `session_id` from the hook event. Never in the synced vault
(it is written incrementally, same SQLite-sync hazard reasoning as the index).

**Reads.** SessionStart hook reads the ledger for the resolved `session_id` and
emits it as `additionalContext`.

**Why it preserves quality.** The ledger is the antidote to compaction amnesia.
Generic compaction summarizes the *prose* of the transcript and is at the mercy
of what looked important to the summarizer. The ledger is a *structured*
distillation Precept controls, written turn-by-turn while the detail is fresh, so
it never has to reconstruct a decision from a half-truncated tail. Re-injecting it
at SessionStart means a resumed or compacted session starts from a deliberate,
high-signal page, not a lossy one.

**Where it lives.** New module `precept/session.py` (ledger read/update/render);
new entrypoint `precept-hook-sessionstart` -> `hooks.sessionstart_main`; install
adds the `SessionStart` entry to `_ENTRIES`. Store under `state_dir()/sessions/`.

---

## 3. Retrieval over recall

**Mechanism.** Keep the window lean by *retrieving* the relevant knowledge and
rules on demand rather than holding everything in context. This is the RAG
injection already specced in BACKLOG #7: at UserPromptSubmit, take the user's
prompt, run it against the knowledge index (FTS5/BM25 today, the same
`knowledge.search` / `kindex.search` already built), and inject the top-k
relevant cards as `additionalContext`. At SessionStart, inject the ledger
(mechanism 2) plus a small set of cards relevant to the resumed task.

The contrast that matters: the alternative to retrieval is *recall*, stuffing
every note and every rule into CLAUDE.md or the opening context and hoping the
model finds the relevant bit. That bloats the window (hastening the limit) and
*dilutes* attention (hurting quality even before the limit). Retrieval injects
only what this prompt needs.

**Hook.** UserPromptSubmit (`precept-hook-userpromptsubmit` ->
`enforce.evaluate_userpromptsubmit`, extended with a retrieval-inject step) and
SessionStart.

**Writes.** Nothing. Pure read + inject.

**Reads.** The knowledge index (`paths.index_db()` / the vault knowledge index)
and the active policy cache, both local.

**Why it preserves quality.** Two compounding wins. Smaller relevant context
*delays* the context limit (fewer tokens per turn means more turns before
compaction is even considered). And smaller relevant context *improves* per-turn
quality independent of length: less irrelevant material to distract the model,
higher signal-to-noise, the right rule visible at the moment it applies. Lean and
relevant beats big and complete.

---

## 4. PreCompact checkpoint

**Mechanism.** Claude Code exposes a `PreCompact` hook that fires *immediately
before* it runs its own compaction (both the manual `/compact` and the automatic
fill-the-window case; the `trigger` field says which). Precept hooks it to write
a **high-fidelity, structured checkpoint to disk before the lossy summary runs.**
The checkpoint is not a re-summary of the transcript. It is a *snapshot grounded
in the externalized stores*: the current ledger (mechanism 2), the active rules
for this cwd, the knowledge cards already in play, the open threads and key
paths, plus a structured pull of the recent decision-bearing turns. Because
DETECT and capture have been writing durable state all along, PreCompact mostly
*assembles* a checkpoint from material already on disk rather than racing to
distill a full window in one shot.

**Hook.** PreCompact (`precept-hook-precompact` -> `hooks.precompact_main`). New
`HookEvent.PRE_COMPACT` enum value, new entrypoint, new `_ENTRIES` line.

**Writes.** `state_dir()/sessions/<session_id>/checkpoint-<ts>.json` plus an
updated `ledger.json`. The checkpoint is the durable record of "what the session
knew at the moment before Claude Code compacted it."

**Reads.** The ledger, the policy cache, the knowledge index, all already on
disk. PreCompact's job is assembly, not derivation.

**Precept's structured checkpoint vs. generic compaction.**

| | Generic Claude Code compaction | Precept PreCompact checkpoint |
|---|---|---|
| What it summarizes | The prose of the transcript window | The externalized stores (cards, ledger, decisions) |
| Fidelity | Lossy; the summarizer chooses what survives | Structured; the fields are fixed and Precept-controlled |
| Timing | Distills the whole window in one pass under pressure | Assembled incrementally over the session, finalized just-in-time |
| What it can drop | A specific decision, a file path, a rule | Nothing in the schema; those are first-class fields |
| Recoverability | Gone once summarized | On disk, re-injectable at the next SessionStart |
| Who controls it | Claude Code | Precept |

The reason it loses less is that it does not *summarize* the irreplaceable detail
at all. It captured that detail to disk turn-by-turn (mechanism 1) and structures
it (mechanism 2). Generic compaction is a one-shot lossy compression of prose
under pressure; the Precept checkpoint is a structured read of state that was
already preserved. PreCompact is the seam where Precept gets to capture the
session *first*, so that even if Claude Code's summary then drops something, the
next SessionStart re-injects it from Precept's record.

**Honest boundary.** PreCompact cannot *stop* or *replace* Claude Code's
compaction, and the current contract does not let a hook substitute its own
summary for the model's. What PreCompact gives us is the *timing guarantee*:
Precept gets to write its checkpoint before the lossy step runs, so the
high-fidelity record exists independently of whatever the compaction keeps.

---

## 5. Context-budget monitoring + handoff

**Mechanism.** Estimate how full the context window is, and when it approaches the
limit, recommend a clean checkpoint-and-resume rather than waiting to fall off the
cliff into auto-compaction.

*Estimation.* On each Stop, read the transcript (the hook already gives us
`transcript_path`, and `cc.read_transcript` already parses it) and estimate token
usage. A cheap heuristic (chars/4 over the message contents, plus a tool-output
weighting) is enough to know whether we are at 50% / 80% / 95% of a configured
budget. This is an estimate, not a measurement; Claude Code does not hand us an
exact live token count, and we are honest that the threshold is approximate.

*Advice.* When usage crosses a high-water mark, the Stop hook injects (via
`additionalContext`) a recommendation: "context is ~85% full; a clean checkpoint
and resume will preserve quality better than auto-compaction. Run
`precept handoff`." This is advice, not enforcement; it never blocks the user
from continuing.

*The `precept handoff` command.* Emits a **rehydration bundle** to start a fresh
session cleanly: the session ledger + the relevant knowledge cards + the active
rules for this cwd + the open tasks/threads, rendered as one compact markdown
brief. The user starts a new Claude Code session, and SessionStart injects the
bundle (the same ledger-injection path as mechanism 2, pointed at the handoff
bundle). The new session begins with a small, high-signal context instead of a
large, auto-compacted one.

This is the payoff of the whole design: it **turns compaction from a lossy event
into a deliberate checkpoint+resume.** Auto-compaction is what happens *to* you
when the window fills; a handoff is something you *do*, at a clean boundary, from
state that was externalized all along.

**Hook / command.** Stop (budget estimate + advice injection,
`enforce.evaluate_stop` extended or a sibling step in `stop_main`); a new
`precept handoff` CLI command in `cli.py`; SessionStart consumes the bundle.

**Writes.** `state_dir()/sessions/<session_id>/handoff.md` (the bundle).
**Reads.** Transcript (for the estimate), ledger, policy cache, knowledge index.

**Why it preserves quality.** A handoff resets the window to a small, curated,
*uncompacted* context. The model resumes with full-fidelity essentials and none
of the accumulated noise. Compared to riding into auto-compaction, the resumed
session is both leaner (faster, more turns of headroom) and higher-fidelity
(nothing important was summarized away, because the bundle was built from the
externalized stores, not from a lossy pass over the window).

**Where it lives.** Budget heuristic in `precept/session.py` (or a small
`precept/context_budget.py`); `handoff` command in `cli.py`; advice injection in
`hooks.stop_main` via the existing adapter `additionalContext` helpers.

---

## 6. Pruning

**Mechanism.** Identify context that is *safe to drop* because it is already
captured durably elsewhere. The clearest case: **large tool outputs already
written to knowledge.** A big file read, a long command output, a fetched
document: once its salient content is captured to a knowledge card (mechanism 1),
the raw blob in the transcript is redundant; its durable value is on disk and
retrievable (mechanism 3). The same holds for resolved threads and superseded
intermediate state.

**The honest boundary (stated plainly).** Claude Code owns the window. Precept
cannot reach into the transcript and delete a tool output. So "pruning" here is
*not* Precept excising bytes from the window. Precept's actual levers are:

- **Advice:** at PreCompact (or at a budget high-water mark), tell the model which
  context is safe to let go because it is captured: "the contents of `<file>`
  and the `<cmd>` output are saved to knowledge `<id>`; they need not be retained
  verbatim." This biases what survives toward signal.
- **Replacement-by-reference on rehydration:** when Precept rebuilds context at
  SessionStart / handoff, it injects a *reference* to the captured knowledge
  (id/title/one-line) instead of the original multi-kilobyte blob. The pruning
  happens at the rehydration boundary, which Precept *does* control, not in the
  live window, which it does not.

So pruning is real but it operates on the injection/summary/advice side, never by
mutating Claude Code's transcript. We are explicit about that so the doc does not
over-claim.

**Hook.** PreCompact and Stop (advice via `additionalContext`); SessionStart /
handoff (replacement-by-reference on rebuild).
**Writes.** Nothing new (the knowledge capture already happened).
**Reads.** Knowledge index, to know what is already captured and reference-able.

**Why it preserves quality.** A window full of stale tool dumps is a window that
hits the limit sooner and reasons worse. Replacing captured blobs with compact
references on every rehydration keeps the *recoverable* information while shedding
the *redundant* bytes. Lean and relevant, again.

---

## How this ties to performance quality

The thread through all six mechanisms: **lean, relevant, uncompacted context
outperforms a bloated or auto-compacted one**, for two independent reasons.

1. **Length.** Fewer tokens per turn means more turns before the limit, which
   means auto-compaction is reached later or not at all. Retrieval (3), pruning
   (6), and handoff (5) all push the limit out.
2. **Signal.** Even below the limit, a window of only relevant material reasons
   better than a window padded with stale dumps and irrelevant notes: less
   distraction, the right rule visible at the right moment. Retrieval (3) and
   pruning (6) raise signal directly.

And when the limit *is* reached, the failure mode is bounded: durable state was
externalized every turn (1), structured into a ledger (2), and snapshotted before
compaction (4), so a resume (5) rehydrates full-fidelity essentials instead of
inheriting a lossy summary. Generic auto-compaction sacrifices both length and
signal at once, silently, and on Claude Code's terms. Precept's design sacrifices
neither, deliberately, on the user's terms.

## How it would be measured

Consistent with Precept's two-tier eval discipline (a deterministic headline plus
a paired, error-barred live delta):

- **Rehydration-vs-baseline (the headline live eval).** Take a set of multi-step
  tasks long enough to force a context reset. Run each two ways: (a) **baseline**,
  let Claude Code auto-compact at the limit; (b) **rehydrated**, at the same
  point, force a reset and resume from a `precept handoff` bundle. Score
  corrected-task-quality (same metric family as the live Tier-2 eval) and report a
  **paired, multi-trial delta with a 95% CI** (infra noise alone swings agentic
  scores several points, so a single before/after number is not trustworthy). The
  claim to earn: rehydration recovers measurably more post-reset task quality than
  auto-compaction.
- **Detail-survival (deterministic, zero-variance).** Seed a session with N
  load-bearing facts (a decision, a file path, a rule id, a constraint). Force a
  reset. Assert how many survive in (a) the auto-compacted summary vs. (b) the
  Precept ledger/checkpoint. The ledger should be ~100% by construction (the facts
  are first-class fields); the generic summary will drop some. This is the
  context-management analogue of the Tier-1 confusion matrix: committed inputs,
  deterministic check, CI-gateable.
- **Window-fraction-under-budget (an operating metric).** Over real sessions, the
  share of turns kept under a target window fraction (say 70%) with retrieval +
  pruning on vs. off. A leading indicator that the lean-context levers are working,
  separate from end-task quality.
- **Recall@k for the retrieval injection.** The same Recall@k gate already named
  in the knowledge decisions: does BM25 injection surface the relevant card for a
  given prompt? (And the existing trigger to add sqlite-vec only if keyword recall
  measurably misses.) Retrieval quality (3) is upstream of context quality.

## Where each piece lives (hook -> module -> store)

| Mechanism | Hook | Module | Store (read/write) |
|---|---|---|---|
| 1 Externalize-as-you-go | Stop, SessionEnd | `detect.py`, `knowledge/` | catalog + notes/vault (write) |
| 2 Session ledger | Stop (write), SessionStart (read) | new `session.py`; `hooks.py` (`sessionstart_main`) | `state_dir()/sessions/<id>/ledger.json` |
| 3 Retrieval over recall | UserPromptSubmit, SessionStart | `enforce.py` (+inject step), `knowledge/index.py` | index.db / vault index (read) |
| 4 PreCompact checkpoint | PreCompact (new) | new `precompact_main` in `hooks.py`; `session.py` | `state_dir()/sessions/<id>/checkpoint-*.json` (write) |
| 5 Budget + handoff | Stop (estimate/advise) + `precept handoff` CLI | `session.py`/`context_budget.py`, `cli.py` | transcript (read), `handoff.md` (write) |
| 6 Pruning | PreCompact, Stop, SessionStart | `session.py`, `knowledge/index.py` | knowledge index (read) |

New install `_ENTRIES` lines: `("SessionStart", None, "precept-hook-sessionstart")`
and `("PreCompact", None, "precept-hook-precompact")`. New `HookEvent` enum
values: `SESSION_START` already exists; add `PRE_COMPACT`. All new hooks stay
**fail-open** (the existing `hooks.py` contract: any error emits nothing, exits 0),
so context management can never wedge a session. All new stores live under the
**local** `state_dir()`, never the synced vault (incremental writes + sync =
corruption, the same invariant `paths.py` already enforces for the index).

## Relation to the existing artifact types

This is **not a tenth artifact type.** It is an operational layer over the
existing capture and retrieval machinery:

- **Capture (extends #1 Rule + #2 Knowledge).** Externalize-as-you-go (1) is just
  the per-turn DETECT + knowledge-capture already running, viewed through a
  memory-durability lens. No new artifact, new framing.
- **Retrieval (extends #2 Knowledge).** Retrieval-over-recall (3) is the
  SessionStart/UserPromptSubmit injection already named in ARTIFACTS #2 ("planned:
  injected at SessionStart/UserPromptSubmit as additionalContext") and BACKLOG #7.
- **The session ledger / checkpoint / handoff bundle** are a new *internal*
  store (session-scoped operational state), not a user-facing artifact the user
  reviews and keeps. They are derived, local, disposable, and never go through the
  PENDING -> keep gate, because they are not learned policy; they are working
  memory. This keeps the credibility core (the human keep/veto gate) untouched:
  context management never enforces anything and never asks to be kept.

So the artifact catalog stays at nine. Context management is the layer that makes
those nine survive a long session intact.

---

## Open questions

1. **Ledger update cost.** How often does the deterministic structured patch
   suffice vs. needing a Haiku distill? If most turns need the model, the ledger
   stops being cheap. Measure the patch-vs-distill ratio on real sessions before
   committing to a per-turn model call.
2. **Token estimation accuracy.** chars/4 is crude and Claude Code does not expose
   a live token count. How wrong can the estimate be before the budget advice
   fires too early (annoying) or too late (useless)? Is there a better signal in
   the transcript than a char heuristic?
3. **PreCompact contract stability.** The hook contract has already moved once
   (the `stop_hook_active` field and block cap vanished). Re-verify the PreCompact
   stdin/stdout shape and the `trigger`/`source` fields at codegen; do not assume
   from memory.
4. **Does the model honor injected pruning advice?** Telling the model "this blob
   is safe to drop" is soft. Without control of the window we cannot guarantee it
   acts on the advice. Worth a small eval: does injected advice measurably change
   what survives a compaction?
5. **Session identity across a resume.** A handoff starts a *new* `session_id`.
   How does the new session find the prior ledger/bundle? A pointer file, a
   `--from <session>` flag on resume, or the handoff bundle carrying its own id?
   Needs a concrete handoff-to-resume linkage.
6. **Multi-session / parallel work.** Worktrees and parallel agents mean several
   live sessions sharing one catalog. Ledgers are per-session (fine), but does the
   budget advice or handoff need to be aware of sibling sessions on the same repo?
7. **Ledger as a soft attack surface.** The ledger is injected as
   `additionalContext`, i.e. into the model's context. DETECT already has a
   provenance gate (user-typed turns only) to keep junk out of rules; does the
   ledger need an analogous gate so a poisoned tool output cannot write a
   misleading "decision" that then gets re-injected every resume?
8. **When is a handoff worth it vs. just continuing?** Below the limit, a handoff
   has a cost (a context reset, lost implicit nuance). Where exactly is the
   crossover where checkpoint+resume beats riding the current window? The eval in
   "how it would be measured" should locate that threshold, not assume it.
