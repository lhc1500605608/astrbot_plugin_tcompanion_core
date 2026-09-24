"""Life content (v1.7 · Phase 3-B): configurable 见闻 / topic material.

Pure helpers (no SQLite, no network by default) plus the effective config. The
contract layer combines these with the store and optional injected fetcher /
summarizer.

Privacy & safety invariants:

* **No full text**: only a de-HTML'd, truncated summary is ever produced here;
  the raw source body never leaves this module.
* **SSRF guard**: sources must be ``http(s)`` and must not be a localhost /
  private / loopback / link-local literal.
* **Silent failure**: feed fetching/parsing returns empty/``None`` instead of
  raising, so a bad source never breaks the caller.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

#: Frozen defaults (mirrored by ``_conf_schema.json``).
CONTENT_MAX_ITEMS_PER_DAY_DEFAULT = 2
CONTENT_MAX_ITEMS_PER_DAY_MIN = 1
CONTENT_MAX_ITEMS_PER_DAY_MAX = 3
CONTENT_MAX_CHARS_DEFAULT = 80
CONTENT_TTL_DAYS_DEFAULT = 14

#: Internal guardrails (never surfaced in user-facing config).
MIN_REFRESH_INTERVAL_MIN = 120
CONTENT_SOURCE_TIMEOUT_SEC = 5.0
CONTENT_TOTAL_TIMEOUT_SEC = 12.0
CONTENT_SUMMARIZE_TIMEOUT_SEC = 6.0
CONTENT_READ_LIMIT = 20
CONTENT_WINDOW_HOURS = 72

#: Hard cap on a downloaded feed body (bounded memory / cost).
MAX_FEED_BYTES = 512 * 1024

#: Content kinds.
KIND_RSS = "rss"
KIND_TOPIC = "topic"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _cfg_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cfg_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cfg_str_list(value) -> tuple[str, ...]:
    """Coerce a config value into a tuple of non-empty, stripped strings."""
    if isinstance(value, str):
        raw: Sequence = value.replace(",", "\n").splitlines()
    elif isinstance(value, (list, tuple)):
        raw = value
    else:
        return ()
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return tuple(out)


@dataclass(frozen=True)
class ContentConfig:
    """Effective ``content`` config group (coerced + defaulted)."""

    enabled: bool = False
    sources: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    max_items_per_day: int = CONTENT_MAX_ITEMS_PER_DAY_DEFAULT
    summarize: bool = False
    provider_id: str = ""
    max_chars: int = CONTENT_MAX_CHARS_DEFAULT
    ttl_days: int = CONTENT_TTL_DAYS_DEFAULT

    def to_dict(self) -> dict:
        return asdict(self)


def parse_content_config(config) -> ContentConfig:
    """Read the ``content`` group from an AstrBot config mapping.

    Accepts the nested group and flat ``content_*`` keys; a missing group or an
    unparseable value falls back to the documented default. Re-parsed on each
    call because AstrBot hot-reload mutates the injected mapping in place.
    """
    mapping = config if isinstance(config, dict) else {}
    section = mapping.get("content")
    if not isinstance(section, dict):
        section = {}

    def pick(name: str, default, *, flat: str | None = None, aliases: tuple[str, ...] = ()):
        if name in section:
            return section[name]
        for alias in aliases:
            if alias in section:
                return section[alias]
        if flat and flat in mapping:
            return mapping[flat]
        return default

    max_items = _cfg_int(
        pick(
            "content_max_items_per_day",
            CONTENT_MAX_ITEMS_PER_DAY_DEFAULT,
            flat="content_max_items_per_day",
        ),
        CONTENT_MAX_ITEMS_PER_DAY_DEFAULT,
    )
    max_items = max(CONTENT_MAX_ITEMS_PER_DAY_MIN, min(CONTENT_MAX_ITEMS_PER_DAY_MAX, max_items))
    return ContentConfig(
        enabled=_cfg_bool(
            pick("content_enabled", False, flat="content_enabled", aliases=("enabled",)),
            False,
        ),
        sources=_cfg_str_list(pick("content_sources", (), flat="content_sources")),
        topics=_cfg_str_list(pick("content_topics", (), flat="content_topics")),
        max_items_per_day=max_items,
        summarize=_cfg_bool(
            pick("content_summarize", False, flat="content_summarize"), False
        ),
        provider_id=str(
            pick("content_provider_id", "", flat="content_provider_id") or ""
        ).strip(),
        max_chars=max(
            1,
            _cfg_int(
                pick("content_max_chars", CONTENT_MAX_CHARS_DEFAULT, flat="content_max_chars"),
                CONTENT_MAX_CHARS_DEFAULT,
            ),
        ),
        ttl_days=max(
            1,
            _cfg_int(
                pick("content_ttl_days", CONTENT_TTL_DAYS_DEFAULT, flat="content_ttl_days"),
                CONTENT_TTL_DAYS_DEFAULT,
            ),
        ),
    )


# -- text sanitising --------------------------------------------------------
def strip_html(text) -> str:
    """Drop HTML tags, unescape entities and collapse whitespace."""
    if text is None:
        return ""
    cleaned = _TAG_RE.sub(" ", str(text))
    cleaned = html.unescape(cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def truncate(text: str, max_chars: int) -> str:
    """Truncate to at most ``max_chars`` characters (ellipsis included)."""
    limit = max(1, int(max_chars))
    value = str(text or "")
    if len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    return value[: limit - 1].rstrip() + "…"


# -- source safety ----------------------------------------------------------
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def is_safe_source_url(url) -> bool:
    """Return whether ``url`` is an ``http(s)`` URL without a private target.

    Rejects non-http schemes, empty hosts, ``localhost`` / ``.local`` names and
    private, loopback, link-local, reserved, multicast or unspecified IP
    literals (SSRF guard). DNS names are allowed without resolving them.
    """
    try:
        parsed = urlparse(str(url or "").strip())
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in _BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def source_ref_for(url: str) -> str:
    """Return the de-identified source reference: ``sha256(url)`` truncated."""
    return hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()[:16]


def dedupe_key_for(source_ref: str, item: dict) -> str:
    """Build a stable dedupe key for one item (guid → link → title)."""
    identity = item.get("guid") or item.get("link") or item.get("title") or ""
    raw = f"{source_ref}|{identity}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# -- feed parsing -----------------------------------------------------------
def _local_tag(tag: str) -> str:
    return str(tag or "").split("}", 1)[-1].lower()


def _child_text(element, name: str) -> str:
    for child in element:
        if _local_tag(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _atom_link(element) -> str:
    fallback = ""
    for child in element:
        if _local_tag(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if not href:
            continue
        if (child.get("rel") or "alternate").lower() == "alternate":
            return href
        fallback = fallback or href
    return fallback


def _rss_item(element) -> dict:
    link = _child_text(element, "link")
    if not link:
        for child in element:
            if _local_tag(child.tag) == "link":
                link = (child.get("href") or "").strip()
                break
    return {
        "title": _child_text(element, "title"),
        "link": link,
        "summary": _child_text(element, "description") or _child_text(element, "summary"),
        "guid": _child_text(element, "guid"),
    }


def _atom_item(element) -> dict:
    return {
        "title": _child_text(element, "title"),
        "link": _atom_link(element),
        "summary": _child_text(element, "summary") or _child_text(element, "content"),
        "guid": _child_text(element, "id"),
    }


def parse_feed(xml_text) -> list[dict]:
    """Parse an RSS 2.0 or Atom document into ``{title,link,summary,guid}``.

    Namespace-agnostic and fail-silent: any parse error yields ``[]``.
    """
    if not isinstance(xml_text, str) or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError, TypeError):
        return []
    entries: list = []
    root_name = _local_tag(root.tag)
    if root_name == "feed":
        entries = [child for child in root if _local_tag(child.tag) == "entry"]
        parsed = [_atom_item(entry) for entry in entries]
    else:
        channel = next((c for c in root if _local_tag(c.tag) == "channel"), root)
        entries = [child for child in channel if _local_tag(child.tag) == "item"]
        parsed = [_rss_item(entry) for entry in entries]
    return [item for item in parsed if any(item.values())]


def _urllib_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "tcompanion-core/1.7"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data = response.read(MAX_FEED_BYTES)
    return data.decode("utf-8", errors="replace")


async def fetch_feed_text(url: str, *, timeout: float, fetcher=None) -> str | None:
    """Fetch a feed body; returns ``None`` on any error/timeout (never raises).

    ``fetcher`` may be injected (tests/QA): an async callable ``(url) -> str``.
    """
    try:
        if fetcher is not None:
            text = await asyncio.wait_for(fetcher(url), timeout=timeout)
        else:
            text = await asyncio.wait_for(
                asyncio.to_thread(_urllib_text, url, timeout), timeout=timeout
            )
    except Exception:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    return text
