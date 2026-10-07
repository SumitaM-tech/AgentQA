"""Target URL validation for run creation (SSRF guard + user-facing warnings).

Reuses the browser layer's checks so the API and Playwright enforce the same rules:
http/https only, no embedded credentials, and (unless BROWSER_ALLOW_PRIVATE_NETWORKS)
no loopback / private / link-local / reserved addresses. Cloud-metadata (link-local)
targets are blocked unconditionally.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.browser.actions import ActionError, assert_url_allowed
from app.core.config import get_settings


@dataclass
class TargetCheck:
    ok: bool
    url: str
    host: str = ""
    error: str | None = None
    blocked: bool = False  # True = rejected by security policy (403), False = malformed input (400)
    warnings: list[str] = field(default_factory=list)


def _looks_local(host: str) -> bool:
    h = host.lower()
    if h in {"localhost", "0.0.0.0"} or h.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def host_matches(host: str, domains: list[str]) -> bool:
    h = host.lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in domains)


async def check_target_url(
    url: str, *, allow_private: bool | None = None, allowed_domains: list[str] | None = None,
) -> TargetCheck:
    """Validate a user-supplied target. Never raises; inspect `.ok` / `.error` / `.warnings`."""
    if allow_private is None:
        allow_private = get_settings().browser_allow_private_networks
    url = (url or "").strip()
    host = urlsplit(url).hostname or ""
    result = TargetCheck(ok=True, url=url, host=host)
    allow = get_settings().allowed_domains if allowed_domains is None else [d.lower() for d in allowed_domains]
    if allow and host and not host_matches(host, allow):
        result.ok, result.blocked = False, True
        result.error = f"'{host}' is not in the allowed domains ({', '.join(allow)})."
        return result
    try:
        await assert_url_allowed(url, allow_private)
    except ActionError as exc:
        if exc.code == "navigation_failed":  # DNS failure: allowed to proceed, but warn
            result.warnings.append(f"Could not resolve '{host}' right now; the run may fail to load the page.")
        else:
            result.ok = False
            result.error = str(exc)
            result.blocked = exc.code in ("domain_not_allowed", "private_network", "blocked_url", "forbidden") or \
                any(w in str(exc).lower() for w in ("private", "loopback", "link-local", "metadata", "not allowed", "blocked"))
            return result
    if _looks_local(host):
        result.warnings.append(
            "This target is a local/private address. It is only reachable because private networks are enabled "
            "(BROWSER_ALLOW_PRIVATE_NETWORKS=true); do not enable that on a shared or public deployment."
        )
    if url.startswith("http://") and not _looks_local(host):
        result.warnings.append("This site uses plain HTTP; traffic (including any credentials you provide) is unencrypted.")
    return result
