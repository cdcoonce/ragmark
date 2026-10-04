#!/usr/bin/env python3
"""Check the literal Track D absorption reference criterion (#173)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

VAULT_SHIMS = frozenset({".claude/scripts/semantic_index.py", ".claude/scripts/vault_mcp.py"})
WORKSHOP_ENGINE = "plugins/workbench/machinery/engine"
WORKSHOP_SHIMS = frozenset(
    {f"{WORKSHOP_ENGINE}/semantic_index.py", f"{WORKSHOP_ENGINE}/vault_mcp.py"}
)


def scan(root: Path, allowed_paths: frozenset[str]) -> tuple[list[str], list[str]]:
    findings = []
    errors = []
    for directory, directories, filenames in os.walk(
        root, onerror=lambda error: errors.append(str(error))
    ):
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in directories[:]:
            path = Path(directory) / name
            if path.is_symlink():
                errors.append(f"{path}: symlink makes scan incomplete")
                directories.remove(name)
        for filename in sorted(filenames):
            if filename == ".git":
                continue
            path = Path(directory) / filename
            if path.is_symlink():
                errors.append(f"{path}: symlink makes scan incomplete")
                continue
            try:
                if not path.is_file():
                    errors.append(f"{path}: not a regular file; scan incomplete")
                    continue
                content = path.read_bytes()
            except OSError as error:
                errors.append(f"{path}: {error}")
                continue
            if b"\x00" in content or path.relative_to(root).as_posix() in allowed_paths:
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                if b"fastembed" in line:
                    findings.append(f"{path}:{number}")
    return findings, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", required=True, type=Path)
    parser.add_argument("--workshop-root", required=True, type=Path)
    args = parser.parse_args()
    for name, root in (("--vault-root", args.vault_root), ("--workshop-root", args.workshop_root)):
        if root.is_symlink():
            parser.error(f"{name} must not be a symlink: {root}")
        if not root.is_dir():
            parser.error(f"{name} must be an existing directory: {root}")
    if args.vault_root.resolve() == args.workshop_root.resolve():
        parser.error("--vault-root and --workshop-root must be distinct directories")
    if not (args.workshop_root / WORKSHOP_ENGINE).is_dir():
        parser.error(f"--workshop-root must contain {WORKSHOP_ENGINE}")
    vault_findings, vault_errors = scan(args.vault_root, VAULT_SHIMS)
    workshop_findings, workshop_errors = scan(args.workshop_root, WORKSHOP_SHIMS)
    findings = vault_findings + workshop_findings
    errors = vault_errors + workshop_errors
    if findings:
        print("FAIL: references outside the documented shim paths:")
        print("\n".join(findings))
    if errors:
        print("ERROR: incomplete scan:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 2
    if findings:
        return 1
    print("PASS: no references outside the documented shim paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
