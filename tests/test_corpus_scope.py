"""Corpus policy binds storage and every reader independently of context (#94)."""

from dataclasses import replace
from pathlib import Path

import pytest
from test_index import RecordingEmbedder, assert_conservation

from ragmark import gate, index
from ragmark.activity import recent_activity
from ragmark.config import CONTEXT_FILE, RagmarkConfig
from ragmark.neighbors import vault_neighbors
from ragmark.search import search, similar_notes
from ragmark.store import IndexStore

ALLOWED = ["brain/live.md", "work/live.md", "personal/live.md", "school/live.md"]
EXCLUDED = [
    "README.md",
    "outside/copy.md",
    "brain/AGENTS.md",
    "work/CLAUDE.local.md",
    "personal/tasks/old.md",
    "work/Tasks.md",
    "work/Tasks.md.backup.md",
    "brain/templates/draft.md",
    "school/session-logs/old.md",
    "brain/.hidden.md",
    "brain/.private/hidden.md",
]


def _write(config: RagmarkConfig, path: str, text: str = "scope signal apples oranges\n") -> None:
    target = config.vault_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def scoped(tmp_path: Path) -> RagmarkConfig:
    config = replace(
        RagmarkConfig.for_vault(tmp_path),
        scoped_folders=frozenset({"brain", "work", "personal", "school"}),
        excluded_filenames=frozenset(
            {"AGENTS.md", "AGENTS.local.md", "CLAUDE.md", "CLAUDE.local.md"}
        ),
        excluded_path_prefixes=("personal/tasks/", "work/Tasks.md"),
        excluded_dirs=frozenset({"templates", "session-logs"}),
    )
    (tmp_path / CONTEXT_FILE).write_text("personal\n")
    for path in ALLOWED + EXCLUDED:
        _write(config, path)
    return config


def test_corpus_scope_binds_access_and_indexable_boundary(scoped: RagmarkConfig) -> None:
    for path in ALLOWED:
        assert gate.read_note(path, scoped) == "scope signal apples oranges\n"
        assert gate.is_indexable_note(scoped.vault_root / path, scoped)
    for path in EXCLUDED:
        assert not gate.is_indexable_note(scoped.vault_root / path, scoped), path
        with pytest.raises(gate.VaultAccessError, match="path is not available"):
            gate.read_note(path, scoped)


def test_scope_filters_existing_index_results_before_refresh(scoped: RagmarkConfig) -> None:
    old_config = replace(
        scoped, scoped_folders=(), excluded_filenames=(), excluded_path_prefixes=()
    )
    store = IndexStore(scoped.index_dir)
    embedder = RecordingEmbedder()
    index.reindex(old_config, store, embedder)
    assert "README.md" in store.read_notes(store.connect())
    assert gate.filter_visible(ALLOWED + EXCLUDED, scoped) == ALLOWED
    similar = similar_notes("brain/live.md", k=25, config=scoped, store=store)
    assert {path for path, _ in similar} == set(ALLOWED) - {"brain/live.md"}


def test_refresh_removes_excluded_rows_and_all_readers_agree(scoped: RagmarkConfig) -> None:
    old_config = replace(
        scoped, scoped_folders=(), excluded_filenames=(), excluded_path_prefixes=()
    )
    store = IndexStore(scoped.index_dir)
    embedder = RecordingEmbedder()
    index.reindex(old_config, store, embedder)
    old_paths = set(store.read_notes(store.connect()))
    embedder.count_tokens_calls.clear()
    report = index.refresh(scoped, store, embedder)
    assert report.removed == len(old_paths - set(ALLOWED))
    assert set(store.read_notes(store.connect())) == set(ALLOWED)
    assert embedder.count_tokens_calls == []  # existing allowed notes need no embedding
    assert_conservation(store)
    assert {
        hit.note_path
        for hit in search("scope", k=25, config=scoped, store=store, embedder=embedder)
    } == set(ALLOWED)
    assert {entry.note_path for entry in recent_activity(config=scoped)} == set(ALLOWED)


