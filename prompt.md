You are working on Lantern, an open-source Python agent runtime.

IMPORTANT CONTEXT:

Lantern is NOT intended to become another LangGraph.

LangGraph / agent frameworks can own:

- agent reasoning
- agent state
- agent routing
- internal graph construction

Lantern is the operational runtime underneath agents.

Lantern's responsibility is:

- reliable execution
- validation
- retries
- recovery
- checkpoint/resume
- governance
- tracing
- auditability
- observability
- evaluation

We have already implemented:

- Step
- Flow
- Runtime
- Agent integration
- ExecutionContext
- Contracts
- Retry
- Goto/recovery
- Checkpointing
- Governance
- Tracing
- explicit transition validation
- rejection of undeclared transitions when explicit transitions are defined

Do NOT turn Lantern into a more sophisticated graph orchestration framework.

==================================================
TASK: BUILD THE RUN + STRUCTURED EVENT FOUNDATION
==================================================

The next major capability is observability.

We eventually want a UI that shows a live execution graph generated from the actual runtime execution.

For example, during a run:

    ┌──────────┐
    │ classify │ ✓
    └────┬─────┘
         ↓
    ┌──────────┐
    │  draft   │ ✓
    └────┬─────┘
         ↓
    ┌──────────────┐
    │ quality_check│ ✗
    └──────┬───────┘
           ↓
         retry
           ↓
    ┌──────────┐
    │  draft   │ ↻
    └────┬─────┘
         ↓
    ┌──────────────┐
    │ quality_check│ ✓
    └──────────────┘

After completion, the same execution graph should contain the complete
history of what actually happened.

IMPORTANT:

The future UI must NOT have to infer the execution graph by inspecting
random logs, checkpoints, or agent output.

The Runtime should emit structured events that are sufficient to reconstruct
the execution timeline and graph.

==================================================

1. # FIRST INSPECT THE EXISTING CODE

Before changing anything:

- inspect Runtime
- inspect Flow
- inspect Step
- inspect tracing
- inspect checkpointing
- inspect Goto
- inspect contracts
- inspect ExecutionContext
- inspect all existing tests

Do not create a second tracing system if the existing tracing architecture
can be evolved.

Do not rewrite the Runtime.

Preserve the current public API wherever possible.

Run the existing tests before changing anything.

# ================================================== 2. INTRODUCE A FIRST-CLASS RUN

We need a coherent representation of one Runtime execution.

Conceptually:

    Run
      ├── run_id
      ├── flow / agent identity
      ├── status
      ├── started_at
      ├── finished_at
      ├── result
      ├── error
      ├── events
      └── execution metadata

The exact API should fit Lantern's current architecture.

Possible statuses:

    running
    completed
    failed
    rejected
    interrupted

Do not overengineer this.

The purpose of Run is to provide a coherent record of one execution.

# ================================================== 3. STRUCTURED EVENTS

Every important runtime action should produce a structured event.

At minimum support:

    run_started
    step_started
    step_completed
    step_failed
    contract_failed
    retry_started
    transition
    goto
    human_approval_requested
    human_approval_received
    run_completed
    run_failed

Use the existing tracing implementation where possible.

Do not create two competing event/tracing concepts.

If the existing trace model can become the event model, evolve it.

# ================================================== 4. EVENT SCHEMA

Create a stable structured event representation.

Conceptually:

    Event(
        event_id,
        run_id,
        type,
        timestamp,
        step,
        attempt,
        data
    )

The exact names/types can differ if the existing code has better conventions.

Important properties:

- events belong to a run
- events are ordered
- events are immutable after emission
- event type is explicit
- event data is structured
- events contain enough information for future UI rendering

Do not store giant unstructured log strings as the primary representation.

# ================================================== 5. STEP EVENTS

For every step execution, record enough information to reconstruct:

    step started
    step completed / failed
    duration
    attempt number
    error/contract failure when applicable

Example conceptual event:

    {
        "type": "step_started",
        "run_id": "...",
        "step": "quality_check",
        "attempt": 1
    }

