#!/usr/bin/env python3
"""Teeth-check the gating suite by defect re-injection (the-vault#144 d3).

Runs the `gating`-marked tests twice:

1. Normally — they must PASS (exit 0). Pytest exit 5 ("no tests collected")
   fails loudly: an empty gating suite passes trivially and proves nothing —
   an absent row can't prove a detector fires.
2. With `--defang-gate` (conftest disables the context filter) — they must
   FAIL. A gating suite that stays green with the filter off is itself a
   build failure: it means the tests do not actually depend on the gate.

This script is part of the CI gate (see .github/workflows/ci.yml), not a
convention. Exit 0 only when both runs behave.
"""

from __future__ import annotations

import subprocess
import sys

NO_TESTS_COLLECTED = 5


def run_gating(extra_args: list[str]) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "gating", *extra_args],
        capture_output=True,
        text=True,
    )
    tail = "\n".join(result.stdout.strip().splitlines()[-3:])
    print(f"  exit {result.returncode}\n  {tail}\n")
    return result.returncode


def main() -> int:
    print("[teeth] 1/2 gating suite, gate armed (must pass):")
    armed = run_gating([])
    if armed == NO_TESTS_COLLECTED:
        print("[teeth] FAIL: no gating tests collected — an empty suite proves nothing")
        return 1
    if armed != 0:
        print("[teeth] FAIL: gating suite is red with the gate armed")
        return 1

    print("[teeth] 2/2 gating suite, gate DEFANGED (must fail):")
    defanged = run_gating(["--defang-gate"])
    if defanged == 0:
        print("[teeth] FAIL: gating suite stayed green with the filter off — no teeth")
        return 1
    if defanged == NO_TESTS_COLLECTED:
        print("[teeth] FAIL: no gating tests collected in the defanged run")
        return 1

    print("[teeth] OK: suite passes armed and goes red defanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
