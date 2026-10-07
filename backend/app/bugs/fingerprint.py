"""Deterministic bug fingerprints used to avoid duplicate reports.

Two findings are "the same bug" when they share category, normalized URL path (no query/ids),
and a normalized description of the symptom (numbers/ids/quoted values stripped).
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

_HEX_OR_ID = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_NUM = re.compile(r"\d+")
_QUOTED = re.compile(r"(['\"]).*?\1")
_WS = re.compile(r"\s+")
_PATH_ID = re.compile(r"/(?:\d+|[0-9a-f]{8,}(?:-[0-9a-f]{4,})*)(?=/|$)", re.I)


def normalize_url(url: str) -> str:
    """scheme-less host + path with numeric/uuid segments collapsed; query and fragment dropped."""
    parts = urlsplit(url or "")
    path = _PATH_ID.sub("/:id", parts.path or "/").rstrip("/") or "/"
    return f"{(parts.hostname or '').lower()}{path}"


def normalize_text(text: str) -> str:
    t = _QUOTED.sub("", (text or "").lower())
    t = _HEX_OR_ID.sub("", t)
    t = _NUM.sub("#", t)
    return _WS.sub(" ", t).strip()[:160]


def bug_fingerprint(category: str, url: str, title: str) -> str:
    key = "|".join([(category or "").lower(), normalize_url(url), normalize_text(title)])
    return hashlib.sha256(key.encode()).hexdigest()[:32]