def test_scope_change_to_empty_corpus_removes_all_vectors(scoped: RagmarkConfig) -> None:
    store = IndexStore(scoped.index_dir)
    embedder = RecordingEmbedder()
    index.reindex(scoped, store, embedder)
    empty = replace(scoped, scoped_folders=("nothing-here",))
    report = index.refresh(empty, store, embedder)
    assert report.removed == len(ALLOWED)
    assert store.read_notes(store.connect()) == {}
    assert_conservation(store)
    assert index.refresh(empty, store, embedder).removed == 0


@pytest.mark.parametrize(
    ("policy", "excluded", "link"),
    [
        ({"scoped_folders": ("brain",)}, "outside/target.md", "target"),
        ({"scoped_folders": ("brain",)}, "outside/copy.md", "Friendly"),
        ({"excluded_filenames": ("AGENTS.md",)}, "brain/AGENTS.md", "Friendly"),
        ({"excluded_path_prefixes": ("brain/archive/",)}, "brain/archive/target.md", "target"),
        ({"excluded_path_prefixes": ("brain/archive/",)}, "brain/archive/copy.md", "Friendly"),
    ],
)
def test_exclusions_precede_graph_name_and_alias_resolution(
    tmp_path: Path, policy, excluded: str, link: str, monkeypatch
) -> None:
    import graphmark

    config = replace(RagmarkConfig.for_vault(tmp_path), **policy)
    _write(config, "brain/origin.md", f"[[{link}]]\n")
    _write(config, "brain/target.md", "---\naliases: [Friendly]\n---\nLive decision\n")
    _write(config, excluded, "---\naliases: [Friendly]\n---\nExcluded duplicate\n")
    parsed = []
    original = graphmark.parse_document

    def record_parse(path, root):
        parsed.append(path.relative_to(root).as_posix())
        return original(path, root)

    monkeypatch.setattr(graphmark, "parse_document", record_parse)
    result = vault_neighbors("brain/origin.md", config=config)
    assert [neighbor.note_path for neighbor in result.neighbors] == ["brain/target.md"]
    assert excluded not in parsed
    assert set(parsed) == {"brain/origin.md", "brain/target.md"}


def test_index_cannot_follow_symlinks_around_corpus_scope(scoped: RagmarkConfig) -> None:
    (scoped.vault_root / "brain" / "linked-outside.md").symlink_to(
        scoped.vault_root / "outside" / "copy.md"
    )
    (scoped.vault_root / "brain" / "linked-tasks.md").symlink_to(
        scoped.vault_root / "personal" / "tasks" / "old.md"
    )
    outside = scoped.vault_root.parent / "outside-vault.md"
    outside.write_text("must never be embedded\n")
    (scoped.vault_root / "brain" / "escape.md").symlink_to(outside)
    store = IndexStore(scoped.index_dir)
    embedder = RecordingEmbedder()
    index.reindex(scoped, store, embedder)
    assert set(store.read_notes(store.connect())) == set(ALLOWED)
    assert all("must never be embedded" not in text for text in embedder.count_tokens_calls)


@pytest.mark.gating
@pytest.mark.parametrize("context", ["work", None])
def test_owner_scope_preserves_fail_closed_context_on_every_reader(
    scoped: RagmarkConfig, context: str | None
) -> None:
    marker = scoped.vault_root / CONTEXT_FILE
    if context is None:
        marker.unlink()
    else:
        marker.write_text(context)
    _write(
        scoped, "brain/live.md", "scope signal [[work/live]] [[personal/live]] [[school/live]]\n"
    )
    expected = {"brain/live.md", "school/live.md"}
    if context == "work":
        expected.add("work/live.md")
    store = IndexStore(scoped.index_dir)
    embedder = RecordingEmbedder()
    hits = search("scope", k=25, config=scoped, store=store, embedder=embedder)
    assert {hit.note_path for hit in hits} == expected
    assert {
        path for path, _ in similar_notes("brain/live.md", config=scoped, store=store)
    } == expected - {"brain/live.md"}
    assert {entry.note_path for entry in recent_activity(config=scoped)} == expected
    assert {
        neighbor.note_path for neighbor in vault_neighbors("brain/live.md", config=scoped).neighbors
    } == expected - {"brain/live.md"}
    with pytest.raises(gate.VaultAccessError):
        gate.read_note("personal/live.md", scoped)


