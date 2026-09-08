"""Bring-your-own-agent: wrap an existing class unmodified via Harness.

The agent class below has no knowledge of the harness package: no imports, no
inheritance, no Step/Flow/Contract types. Harness adapts it as-is.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness import Harness
from harness.trace_viewer import print_trace


class GreetingAgent:
    """A plain, harness-unaware agent."""

    def run(self, input):
        return f"processed: {input}"


def main() -> None:
    trace_path = Path(__file__).with_name("bring_your_own_agent_trace.jsonl")
    harness = Harness(
        GreetingAgent(),
        trace_path=trace_path,
        retry_delay=0,
    )

    result = harness.run("some task")

    print("Result:", result)
    print()
    print_trace(trace_path)


if __name__ == "__main__":
    main()
