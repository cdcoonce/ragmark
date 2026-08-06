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
_RUN_RE = re.compile(r"\*+|_+")
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


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _strip_emphasis(text: str) -> str:
    """Strip paired emphasis delimiters, leaving unpaired runs and identifiers alone.

    Narrows the-vault#136 decision 5.3 per the-vault issue #12: a run of one to three
    `*`/`_` is emphasis only when closed by an identical run whose enclosed content has
    no leading/trailing whitespace, doesn't cross a blank line, and — for `_` only — does
    contain whitespace somewhere (an underscore run around a single token, e.g.
    `snake_case` or `__init__`, is an identifier, not emphasis). Runs of four or more
    delimiters are never emphasis, and a run immediately preceded by a word character can
    never open emphasis. Pairing is a single left-to-right, non-recursive pass: the
    leftmost eligible opener takes the nearest identical run as its closer, and content
    inside a formed pair is not re-scanned for further emphasis.
    """
    runs = [(m.start(), m.end(), m.group(0)[0], len(m.group(0))) for m in _RUN_RE.finditer(text)]
    dead: set[int] = set()
    strip: set[int] = set()

    for i, run in enumerate(runs):
        if i in dead or run[3] > 3:
            continue
        preceding = text[run[0] - 1] if run[0] > 0 else ""
        if _is_word_char(preceding):
            continue

        closer = next(
            (
                k
                for k in range(i + 1, len(runs))
                if k not in dead and runs[k][2] == run[2] and runs[k][3] == run[3]
            ),
            None,
        )
        if closer is None:
            continue

        content = text[run[1] : runs[closer][0]]
        if not content or content[0].isspace() or content[-1].isspace():
            continue
        if "\n\n" in content:
            continue
        if run[2] == "_" and not any(c.isspace() for c in content):
            continue

        strip.add(i)
        strip.add(closer)
        dead.update(range(i, closer + 1))

    if not strip:
        return text

    pieces = []
    cursor = 0
    for idx, run in enumerate(runs):
        pieces.append(text[cursor : run[0]])
        if idx not in strip:
            pieces.append(text[run[0] : run[1]])
        cursor = run[1]
    pieces.append(text[cursor:])
    return "".join(pieces)


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
    stripped = _strip_emphasis(stripped)

    return _PLACEHOLDER_RE.sub(lambda m: stashed[int(m.group(1))], stripped)