and:

    {
        "type": "step_failed",
        "run_id": "...",
        "step": "quality_check",
        "attempt": 1,
        "reason": "contract_failed"
    }

Do not expose sensitive input/output automatically in events.

Avoid dumping arbitrary user data into traces.

# ================================================== 6. TRANSITION EVENTS

A future execution graph will need to know which transitions actually
occurred.

Record:

    source
    target
    reason
    attempt

Example:

    {
        "type": "transition",
        "source": "quality_check",
        "target": "draft",
        "reason": "contract_failure",
        "attempt": 1
    }

This should describe what Lantern actually executed.

Do not generate graph edges by reading agent text.

# ================================================== 7. RETRIES AND RECOVERY

Make retries and Goto/recovery visible as runtime events.

For example:

    step_started(draft, attempt=1)
    step_failed(draft, attempt=1)
    retry_started(draft, attempt=2)
    step_started(draft, attempt=2)
    step_completed(draft, attempt=2)

For Goto:

    step_failed(quality_check)
    transition(
        source="quality_check",
        target="draft",
        reason="contract_failure"
    )

The event stream must preserve the actual order.

# ================================================== 8. RUN RESULT

At the end of Runtime execution, the caller should have access to the
completed Run / execution result.

Conceptually:

    run = runtime.run(flow, input)

    run.status
    run.result
    run.events
    run.started_at
    run.finished_at

Do not necessarily change Runtime.run() to return exactly this if that would
break the existing API.

If backward compatibility requires keeping the current return value,
introduce another clean mechanism for retrieving the Run.

Do not break existing user code merely to add observability.

# ================================================== 9. GRAPH-READY DATA, NOT GRAPH UI

This task must prepare the runtime for a future execution graph UI.

DO NOT build the UI now.

DO NOT add React.

DO NOT add a web server.

DO NOT add a frontend dependency.

DO NOT build a graph visualization library.

Instead ensure the event model can later produce:

    nodes:
        classify
        draft
        quality_check
        approve

and actual execution edges:

    classify -> draft
    draft -> quality_check
    quality_check -> draft
    draft -> quality_check
    quality_check -> approve

The same step may appear multiple times in execution history.

That is intentional.

The UI will later distinguish:

    declared Flow

from:

    actual execution trajectory

This distinction is important.

# ================================================== 10. DECLARED FLOW VS ACTUAL EXECUTION

Do not confuse the Flow definition with the execution history.

Flow says:

    A -> B
    B -> C
    C -> D
    C -> B

Actual run might be:

    A
    B
    C
    B
    C
    D

The future UI should be able to show both:

    Declared Flow
        +
    Actual Run

Therefore the event stream must represent actual execution.

Do not mutate the Flow itself to represent execution.

# ================================================== 11. RUN SUMMARY

Provide a way to derive a summary from the event stream.

Conceptually:

    RunSummary(
        status,
        total_steps,
        total_attempts,
        retries,
        recoveries,
        failures,
        contract_failures,
        human_interventions,
        duration
    )

Do not manually maintain dozens of counters throughout Runtime if they can
be reliably derived from immutable events.

Prefer:

    events -> summary

over duplicated mutable state.

However, use reasonable judgment if some metrics are better maintained
directly.

# ================================================== 12. ERROR HANDLING

When a run fails:

- emit the appropriate failure event
- preserve the original error
- mark Run status correctly
- do not lose events that occurred before failure

When a run succeeds:

- emit run_completed
- preserve final result
- preserve complete event history

When a contract rejects output:

- distinguish that from an unexpected runtime exception

When a retry happens:

- preserve both failed and successful attempts.

# ================================================== 13. CHECKPOINT COMPATIBILITY

Do not replace checkpointing with the new Run model.

Run/event history and checkpoints have different purposes.

Checkpoint:
"Where can I resume?"

Run:
"What happened?"

They should work together.

If necessary, include the run_id or relevant event position in checkpoint
metadata so resumed execution can remain observable.

