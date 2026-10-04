"""Behavior tests for real-YAML frontmatter parsing and embedding normalization."""

from __future__ import annotations

import pytest

import ragmark.parse as parse_module
from ragmark.fences import find_fences
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


def test_parse_note_crlf_frontmatter_matches_lf_twin() -> None:
    text = "---\r\ndescription: A note\r\ntags: [x, y]\r\n---\r\nbody text"

    meta, body = parse_note(text)

    assert meta == NoteMeta("A note", ("x", "y"), ())
    assert body == "body text"


def test_parse_note_crlf_body_normalized_to_lf() -> None:
    frontmatter_text = (
        "---\r\ndescription: A note\r\n---\r\nline one\r\nline two\r\n\r\nline three\r\n"
    )
    no_frontmatter_text = "line one\r\nline two\r\n\r\nline three\r\n"

    _, frontmatter_body = parse_note(frontmatter_text)
    _, no_frontmatter_body = parse_note(no_frontmatter_text)

    assert "\r" not in frontmatter_body
    assert "\r" not in no_frontmatter_body
    assert no_frontmatter_body == "line one\nline two\n\nline three\n"


def test_parse_note_lf_frontmatter_unchanged() -> None:
    text = "---\ndescription: A note\ntags: [x, y]\n---\nline one\n\nline two\n"

    meta, body = parse_note(text)

    assert meta == NoteMeta("A note", ("x", "y"), ())
    assert body == "line one\n\nline two\n"


def test_parse_note_lone_cr_left_unchanged() -> None:
    text = "---\ndescription: d\n---\na\rb"

    _, body = parse_note(text)

    assert body == "a\rb"


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


def test_render_preserves_underscore_identifiers_in_prose() -> None:
    assert render_for_embedding("see semantic_index.py for details") == (
        "see semantic_index.py for details"
    )
    assert render_for_embedding("the __init__ method") == "the __init__ method"
    assert render_for_embedding("snake_case_name in prose") == "snake_case_name in prose"
    assert render_for_embedding("a lone 5 * 3") == "a lone 5 * 3"


def test_render_underscore_run_with_no_whitespace_is_not_emphasis() -> None:
    assert render_for_embedding("_oneword_") == "_oneword_"


def test_render_underscore_run_with_whitespace_is_emphasis() -> None:
    assert render_for_embedding("_two words here_") == "two words here"


def test_render_leaves_unpaired_asterisk_untouched() -> None:
    assert render_for_embedding("5 * 3") == "5 * 3"


def test_render_leaves_run_of_four_or_more_delimiters_untouched() -> None:
    assert render_for_embedding("****quad****") == "****quad****"


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


# --- render_for_embedding: shared fence scanner (#157) --------------------

