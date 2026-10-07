"""Sanitization, redaction and truncation for anything page-derived that may
reach an LLM. Pages are untrusted input: strip invisible/control characters
(used to hide prompt-injection text), redact obvious secrets, bound sizes."""
from __future__ import annotations

import re
import unicodedata

REDACTED = "[redacted]"

_KEEP_CONTROL = {"\n", "\t"}
_WS = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")

_SECRET_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),  # Google API key
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),  # GitHub token
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),  # generic secret-key style
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
]
_CARD_CANDIDATE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")

_SENSITIVE_NAME = re.compile(
    r"pass(word|wd)?|pwd|secret|token|otp|cvv|cvc|ssn|card.?n(um|o)|api.?key", re.IGNORECASE
)
_SENSITIVE_AUTOCOMPLETE = re.compile(r"password|cc-|one-time-code", re.IGNORECASE)

# Aria-snapshot lines that carry a live field value, e.g.  - textbox "Pass": hunter2
_ARIA_VALUE_LINE = re.compile(r'^(\s*- (?:textbox|searchbox|spinbutton|slider|combobox)(?: "[^"]*")?):\s*\S.*$')
_ARIA_URL_LINE = re.compile(r"^(\s*- /url:\s*[^?\s]*)\?\S*$")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def strip_invisible(text: str) -> str:
    """Drop control chars and format chars (zero-width, bidi overrides, Unicode
    tag characters), plus private-use/surrogates. Keeps \\n and \\t."""
    out = []
    for ch in text:
        if ch in _KEEP_CONTROL:
            out.append(ch)
            continue
        if unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        out.append(ch)
    return "".join(out)


def redact_secrets(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(REDACTED, text)

    def _card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return REDACTED if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

    return _CARD_CANDIDATE.sub(_card, text)


def truncate(text: str, max_chars: int) -> tuple[str, int]:
    """Truncate to max_chars (marker included). Returns (text, omitted_chars)."""
    if len(text) <= max_chars:
        return text, 0
    omitted = len(text) - max_chars
    marker = f"…[+{omitted} chars]"
    keep = max(0, max_chars - len(marker))
    return text[:keep].rstrip() + marker, omitted


def clean_inline(text: str | None, max_chars: int, *, redact: bool = True) -> str:
    """Single-line field (names, labels, values): sanitize, collapse whitespace, truncate."""
    if not text:
        return ""
    text = strip_invisible(text)
    text = " ".join(text.split())
    if redact:
        text = redact_secrets(text)
    return truncate(text, max_chars)[0]


def clean_block(text: str | None, max_chars: int, *, redact: bool = True) -> tuple[str, int]:
    """Multi-line text: sanitize, normalize whitespace, cap blank lines, truncate."""
    if not text:
        return "", 0
    text = strip_invisible(text).replace("\r", "")
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text).strip()
    if redact:
        text = redact_secrets(text)
    return truncate(text, max_chars)


def is_sensitive_field(*hints: str | None) -> bool:
    """True if a field's type/name/autocomplete hints indicate a secret."""
    for h in hints:
        if not h:
            continue
        if h.lower() == "password" or _SENSITIVE_NAME.search(h) or _SENSITIVE_AUTOCOMPLETE.search(h):
            return True
    return False


def sanitize_aria_snapshot(snapshot: str, max_chars: int) -> tuple[str, int]:
    """Remove live field values and URL query strings from an aria snapshot,
    then sanitize/truncate on a line boundary."""
    lines = []
    for line in snapshot.splitlines():
        m = _ARIA_VALUE_LINE.match(line)
        if m:
            line = f"{m.group(1)}: [value omitted]"
        m = _ARIA_URL_LINE.match(line)
        if m:
            line = f"{m.group(1)}?…"
        lines.append(line)
    text = strip_invisible("\n".join(lines))
    text = redact_secrets(text)
    if len(text) <= max_chars:
        return text, 0
    cut = text[:max_chars].rsplit("\n", 1)[0]
    omitted = len(text) - len(cut)
    return f"{cut}\n…[+{omitted} chars]", omitted


def escape_untrusted(text: str) -> str:
    """Neutralize our delimiter so page text cannot forge the end of the
    untrusted block."""
    return text.replace("===", "= = =")
