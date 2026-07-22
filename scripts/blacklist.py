#!/usr/bin/env python3
"""Shared blacklist of manually-audited non-hardware slugs.

Projects listed here were confirmed (by human review of the audit report) to
NOT be tech-hardware, and were removed from projects.json. The fetch pipeline
must never re-ingest them. Loaded once at import; call reload() if the file
changes mid-process.
"""
import json
from pathlib import Path

BLACKLIST_FILE = Path(__file__).parent / "blacklist_slugs.json"

_BLACKLIST: set = set()


def _load() -> set:
    if not BLACKLIST_FILE.exists():
        return set()
    try:
        data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
        return set(data.get("slugs", []))
    except Exception:
        return set()


_BLACKLIST = _load()


def is_blacklisted(slug: str) -> bool:
    """Return True if the slug was manually blacklisted (do NOT fetch)."""
    if not slug:
        return False
    return slug in _BLACKLIST


def blacklist_size() -> int:
    return len(_BLACKLIST)


def reload() -> None:
    """Re-read blacklist_slugs.json (call if the file changed at runtime)."""
    global _BLACKLIST
    _BLACKLIST = _load()
