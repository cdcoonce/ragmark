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

from ragmark.model import NoteMeta


def parse_note(text: str) -> tuple[NoteMeta, str]:
    """Split *text* into (frontmatter meta, body).

    A note without frontmatter yields empty meta and the full text as body.
    Malformed YAML is a detected condition, not a crash: the note is indexed
    with empty meta and the defect is surfaced in the refresh report.
    """
    raise NotImplementedError("build slice: frontmatter parsing (the-vault#140 d3)")


def render_for_embedding(body: str) -> str:
    """Return the normalized text surface that gets embedded."""
    raise NotImplementedError("build slice: embedding normalization (the-vault#140 d3)")