Do not redesign checkpointing unless required.

# ================================================== 14. TESTS

Add focused tests.

At minimum:

### Test 1 — Run starts and completes

Verify:

- run exists
- status becomes completed
- start/end information exists
- completion event exists

### Test 2 — Step lifecycle events

Verify:

    step_started
    step_completed

are emitted in the correct order.

### Test 3 — Step failure

Verify:

    step_started
    step_failed

and the failure information is retained.

### Test 4 — Retry history

A failing step that retries should produce events for BOTH attempts.

### Test 5 — Goto/recovery history

Example:

    A -> B -> C
         ↑    |
         └────|

Verify the event stream contains the actual:

    A
    B
    C
    B
    C

trajectory.

### Test 6 — Transition event

Verify source, target, reason, and attempt.

### Test 7 — Contract failure

Verify contract failure is represented distinctly from an arbitrary exception.

### Test 8 — Failed run

Verify run_failed and final status.

### Test 9 — Event ordering

Verify events are strictly ordered for one run.

### Test 10 — Summary

Verify derived summary metrics match the actual event stream.

### Test 11 — Existing compatibility

All existing tests must continue to pass.

# ================================================== 15. IMPORTANT DESIGN CONSTRAINT

Do not turn Lantern into an event-sourcing framework.

We only need a clean event history for observability.

Keep the implementation small and understandable.

Do not introduce Kafka, Redis Streams, OpenTelemetry, databases, or other
infrastructure just for this feature.

An in-memory event collector is sufficient for now.

The architecture should leave room for a future persistent exporter.

For example, conceptually:

    Runtime
       ↓
    EventEmitter
       ↓
    EventSink

Current sink:
InMemoryEventSink

Future possibilities:
JSONL
OpenTelemetry
database
web UI
remote collector

Do not implement those future sinks now.

# ================================================== 16. FUTURE EXECUTION GRAPH REQUIREMENT

Keep this future use case in mind:

We will later build a Lantern UI that displays an execution graph while a
run is happening.

The UI will receive events such as:

    step_started
    step_completed
    step_failed
    transition
    retry_started
    run_completed

and progressively construct the visualization.

During execution:

    RUNNING

After execution:

    COMPLETED / FAILED / REJECTED

The graph should represent what ACTUALLY happened.

Therefore:

    Runtime event stream
            ↓
       execution graph
            ↓
          UI

NOT:

    Runtime
       ↓
    scrape logs
       ↓
    guess graph

The event model is the API boundary for that future UI.

# ================================================== 17. DO NOT BUILD THESE YET

Do NOT implement:

- execution graph UI
- React frontend
- web dashboard
- YAML flows
- visual flow editor
- memory
- experience
- learning
- autonomous flow generation
- advanced state-machine features
- complex event infrastructure
- external event databases

This task is ONLY:

    Run
    +
    Structured Events
    +
    Run Summary
    +
    Graph-ready execution history

# ================================================== 18. SUCCESS CRITERIA

When this is complete, I should be able to run:

    run = runtime.run(my_agent)

and reliably answer:

    What happened?

    Which steps ran?

    In what order?

    Which steps failed?

    Which attempts were retries?

    Which transitions actually happened?

    Why did recovery happen?

    Did a contract fail?

    Did a human approval occur?

    Did the run complete or fail?

    How long did it take?

And a future UI should be able to answer all of those questions using the
structured Run/Event data without inspecting internal Runtime implementation.

# ================================================== 19. FINAL REPORT

After implementation:

1. Explain the Run abstraction.
2. Explain the Event model.
3. Explain how it integrates with existing tracing.
4. Explain how retries/Goto/contracts appear in the event stream.
5. Explain how the future execution graph can consume the events.
6. List modified files.
7. List tests added.
8. Run the complete test suite.
9. Report exact test results.
10. Report any compatibility concerns.

Keep the implementation focused.

The goal is NOT to make Lantern better at constructing agent graphs.

The goal is to make Lantern exceptionally good at answering:

    "What actually happened during this agent run?"
