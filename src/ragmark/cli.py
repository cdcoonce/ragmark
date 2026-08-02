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
import json
import os
import sys
from pathlib import Path

from ragmark import activity, gaps, gate, golden, index, neighbors, search
from ragmark.config import RagmarkConfig
from ragmark.embed import FastembedEmbedder
from ragmark.store import IndexStore

VAULT_ENV = "RAGMARK_VAULT"


def _resolve_vault(arg: str | None) -> Path:
    """Vault root from --vault, then $RAGMARK_VAULT — never from __file__."""
    if arg is not None:
        return Path(arg)
    env = os.environ.get(VAULT_ENV, "")
    if env:
        return Path(env)
    print(f"error: no vault given (use --vault or ${VAULT_ENV})", file=sys.stderr)
    raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragmark", description=__doc__)
    parser.add_argument("--vault", help=f"vault root (or ${VAULT_ENV})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="hybrid chunk search")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=search.DEFAULT_RESULTS)

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
            hits = search.search(args.query, args.k, config=config, store=store, embedder=embedder)
            print(json.dumps([hit.__dict__ for hit in hits], indent=2))
        elif args.command == "read":
            print(gate.read_note(args.path, config))
        elif args.command == "neighbors":
            result = neighbors.vault_neighbors(args.path, args.depth, args.budget, config=config)
            print(json.dumps(result, default=lambda o: o.__dict__, indent=2))
        elif args.command == "recent":
            entries = activity.recent_activity(args.days, args.limit, config=config)
            print(json.dumps([entry.__dict__ for entry in entries], indent=2))
        elif args.command == "golden":
            return _run_golden(args, config, store, embedder)
        elif args.command == "index":
            run = index.reindex if args.force else index.refresh
            report = run(config, store, embedder)
            print(json.dumps(report.__dict__, default=list, indent=2))
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


def _run_golden(
    args: argparse.Namespace,
    config: RagmarkConfig,
    store: IndexStore,
    embedder: FastembedEmbedder,
) -> int:
    """Evaluate the golden set against live search; gate on --min-recall."""

    def search_notes(query: str, k: int) -> list[str]:
        hits = search.search(query, k, config=config, store=store, embedder=embedder)
        ranked_notes: list[str] = []
        for hit in hits:
            if hit.note_path not in ranked_notes:
                ranked_notes.append(hit.note_path)
        return ranked_notes

    report = golden.evaluate(golden.load_golden(args.file), search_notes)
    print(json.dumps(report, default=lambda o: o.__dict__, indent=2))
    if args.min_recall is not None and report.mean_recall < args.min_recall:
        print(
            f"golden gate FAILED: mean recall {report.mean_recall:.3f} < {args.min_recall:.3f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
