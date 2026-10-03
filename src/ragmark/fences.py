"""The one code-fence scanner for the engine (issue #108).

`chunk.py` now and `parse.py` after #157 both need to know where a fenced code
block starts and ends. This module is that single definition. It is a leaf: it
imports nothing from ragmark, because `chunk.py` imports `parse.py` and so
`parse.py` could not import from `chunk.py`.

Semantics:
- Opener: 0-3 spaces, then a run of >=3 backticks or tildes, then an optional
  info string. A backtick opener whose info string contains a backtick is not
  a fence. A tilde opener's info string may contain anything.
- Closer: 0-3 spaces, then a run of the same character at least as long as the
  opener, then only spaces or tabs. Anything else is fence content.
- Inside an open fence every other line is content.
- An opener that never closes is demoted to plain text and scanning restarts on
  the line after it, so one stray marker cannot hide the headings after it.
"""

from __future__ import annotations

import re

_OPENER_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CLOSER_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


def find_fences(lines: list[str]) -> tuple[list[tuple[int, int]], list[int]]:
    """Return the closed fences as (open, close) 0-based inclusive line indices,
    and the indices of openers demoted for never closing.

    `lines` must already have their line endings removed.
    """
    fences: list[tuple[int, int]] = []
    demoted: list[int] = []
    index = 0
    while index < len(lines):
        opener = _OPENER_RE.match(lines[index])
        if opener is None or not _is_fence_opener(opener):
            index += 1
            continue
        close = _find_closer(lines, index + 1, opener.group(1))
        if close is None:
            demoted.append(index)
            index += 1
            continue
        fences.append((index, close))
        index = close + 1
    return fences, demoted


def unterminated_fence_line(body: str) -> int | None:
    """1-based line number of the lowest demoted opener in `body`, or None."""
    lines = [line.rstrip("\r\n") for line in body.splitlines(keepends=True)]
    _, demoted = find_fences(lines)
    return demoted[0] + 1 if demoted else None


def _is_fence_opener(match: re.Match[str]) -> bool:
    run, info = match.group(1), match.group(2)
    return not (run[0] == "`" and "`" in info)


def _find_closer(lines: list[str], start: int, run: str) -> int | None:
    for index in range(start, len(lines)):
        closer = _CLOSER_RE.match(lines[index])
        if closer is None:
            continue
        close_run = closer.group(1)
        if close_run[0] == run[0] and len(close_run) >= len(run):
            return index
    return None