_FENCE_CASES: dict[str, tuple[str, str]] = {
    "a": (
        "intro\n```\nunterminated *x* [[L]]\n```python\n# a comment\n[[real link]]\n```\n",
        "intro\n```\nunterminated *x* [[L]]\n```python\n# a comment\n[[real link]]\n```\n",
    ),
    "b": ("~~~\n[[fake]]\n# comment\n~~~", "~~~\n[[fake]]\n# comment\n~~~"),
    "c": (
        "```\n```python\n# kept [[k]]\n```\nx [[L]]",
        "```\n```python\n# kept [[k]]\n```\nx L",
    ),
    "d1": (
        "```\n~~~\n# kept [[k]]\n```\nx [[L]]",
        "```\n~~~\n# kept [[k]]\n```\nx L",
    ),
    "d2": (
        "~~~\n```\n# kept [[k]]\n~~~\nx [[L]]",
        "~~~\n```\n# kept [[k]]\n~~~\nx L",
    ),
    "e": (
        "```\n# kept [[k]]\n````\nx [[L]]",
        "```\n# kept [[k]]\n````\nx L",
    ),
    "f": ("intro\n```\n# h [[L]]\n", "intro\n```\nh L\n"),
    "g": ("see ```x``` here", "see ```x``` here"),
    "h": (
        "````\n```\n# kept [[k]]\n````\nx [[L]]",
        "````\n```\n# kept [[k]]\n````\nx L",
    ),
    "i": (
        "a [[L]]\r\n```\r\n# c\r\n```\r\n# H\r\n[[M]]\r\n",
        "a L\r\n```\r\n# c\r\n```\r\nH\r\nM\r\n",
    ),
    "j": (
        "~~~ a`b\n# kept [[k]]\n~~~\nx [[L]]",
        "~~~ a`b\n# kept [[k]]\n~~~\nx L",
    ),
    "k1": (
        "   ```\n# kept [[k]]\n   ```\nx [[L]]",
        "   ```\n# kept [[k]]\n   ```\nx L",
    ),
    "k2": ("    ```\n# H [[L]]\n    ```", "    ```\nH L\n    ```"),
    "l": ("```a`b\n# H [[L]]", "```a`b\nH L"),
    "m": (
        "```\n# kept [[k]]\n``` \t\nafter [[L]]",
        "```\n# kept [[k]]\n``` \t\nafter L",
    ),
    "n": ("```\n`x` [[k]]\n```\ny [[L]]", "```\n`x` [[k]]\n```\ny L"),
    "o": (
        "```\n# a [[a]]\n```\nmid [[m]]\n~~~\n# b [[b]]\n~~~\n",
        "```\n# a [[a]]\n```\nmid m\n~~~\n# b [[b]]\n~~~\n",
    ),
    "p": (
        "a [[L]]\r~~~\r# kept [[k]]\r~~~\rafter [[M]]",
        "a L\r~~~\r# kept [[k]]\r~~~\rafter M",
    ),
    "q": (
        "````\nx\n```\n# kept [[k]]\n```\ny [[L]]\n",
        "````\nx\n```\n# kept [[k]]\n```\ny L\n",
    ),
    # A heading right after an LF-terminated closer is still stripped.
    "r": ("```\n# kept\n```\n# H\n", "```\n# kept\n```\nH\n"),
    # The opener line's own text is protected, not only the interior.
    "s": (
        "~~~ *x* [[L]]\n# k [[m]]\n~~~\n",
        "~~~ *x* [[L]]\n# k [[m]]\n~~~\n",
    ),
    # Line breaks other than \n and \r\n follow chunk.py's rstrip("\r\n"):
    # a closer followed by a form feed is not a closer.
    "t": (
        "```\n# k [[m]]\n```\x0c\n# H [[n]]\n",
        "```\nk m\n```\x0c\nH n\n",
    ),
}


@pytest.mark.parametrize("case", list(_FENCE_CASES))
def test_render_fence_cases(case: str) -> None:
    body, expected = _FENCE_CASES[case]

    assert render_for_embedding(body) == expected


def test_render_fence_case_n_leaves_no_placeholder() -> None:
    assert "\x00" not in render_for_embedding(_FENCE_CASES["n"][0])


def test_render_uses_find_fences_for_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _FENCE_CASES["b"][0]
    monkeypatch.setattr(parse_module, "find_fences", lambda lines: ([], []))

    assert render_for_embedding(body) == "~~~\nfake\ncomment\n~~~"


@pytest.mark.parametrize("case", list(_FENCE_CASES))
def test_render_keeps_every_fenced_line_verbatim(case: str) -> None:
    body = _FENCE_CASES[case][0]
    lines = [line.rstrip("\r\n") for line in body.splitlines(keepends=True)]
    fences, _ = find_fences(lines)
    rendered = render_for_embedding(body)

    for start, end in fences:
        for line in lines[start : end + 1]:
            assert line in rendered


def test_render_drops_lookalike_placeholder_nuls_without_duplicating_code_span() -> None:
    body = "lookalike \x000\x00 mid and `real span`"

    assert render_for_embedding(body) == "lookalike 0 mid and `real span`"


def test_render_does_not_raise_on_out_of_range_lookalike_placeholder() -> None:
    assert render_for_embedding("x \x0099\x00 y") == "x 99 y"


def test_render_drops_nuls_inside_fenced_block() -> None:
    body = "```\na\x00b [[x]]\n# h\n```"

    assert render_for_embedding(body) == "```\nab [[x]]\n# h\n```"


def test_render_drops_lone_nul_adjacent_to_code_span() -> None:
    assert render_for_embedding("\x001`c`") == "1`c`"
