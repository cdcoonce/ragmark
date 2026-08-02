"""Recent activity — "what moved lately", without a query to aim.

Decided shape (the-vault#142, accepted live): `{note_path, modified,
first_line}`, newest first, **git-log-backed** — the vault is always a repo,
and mtimes lie after a fresh sync — with an mtime fallback for non-repo
vaults. Results are context-gated like every other surface.
"""

from __future__ import annotations

from ragmark.config import RagmarkConfig
from ragmark.model import ActivityEntry

DEFAULT_DAYS = 7
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def recent_activity(
    days: int = DEFAULT_DAYS,
    limit: int = DEFAULT_LIMIT,
    *,
    config: RagmarkConfig,
) -> list[ActivityEntry]:
    """Context-visible notes changed in the last *days*, newest first."""
    raise NotImplementedError("build slice: git-log activity (the-vault#142)")
