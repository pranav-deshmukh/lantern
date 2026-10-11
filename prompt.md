TASK: Implement "IDE handoff" for Lantern as a purely additive, opt-in
subpackage. It lets any flow step be executed by a human running Cursor,
Copilot, Claude Code or Codex (file-based, no API key, no automation of the
IDE), adds an orchestrator-to-Goto bridge, and adds a generic deterministic
check step that sends work back with the exact violations.

PRODUCT RULE (most important): Lantern is multi-platform. Normal Python
agents, API-driven agents and wrapped CLI agents must keep working exactly as
they do today. This feature only exists for a user who imports it:

    from harness import Harness, Flow, Step                  # unchanged
    from harness.ide_handoff import make_ide_handoff_step    # opt-in

A single Flow can mix worker types: a plain Python step, then a human
handoff step, then a Python check step, with loop-back between them. A step
is just a worker. Do NOT add any global "platform" or "cursor mode" switch.

READ FIRST, follow exactly: harness/README.md and the root Readme.md
"Contribution discipline". Narrow scope. Write failing tests first. Never
weaken, edit or delete an existing passing test. Run the real test suite and
paste its actual output before saying done. harness/ must never import from
demos/.

BEFORE WRITING CODE read: core.py (Step, Flow, Runtime, Transition,
IllegalTransitionError, GotoTargetError), routing.py, context.py
(ExecutionContext and how a step opts in via a `context` parameter),
governance.py, and the existing tests and examples. Reuse what exists. Do not
rebuild or duplicate anything. Do not touch harness/harness/agents_for_cursor/
(the API-key path).

ACCEPTED LIMITATION (do not try to fix; no code, comment or doc may imply
otherwise): nothing here guarantees the agent read or obeyed the packet or
bundled rules/skills. Lantern guarantees delivery, sequencing and an audit
trail. Rule compliance is only ever established by deterministic check steps
that inspect the result.

ISOLATION REQUIREMENTS
 - New code lives only in harness/harness/ide_handoff/ (with __init__.py).
 - Do NOT modify harness/__init__.py. Do not re-export anything from the
   top-level package.
 - stdlib only. Imports allowed: the standard library and harness.* modules.
   No new dependencies, no pyproject changes except none.
 - Cross-platform: must work on Windows and Linux. Use pathlib, no shell, no
   symlinks, no hardcoded path separators. Read artifacts as utf-8-sig so a
   BOM written by a Windows editor does not break JSON parsing.

MODULES

1. ide_handoff/packet.py
   compose_ide_packet(task, context=None, *, step_name, run_id, packet_id,
   artifact_path, extra_instructions=None, invoke_hint=None, feedback=None)
   -> str
   One markdown string with, in order: step name, run id, packet_id,
   invoke_hint (only if given), the exact artifact path to write, the bundled
   rules/skills text (only if context is given and non-empty),
   extra_instructions (only if given), feedback under a heading like "Fix
   these before finishing" (only if given), then the task (json.dumps
   indent=2, default=str unless already a str). The packet must instruct the
   agent: write the result as a single JSON OBJECT to the exact artifact path,
   include "packet_id" with the exact value above, and include
   "changed_files" (list of workspace-relative paths) when it edited files.

