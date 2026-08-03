"""Note parsing — frontmatter and embedding-surface normalization (owed to slices).

Decisions this module implements (the-vault#140, decision 3):

- Frontmatter is parsed as **real YAML** (the vendored predecessor used a
  naive line parser and silently discarded `tags`/`aliases` — both are
  first-class, filterable metadata here).
- For embedding, markup is stripped: wikilinks render to their display text
  (`[[Note|alias]]` → "alias", `[[Note]]` → "Note"), heading markers and
  emphasis go, code fences are preserved as text. The RAW text is retained by
  the caller for display; only the embedded surface is normalized.
"""

from __future__ import annotations

import re

import yaml

from ragmark.model import NoteMeta

_FRONTMATTER_DELIM = "---"

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+?`")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_HEADING_RE = re.compile(r"^#{1,6}[ \t]+", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"[*_]{1,3}")
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


class FrontmatterError(Exception):
    """Raised when a `---`-delimited frontmatter block fails to parse as YAML.

    `parse_note` never lets this escape uncaught internally — it is raised
    to the caller, which is expected to catch it, index the note with empty
    meta, and surface the defect in the refresh report (owed to the index
    slice; this module does not do that catching itself).
    """


def parse_note(text: str) -> tuple[NoteMeta, str]:
    """Split *text* into (frontmatter meta, body).

    A note without frontmatter yields empty meta and the full text as body.
    Malformed YAML raises `FrontmatterError` rather than crashing on a raw
    `yaml.YAMLError` — the caller is expected to catch it, index the note
    with empty meta, and surface the defect in the refresh report.
    """
    if text != _FRONTMATTER_DELIM and not text.startswith(f"{_FRONTMATTER_DELIM}\n"):
        return NoteMeta(None, (), ()), text

    lines = text.split("\n")
    closing_index = next((i for i in range(1, len(lines)) if lines[i] == _FRONTMATTER_DELIM), None)
    if closing_index is None:
        return NoteMeta(None, (), ()), text

    frontmatter_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])

    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise FrontmatterError(str(exc)) from exc

    if not isinstance(data, dict):
        return NoteMeta(None, (), ()), body

    description = data.get("description")
    if not isinstance(description, str):
        description = None

    tags = _as_str_tuple(data.get("tags"))
    aliases = _as_str_tuple(data.get("aliases"))
    return NoteMeta(description, tags, aliases), body


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        return (value,)
    return ()


def render_for_embedding(body: str) -> str:
    """Return the normalized text surface that gets embedded.

    Fenced code blocks and inline code spans are carved out first and left
    byte-for-byte untouched; wikilink, heading, and emphasis stripping run
    only over the remaining prose.
    """
    stashed: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        stashed.append(match.group(0))
        return f"\x00{len(stashed) - 1}\x00"

    protected = _FENCE_RE.sub(_stash, body)
    protected = _INLINE_CODE_RE.sub(_stash, protected)

    def _wikilink_sub(match: re.Match[str]) -> str:
        target, alias = match.group(1), match.group(2)
        return alias if alias is not None else target

    stripped = _WIKILINK_RE.sub(_wikilink_sub, protected)
    stripped = _HEADING_RE.sub("", stripped)
    stripped = _EMPHASIS_RE.sub("", stripped)

    return _PLACEHOLDER_RE.sub(lambda m: stashed[int(m.group(1))], stripped)