def test_empty_scope_defaults_keep_existing_root_notes_and_graph_path(
    tmp_path: Path, monkeypatch
) -> None:
    import graphmark

    config = RagmarkConfig.for_vault(tmp_path)
    _write(config, "origin.md", "[[target]]\n")
    _write(config, "target.md", "Visible default root note\n")
    calls = []
    original = graphmark.build

    def record_build(source):
        calls.append(source)
        return original(source)

    monkeypatch.setattr(graphmark, "build", record_build)
    result = vault_neighbors("origin.md", config=config)
    assert [neighbor.note_path for neighbor in result.neighbors] == ["target.md"]
    assert len(calls) == 1
    store = IndexStore(config.index_dir)
    index.reindex(config, store, RecordingEmbedder())
    assert set(store.read_notes(store.connect())) == {"origin.md", "target.md"}


def test_scoped_graph_keeps_real_visible_ambiguity(tmp_path: Path) -> None:
    config = replace(RagmarkConfig.for_vault(tmp_path), scoped_folders=("brain",))
    _write(config, "brain/origin.md", "[[target]] [[Friendly]]\n")
    for path in ("brain/one/target.md", "brain/two/target.md"):
        _write(config, path, "---\naliases: [Friendly]\n---\nVisible duplicate\n")
    assert vault_neighbors("brain/origin.md", config=config).neighbors == ()


@pytest.mark.parametrize("alias", ["brain/AGENTS.md", "personal/tasks/link.md", "brain/.alias.md"])
def test_excluded_alias_path_cannot_bypass_scope_with_allowed_target(
    scoped: RagmarkConfig, alias: str
) -> None:
    path = scoped.vault_root / alias
    path.unlink(missing_ok=True)
    path.symlink_to(scoped.vault_root / "brain" / "live.md")
    with pytest.raises(gate.VaultAccessError):
        gate.read_note(alias, scoped)


def test_scoped_neighbor_origin_uses_canonical_contained_path(tmp_path: Path) -> None:
    config = replace(RagmarkConfig.for_vault(tmp_path), scoped_folders=("brain",))
    _write(config, "brain/origin.md", "[[target]]\n")
    _write(config, "brain/target.md", "Real target\n")
    (tmp_path / "brain" / "alias.md").symlink_to(tmp_path / "brain" / "origin.md")
    result = vault_neighbors("brain/alias.md", config=config)
    assert result.origin == "brain/alias.md"
    assert [neighbor.note_path for neighbor in result.neighbors] == ["brain/target.md"]


@pytest.mark.gating
@pytest.mark.parametrize(
    ("surface", "owner_scope"),
    [
        (surface, scoped)
        for surface in ("read", "filter", "similar", "recent")
        for scoped in (False, True)
    ]
    + [("neighbors", False)],
)
def test_private_path_retargeted_to_shared_note_stays_private(
    tmp_path: Path, owner_scope: bool, surface: str
) -> None:
    config = RagmarkConfig.for_vault(tmp_path)
    if owner_scope:
        config = replace(config, scoped_folders=("brain", "work", "personal"))
    _write(config, "brain/source.md", "[[personal/private]] [[work/visible]] [[brain/open]]\n")
    _write(config, "brain/open.md", "Shared content\n")
    _write(config, "personal/private.md", "Previously indexed private content\n")
    _write(config, "work/visible.md", "Previously indexed visible content\n")
    marker = tmp_path / CONTEXT_FILE
    marker.write_text("personal\n")
    store = IndexStore(config.index_dir)
    index.reindex(config, store, RecordingEmbedder())
    for alias in ("personal/private.md", "work/visible.md"):
        (tmp_path / alias).unlink()
        (tmp_path / alias).symlink_to(tmp_path / "brain/open.md")
    marker.write_text("work\n")

    if surface == "read":
        assert gate.read_note("work/visible.md", config) == "Shared content\n"
        with pytest.raises(gate.VaultAccessError) as refused:
            gate.read_note("personal/private.md", config)
        (tmp_path / "personal/private.md").unlink()
        with pytest.raises(gate.VaultAccessError) as missing:
            gate.read_note("personal/private.md", config)
        assert str(refused.value) == str(missing.value)
        return
    if surface == "filter":
        paths = gate.filter_visible(["personal/private.md", "work/visible.md"], config)
    elif surface == "similar":
        paths = [path for path, _ in similar_notes("brain/source.md", config=config, store=store)]
    elif surface == "recent":
        paths = [entry.note_path for entry in recent_activity(config=config)]
    else:
        paths = [
            neighbor.note_path
            for neighbor in vault_neighbors("brain/source.md", config=config).neighbors
        ]
    assert "personal/private.md" not in paths
    assert "work/visible.md" in paths