2. ide_handoff/agent.py
   IdeHandoffConfig dataclass: workspace (str|Path), run_id (str),
   packet_root (default ".lantern/handoff"), extra_instructions (str|None),
   invoke_hint (str|None, static text such as "@migration-orchestrator
   migrate page X", no templating), poll_seconds (float, default 1.0),
   timeout_seconds (float|None, default None = wait forever),
   partial_write_grace_seconds (float, default 2.0).
   Note in the docstring: config.run_id must equal the run_id given to
   Runtime, and the step_name must equal the Step's name, so resume finds the
   same directory.
   IdeHandoffError(RuntimeError), IdeHandoffTimeout(IdeHandoffError).

   IdeHandoffStep(step_name, config, *, artifact_waiter=None, sleep=None,
   clock=None, notify=None):
   injectable sleep, clock and notify so tests never really sleep or print.
   notify defaults to print.
   - write_packet(task, context=None) -> Path: writes
     <workspace>/<packet_root>/<run_id>/<step_name>/packet.md
   - wait_for_artifact(...) -> dict: polls <same dir>/artifact.json
   - run(task, context=None) -> Any: the function assigned as a Step's
     `function`. It must work with zero changes to Step or Runtime
     (including the `context` opt-in).
   make_ide_handoff_step(step_name, config, **kwargs) -> Callable (the bound
   run method, directly usable as Step(name, fn, rules_files=[...])).
   new_run_id() -> short uuid4 hex.

   INPUT CONVENTION: if the task passed to run() is a dict containing both
   "task" and "feedback", treat "task" as the original task and "feedback" as
   the retry feedback (rendered under the Fix-these heading). Any other input
   is the task as-is. This is how check steps send work back, and it is what
   prevents loop-backs from nesting payloads inside payloads.

   RETURN SHAPE: the parsed artifact dict, plus one key added by Lantern:
   "handoff": {"step_name", "packet_id", "original_task"}. Artifacts must be
   JSON objects; any other JSON type raises IdeHandoffError naming the path.

   STALE-ARTIFACT RULE (main design requirement; implement all of it). The
   same step can be entered more than once in one run (a check step sends the
   flow back with Goto) and a crashed run can be resumed. These must be told
   apart.
   a. Each fresh visit gets a new packet_id (uuid4 hex). A state file
      <dir>/current.json records {packet_id, task_hash, consumed}. task_hash
      is a stable hash of the full input (json.dumps sort_keys, default=str).
      Write current.json atomically (temp file, then os.replace).
   b. RESUME: on entry, if current.json exists with the same task_hash and
      consumed == false, reuse that packet_id and do not write a new packet
      (if packet.md is missing, rewrite it with the same packet_id). An
      artifact that already exists for that packet_id is accepted, so work
      finished while the process was down is picked up.
   c. NEW VISIT: otherwise (no state, different task_hash, or consumed ==
      true) generate a new packet_id and write a new packet. Identical task
      text on a later visit is still a new visit once consumed == true.
   d. Accept an artifact only if its "packet_id" equals the current packet_id.
      A parsed artifact with a different packet_id is stale: ignore it and
      keep waiting. An artifact with no "packet_id" raises IdeHandoffError
      naming the artifact path and saying the field is required (agent
      non-compliance must be loud, not silently waited on).
   e. After a matching artifact is read, set consumed = true and rename the
      artifact to artifact.consumed-<packet_id>.json so a later visit can
      never read it. Use os.replace; on PermissionError (a Windows editor may
      briefly hold the file) retry a few times using the injected sleep, then
      raise IdeHandoffError naming the path.
   f. Known window: if the process dies after reading the artifact but before
      Runtime writes its checkpoint, the resumed step starts a new visit and
      waits again. That fails safe (waits) rather than returning stale data.
      Document this in a code comment. Do not try to remove it.
   g. Partial writes: invalid JSON is "not ready yet". Re-poll until
      partial_write_grace_seconds have elapsed (injected clock) since the file
      first appeared, then raise IdeHandoffError naming the artifact path.
   h. Timeout: raise IdeHandoffTimeout naming the artifact path.
   i. When a new visit starts waiting, call notify(...) once with: step name,
      packet path, expected artifact path, and invoke_hint if set.

3. ide_handoff/handoff_decision.py
   HandoffDecisionError(ValueError).
   goto_from_handoff(artifact: dict, *, valid_step_names: set[str]) -> Goto
   Expects artifact["next_step"] (str) and optional artifact["payload"]. If
   payload is absent, the payload is the artifact without the keys
   "next_step", "packet_id" and "handoff" (document this). If next_step is not
   in valid_step_names raise HandoffDecisionError naming the invalid value AND
   the valid set. Never fall back to a default step.
   make_orchestrator_step(step_name, config, valid_step_names, **kwargs) ->
   Callable: IdeHandoffStep.run composed with goto_from_handoff, returning a
   validated Goto.

4. ide_handoff/checks.py (generic deterministic verification; this is where
   rule compliance is actually checked)
   PatternRule(name, pattern (regex string), mode ("forbid" or "require"),
   glob (fnmatch pattern on the workspace-relative posix path), message=None).
   Ship no domain-specific rules; callers define them.
   make_pattern_check_step(rules, *, base_dir, retry_target,
   files_key="changed_files", files_provider=None) -> Callable
   Input is the dict returned by a handoff step. File list = files_provider(
   input) if given, else input[files_key]. Provide files_provider so callers
   can list files from a source they trust (for example git diff) instead of
   the agent's self-report. Document that a self-reported list can omit files.
   For each listed file matching a rule's glob (read as utf-8,
   errors="replace"):
   - forbid: every match is a violation (file, line number, rule name,
     matched text, message)
   - require: a file with no match is a violation (file, rule name, message)
   A rule with no matching files produces no violation (document this).
   A missing or unreadable file is itself a violation, never a crash.
   No violations: return the input unchanged.
   Violations: return Goto(retry_target, {"task": <input["handoff"][
   "original_task"] if present else None>, "feedback": <readable multi-line
   violation summary naming each file, line and rule>, "violations": [...]}).
   This payload shape is exactly the handoff INPUT CONVENTION above. Pure
   Python: no LLM, no subprocess, no network.

5. ide_handoff/__init__.py exports: compose_ide_packet, IdeHandoffConfig,
   IdeHandoffError, IdeHandoffTimeout, IdeHandoffStep, make_ide_handoff_step,
   new_run_id, HandoffDecisionError, goto_from_handoff, make_orchestrator_step,
   PatternRule, make_pattern_check_step.

