"""Explicit configuration loading through the CLI and MCP launcher (issue #26)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from ragmark import cli
from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.model import ModelIdentity


@pytest.fixture
def configured_vault(tmp_path: Path) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    for relative, text in {
        ".vault-context": "work\n",
        "shared.md": "# Searchneedle\nShared note.\n",
        "company/visible.md": "# Searchneedle\nWork note.\n",
        "private/hidden.md": "# Searchneedle\nPrivate note.\n",
        "templates/excluded.md": "# Searchneedle\nExcluded template.\n",
    }.items():
        path = vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    config_path = tmp_path / "settings" / "ragmark.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        'vault_root = "../vault"\n'
        'index_dir = "../derived"\n'
        'excluded_dirs = ["templates"]\n'
        "[context_dirs]\n"
        'company = "work"\n'
        'private = "personal"\n'
        "[visible_scopes]\n"
        'personal = ["personal", "work"]\n'
        'work = ["work"]\n',
        encoding="utf-8",
    )
    return config_path, vault, tmp_path / "derived"


def test_config_reads_selected_vault_from_another_cwd_despite_environment(
    configured_vault, monkeypatch, capsys, tmp_path
) -> None:
    config_path, _vault, _index_dir = configured_vault
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setenv(cli.VAULT_ENV, str(other))
    monkeypatch.setattr(
        sys, "argv", ["ragmark", "--config", str(config_path), "read", "company/visible.md"]
    )

    assert cli.main() == 0
    captured = capsys.readouterr()
    assert "Work note." in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("config_first", [True, False])
def test_config_and_vault_are_mutually_exclusive(configured_vault, capsys, config_first) -> None:
    config_path, vault, _index_dir = configured_vault
    config_args = ["--config", str(config_path)]
    vault_args = ["--vault", str(vault)]
    flags = config_args + vault_args if config_first else vault_args + config_args

    with pytest.raises(SystemExit) as excinfo:
        cli._build_parser().parse_args([*flags, "read", "shared.md"])

    assert excinfo.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize(
    "contents",
    [None, "vault_root = [\n", "", "vault_root = 7\n", 'vault_root = "."\nvisible_scopes = []\n'],
    ids=["missing-file", "invalid-toml", "missing-root", "invalid-root", "invalid-scopes"],
)
def test_invalid_config_exits_2_before_store_or_embedder(
    contents, tmp_path, monkeypatch, capsys
) -> None:
    config_path = tmp_path / "bad.toml"
    if contents is not None:
        config_path.write_text(contents, encoding="utf-8")

    def unexpected_construction(*args, **kwargs):
        pytest.fail("invalid config must fail before constructing a store or embedder")

    monkeypatch.setattr(cli, "IndexStore", unexpected_construction)
    monkeypatch.setattr(cli, "FastembedEmbedder", unexpected_construction)
    monkeypatch.setenv(cli.VAULT_ENV, str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["ragmark", "--config", str(config_path), "mcp"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: cannot load config" in captured.err
    assert str(config_path) in captured.err
    assert "Traceback" not in captured.err


class _StubEmbedder(Embedder):
    """Exercise the real search/index path using only temporary fixture data."""

    def identity(self) -> ModelIdentity:
        return ModelIdentity(name="config-test", dim=2, version="1")

    def embed(self, texts):
        return np.ones((len(texts), 2), dtype=np.float32)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


@pytest.mark.parametrize(
    "context",
    [
        pytest.param("work", marks=pytest.mark.gating),
        "personal",
        pytest.param("unknown", marks=pytest.mark.gating),
    ],
)
@pytest.mark.parametrize("verb", ["search", "recent"])
def test_config_search_and_recent_apply_exclusions_and_asymmetric_context(
    configured_vault, monkeypatch, capsys, context, verb
) -> None:
    config_path, vault, index_dir = configured_vault
    (vault / ".vault-context").write_text(context + "\n", encoding="utf-8")
    monkeypatch.delenv(cli.VAULT_ENV, raising=False)
    monkeypatch.setattr(cli, "FastembedEmbedder", _StubEmbedder)
    args = ["search", "Searchneedle", "-k", "25"] if verb == "search" else ["recent"]
    monkeypatch.setattr(sys, "argv", ["ragmark", "--config", str(config_path), *args])

    assert cli.main() == 0

    captured = capsys.readouterr()
    paths = {item["note_path"] for item in json.loads(captured.out)}
    expected = {"shared.md"}
    if context in {"work", "personal"}:
        expected.add("company/visible.md")
    if context == "personal":
        expected.add("private/hidden.md")
    assert paths == expected
    assert "templates/excluded.md" not in paths
    assert captured.err == ""
    if verb == "search":
        assert (index_dir / "ragmark.db").is_file()
        assert (index_dir / "vectors.npy").is_file()
    else:
        assert not index_dir.exists()
    assert not (vault / ".ragmark").exists()


def test_config_read_refuses_excluded_note(configured_vault, monkeypatch, capsys) -> None:
    config_path, _vault, _index_dir = configured_vault
    monkeypatch.setattr(
        sys, "argv", ["ragmark", "--config", str(config_path), "read", "templates/excluded.md"]
    )

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "path is not available" in captured.err
    assert "Excluded template." not in captured.err


@pytest.mark.gating
def test_config_read_refuses_custom_private_scope(configured_vault, monkeypatch, capsys) -> None:
    config_path, _vault, _index_dir = configured_vault
    monkeypatch.setattr(
        sys, "argv", ["ragmark", "--config", str(config_path), "read", "private/hidden.md"]
    )

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "path is not available" in captured.err
    assert "Private note." not in captured.err


def test_config_reaches_mcp_launcher(configured_vault, monkeypatch, capsys) -> None:
    from ragmark import mcp

    config_path, _vault, index_dir = configured_vault
    seen = []
    monkeypatch.setattr(mcp, "serve", seen.append)
    monkeypatch.delenv(cli.VAULT_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["ragmark", "--config", str(config_path), "mcp"])

    assert cli.main() == 0
    assert seen == [RagmarkConfig.from_toml(config_path)]
    assert not index_dir.exists()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_reference_config_remains_loadable() -> None:
    reference = Path(__file__).resolve().parents[1] / "configs" / "the-vault.toml"

    config = RagmarkConfig.from_toml(reference)

    assert config.vault_root == (reference.parent / "../../the-vault").resolve()
    assert config.index_dir == config.vault_root / ".ragmark"
    assert config.excluded_dirs == frozenset({"templates", "session-logs"})
    assert config.context_dirs == {"work": "work", "personal": "personal"}
    assert config.visible_scopes == {
        "personal": frozenset({"personal", "work"}),
        "work": frozenset({"work"}),
    }


@pytest.mark.parametrize("explicit_vault", [True, False])
def test_without_config_retains_default_policy(
    configured_vault, monkeypatch, capsys, explicit_vault
) -> None:
    _config_path, vault, _index_dir = configured_vault
    # Default config has no excluded directories; a nearby TOML is not autodiscovered.
    (vault / ".ragmark.toml").write_text('vault_root = "missing"\n', encoding="utf-8")
    monkeypatch.setenv(cli.VAULT_ENV, str(vault))
    flags = ["--vault", str(vault)] if explicit_vault else []
    monkeypatch.setattr(sys, "argv", ["ragmark", *flags, "read", "templates/excluded.md"])

    assert cli.main() == 0
    assert "Excluded template." in capsys.readouterr().out
