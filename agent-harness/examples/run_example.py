"""Run an example YAML flow from the command line.

Usage:
    python examples/run_example.py examples/migration_flow.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness import Runtime, load_flow


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python examples/run_example.py <yaml_path>")
        raise SystemExit(1)

    flow = load_flow(sys.argv[1])
    runtime = Runtime(retry_delay=0)
    result = runtime.run(flow, {})
    print(result)


if __name__ == "__main__":
    main()
