# Precept: deciding where an AI agent should be constrained by code, and where it should be trusted to reason

I built a system that watches the corrections I make while working inside Claude Code and compiles the mechanically checkable ones into hooks that block the agent's next mistake. The plumbing was not the hard part. The hard part was the classification I had to get right first: for any given instruction, do I enforce it deterministically or leave it to the model's judgment, and how do I keep myself honest about which is which.

## The problem

Coding agents follow instructions most of the time, not all of the time. If you tell one "use pnpm, never npm" or "run the tests before you tell me it works," it will comply on most turns and quietly break the instruction on some fraction of them. That fraction is small enough to feel reliable and large enough to matter, because the misses tend to land when you have stopped watching.

There is a structural reason. In Claude Code, `CLAUDE.md` and rules files are context. They are strong suggestions injected into the prompt, and the model weighs them against everything else it is doing. They are not enforced. The parts of the system that are enforced (hooks, permission rules, subagent tool scoping) are a separate configuration surface that most people never touch, because hand writing a hook for every small correction is not worth the effort.

So there is a gap between the place where you express an instruction (a sentence, in context, soft) and the place where an instruction can actually be made to hold (a hook, in config, hard). Precept is a bridge across that gap. You keep correcting the agent in plain language the way you already do, and the corrections that can be checked mechanically get promoted into the enforced layer, with your approval, without you writing any config.

## The insight

The instruction following gap tempts you toward an obvious framing: "make the agent follow instructions more reliably." That framing is wrong, and seeing why it is wrong is the whole project.

"Follow instructions reliably" implies every instruction wants the same treatment. It does not. Some instructions are decidable by a string match on a tool call: "never call npm" is true or false the instant the agent tries to run a command, no interpretation required. Some are decidable only over a trajectory: "run tests before claiming success" is a fact about what happened earlier in the session, checkable at the moment the agent tries to stop. And some are genuinely a matter of judgment: "do not leave stub code" has no regex. Whether a diff is stubby is a reading, not a match.

The competency I wanted to demonstrate, and the one I think matters most for building agentic products, is knowing which bucket an instruction falls into, and refusing to pretend a judgment call is a mechanical one. Over-constrain, and you get a brittle rules engine that false-blocks correct work and trains the user to turn it off. Under-constrain, and you are back to hoping the model complies, which is the problem you started with. The value is in drawing the line precisely, per instruction, and being able to defend where you drew it.

That line is the core competency because it is the same decision, repeated at every layer of an agentic product. Where do you trust the model, and where do you put a deterministic rail. Precept is a small, testable instance of that decision applied to agent configuration itself.

## Options I considered

**Pure prompt and memory (write everything into `CLAUDE.md`).** This is the free, native option: append every correction to a memory file and let the model read it. I rejected it as the primary mechanism because it is exactly the soft layer whose unreliability is the problem. It is the right home for genuinely soft guidance (recall, style, conventions), and Precept still uses it for precisely that. But treating it as enforcement would relabel the gap as a solution. Anthropic's own guidance is explicit that memory files are context and hooks are the deterministic layer. Leaning on memory for a "never" rule contradicts the platform's own documented model, and I did not want to ship a tool whose central claim its host system says is false.

**A full LLM judge on everything.** Route every tool call and every stop through a model that reads the situation and decides whether to block. This handles the judgment cases well, so it is tempting to make it the general mechanism. I rejected it for three separate reasons, any one of which is disqualifying. Cost and latency: paying for a model call on every `Bash` invocation to check a rule that a five character string match settles is not defensible at the frequency tool calls happen. Non-determinism: a judge that can change its answer turn to turn is not a rail. You cannot write a regression test against it, and a rail you cannot test is not a rail. Failure mode: if enforcement depends on a model call and the call fails, you either block everything (the tool wedges the session and the user rips it out) or allow everything (enforcement silently evaporates and the user never learns it stopped working). For the class of rule that could have been a deterministic check, accepting any of those three to buy flexibility you do not need is a bad trade.

**Deterministic only (no model in the enforcement path, ever, and no model anywhere in the loop).** The opposite extreme: only ship rules that reduce to a matcher, and drop every correction that needs judgment. This is what the enforcement engine should be, and it is exactly what I built for the hard tier. But as the whole product it is too small. "Do not leave stub code," "do not swallow exceptions," "do not hardcode the API key" are common, valuable corrections with no matcher. Refusing to handle them means refusing the most useful half of what people actually correct, and shipping a governance tool that is silent on the failures people care about most.

The resolution was not to pick one. It was to notice that these are three different tools for three different kinds of instruction, and that the design job was to classify each instruction and route it to the right tool, while being strict about labeling which tier a rule ended up in. The judgment cases in particular do not go to a pure LLM judge; they get a narrower construction (below) that keeps the determinism where it belongs and confines the model to the one decision only a model can make.

## The decision and the architecture

I split every learned instruction into two tiers and made the split load bearing.