@pytest.mark.parametrize(
    ("actual", "alternate"),
    [
        ("brain/AGENTS.md", "brain/agents.md"),
        ("personal/tasks/old.md", "personal/TASKS/old.md"),
        ("personal/live.md", "PERSONAL/live.md"),
        ("personal/live.md", "Personal/live.md"),
    ],
)
@pytest.mark.parametrize("via_symlink", [False, True])
def test_case_insensitive_filesystem_alias_cannot_bypass_literal_policy(
    scoped: RagmarkConfig, actual: str, alternate: str, via_symlink: bool
) -> None:
    if not (scoped.vault_root / alternate).exists():
        pytest.skip("filesystem does not accept this alternate-case spelling")
    assert (scoped.vault_root / actual).samefile(scoped.vault_root / alternate)
    # No top-level allowlist: context itself must not be bypassed by PERSONAL/.
    config = replace(scoped, scoped_folders=())
    context = "personal" if actual.startswith("personal/tasks/") else "work"
    (scoped.vault_root / CONTEXT_FILE).write_text(context + "\n")
    if via_symlink:
        (scoped.vault_root / "brain/alias.md").symlink_to(scoped.vault_root / alternate)
        alternate = "brain/alias.md"
    assert gate.read_note("brain/live.md", config) == "scope signal apples oranges\n"
    with pytest.raises(gate.VaultAccessError):
        gate.read_note(alternate, config)
    assert gate.filter_visible([alternate, "brain/live.md"], config) == ["brain/live.md"]


def test_exact_spelling_preserves_literal_case_and_allowed_symlinks(tmp_path: Path) -> None:
    config = replace(
        RagmarkConfig.for_vault(tmp_path),
        excluded_filenames=("AGENTS.md",),
        excluded_path_prefixes=("personal/tasks/",),
    )
    (tmp_path / CONTEXT_FILE).write_text("personal\n")
    _write(config, "brain/agents.md", "Actual lowercase filename is allowed\n")
    _write(config, "personal/TASKS/note.md", "Actual uppercase directory is allowed\n")
    (tmp_path / "brain/alias.md").symlink_to(tmp_path / "brain/agents.md")
    assert gate.read_note("brain/agents.md", config) == "Actual lowercase filename is allowed\n"
    assert (
        gate.read_note("personal/TASKS/note.md", config)
        == "Actual uppercase directory is allowed\n"
    )
    assert gate.read_note("brain/alias.md", config) == "Actual lowercase filename is allowed\n"


@pytest.mark.parametrize("surface", ["index", "neighbors"])
def test_alternate_case_symlink_target_is_excluded_before_parsing(
    tmp_path: Path, surface: str
) -> None:
    config = replace(RagmarkConfig.for_vault(tmp_path), excluded_filenames=("AGENTS.md",))
    _write(config, "brain/AGENTS.md", "---\naliases: [Friendly]\n---\nForbidden payload\n")
    if not (tmp_path / "brain/agents.md").exists():
        pytest.skip("filesystem does not accept this alternate-case spelling")
    _write(config, "brain/target.md", "---\naliases: [Friendly]\n---\nAllowed payload\n")
    _write(config, "brain/origin.md", "[[Friendly]]\n")
    (tmp_path / "brain/alias.md").symlink_to(tmp_path / "brain/agents.md")
    if surface == "index":
        store = IndexStore(config.index_dir)
        embedder = RecordingEmbedder()
        index.reindex(config, store, embedder)
        assert set(store.read_notes(store.connect())) == {"brain/target.md", "brain/origin.md"}
        assert all("Forbidden payload" not in text for text in embedder.count_tokens_calls)
    else:
        result = vault_neighbors("brain/origin.md", config=config)
        assert [neighbor.note_path for neighbor in result.neighbors] == ["brain/target.md"]
