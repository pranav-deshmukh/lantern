"""Run the real DeepSeek-backed summarize flow and print its trace.

Usage:
    python examples/run_summarize.py [optional text to summarize]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness import Runtime, load_flow
from harness.trace_viewer import print_trace


DEFAULT_TEXT = (
    "The harness package executes ordered Python steps with contracts, "
    "governance, tracing, and declarative YAML flows."
)


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT
    flow = load_flow(str(Path(__file__).with_name("summarize_flow.yaml")))
    trace_path = Path(__file__).with_name("summarize_trace.jsonl")

    runtime = Runtime(
        trace_path=trace_path,
        max_retries=0,  # Do not auto-retry a paid external API call.
        retry_delay=0,
    )
    result = runtime.run(flow, {"text": text})

    print("Result:", result.model_dump())
    print()
    print_trace(trace_path)


if __name__ == "__main__":
    main()
