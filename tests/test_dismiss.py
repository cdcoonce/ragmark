"""Cross-reads ragmark.dismiss against graphmark.dismiss for byte-compatibility.

Provenance: graphmark v0.10.1 dismiss.py, the-vault#143 decision 2, 2026-09-26.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import graphmark.dismiss as gdismiss
import pytest

import ragmark.dismiss as rdismiss

DISMISS_SRC = Path(__file__).resolve().parent.parent / "src" / "ragmark" / "dismiss.py"


def _make_notes(root: Path, a_text: str = "a content", b_text: str = "b content") -> None:
    (root / "a.md").write_text(a_text)
    (root / "b.md").write_text(b_text)


def test_ragmark_reads_graphmark_store(tmp_path):
    _make_notes(tmp_path)
    gdismiss.record_dismissal(tmp_path, "a.md", "b.md")

    assert rdismiss.active_dismissed_sigs(tmp_path) == gdismiss.active_dismissed_sigs(tmp_path)


def test_ragmark_write_byte_identical_to_graphmark(tmp_path):
    graphmark_root = tmp_path / "graphmark_root"
    ragmark_root = tmp_path / "ragmark_root"
    graphmark_root.mkdir()
    ragmark_root.mkdir()
    _make_notes(graphmark_root)
    _make_notes(ragmark_root)

    gdismiss.record_dismissal(graphmark_root, "a.md", "b.md")
    rdismiss.record_dismissal(ragmark_root, "a.md", "b.md")

    graphmark_bytes = (graphmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    ragmark_bytes = (ragmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    assert ragmark_bytes == graphmark_bytes


def test_graphmark_reads_ragmark_store(tmp_path):
    _make_notes(tmp_path)
    rdismiss.record_dismissal(tmp_path, "a.md", "b.md")

    assert gdismiss.active_dismissed_sigs(tmp_path) == rdismiss.active_dismissed_sigs(tmp_path)


def test_editing_note_deactivates_dismissal_in_both_readers(tmp_path):
    _make_notes(tmp_path)
    rdismiss.record_dismissal(tmp_path, "a.md", "b.md")
    sig = rdismiss.weaklink_sig("a.md", "b.md")

    (tmp_path / "a.md").write_text("edited content")

    assert sig not in rdismiss.active_dismissed_sigs(tmp_path)
    assert sig not in gdismiss.active_dismissed_sigs(tmp_path)


def test_deleting_note_deactivates_dismissal_in_both_readers(tmp_path):
    _make_notes(tmp_path)
    rdismiss.record_dismissal(tmp_path, "a.md", "b.md")
    sig = rdismiss.weaklink_sig("a.md", "b.md")

    (tmp_path / "b.md").unlink()

    assert sig not in rdismiss.active_dismissed_sigs(tmp_path)
    assert sig not in gdismiss.active_dismissed_sigs(tmp_path)


def test_absent_store_reads_empty(tmp_path):
    assert rdismiss.load_dismissed(tmp_path) == {}
    assert rdismiss.active_dismissed_sigs(tmp_path) == set()


def test_corrupt_store_reads_empty(tmp_path):
    store = tmp_path / rdismiss._DEFAULT_PATH
    store.parent.mkdir(parents=True)
    store.write_text("not json{{{")

    assert rdismiss.load_dismissed(tmp_path) == {}
    assert rdismiss.active_dismissed_sigs(tmp_path) == set()


def test_non_object_store_reads_empty(tmp_path):
    store = tmp_path / rdismiss._DEFAULT_PATH
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps(["not", "an", "object"]))

    assert rdismiss.load_dismissed(tmp_path) == {}
    assert rdismiss.active_dismissed_sigs(tmp_path) == set()


def test_reverse_order_record_yields_sorted_sig_and_matches_graphmark(tmp_path):
    graphmark_root = tmp_path / "graphmark_root"
    ragmark_root = tmp_path / "ragmark_root"
    graphmark_root.mkdir()
    ragmark_root.mkdir()
    _make_notes(graphmark_root)
    _make_notes(ragmark_root)

    gdismiss.record_dismissal(graphmark_root, "b.md", "a.md")
    rdismiss.record_dismissal(ragmark_root, "b.md", "a.md")

    ragmark_data = rdismiss.load_dismissed(ragmark_root)
    sig = "weaklink|a.md|b.md"
    assert sig in ragmark_data
    assert ragmark_data[sig]["a"] == "b.md"
    assert ragmark_data[sig]["b"] == "a.md"

    graphmark_bytes = (graphmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    ragmark_bytes = (ragmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    assert ragmark_bytes == graphmark_bytes


def test_readers_do_not_mutate_store_and_stale_entry_survives(tmp_path):
    graphmark_root = tmp_path / "graphmark_root"
    ragmark_root = tmp_path / "ragmark_root"
    graphmark_root.mkdir()
    ragmark_root.mkdir()
    for root in (graphmark_root, ragmark_root):
        _make_notes(root)
        (root / "c.md").write_text("c content")
        (root / "d.md").write_text("d content")

    gdismiss.record_dismissal(graphmark_root, "a.md", "b.md")
    rdismiss.record_dismissal(ragmark_root, "a.md", "b.md")

    (graphmark_root / "a.md").write_text("edited content")
    (ragmark_root / "a.md").write_text("edited content")

    bytes_before = (ragmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    rdismiss.load_dismissed(ragmark_root)
    rdismiss.active_dismissed_sigs(ragmark_root)
    assert (ragmark_root / rdismiss._DEFAULT_PATH).read_bytes() == bytes_before

    gdismiss.record_dismissal(graphmark_root, "c.md", "d.md")
    rdismiss.record_dismissal(ragmark_root, "c.md", "d.md")

    ragmark_data = rdismiss.load_dismissed(ragmark_root)
    stale_sig = rdismiss.weaklink_sig("a.md", "b.md")
    assert stale_sig in ragmark_data

    graphmark_bytes = (graphmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    ragmark_bytes = (ragmark_root / rdismiss._DEFAULT_PATH).read_bytes()
    assert ragmark_bytes == graphmark_bytes


def test_record_dismissal_on_list_store_replaces_it_with_a_record_in_both_modules(tmp_path):
    # graphmark v0.10.0 reads the store through load_dismissed, which treats a non-object
    # store as empty, so recording succeeds instead of raising TypeError.
    _make_notes(tmp_path)
    for mod in (rdismiss, gdismiss):
        store = tmp_path / mod._DEFAULT_PATH
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(["not", "an", "object"]))
        mod.record_dismissal(tmp_path, "a.md", "b.md")
        assert list(json.loads(store.read_text())) == [rdismiss.weaklink_sig("a.md", "b.md")]
        store.unlink()


def test_record_dismissal_rejected_write_leaves_store_bytes_unchanged(tmp_path):
    store = tmp_path / rdismiss._DEFAULT_PATH
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({}))
    bytes_before = store.read_bytes()
    _make_notes(tmp_path)

    with pytest.raises(ValueError):
        rdismiss.record_dismissal(tmp_path, "a.md", "missing.md")
    with pytest.raises(ValueError):
        rdismiss.record_dismissal(tmp_path, "a.md", "../outside.md")

    assert store.read_bytes() == bytes_before


def test_record_dismissal_missing_note_raises_value_error_in_both_modules(tmp_path):
    (tmp_path / "a.md").write_text("a content")
    for mod in (rdismiss, gdismiss):
        with pytest.raises(ValueError, match="note not found"):
            mod.record_dismissal(tmp_path, "a.md", "nope.md")
        assert not (tmp_path / mod._DEFAULT_PATH).exists()


def test_record_dismissal_rejects_out_of_vault_path_in_both_modules(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "a.md").write_text("a content")
    (tmp_path / "outside.md").write_text("outside")
    for mod in (rdismiss, gdismiss):
        for a, b in (
            ("a.md", "../outside.md"),
            ("../outside.md", "a.md"),
            ("a.md", str(tmp_path / "outside.md")),
        ):
            with pytest.raises(ValueError, match="resolves outside"):
                mod.record_dismissal(root, a, b)
        assert not (root / mod._DEFAULT_PATH).exists()


def test_record_dismissal_atomic_write_leaves_no_temp_file(tmp_path):
    _make_notes(tmp_path)
    rdismiss.record_dismissal(tmp_path, "a.md", "b.md")
    store = tmp_path / rdismiss._DEFAULT_PATH
    assert [p.name for p in store.parent.iterdir()] == [store.name]


def test_record_dismissal_interrupted_write_keeps_prior_store_and_no_temp_file(
    tmp_path, monkeypatch
):
    _make_notes(tmp_path)
    (tmp_path / "c.md").write_text("c content")
    rdismiss.record_dismissal(tmp_path, "a.md", "b.md")
    store = tmp_path / rdismiss._DEFAULT_PATH
    before = store.read_bytes()

    real_write_text = Path.write_text

    def flaky(self, data, *args, **kwargs):
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("simulated interruption")

    monkeypatch.setattr(Path, "write_text", flaky)
    with pytest.raises(OSError):
        rdismiss.record_dismissal(tmp_path, "a.md", "c.md")

    assert store.read_bytes() == before
    assert [p.name for p in store.parent.iterdir()] == [store.name]


def test_non_utf8_store_raises_unicode_decode_error_and_leaves_bytes_unchanged(tmp_path):
    store = tmp_path / rdismiss._DEFAULT_PATH
    store.parent.mkdir(parents=True)
    store.write_bytes(b"\xff\xfe\x00\x01not utf8")
    bytes_before = store.read_bytes()
    _make_notes(tmp_path)

    with pytest.raises(UnicodeDecodeError):
        rdismiss.record_dismissal(tmp_path, "a.md", "b.md")
    assert store.read_bytes() == bytes_before

    with pytest.raises(UnicodeDecodeError):
        gdismiss.record_dismissal(tmp_path, "a.md", "b.md")
    assert store.read_bytes() == bytes_before


def test_active_dismissed_sigs_skips_record_missing_keys_in_both_modules(tmp_path):
    store = tmp_path / rdismiss._DEFAULT_PATH
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"x": {}}))
    bytes_before = store.read_bytes()

    assert rdismiss.active_dismissed_sigs(tmp_path) == set()
    assert gdismiss.active_dismissed_sigs(tmp_path) == set()
    assert store.read_bytes() == bytes_before


def test_active_dismissed_sigs_skips_out_of_vault_record_but_keeps_valid_one(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    _make_notes(root)
    (tmp_path / "outside.md").write_text("outside")
    rdismiss.record_dismissal(root, "a.md", "b.md")
    store = root / rdismiss._DEFAULT_PATH
    records = json.loads(store.read_text())
    records["weaklink|../outside.md|a.md"] = {
        "a": "../outside.md",
        "b": "a.md",
        "a_hash": rdismiss.content_hash(tmp_path / "outside.md"),
        "b_hash": rdismiss.content_hash(root / "a.md"),
    }
    store.write_text(json.dumps(records))

    expected = {rdismiss.weaklink_sig("a.md", "b.md")}
    assert rdismiss.active_dismissed_sigs(root) == expected
    assert gdismiss.active_dismissed_sigs(root) == expected


def test_dismiss_module_does_not_import_graphmark():
    tree = ast.parse(DISMISS_SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "graphmark"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or node.module.split(".")[0] != "graphmark"


@pytest.mark.parametrize(
    "name",
    [
        "weaklink_sig",
        "content_hash",
        "record_dismissal",
        "load_dismissed",
        "active_dismissed_sigs",
    ],
)
def test_signatures_match_graphmark(name):
    assert inspect.signature(getattr(rdismiss, name)) == inspect.signature(getattr(gdismiss, name))


def test_default_path_matches_graphmark():
    assert rdismiss._DEFAULT_PATH == gdismiss._DEFAULT_PATH


def test_module_docstring_cites_provenance():
    docstring = rdismiss.__doc__
    assert "graphmark v0.10.1" in docstring
    assert "the-vault#143" in docstring
    assert "2026-09-26" in docstring


_PIPE_CASES = [
    (("x", "y|z"), "weaklink2|x|y\\|z"),
    (("y|z", "x"), "weaklink2|x|y\\|z"),
    (("|", "x"), "weaklink2|\\||x"),
    (("a\\b", "c"), "weaklink|a\\b|c"),
    (("b.md", "a.md"), "weaklink|a.md|b.md"),
]


@pytest.mark.parametrize(("args", "expected"), _PIPE_CASES)
def test_weaklink_sig_exact_bytes_match_graphmark(args, expected):
    assert rdismiss.weaklink_sig(*args) == expected
    assert gdismiss.weaklink_sig(*args) == expected


def test_weaklink_sig_pipe_pairs_do_not_collide():
    assert rdismiss.weaklink_sig("x", "y|z") != rdismiss.weaklink_sig("x|y", "z")
