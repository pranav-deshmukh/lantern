# Lantern

**Lantern is a domain-agnostic execution harness for AI agents.** It is not an
agent framework, and it is not a replacement for LangChain, LangGraph, CrewAI,
or any other agent-building tool. Lantern does not help you build an agent's
reasoning. It helps you **run an agent you already built** — in production,
safely, with the operational guarantees every real agent deployment eventually
needs and almost nobody builds correctly the first time.

If you are an AI coding agent (Codex, DeepSeek, Claude, or otherwise) picking
up this project, read this file fully before writing any code. It tells you
what Lantern is trying to be, what it explicitly refuses to be, and the
discipline this project has been built with so far.

---

## The one-sentence pitch

> Bring any agent — a custom Python class, a LangGraph app, a CLI tool like
> Cursor Agent or Codex — and Lantern gives it crash-resume, typed validation
> between steps, automatic tracing, human-approval gates on risky actions, and
> dynamic loop-back, without requiring you to rewrite the agent around Lantern.

## Why this exists

Every real agentic project eventually needs the same five things, regardless
of what the agent actually does:

1. **It will crash mid-run.** You need to resume from where it left off, not
   restart from zero.
2. **One stage will hand bad data to the next stage.** You need this caught
   immediately, with a clear error, not discovered three steps later as a
   mysterious failure.
3. **Someone will ask "what did the agent actually do."** You need a real,
   structured record — not scattered `print()` statements.
4. **The agent will eventually want to do something dangerous** (delete a
   file, push to prod, send a real email). You need a gate a human can
   approve or deny, and a denial must not be silently retried.
5. **A single fixed pipeline is rarely enough.** Real agent workflows loop
   back — a verifier fails, so you retry an earlier stage with feedback, not
   just fail the whole run.

Every one of these is boring, hard to get exactly right, and gets rebuilt
from scratch on every new agent project unless it lives in a shared layer.
Lantern is that shared layer.

## What Lantern is explicitly NOT

- **Not an agent-building framework.** It doesn't give an agent reasoning,
  memory, or tool-calling logic. That's the agent's job, built however you
  want (LangGraph, a bare Python class, a subprocess wrapping a CLI tool).
- **Not a rule-enforcement engine.** Lantern's context-bundling feature
  *guarantees delivery* of rules/skills files to an agent and *audits* which
  version was used (via content hash) — it does **not** guarantee the agent
  actually complied with what it read. That's still on the agent/prompt.
  Never describe this project as "enforcing" agent behavior.
- **Not trying to support 20 frameworks on day one.** The core primitive is
  "any single-argument callable" (a plain function, or a bound method like
  `agent.run`) — this already covers custom agents and most frameworks with
  zero adapter code, since Python doesn't care whether a callable is a
  function or a bound method. CLI-based agents (Cursor, Codex, Pi) need a
  thin subprocess adapter, which is expected and fine.

## Architecture — what's actually built (as of this file's writing)

The public package lives in `harness/`, as an installable, standalone Python
package (`harness/pyproject.toml`). It has **zero dependency on any demo or
example** — that separation is intentional and load-bearing. Demos live in
`demos/` as independent projects that depend on `harness` the same way any
external user would (`from harness import ...`), never via a relative import
into harness internals.

Built and tested so far, in the order they were built:

| Layer | What it does |
|---|---|
| `core.py` (`Runtime`, `Flow`, `Step`) | Runs an ordered sequence of steps. Retries on failure. Atomic crash-resume via a JSON checkpoint file — resuming picks up exactly where it left off, not from zero. |
| `contracts.py` (`Contract`) | Pydantic-based validation of a step's input and output. A mismatch fails immediately and loudly, naming the step and the exact field — never a silent bad handoff. |
| `tracing.py` (`Tracer`) | Automatically records every step execution — input, output, duration, timestamp, success/failure — to a JSONL trace file. No manual logging calls needed from step authors. |
| `trace_viewer.py` | Reads a trace file and prints a readable, indented execution tree. |
| `governance.py` (`PolicyEngine`, `PolicyRule`, `PolicyViolation`) | Gates specific named actions behind a policy (allow / require-approval). A denial raises immediately and is **provably excluded from the retry loop** — retrying a human's "no" makes no sense and doesn't happen. Denials are still traced for audit purposes. |
| `flow_loader.py` (`load_flow`) | Declarative YAML flow definitions. A flow is data, not code — the exact same `Runtime`/`Step`/`Contract`/`PolicyEngine` machinery runs a migration-shaped flow or a PR-review-shaped flow with zero code differences, only the YAML differs. Fails eagerly at load time (bad import paths, missing files) rather than partway through a run. |
| `routing.py` (`Goto`) | Non-linear flows. A step can return `Goto(target_step_name, payload)` to jump to any other named step instead of proceeding sequentially — this is what makes loop-back ("verifier failed, retry an earlier step with feedback") possible. Bounded by `max_jumps` to prevent infinite loops. |
| `anomaly.py` (`Baseline`, `find_anomalies`) | Learns "normal" duration per step from past successful runs, then flags a new run's steps that deviate significantly, are entirely new/unrecognized, or failed outright — with a human-readable reason for each. |
| `context.py` (`load_context_files`, `ContextBundle`) | A step can declare `rules_files` / `skills_files` (markdown or any text files). Their content is mechanically bundled into the step's input, and — critically — the trace records each file's path **and SHA-256 content hash**, so you can prove exactly which version of a rules file was in effect for any given run. This is the "agents/*.md folder" pattern made auditable. |
| `llm_step.py` (`call_deepseek`) | A real, working LLM call wrapper (DeepSeek's OpenAI-compatible API). Proves the whole system works with a genuine, non-deterministic model in the loop, not just deterministic stub functions. |
| `agent.py` (`Agent`, `Harness`) | Beginner-friendly single entry point: `Harness(agent_or_flow).run(input)` wraps a plain callable, any object with a `run` method, or an existing multi-step `Flow`, delegating to `Runtime` with all of its options intact. |

Every layer above has been stress-tested beyond its own unit tests during
review — including real bugs found and fixed:

- **Resume + Contract interaction bug** (Phase 2): a checkpointed step's
  Pydantic output was resumed as a raw dict instead of being rehydrated,
  breaking any step after it that expected attribute access. Fixed by
  rehydrating through the contract's `output_model` on resume.
- **Duplicate step name hang** (Phase 7 / routing): switching from
  index-based to name-based step advancement (needed to support `Goto`)
  accidentally made *ordinary sequential* advancement also resolve by name,
  which silently infinite-loops if any two steps in a flow share a name.
  Fixed by keeping sequential advancement strictly index-based, and using
  name resolution *only* for actual `Goto` targets.

Both were caught by writing an adversarial manual repro, not by trusting a
green test suite. **This is the standard for this project: passing tests are
necessary, not sufficient.** See "Contribution discipline" below.

## Built demo

- **`demos/code_reviewer`** — an automated code review & auto-fix demo using
  real `ruff` execution (not LLM self-judgment) as the verify step, with a
  governed apply-fix action. Built as an external consumer of the `harness`
  package to prove it's genuinely reusable, not coupled to its own examples.

## In progress / not yet built

- **`demos/adaptive_coding_agent`** — the most ambitious demo to date, in
  two phases:
  - *Phase A (init flow, one-time per project):* scans a real small
    codebase, asks clarifying questions, and produces a `project-profile.json`
    (detected stack, dependencies, test/lint commands, conventions) — a
    project-generated context artifact, not a human-authored one.
  - *Phase B (per-story flow, repeatable):* given a dev's task, plans → codes
    → runs **three independent real-execution gates** (parity/compile check,
    the project's own test command, the project's own lint/quality command)
    → any of the three can trigger loop-back to the coding step with real
    failure feedback → human-readable review → governed push. This is the
    hardest routing scenario built so far (three gates feeding one retry
    loop, tool commands driven by config rather than hardcoded).

## Contribution discipline — read this before writing code

This project has been built through disciplined, narrow, single-phase prompts
to AI coding agents (DeepSeek via Pi, and Codex), each reviewed before the
next phase begins. If you are an agent picking up work here:

1. **Stay inside the scope you were given.** Do not build ahead ("while I was
   at it, I also added...") — this has been an explicit failure mode to guard
   against. If something seems missing, say so, don't silently add it.
2. **Never modify or weaken an existing passing test to make new code pass.**
   If your change breaks an old test, the fix is in your new code, not the
   old test — unless the human explicitly says otherwise.
3. **Run the tests yourself and show the real output before declaring done.**
   Don't describe what tests "should" show.
4. **Explain non-obvious design decisions in comments**, especially on
   ambiguous points you had to judge-call. Silent judgment calls are the
   hardest thing for a reviewer to catch.
5. **Mocked tests prove the code path. They do not prove a real API/tool
   integration works.** Any step that calls a real external thing (an LLM,
   `ruff`, `pytest`) must be exercised for real at least once, separate from
   the mocked test suite, before being trusted.
6. **The harness package must never depend on any demo.** If you're working
   in `harness/`, importing anything from `demos/` is always wrong.

## Getting started

```bash
cd harness
pip install -e .
pytest tests/ -v
```

See `demos/` for real, working end-to-end examples built on top of the
harness as an external consumer.
