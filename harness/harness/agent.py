"""Beginner-friendly façade over the Runtime/Flow/Step primitives."""

from __future__ import annotations

from typing import Any, Protocol

from .core import Flow, Runtime, Step


class Agent(Protocol):
    """Documentary protocol for a single-input agent.

    This is duck-typing documentation only. An agent does NOT need to inherit
    from this protocol, import it, or reference any Lantern type in its own
    code — any object with a ``run(input)`` method (or any plain callable)
    satisfies the expectation at runtime.
    """

    def run(self, input: Any) -> Any: ...


class Harness:
    """Wrap a single agent/callable or an existing :class:`Flow` behind ``run``.

    ``Harness(agent)`` builds a one-step flow around ``agent.run`` (or the
    callable itself) and delegates to :class:`Runtime`. ``Harness(flow)`` wraps
    a multi-step flow directly. All :class:`Runtime` keyword options are
    accepted and forwarded unchanged, so checkpointing, tracing, retries, run
    ids, and jump limits all keep working.
    """

    def __init__(self, agent_or_flow: Any, **runtime_options: Any) -> None:
        if isinstance(agent_or_flow, Flow):
            self._flow = agent_or_flow
        elif callable(getattr(agent_or_flow, "run", None)):
            self._flow = Flow([Step("agent", agent_or_flow.run)])
        elif callable(agent_or_flow):
            self._flow = Flow([Step("agent", agent_or_flow)])
        else:
            raise TypeError(
                "Harness expects an object with a callable .run() method, a "
                "plain callable, or a Flow instance."
            )
        self._runtime = Runtime(**runtime_options)

    def run(self, input: Any) -> Any:
        """Run the wrapped agent/flow with ``input`` and return its result."""
        return self._runtime.run(self._flow, input)
