"""Behavior tests for real-YAML frontmatter parsing and embedding normalization."""

from __future__ import annotations

import pytest

from ragmark.model import NoteMeta
from ragmark.parse import FrontmatterError, parse_note, render_for_embedding

# --- parse_note ---------------------------------------------------------


def test_parse_note_extracts_tags_aliases_description() -> None:
    text = (
        "---\ndescription: A note about things\ntags: [x, y]\naliases: [Foo, Bar]\n---\nbody text"
    )

    meta, body = parse_note(text)

    assert meta == NoteMeta("A note about things", ("x", "y"), ("Foo", "Bar"))
    assert body == "body text"


def test_parse_note_no_frontmatter_returns_text_unchanged() -> None:
    text = "# Just a note\n\nNo frontmatter here."

    meta, body = parse_note(text)

    assert meta == NoteMeta(None, (), ())
    assert body == text


def test_parse_note_malformed_yaml_raises_frontmatter_error() -> None:
    text = "---\ntags: [unclosed\n---\nbody"

    with pytest.raises(FrontmatterError):
        parse_note(text)


def test_parse_note_empty_frontmatter_block() -> None:
    text = "---\n---\nbody"

    meta, body = parse_note(text)

    assert meta == NoteMeta(None, (), ())
    assert body == "body"


# --- render_for_embedding -----------------------------------------------


def test_render_wikilink_bare_form() -> None:
    assert render_for_embedding("see [[Note]] for details") == "see Note for details"


def test_render_wikilink_alias_form() -> None:
    assert render_for_embedding("see [[Note|alias]] for details") == "see alias for details"


def test_render_strips_headings_and_emphasis() -> None:
    text = "# Heading\n\nSome *italic*, **bold**, and ***bold-italic*** text."

    result = render_for_embedding(text)

    assert result == "Heading\n\nSome italic, bold, and bold-italic text."


def test_render_preserves_strikethrough() -> None:
    assert render_for_embedding("~~struck~~ text") == "~~struck~~ text"


def test_render_preserves_fenced_code_block() -> None:
    text = "prose\n\n```python\nx = [[fake]]\n# a comment\ny = 5 * 3\n```\n\nmore prose"

    result = render_for_embedding(text)

    assert "```python\nx = [[fake]]\n# a comment\ny = 5 * 3\n```" in result


def test_render_preserves_inline_code_span() -> None:
    text = "run `# comment [[fake]] 5 * 3` now"

    result = render_for_embedding(text)

    assert result == "run `# comment [[fake]] 5 * 3` now"


def test_render_mixed_prose_and_code_survives_intact() -> None:
    text = (
        "# Heading\n\n"
        "Some *emphasis* and [[Note|alias]] in prose.\n\n"
        "```\n"
        "# a shell comment\n"
        "x = [[fake]]\n"
        "y = 5 * 3\n"
        "```\n\n"
        "Inline code: `# comment [[fake]] 5 * 3` end.\n"
    )

    result = render_for_embedding(text)

    assert (
        result == "Heading\n\n"
        "Some emphasis and alias in prose.\n\n"
        "```\n"
        "# a shell comment\n"
        "x = [[fake]]\n"
        "y = 5 * 3\n"
        "```\n\n"
        "Inline code: `# comment [[fake]] 5 * 3` end.\n"
    )