**HARD** is the only tier that blocks. It is exactly the surface Claude Code lets you enforce: PreToolUse permission-deny, Stop-hook block, and subagent tool scoping. Nothing else. A HARD rule is data (a matcher over a tool call, or a trajectory condition) interpreted by a fixed stdlib engine with no model in the loop.

**SOFT** is everything else: knowledge notes for recall, conventions and style, the roadmapped skills and personas. SOFT steers. It never claims to block.

The honesty of that split is enforced in code, not asserted in a doc. The `Policy` model carries a validator, `_shape_matches_kind`, that refuses to construct a HARD policy on an event that cannot block. The blockable set is PreToolUse, Stop, and UserPromptSubmit; anything else raises:

```
if self.enforcement_tier == EnforcementTier.HARD and self.hook_event not in (
    HookEvent.PRE_TOOL_USE, HookEvent.STOP, HookEvent.USER_PROMPT_SUBMIT,
):
    raise ValueError(f"{self.hook_event} cannot HARD-enforce; use SOFT")
```

You cannot build a Precept policy that claims to enforce something it structurally cannot enforce. The intellectual-honesty rule is a unit-tested invariant, not a promise in a README.

The judgment cases get a specific, defensible construction rather than being forced into either extreme. "Do not leave stub code" runs as a cheap model verdict at a deterministic gate. The Stop hook fires every time (deterministic; no model decides whether to check). At that gate a Haiku call returns a structured `{ok, reason}`. Three properties make this honest rather than hand-wavy. The gate is deterministic even though the verdict is not. The exact prompt is stored on the rule's card, so the judgment is auditable rather than a black box. And it fails open: if the model call errors or a key is missing, the verdict returns nothing and the session proceeds. A missing API key can cost you a catch. It can never wedge your work. The bias is written into the prompt itself: block only on a clear violation, because a wrongful block is worse than a miss.

Rules are data, never code. The enforcement engine (`enforce.py`) is a fixed interpreter over compiled JSON. There is no `eval` or `exec` anywhere in the path. Model-generated regex is length-capped and fails safe on a `re.error`. This matters because the rules are authored by a model from my messy corrections, and I did not want model-authored logic executing as code on my machine.

The pipeline that carries a correction from a chat message to an enforced hook:

```
  DETECT          COMPILE           REVIEW          COMMIT             ENFORCE
  ------          -------           ------          ------             -------
  Haiku           Lesson ->         human           markdown card      PreToolUse /
  structured      typed Policy      `precept        = source of        Stop /
  extraction,     (determinism      keep |          truth  +           UserPromptSubmit
  abstain-        earned here)      delete`         compiled           hooks read the
  aware                             gate            policies.json      JSON cache;
  (MaybeLesson)                                     (hot path)         stdlib only, fast
     |                |                |                |                  |
  reads only      classifies      nothing         atomic write       zero LLM in
  user-typed      HARD vs SOFT,    enforces        (temp -> fsync     the enforcement
  turns,          single-call vs   until a         -> os.replace),    path
  fail-closed     trajectory vs    human keeps      .bak backup
                  judgment         it
```

Two things about this spine. First, determinism is earned at COMPILE, not assumed. A correction arrives as fuzzy natural language and only becomes a deterministic matcher if it can be compiled into one; otherwise it stays SOFT or becomes a judgment gate. Second, the REVIEW gate is the credibility core. Nothing Precept detects enforces anything until I run `precept keep` on it. The system proposes; the human disposes. That gate is also Anthropic's own "would removing this cause a mistake?" test for what belongs in memory, applied by a person at the moment of promotion.

Local first throughout. The markdown cards are the source of truth and are safe to keep in a synced vault. The derived SQLite and policy cache live on local disk (`~/.local/state/precept`) and never in a cloud-synced folder, because SQLite corrupts under sync. The cache is disposable and rebuilt by `precept compile`. Install and uninstall are exact inverses: sidecar manifests record precisely what Precept wrote, and uninstall strips only its own entries. Policy precedence is deny, then ask, then rewrite, then allow, which I arrived at independently and later found matches Cedar, OPA, and Microsoft's agent-governance toolkit. The enforcement engine runs with zero LLM. The learning loop needs a model (a subscription token routed through `claude -p`, or a billed API key); enforcement does not, and I am explicit about that seam because it is the kind of dependency a reviewer should be able to see at a glance.

## How I measured it

I did not want a single before and after number, because in agentic evaluation that number is usually noise wearing the costume of signal. I split the evaluation to match what each half can honestly prove.

Tier 1 is the trustworthy headline: a deterministic confusion matrix over a committed golden set of 25 enforcement cases. Each case carries its own compiled policies, a tool call, and the expected decision. The harness runs the real enforcement engine over them with zero model calls, so the result has zero variance. It is the same every run, on any machine, in CI. On that set, recall is 100 percent and the false-block rate is 0 percent. The claim is narrow on purpose: Precept catches 100 percent of the violations it has a rule for, and blocks zero compliant calls. It does not prove Precept catches violations it has no rule for. It proves the engine does what its compiled rules say, deterministically, which is the property you want an enforcement layer to have.

