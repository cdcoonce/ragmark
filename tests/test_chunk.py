"""Behavior tests for the hardened heading-split chunker (the-vault#140 d1).

Two conservation assertions run over both synthetic adversarial inputs and
the real fixture vault:

(a) character conservation — chunk text is an exact partition of
    `render_for_embedding(body)` plus the raw description; no dropped or
    duplicated characters.
(b) heading coverage — every heading section of the raw body is represented
    by at least one chunk carrying that section's heading.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from ragmark import parse
from ragmark.chunk import HARD_TOKEN_CEILING, chunk_note
from ragmark.model import NoteMeta

FIXTURES_VAULT = Path(__file__).parent / "fixtures" / "gating" / "vault"


def fake_count_tokens(text: str) -> int:
    """char/4, ceiling-rounded — scales with length even for space-free text,
    unlike a word-count fake (which a 10k-char spaceless blob would dodge)."""
    return math.ceil(len(text) / 4) if text else 0


_HEADING_LINE_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*?)\s*$")
_FENCE_TOGGLE_RE = re.compile(r"^\s*```")


def headings_outside_fences(body: str) -> list[str]:
    """Independent oracle: heading text for every `#`-line not inside a
    fenced code block, walked line-by-line without reusing chunk.py's
    own splitter."""
    headings = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE_TOGGLE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_LINE_RE.match(line)
        if match is not None:
            headings.append(match.group(2))
    return headings


def assert_ceiling_and_token_count(chunks, count_tokens) -> None:
    for c in chunks:
        assert count_tokens(c.text) <= HARD_TOKEN_CEILING
        assert c.token_count == count_tokens(c.text)


def assert_conservation(chunks, body: str, meta: NoteMeta) -> None:
    expected = len(parse.render_for_embedding(body)) + len(meta.description or "")
    assert sum(len(c.text) for c in chunks) == expected


def assert_heading_coverage(chunks, body: str) -> None:
    present = {c.heading for c in chunks}
    for heading in headings_outside_fences(body):
        assert heading in present


# --- adversarial inputs -------------------------------------------------


def _unbroken_10k_paragraph() -> str:
    return "# Big\n\n" + ("x" * 10_000) + "\n"


def _no_sentence_boundaries() -> str:
    return "# Words\n\n" + " ".join(["word"] * 2000) + "\n"


def _fenced_hash_mixed_with_prose() -> str:
    return (
        "# Heading\n\n"
        "Some prose before the fence.\n\n"
        "```bash\n"
        "# this looks like a heading but is inside a fence\n"
        "echo hi\n"
        "```\n\n"
        "Some prose after the fence.\n"
    )


ADVERSARIAL_BODIES = [
    pytest.param(_unbroken_10k_paragraph(), id="unbroken-10k-paragraph"),
    pytest.param(_no_sentence_boundaries(), id="no-sentence-boundaries"),
    pytest.param(_fenced_hash_mixed_with_prose(), id="fenced-hash-mixed-with-prose"),
]


@pytest.mark.parametrize("body", ADVERSARIAL_BODIES)
def test_adversarial_inputs_respect_ceiling_and_conservation(body: str) -> None:
    meta = NoteMeta(None, (), ())
    chunks = chunk_note("adversarial.md", body, meta, count_tokens=fake_count_tokens)

    assert_ceiling_and_token_count(chunks, fake_count_tokens)
    assert_conservation(chunks, body, meta)
    assert_heading_coverage(chunks, body)


def test_fenced_block_heading_is_not_split() -> None:
    body = _fenced_hash_mixed_with_prose()
    chunks = chunk_note("fenced.md", body, NoteMeta(None, (), ()), count_tokens=fake_count_tokens)

    assert all(c.heading == "Heading" for c in chunks)
    assert any("```bash" in c.text for c in chunks)


# --- fixture vault --------------------------------------------------------


def fixture_notes() -> list[Path]:
    return sorted(FIXTURES_VAULT.rglob("*.md"))


@pytest.mark.parametrize("note_path", fixture_notes(), ids=lambda p: p.name)
def test_fixture_notes_respect_ceiling_and_conservation(note_path: Path) -> None:
    text = note_path.read_text(encoding="utf-8")
    meta, body = parse.parse_note(text)

    chunks = chunk_note(str(note_path), body, meta, count_tokens=fake_count_tokens)

    assert_ceiling_and_token_count(chunks, fake_count_tokens)
    assert_conservation(chunks, body, meta)
    assert_heading_coverage(chunks, body)


# --- description as chunk 0 -----------------------------------------------


def test_description_becomes_standalone_chunk_zero() -> None:
    meta = NoteMeta("A *raw* description", (), ())
    body = "# A\n\nbody text\n"

    chunks = chunk_note("a.md", body, meta, count_tokens=fake_count_tokens)

    assert chunks[0].chunk_id == "a.md#0"
    assert chunks[0].chunk_index == 0
    assert chunks[0].heading is None
    assert chunks[0].parent_ref is None
    assert chunks[0].text == "A *raw* description"  # raw, not rendered
    assert chunks[0].token_count == fake_count_tokens("A *raw* description")


def test_no_description_means_no_chunk_zero_reservation() -> None:
    meta = NoteMeta(None, (), ())
    body = "# A\n\nbody text\n"

    chunks = chunk_note("a.md", body, meta, count_tokens=fake_count_tokens)

    assert chunks[0].heading == "A"


# --- heading / parent_ref format --------------------------------------------


def test_heading_and_parent_ref_breadcrumb() -> None:
    body = "# A\n\nintro\n\n## B\n\ntextB\n\n### C\n\ntextC\n"
    meta = NoteMeta(None, (), ())

    chunks = chunk_note("nested.md", body, meta, count_tokens=fake_count_tokens)

    by_heading = {c.heading: c for c in chunks}
    assert by_heading["A"].parent_ref is None
    assert by_heading["B"].parent_ref == "A"
    assert by_heading["C"].parent_ref == "A > B"


def test_pieces_split_from_one_section_share_heading_and_parent_ref() -> None:
    body = "# A\n\n## Big\n\n" + " ".join(["word"] * 2000) + "\n"
    meta = NoteMeta(None, (), ())

    chunks = chunk_note("split.md", body, meta, count_tokens=fake_count_tokens)

    big_pieces = [c for c in chunks if c.heading == "Big"]
    assert len(big_pieces) > 1
    assert all(c.parent_ref == "A" for c in big_pieces)
