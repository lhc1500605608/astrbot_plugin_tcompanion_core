"""Optional read-only bridge to the memory plugin's public prompt APIs.

companion-core never talks to the memory plugin's database. It resolves the
plugin through ``context.get_registered_star(name)`` (activated check) and calls
two public read-only methods when they exist:

* ``recall_for_prompt(umo, query, session_type, limit) -> list[str]`` — short,
  already-clipped recollection snippets;
* ``get_profile_for_prompt(umo, query, limit, session_type) -> dict`` — the user
  profile projection (``facets`` / ``summary`` / ``highlights``), probed with
  ``hasattr`` so an older memory plugin without it simply yields no profile;
* ``resolve_person(umo) -> dict`` (v1.5) — the authoritative Person identity
  (``person_id`` = the memory plugin's ``canonical_user_id``). Only the private
  ``person_id`` is consumed here; a group scope or an older plugin without the
  method degrades to ``None`` so callers fall back to ``parse_umo``.

Invariants (see ``docs/CONTRACT.md`` §14):

* **Fail-closed**: missing plugin / disabled / timeout / any exception returns
  ``None`` — callers then behave exactly as if the bridge were absent.
* **Read-only, no raw text**: only the (already clipped) short strings the memory
  plugin returns are relayed; nothing is written back and no message body is
  stored. Counters log outcomes, never content.
* **Bounded**: each call is wrapped in ``asyncio.wait_for`` (default 2s) and
  results are cached per scope for a short TTL so a burst of messages does not
  hammer the memory plugin.
* **Group isolation**: group scopes only ever receive ``snippets``; the profile
  is never fetched or returned for a group scope.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

#: Plugin name resolved from the AstrBot star registry by default.
DEFAULT_MEMORY_PLUGIN_NAME = "astrbot_plugin_tmemory"

#: Defaults for the ``memory_bridge`` config group (see ``_conf_schema.json``).
MEMORY_BRIDGE_TIMEOUT_SEC = 2.0
MEMORY_BRIDGE_LIMIT = 4
MEMORY_BRIDGE_TTL_MIN = 5

#: Hard bounds so a malformed config can't blow up latency or memory.
MEMORY_BRIDGE_MAX_TIMEOUT_SEC = 10.0
MEMORY_BRIDGE_MAX_LIMIT = 20
MEMORY_BRIDGE_MAX_TTL_MIN = 120

#: Clipping bounds mirrored from the memory plugin's contract.
SNIPPET_MAX_CHARS = 200
SUMMARY_MAX_CHARS = 200
HIGHLIGHT_MAX_CHARS = 120
#: Query length ceiling (kept short — the memory plugin embeds it).
QUERY_MAX_CHARS = 100

#: ``expression_decision`` warmth nudge when a profile is present.
MEMORY_WARMTH_STEP = 0.03
#: Hard ceiling on that nudge (base + this, never mode-changing).
MEMORY_WARMTH_MAX_DELTA = 0.05


@dataclass(frozen=True)
class MemoryBridgeConfig:
    """Effective ``memory_bridge`` config group (coerced + defaulted)."""

    enabled: bool = True
    plugin_name: str = DEFAULT_MEMORY_PLUGIN_NAME
    timeout_sec: float = MEMORY_BRIDGE_TIMEOUT_SEC
    limit: int = MEMORY_BRIDGE_LIMIT
    ttl_min: int = MEMORY_BRIDGE_TTL_MIN

    def to_dict(self) -> dict:
        return asdict(self)


def _cfg_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cfg_int(value, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _cfg_float(value, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def parse_memory_bridge_config(config) -> MemoryBridgeConfig:
    """Read the ``memory_bridge`` group from an AstrBot config mapping.

    Fail-safe: a missing/!mapping group or an unparseable value falls back to the
    documented default, so a malformed config never disables the bridge or raises
    into a read path. Flat ``memory_bridge_*`` keys are also accepted for
    tolerance. Parsed fresh on each call (config hot-reload mutates the injected
    ``AstrBotConfig`` in place).
    """
    section: dict = {}
    source = config if isinstance(config, dict) else {}
    raw = source.get("memory_bridge")
    if isinstance(raw, dict):
        section = raw
    else:
        section = {
            "enabled": source.get("memory_bridge_enabled"),
            "plugin_name": source.get("memory_bridge_plugin_name"),
            "timeout_sec": source.get("memory_bridge_timeout_sec"),
            "limit": source.get("memory_bridge_limit"),
            "ttl_min": source.get("memory_bridge_ttl_min"),
        }
    name = str(section.get("plugin_name") or "").strip() or DEFAULT_MEMORY_PLUGIN_NAME
    return MemoryBridgeConfig(
        enabled=_cfg_bool(section.get("enabled"), True),
        plugin_name=name,
        timeout_sec=_cfg_float(
            section.get("timeout_sec"),
            MEMORY_BRIDGE_TIMEOUT_SEC,
            0.05,
            MEMORY_BRIDGE_MAX_TIMEOUT_SEC,
        ),
        limit=_cfg_int(section.get("limit"), MEMORY_BRIDGE_LIMIT, 1, MEMORY_BRIDGE_MAX_LIMIT),
        ttl_min=_cfg_int(section.get("ttl_min"), MEMORY_BRIDGE_TTL_MIN, 0, MEMORY_BRIDGE_MAX_TTL_MIN),
    )


def _clip(text: str, max_chars: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


class MemoryBridge:
    """Fail-closed, cached, read-only access to the memory plugin.

    ``context`` is the AstrBot Star context (only ``get_registered_star`` is
    used). ``config`` is the injected AstrBot config mapping; ``clock`` is a
    monotonic source for TTL bookkeeping (overridable in tests).
    """

    def __init__(self, context, config=None, clock: Callable[[], float] | None = None) -> None:
        self._context = context
        self._config = config
        self._clock = clock or time.monotonic
        # cache key -> (expires_at, payload | None); payload is a dict for
        # ``fetch`` and a person-id str for ``resolve_person``
        self._cache: dict[str, tuple[float, dict | str | None]] = {}
        self.hits = 0
        self.degrades = 0
        self.timeouts = 0

    # -- config / resolution ------------------------------------------------
    def config(self) -> MemoryBridgeConfig:
        try:
            return parse_memory_bridge_config(self._config)
        except Exception:
            return MemoryBridgeConfig()

    def _resolve_star(self, plugin_name: str):
        getter = getattr(self._context, "get_registered_star", None)
        if not callable(getter):
            return None
        try:
            metadata = getter(plugin_name)
        except Exception:
            return None
        if metadata is None or not getattr(metadata, "activated", True):
            return None
        return getattr(metadata, "star_cls", None)

    # -- cache --------------------------------------------------------------
    def _cache_get(self, key: str):
        entry = self._cache.get(key)
        if entry is None:
            return False, None
        expires_at, payload = entry
        if self._clock() >= expires_at:
            self._cache.pop(key, None)
            return False, None
        return True, payload

    def _cache_put(self, key: str, payload: dict | str | None, ttl_min: int) -> None:
        if ttl_min <= 0:
            self._cache.pop(key, None)
            return
        self._cache[key] = (self._clock() + ttl_min * 60, payload)

    # -- reads --------------------------------------------------------------
    async def fetch(
        self,
        umo: str,
        *,
        query: str = "",
        session_type: str = "private",
    ) -> dict | None:
        """Return ``{snippets, [profile], as_of}`` or ``None`` (fail-closed).

        Never raises: an unavailable/disabled/timeout/erroring memory plugin, or
        simply no memory data, all collapse to ``None`` (the caller then emits no
        ``memory`` key and behaves exactly as before the bridge existed).
        """
        cfg = self.config()
        umo = str(umo or "").strip()
        if not cfg.enabled or not umo:
            return None

        is_group = str(session_type or "").strip().lower() == "group"
        norm_query = _clip(query, QUERY_MAX_CHARS)
        key = f"{umo}|{'group' if is_group else 'private'}|{norm_query}"
        cached, payload = self._cache_get(key)
        if cached:
            if payload is not None:
                self.hits += 1
            return payload

        star = self._resolve_star(cfg.plugin_name)
        if star is None:
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None

        snippets = await self._read_snippets(star, umo, norm_query, session_type, cfg)
        if snippets is False:  # timeout/exception sentinel
            self._cache_put(key, None, cfg.ttl_min)
            return None

        profile = None
        if not is_group:
            profile = await self._read_profile(star, umo, norm_query, session_type, cfg)

        built: dict = {}
        if snippets:
            built["snippets"] = snippets
        if profile:
            built["profile"] = profile
        if not built:
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None

        built["as_of"] = datetime.now(timezone.utc).isoformat()
        self.hits += 1
        self._cache_put(key, built, cfg.ttl_min)
        return built

    async def resolve_person(self, umo: str) -> str | None:
        """Return the authoritative ``person_id`` for a private ``umo`` (v1.5).

        Consumes the memory plugin's public read-only ``resolve_person(umo)``
        (probed with ``hasattr`` so an older plugin simply degrades). Private
        scopes yield the canonical Person id, which the caller uses as the
        relationship/emotion/life-line key so switching adapters keeps the same
        person. **Fail-closed**: a disabled bridge, missing/older plugin,
        group scope, timeout, error or empty result all return ``None`` — the
        caller then falls back to ``parse_umo()`` and behaves exactly as v1.4.0.

        The result is cached under the ``umo`` for ``ttl_min`` (a negative
        ``None`` is cached too), so a burst of messages never queries per-message.
        """
        cfg = self.config()
        umo = str(umo or "").strip()
        if not cfg.enabled or not umo:
            return None

        key = f"person|{umo}"
        cached, payload = self._cache_get(key)
        if cached:
            if isinstance(payload, str) and payload:
                self.hits += 1
                return payload
            return None

        star = self._resolve_star(cfg.plugin_name)
        if star is None:
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None
        resolver = getattr(star, "resolve_person", None)
        if not callable(resolver):
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None
        try:
            raw = await asyncio.wait_for(resolver(umo), timeout=cfg.timeout_sec)
        except asyncio.TimeoutError:
            self.timeouts += 1
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None
        except Exception:
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None

        person_id = ""
        if isinstance(raw, dict) and not raw.get("is_group"):
            person_id = str(raw.get("person_id") or "").strip()
        if not person_id:
            self.degrades += 1
            self._cache_put(key, None, cfg.ttl_min)
            return None
        self.hits += 1
        self._cache_put(key, person_id, cfg.ttl_min)
        return person_id

    async def _read_snippets(
        self, star, umo: str, query: str, session_type: str, cfg: MemoryBridgeConfig
    ) -> list[str] | bool:
        """Return clipped snippets, ``[]`` for none, or ``False`` on failure."""
        if not query:
            return []
        recall = getattr(star, "recall_for_prompt", None)
        if not callable(recall):
            return []
        try:
            raw = await asyncio.wait_for(
                recall(umo, query, session_type=session_type, limit=cfg.limit),
                timeout=cfg.timeout_sec,
            )
        except asyncio.TimeoutError:
            self.timeouts += 1
            self.degrades += 1
            return False
        except Exception:
            self.degrades += 1
            return False
        if not isinstance(raw, (list, tuple)):
            return []
        out: list[str] = []
        for item in raw:
            text = _clip(item, SNIPPET_MAX_CHARS)
            if text:
                out.append(text)
        return out[: cfg.limit]

    async def _read_profile(
        self, star, umo: str, query: str, session_type: str, cfg: MemoryBridgeConfig
    ) -> dict | None:
        """Return the normalized profile projection, or ``None`` (fail-closed)."""
        getter = getattr(star, "get_profile_for_prompt", None)
        if not callable(getter):
            return None
        try:
            raw = await asyncio.wait_for(
                getter(umo, query, limit=cfg.limit, session_type=session_type),
                timeout=cfg.timeout_sec,
            )
        except asyncio.TimeoutError:
            self.timeouts += 1
            self.degrades += 1
            return None
        except Exception:
            self.degrades += 1
            return None
        if not isinstance(raw, dict) or not raw:
            return None

        facets: dict[str, int] = {}
        raw_facets = raw.get("facets")
        if isinstance(raw_facets, dict):
            for facet, count in raw_facets.items():
                name = str(facet or "").strip()
                if not name:
                    continue
                try:
                    facets[name] = int(count)
                except (TypeError, ValueError):
                    continue

        summary = _clip(raw.get("summary"), SUMMARY_MAX_CHARS)

        highlights: list[str] = []
        raw_highlights = raw.get("highlights")
        if isinstance(raw_highlights, (list, tuple)):
            for item in raw_highlights:
                text = _clip(item, HIGHLIGHT_MAX_CHARS)
                if text:
                    highlights.append(text)

        if not facets and not summary and not highlights:
            return None
        return {"facets": facets, "summary": summary, "highlights": highlights}

    # -- observability ------------------------------------------------------
    def stats(self) -> dict:
        """Read-only counters (no content). Used by panels/tests."""
        return {"hit": self.hits, "degrade": self.degrades, "timeout": self.timeouts}
