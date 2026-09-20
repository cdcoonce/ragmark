"""CLI — the same core as the MCP face, headless (the-vault#142's table).

    ragmark search "query" -k 8        <-> MCP vault_search
    ragmark read path/to/note.md       <-> MCP vault_read
    ragmark neighbors path --depth 1   <-> MCP vault_neighbors
    ragmark recent --days 7            <-> MCP recent_activity
    ragmark golden --file golden.toml      (correctness harness runner)
    ragmark index [--force]                (CLI-ONLY: the MCP face exposes no
                                            maintenance — deliberate asymmetry)
    ragmark mcp                            (serve the MCP face over stdio)

Context gating lives in the core, so every verb here gates identically to the
MCP tools — the /find-vs-MCP asymmetry the survey found cannot recur.

Exit codes: 0 success; 1 unavailable path / failed golden gate; 2 usage or
not-yet-implemented (a seed stub reached before its build slice landed).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

from ragmark import activity, gaps, gate, golden, index, neighbors, search
from ragmark.config import RagmarkConfig
from ragmark.embed import FastembedEmbedder
from ragmark.store import IndexStore

VAULT_ENV = "RAGMARK_VAULT"


def _json_dump(result: object) -> str:
    """Render an engine result as the JSON every verb prints.

    Every result type is a `slots=True` dataclass, so it has no instance
    `__dict__`; `asdict` is the supported accessor and recurses into nested
    dataclasses (a `Neighborhood`'s `neighbors` tuple becomes plain dicts).
    Tuples serialize as JSON arrays natively, so no `default=` hook is needed.
    One helper for all four verbs so none can regress on its own.
    """
    if is_dataclass(result) and not isinstance(result, type):
        return json.dumps(asdict(result), indent=2)
    if isinstance(result, (list, tuple)):
        return json.dumps([asdict(item) for item in result], indent=2)
    return json.dumps(result, indent=2)


def _resolve_vault(arg: str | None) -> Path:
    """Vault root from --vault, then $RAGMARK_VAULT — never from __file__."""
    if arg is not None:
        return Path(arg)
    env = os.environ.get(VAULT_ENV, "")
    if env:
        return Path(env)
    print(f"error: no vault given (use --vault or ${VAULT_ENV})", file=sys.stderr)
    raise SystemExit(2)


def _add_fusion_flag(parser: argparse.ArgumentParser) -> None:
    """Expose the leg-fusion mode, defaulting to the decided behavior.

    Selectable because the golden oracle is the only thing that can compare
    the two modes, and the oracle is driven from this surface. The MCP face
    deliberately does NOT expose it: that face is a pinned contract, and its
    behavior stays the default.
    """
    parser.add_argument(
        "--fusion",
        type=search.Fusion,
        choices=list(search.Fusion),
        default=search.Fusion.RRF,
        help="how the vector and lexical legs combine (default: rrf)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragmark", description=__doc__)
    parser.add_argument("--vault", help=f"vault root (or ${VAULT_ENV})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="hybrid chunk search")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=search.DEFAULT_RESULTS)
    _add_fusion_flag(p_search)

    p_read = sub.add_parser("read", help="print one note")
    p_read.add_argument("path")

    p_neighbors = sub.add_parser("neighbors", help="wikilink neighborhood walk")
    p_neighbors.add_argument("path")
    p_neighbors.add_argument("--depth", type=int, default=neighbors.DEFAULT_DEPTH)
    p_neighbors.add_argument("--budget", type=int, default=neighbors.DEFAULT_TOKEN_BUDGET)

    p_recent = sub.add_parser("recent", help="recently changed notes")
    p_recent.add_argument("--days", type=int, default=activity.DEFAULT_DAYS)
    p_recent.add_argument("--limit", type=int, default=activity.DEFAULT_LIMIT)

    p_golden = sub.add_parser("golden", help="run the golden-query harness")
    p_golden.add_argument("--file", required=True, type=Path)
    p_golden.add_argument("--min-recall", type=float, default=None)
    _add_fusion_flag(p_golden)

    p_index = sub.add_parser("index", help="build/refresh the derived index (CLI-only)")
    p_index.add_argument("--force", action="store_true", help="full rebuild")

    p_gaps = sub.add_parser("gaps", help="ranked unlinked-but-similar note pairs")
    p_gaps.add_argument("--threshold", type=float, default=gaps.GAPS_DEFAULT_THRESHOLD)

    sub.add_parser("mcp", help="serve the MCP face over stdio")
    return parser


def main() -> int:
    """Entry point (error boundary: stubs and gate refusals become exit codes)."""
    args = _build_parser().parse_args()
    config = RagmarkConfig.for_vault(_resolve_vault(args.vault))
    store = IndexStore(config.index_dir)
    embedder = FastembedEmbedder()

    try:
        if args.command == "search":
            hits = search.search(
                args.query,
                args.k,
                config=config,
                store=store,
                embedder=embedder,
                fusion=args.fusion,
            )
            print(_json_dump(hits))
        elif args.command == "read":
            print(gate.read_note(args.path, config))
        elif args.command == "neighbors":
            result = neighbors.vault_neighbors(args.path, args.depth, args.budget, config=config)
            print(_json_dump(result))
        elif args.command == "recent":
            entries = activity.recent_activity(args.days, args.limit, config=config)
            print(_json_dump(entries))
        elif args.command == "golden":
            return _run_golden(args, config, store, embedder)
        elif args.command == "index":
            run = index.reindex if args.force else index.refresh
            report = run(config, store, embedder)
            print(_json_dump(report))
        elif args.command == "gaps":
            pairs = gaps.gaps(config=config, threshold=args.threshold)
            print(json.dumps(pairs, indent=2))
        elif args.command == "mcp":
            from ragmark.mcp import serve

            serve(config)
    except gate.VaultAccessError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except NotImplementedError as error:
        print(f"not implemented in the seed ({error})", file=sys.stderr)
        return 2
    return 0


def _git_output(args: list[str], cwd: Path) -> str | None:
    """Run a git command in *cwd*; `None` on any failure, never a raise.

    Covers a missing `git` binary, a non-zero exit, and a non-repo directory
    alike — the two provenance git lookups are best-effort only.
    """
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _vault_git_state(vault_root: Path) -> tuple[str | None, bool | None]:
    """`(vault_revision, vault_dirty)` — both `None` when not a git work tree."""
    head = _git_output(["rev-parse", "HEAD"], vault_root)
    if head is None:
        return None, None
    status = _git_output(["status", "--porcelain"], vault_root)
    dirty = bool(status.strip()) if status is not None else None
    return head.strip(), dirty


def _gather_golden_provenance(
    args: argparse.Namespace,
    config: RagmarkConfig,
    store: IndexStore,
    embedder: FastembedEmbedder,
    query_count: int,
) -> golden.GoldenProvenance:
    """The measurement's inputs, gathered after the search path has already
    run (so the index dir and schema `store.connect()` creates are the ones
    search itself just used, not a premature empty one)."""
    oracle_bytes = args.file.read_bytes()
    conn = store.connect()
    try:
        note_count = len(store.read_notes(conn))
        chunk_count = store.chunk_count(conn)
    finally:
        conn.close()
    identity = embedder.identity()
    try:
        ragmark_version = importlib.metadata.version("ragmark")
    except importlib.metadata.PackageNotFoundError:
        ragmark_version = None
    vault_revision, vault_dirty = _vault_git_state(config.vault_root)
    return golden.GoldenProvenance(
        oracle_path=args.file.name,
        oracle_sha256=hashlib.sha256(oracle_bytes).hexdigest(),
        query_count=query_count,
        vault_revision=vault_revision,
        vault_dirty=vault_dirty,
        note_count=note_count,
        chunk_count=chunk_count,
        model_name=identity.name,
        model_dim=identity.dim,
        model_version=identity.version,
        fusion=args.fusion.value,
        ragmark_version=ragmark_version,
    )


def _run_golden(
    args: argparse.Namespace,
    config: RagmarkConfig,
    store: IndexStore,
    embedder: FastembedEmbedder,
) -> int:
    """Evaluate the golden set against live search; gate on --min-recall."""

    def search_notes(query: str, k: int) -> list[str]:
        hits = search.search(
            query, k, config=config, store=store, embedder=embedder, fusion=args.fusion
        )
        ranked_notes: list[str] = []
        for hit in hits:
            if hit.note_path not in ranked_notes:
                ranked_notes.append(hit.note_path)
        return ranked_notes

    queries = golden.load_golden(args.file)
    report = golden.evaluate(queries, search_notes)
    provenance = _gather_golden_provenance(args, config, store, embedder, len(queries))
    report = replace(report, provenance=provenance)
    print(_json_dump(report))
    if args.min_recall is not None and report.mean_recall < args.min_recall:
        print(
            f"golden gate FAILED: mean recall {report.mean_recall:.3f} < {args.min_recall:.3f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