Tier 2 is the honest live delta: a paired, multi-trial before and after with a 95 percent confidence interval. Agentic evals are noisy. Infrastructure variance alone swings corrected-behavior scores by several points between identical runs, so a single unpaired comparison is not evidence. The `paired_delta` core measures corrected-behavior rate with enforcement off and on, paired by trial, and reports the mean delta with a 95 percent CI. That reporting core is built; wiring it to live agent runs is the stated next step, and I would rather say that than quote a headline number the methodology is not yet standing behind.

The full test suite is 175 functions and runs offline and hermetic. Every LLM call is injectable through a `FakeClient` at each seam, and the test harness redirects state to temp directories so no test touches the real `~/.claude`. An enforcement tool you cannot test deterministically is one you cannot trust, so testability was a design constraint from the start, not a cleanup pass at the end.

What the numbers do not prove: they do not prove Precept improves any given developer's real-world outcomes, and they do not prove coverage of instructions no rule exists for. What they prove is that the enforcement engine is deterministic and correct on its own compiled rules, and that I keep those two claims separate.

## What I deliberately deferred, and why

Restraint was part of the design. I want the deferrals to read as judgment, not as a roadmap of things I did not finish.

Nine artifact types are declared; three are wired. The enum names all nine things a session could compile into (rule, knowledge, convention, skill, agent persona, output style, slash command, MCP config, permission profile). Three are built: Rule (HARD), Knowledge note (SOFT recall), and Convention (SOFT, a Precept-owned rules file). The permission profile is partial (import plus clean-ban write-back only). The other six are designed and enum-declared, not built. I present them as a sequenced roadmap, three shipped and six designed, and I never imply nine work. Shipping the hard-enforcement wedge end to end, with real evals, is worth more than nine shallow half-features. It is also the only presentation consistent with the project's whole premise: a tool whose central value is refusing to overclaim enforcement cannot itself overclaim what it ships. The scope discipline and the honesty invariant are the same commitment applied at two levels.

Semantic recall is gated behind an eval I have not run. Knowledge retrieval is keyword first (SQLite FTS5 plus a metadata filter). The obvious move is vector embeddings from day one. I deferred it behind a condition: add sqlite-vec embeddings only if a Recall@k eval shows keyword search actually misses on these cards. The cards are terse and jargon dense, which is the regime where single-vector embeddings tend to underperform keyword search, so "semantic from day one" would have been an unmeasured assumption dressed as a best practice. Adding infrastructure to solve a problem you have not measured is how a product gets heavy without getting better. I would rather earn the embedding with a number, and I have specified the exact number that would earn it.

The one honest conformance gap is written down, not smoothed over. I audited Precept against Anthropic's published guidance for creating, retrieving, and configuring agent rules (`docs/ANTHROPIC-CONFORMANCE.md`). Configuration conforms strongly: the HARD/SOFT split, the hook JSON contract, permission precedence, the fact that Bash argument-pattern permissions are bypassable and therefore must stay hooks rather than permission rules, and atomic owned-file writes all line up. Creation mostly conforms. Retrieval has a real gap: path-scoped conventions load just in time as Anthropic recommends, but global conventions are always on rather than activity keyed, which cuts against the finite-context guidance. I wrote the gap into the audit and roadmapped the fix (activity-keyed retrieval through the existing knowledge seam) rather than quietly claiming full conformance. A conformance audit that finds no gaps is not an audit; it is marketing. Publishing the one gap is what makes the rest of it credible.

## What I would do next

Wire the paired live harness to real Claude Code sessions and publish the Tier-2 delta with its CI, so the behavioral claim rests on measured, error-barred evidence rather than the deterministic headline alone. Close the retrieval gap with activity-keyed convention loading. Then build the next artifact in sequence, most likely the permission profile to completion or the skill artifact, chosen by which correction types show up most in my own catalog. The catalog is the demand signal: I would rather let real usage tell me which of the six to build next than guess.

## Reflection

Precept governs an AI agent, and I built it with one. I want to be direct about that, because the structure is the point. A tool that constrains model behavior, authored in collaboration with a model, where the architecture, the tier split, the fail-open judgment gate, the eval methodology, and every decision about where to trust the model versus where to constrain it are mine. The model was a fast implementer. Deciding that a judgment rule must fail open, that determinism is earned at compile time and not assumed, that the honesty invariant belongs in a validator and not a comment, and that a 25-case deterministic matrix is worth more than one dramatic before and after number: those are the judgments, and they are the artifact.

I also expect a frontier lab could subsume most of this. If Claude Code shipped native promotion of an in-session correction into an enforced hook with a human approval gate, the core loop would move into the platform, and that would be a good outcome. What would not be subsumed is the judgment underneath: knowing which instructions deserve a deterministic rail and which deserve the model's reasoning, refusing to conflate the two, and building the evals that keep you honest about the difference. That judgment is the job. Precept is where I practiced it against a real system.

Source: github.com/NoaBarzelay/precept (MIT).
