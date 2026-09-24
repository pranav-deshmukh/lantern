# lantern-harness

A domain-agnostic execution harness for AI agents. Bring an agent you already
built — a custom Python class, a LangGraph app, a CLI tool — and get
crash-resume, typed contracts between steps, automatic tracing, human-approval
gates on risky actions, and dynamic loop-back, without rewriting the agent
around this library.

```bash
pip install lantern-harness
```

## Quickstart — wrap an agent you already have

```python
from harness import Harness

class MyAgent:
    def run(self, input):
        return f"processed: {input}"

harness = Harness(MyAgent(), trace_path="trace.jsonl")
result = harness.run("some task")
```

That's it — your `MyAgent` class needed zero changes, zero imports from this
library, and zero inheritance. It now has automatic crash-resume (via
`checkpoint_path`), tracing, and retries for free.

## What this gives you

- **Crash-resume**: atomic checkpointing means a crash mid-run resumes from
  the last completed step, not from zero.
- **Typed contracts**: validate a step's input/output against a Pydantic
  model; a bad handoff fails immediately with a clear error, not three steps
  later as a mystery.
- **Automatic tracing**: every step's input, output, duration, and
  success/failure is recorded to a structured JSONL trace — no manual
  logging calls needed.
- **Governance**: gate specific risky actions behind a human-approval policy.
  A denial is provably excluded from the retry loop and still fully audited.
- **Dynamic routing**: a step can jump back to any earlier named step with
  `Goto(target, payload)` — the pattern behind "verifier failed, retry an
  earlier step with feedback," bounded by a configurable jump limit.
- **Declarative YAML flows**: define a multi-step flow as data, not code —
  the same runtime executes any flow shape you describe.
- **Auditable context injection**: attach rules/skills files to a step; their
  content and SHA-256 hash are recorded in the trace, so you can prove
  exactly which version of a rules file was in effect for any run.

## What this is *not*

This is not an agent-building framework — it doesn't give your agent
reasoning, memory, or tool-calling logic. It's the operational layer
*underneath* whatever agent you already built: think Temporal or Airflow for
agents, not LangChain or LangGraph.

It also does not *enforce* that an agent follows injected rules/skills
content — it guarantees the content was delivered and audits which version
was used. Compliance is the agent/prompt's responsibility.

## Learn more

Full documentation, architecture notes, and real end-to-end demos (an
automated code reviewer, an adaptive multi-agent coding pipeline) live in the
main repository: https://github.com/pranav-deshmukh/lantern