TESTS FIRST: harness/tests/test_ide_handoff.py, in the style of
test_context.py and test_harness_facade.py. Use fake waiters, injected
sleep/clock/notify, and tmp_path. Required tests:

 Isolation
 - `import harness` in a fresh subprocess (sys.executable) does not put
   "harness.ide_handoff" in sys.modules.
 - Every import in harness/ide_handoff/*.py (parsed with ast) is stdlib
   (sys.stdlib_module_names) or harness.*.
 - Hybrid flow through the real Runtime: a plain Python step, then a handoff
   step with a fake waiter, then a pattern check step, all in one Flow; it
   completes and the Python steps behave exactly as without the new package.

 Packet
 - Contains task, step name, packet_id, artifact path, invoke_hint when set.
 - Omits the context section when context is None; includes bundled
   rules/skills text when given; includes the feedback section only when
   feedback is given.
 - End to end through a real Flow + Runtime: rules_files content appears in
   the written packet.md, and the written file contains the task text.

 Stale / resume
 - Visit 1 completes (artifact consumed). Visit 2 of the same step via a Goto
   loop-back does NOT return visit 1's artifact; it waits and accepts the new
   one. Cover both different task text and IDENTICAL task text.
 - A stale artifact with a different packet_id is ignored, not returned.
 - An artifact with no packet_id raises IdeHandoffError naming the path.
 - A JSON array or string artifact raises IdeHandoffError naming the path.
 - Resume: the wait is interrupted (waiter raises) before any artifact; call
   again with the same input: same packet_id reused, packet.md not rewritten,
   and an artifact written in the meantime for that packet_id is accepted.
 - Artifact written with a UTF-8 BOM parses correctly.
 - Rename retry: a simulated PermissionError on the first os.replace succeeds
   on retry; persistent failure raises IdeHandoffError.

 Partial write / timeout
 - First poll sees truncated JSON, a later poll sees valid JSON: returns it.
 - Truncated JSON that never completes raises IdeHandoffError after the grace
   period (injected clock, no real sleep).
 - Timeout raises IdeHandoffTimeout naming the artifact path and finishes in
   well under a second.
 - notify is called once per new visit with the packet and artifact paths.

 Orchestrator
 - goto_from_handoff: valid next_step gives the correct target and payload;
   invalid next_step raises HandoffDecisionError naming both the bad value and
   the valid set; the default payload excludes next_step, packet_id, handoff.
 - make_orchestrator_step through a real three-step Flow + Runtime: the
   artifact names the second step as next_step with a skip-the-first payload;
   assert Runtime actually jumps there (same pattern as test_routing.py).
 - If the Flow declares transitions and the orchestrator picks an undeclared
   step, Runtime raises the existing IllegalTransitionError (do not catch or
   reinterpret it).
 - Jumping to a name not in the flow still raises GotoTargetError from core.py.

 Pattern checks
 - forbid reports file + line + rule; require reports a file lacking the
   pattern; clean files pass through unchanged; a missing file is a violation;
   a rule whose glob matches nothing produces no violation; files_provider
   overrides the self-reported list (a file the agent did not report is still
   checked).
 - The returned Goto payload has "task", "feedback" and "violations".
 - Full loop: Flow [handoff step (fake waiter) -> pattern check step] where the
   first artifact violates a forbid rule. The check sends it back; the second
   packet.md contains the exact violation text; the second artifact is clean;
   the flow completes. Assert the trace shows the loop-back and that the
   second visit used a different packet_id.
 - Three consecutive loop-backs do not nest: the third packet's task is still
   the original task, not a task containing earlier payloads.

EXAMPLE (run by hand, not part of the automated suite):
harness/examples/ide_handoff_demo.py: a Flow of a handoff step followed by a
pattern check step, wired with rules_files from
harness/examples/context_bundling/*.md and two illustrative PatternRules (one
forbid, one require, commented as examples of "conventions you want
verified"). It uses an invoke_hint, prints the packet and artifact paths, and
is meant to be run by a human who drops an artifact.json by hand and watches
the loop.

DOCS: add ONE section to harness/README.md describing this path honestly:
opt-in import; works alongside normal agents in one Flow; guarantees delivery,
sequencing and deterministic post-checks; does not guarantee the agent
complied; what the checks verify and the per-flow business logic remain the
caller's responsibility. No marketing language implying a no-code solution.

EXPLICIT NON-GOALS (do not build these, however reasonable they seem
mid-work):
 - Any change to core.py, routing.py, governance.py, flow_loader.py,
   harness/__init__.py, pyproject.toml, or any existing test.
 - Any "paused for a human" versus "crashed" distinction in Runtime or the
   trace (separate, later, higher-risk unit).
 - Automatic opening or driving of Cursor or Copilot.
 - cursor-sdk / CURSOR_API_KEY usage.
 - New Pydantic schemas for any specific domain.
 - First-class YAML support for handoff steps.
 - Version bumps or publishing.

DONE MEANS: the full existing suite plus the new tests pass, the actual
pytest output is pasted, no existing file other than harness/README.md is
modified, and `git status` shows only the new ide_handoff/ package, the new
test file, the new example, and the README section.