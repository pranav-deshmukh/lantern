Absolutely. Give your coding agent this prompt. It is intentionally focused on **Flow enforcement v1** and tells it not to jump ahead into YAML, learning, or unnecessary abstractions.

```text
You are working on Lantern, an open-source Python project that is intended to become a general-purpose agentic flow runtime.

IMPORTANT PRODUCT PRINCIPLE:

The LLM/agent must NOT be responsible for orchestrating the workflow.

The LLM proposes/produces an output.
Lantern owns the workflow state, legal transitions, execution order, retries, failures, and recovery.

The main problem we are solving is:

I previously built a 13-agent workflow in Cursor where an orchestrator LLM was given an MD file describing the workflow. Sometimes the orchestrator simply skipped a step. Rules were also sometimes present in the prompt but not actually followed reliably.

Lantern must make this structurally impossible or at minimum mechanically detectable.

CORE PRINCIPLE:

    "The LLM proposes actions; Lantern controls execution."

Your task is to implement FLOW ENFORCEMENT V1.

==================================================
1. FIRST INSPECT THE EXISTING CODEBASE
==================================================

Before changing anything:

- Inspect the existing Step, Flow, Runtime, Agent, ExecutionContext, Goto, Retry, tracing, checkpointing, contracts, and tests.
- Understand the current public API.
- Do NOT rewrite working architecture unnecessarily.
- Do NOT introduce a parallel workflow system.
- Extend the existing abstractions.
- Preserve backward compatibility wherever reasonably possible.
- Run the existing test suite before making changes so we know the baseline.

Do not start by implementing YAML.

Do not start by implementing memory, learning, experience, or evaluation systems.

This task is specifically about making Flow the authoritative execution abstraction.

==================================================
2. MAKE FLOW THE SOURCE OF TRUTH
==================================================

A Flow should represent the declared workflow independently of the LLM.

Conceptually:

    Flow
      |
      +-- Step A
      |
      +-- Step B
      |
      +-- Step C
      |
      +-- Step D

The Runtime owns the current step.

The agent does NOT choose the next step.

For example:

    classify -> draft -> quality_check -> approve

If quality_check fails:

    quality_check -> draft

The agent should never be able to say:

    "I think we can skip draft and go directly to approve."

Lantern must ignore/reject such an attempt because the Flow does not permit it.

==================================================
3. DEFINE EXPLICIT FLOW TRANSITIONS
==================================================

Inspect the current Flow/Step/Goto implementation and evolve it so that legal transitions are explicit.

We need to be able to represent something conceptually like:

    classify
        -> draft

    draft
        -> quality_check

    quality_check
        -> approve
        -> draft   # recovery path

    approve
        -> END

Do not necessarily copy this exact API if the existing architecture suggests a better one.

The important property is:

    Runtime can determine the legal next states WITHOUT asking the LLM.

A transition should have a clear source and destination.

For example, conceptually:

    Transition(
        source="quality_check",
        target="draft",
        condition="failure"
    )

or an equivalent design that fits Lantern.

Avoid overengineering conditional expressions at this stage.

==================================================
4. RUNTIME MUST OWN THE CURRENT STATE
==================================================

Introduce explicit execution state if the current architecture does not already have it.

Conceptually:

    ExecutionState:
        flow
        current_step
        previous_step
        attempt
        status
        transition_history

The exact implementation should fit the existing architecture.

The Runtime should be able to answer:

    What flow am I executing?
    What step am I currently executing?
    What step did I come from?
    What transitions are legal from here?
    What happened previously?

The current step must come from Lantern's runtime state, not from an LLM response.

==================================================
5. AGENT OUTPUT MUST NOT CONTROL FLOW
==================================================

This is extremely important.

Agents should continue returning their normal outputs.

For example:

    result = agent.run(input)

The result should NOT automatically become:

    {
        "output": ...,
        "next_step": "some_step"
    }

where Lantern blindly follows the requested next_step.

If the existing system supports agent-suggested routing, do NOT let that bypass Flow validation.

If an agent can propose a destination, Lantern must validate it against the declared Flow:

    proposed destination
             |
             v
    Is transition legal?
         /       \
       yes        no
       |           |
    execute      reject

Preferably, the runtime itself should determine the transition whenever possible.

==================================================
6. PREVENT SKIPPED STEPS
==================================================

This is the main reason for this feature.

Given:

    A -> B -> C -> D

the Runtime must NOT allow:

    A -> C

unless the Flow explicitly declares:

    A -> C

Likewise:

    A -> B -> C

must not silently become:

    A -> C

just because an agent decided B was unnecessary.

Create tests proving this.

Example:

    flow = A -> B -> C

Run A.

Attempt to transition directly to C.

Expected:

    Lantern rejects the transition.

The rejection should be deterministic and not dependent on an LLM.

==================================================
7. SUPPORT RECOVERY / GOTO
==================================================

Preserve the existing Goto behavior.

For example:

    classify
      ↓
    draft
      ↓
    quality_check
      |
      | failure
      ↓
    draft
      ↓
    quality_check
      |
      | success
      ↓
    approve

This is a VALID transition because the Flow explicitly permits it.

Make sure Goto does not become a loophole for arbitrary jumps.

For example:

    quality_check -> draft

may be legal.

But:

    quality_check -> random_step

must fail unless explicitly declared.

Existing Goto tests must continue passing.

==================================================
8. STEP CONTRACTS / VERIFICATION
==================================================

Integrate with the existing contract system rather than creating a new parallel validation system.

The conceptual execution lifecycle should become:

    current Step
         |
         v
    prepare execution context
         |
         v
    execute Agent
         |
         v
    obtain output
         |
         v
    verify / contract
         |
       /   \
    pass   fail
     |       |
     |       +--> retry/recovery
     |
     v
    determine legal transition
         |
         v
    next Step

The agent output is not trusted as workflow state.

A failed contract should not advance the flow unless the existing semantics explicitly define another recovery behavior.

==================================================
9. RULES AND SKILLS MUST BE STEP-SCOPED
==================================================

Do NOT solve rules by simply stuffing the entire flow's rules into every prompt.

A Step should be able to declare relevant rules and skills.

Conceptually:

    Step(
        name="draft",
        agent=writer,
        rules=["response_policy", "pii_policy"],
        skills=["response_tone"]
    )

The Runtime should construct the ExecutionContext for that step using the applicable rules/skills.

The agent receives the context relevant to its current step.

Do NOT make every agent responsible for remembering the entire 13-agent workflow.

Lantern knows the entire workflow.

The agent only needs enough context to perform its current responsibility.

==================================================
10. IMPORTANT DISTINCTION: CONTEXT VS ENFORCEMENT
==================================================

Keep this distinction explicit in the architecture.

Rules in ExecutionContext are INFORMATION/INSTRUCTIONS available to the agent.

They are NOT automatically enforcement.

For important rules, enforcement should eventually happen through contracts/validators/evaluators.

For example:

    draft agent
         |
         v
    output
         |
         v
    PII validator
         |
      fail
         |
         v
    Runtime recovery

Do not build a huge evaluator framework in this task.

Just make sure the Flow architecture leaves a clean place for verification to happen.

==================================================
11. ADD FLOW VALIDATION
==================================================

Flow should validate itself before execution.

At minimum detect things such as:

- duplicate step names
- missing transition targets
- missing start step
- invalid Goto targets
- impossible references
- invalid transition source
- malformed flow structure

If practical, also detect unreachable steps.

Do not overengineer graph theory.

The goal is to prevent obviously invalid workflow definitions before runtime execution.

==================================================
12. EXECUTION RESULT / STATE
==================================================

If the current Runtime does not already expose enough information, introduce a minimal execution result/state representation.

We eventually want Lantern to be able to report something like:

    Flow: support_ticket
    Run: 8F32

    ✓ classify
    ✓ draft
    ✗ quality_check
      Contract failed: resolution_required

    ↻ draft
    ✓ quality_check
    ⏳ approve

    Skipped steps: 0
    Recovery transitions: 1

Do NOT build the final CLI dashboard yet.

Just make the underlying state/history available in a clean way.

==================================================
13. TRACE TRANSITIONS
==================================================

Extend the existing tracing system so transitions are observable.

A trace should be able to distinguish:

    step_started
    step_completed
    step_failed
    transition
    retry
    goto/recovery

A transition event should contain enough information to understand:

    source step
    destination step
    reason
    attempt

Example:

    {
        "event": "transition",
        "from": "quality_check",
        "to": "draft",
        "reason": "contract_failure",
        "attempt": 1
    }

Use the existing tracing architecture if possible.

Do not create a second tracing system.

==================================================
14. CHECKPOINTING
==================================================

Ensure checkpoints capture enough state to resume the flow safely.

A checkpoint should not merely say:

    "last function executed = quality_check"

It should preserve enough information for Lantern to know:

    current flow
    current step
    transition history / relevant execution state
    attempts
    existing checkpoint metadata

Do not redesign checkpointing unnecessarily.

Only extend it if needed for authoritative Flow state.

==================================================
15. TESTS ARE CRITICAL
==================================================

Add focused tests proving that Lantern—not the LLM—controls execution.

At minimum implement tests for:

### Test 1: Sequential flow

    A -> B -> C

Expected:

    A, B, C

### Test 2: Skipped step is rejected

Declared:

    A -> B -> C

Attempt:

    A -> C

Expected:

    deterministic transition error

### Test 3: Valid branch

Declared:

    A -> B
    B -> C
    B -> D

A valid condition can select C or D according to the Runtime's transition mechanism.

### Test 4: Invalid branch

Attempt:

    B -> X

Expected:

    deterministic failure

### Test 5: Goto recovery

    A -> B -> C
          ^    |
          |____|

If C fails and recovery says B:

    A -> B -> C -> B -> C

### Test 6: Agent cannot bypass Flow

Create a fake agent that attempts to request/return a destination that would skip a step.

Prove that Lantern does not blindly follow it.

### Test 7: Contract failure

Agent output fails the contract.

Expected:

    flow does not advance as if successful.

### Test 8: Rules are attached to the correct step

Verify that a step receives its declared rules/skills through ExecutionContext.

### Test 9: Trace records transitions

Verify source, destination, reason, and attempt.

### Test 10: Existing compatibility

All existing Lantern tests must still pass.

==================================================
16. DO NOT DO THESE THINGS
==================================================

Do NOT:

- implement YAML yet
- implement a visual editor
- implement memory learning
- implement experience extraction
- implement automatic workflow generation
- add another orchestration LLM
- make an LLM decide whether a transition is legal
- rewrite the existing Runtime from scratch
- introduce unnecessary dependencies
- build a giant state-machine framework
- break the current Step/Flow API unnecessarily
- turn Lantern into a coding-agent sandbox

This task is about one thing:

MAKE FLOW AUTHORITATIVE.

==================================================
17. DESIGN TARGET
==================================================

The resulting architecture should conceptually look like:

                FLOW
                 |
        +--------+--------+
        |        |        |
       A        B        C
        |        |
        |        +----> D
        |
      Runtime
        |
        v
   Current Step
        |
        v
      Agent
        |
        v
      Output
        |
        v
    Verification
        |
     +--+--+
     |     |
   pass   fail
     |     |
     v     v
 Transition Retry/Recovery
     |
     v
Next legal Step

The key point:

    Agent output != workflow control.

    Flow + Runtime = workflow control.

==================================================
18. SUCCESS CRITERIA
==================================================

When you are finished, I should be able to define something conceptually like:

    A -> B -> C

and know that Lantern guarantees:

- A executes before B
- B executes before C
- C cannot execute before B
- an agent cannot silently skip B
- invalid transitions are rejected
- valid recovery transitions work
- contracts can prevent advancement
- rules/skills are attached to the relevant step
- transitions are observable
- execution state can be checkpointed/resumed

The important test is:

"If I give Lantern a 13-step flow, can I trust Lantern to execute the declared flow even if the LLM tries to skip around?"

The answer should become YES because the runtime enforces the graph, rather than because the prompt tells the LLM to behave.

==================================================
19. FINAL REPORT
==================================================

After implementation:

1. Summarize the architecture changes.
2. List the new/modified public APIs.
3. Explain how Flow enforcement prevents skipped steps.
4. Explain how Goto/recovery works.
5. Explain how rules/skills are scoped to steps.
6. List all tests added.
7. Run the complete existing test suite.
8. Report exact test results.
9. Report any backwards-compatibility concerns.
10. Do NOT move on to YAML, evaluation, memory, or experience unless the existing architecture absolutely requires a minimal change for this task.

Focus on correctness and a clean foundation over adding lots of features.
```
