from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.web import json_response

try:  # pragma: no cover - older AstrBot / the off-device test stub
    from astrbot.api.web import request as _web_request
except Exception:  # pragma: no cover
    _web_request = None

from .core.contract import PLUGIN_NAME, PLUGIN_VERSION, ContractV1
from .core.emotion import VALENCE_WINDOW_HOURS, emotion_snapshot, expression_for
from .core.memory_bridge import MemoryBridge
from .core.paths import get_db_path
from .core.relationship import STAGE_STRANGER
from .core.store import Store


@register(
    PLUGIN_NAME,
    "tcompanion",
    "Hearthlight · 守灯：为 AstrBot 提供关系好感度、生活状态与情绪表达档位的持久化数据。",
    PLUGIN_VERSION,
)
class TCompanionCore(Star):
    """Phase 1 Star skeleton.

    Holds the AstrBot ``context``, owns the SQLite store, and exposes the
    frozen contract. It intentionally does NOT start a scheduler and never
    sends messages on its own; the only reply is a user-triggered diagnostic.
    """

    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self._store: Store | None = None
        self.contract: ContractV1 | None = None
        self._memory_bridge: MemoryBridge | None = None
        context.register_web_api(
            f"/{PLUGIN_NAME}/life-state",
            self.api_life_state,
            ["GET"],
            "Current life state for all personas (today)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/relationships",
            self.api_relationships,
            ["GET"],
            "All relationships (read-only)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/motivation-log",
            self.api_motivation_log,
            ["GET"],
            "Motivation audit log (read-only)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/emotion-state",
            self.api_emotion_state,
            ["GET"],
            "Derived emotion state / expression mode per relationship (read-only)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/group-state",
            self.api_group_state,
            ["GET"],
            "Group activity + advisory participation gate (read-only)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/growth-state",
            self.api_growth_state,
            ["GET"],
            "Derived growth per private relationship (read-only)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/person/keys",
            self.api_person_keys,
            ["GET"],
            "Distinct private (persona_id, user_id) keys seen in the store (read-only)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/person/migrate",
            self.api_person_migrate,
            ["POST"],
            "One-time merge of per-adapter private rows onto a Person key",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/person/migrate/rollback",
            self.api_person_migrate_rollback,
            ["POST"],
            "Roll back the latest Person-key migration from its JSON backup",
        )

    async def initialize(self):
        db_path = get_db_path()
        self._store = Store.open(db_path)
        # Optional read-only bridge to the memory plugin (fail-closed when absent).
        self._memory_bridge = MemoryBridge(context=self.context, config=self.config)
        self.contract = ContractV1(
            self._store, config=self.config, memory_bridge=self._memory_bridge
        )
        logger.info(
            "[tcompanion_core] initialized: contract v%s schema v%s db=%s",
            self.contract.api_version,
            self._store.schema_version,
            db_path,
        )

    @filter.command("tcompanion_info")
    async def tcompanion_info(self, event: AstrMessageEvent):
        """诊断指令（用户主动触发，非主动消息）：查看契约版本与 schema 版本。"""
        if self.contract is None or self._store is None:
            yield event.plain_result("tcompanion_core 尚未初始化。")
            return
        info = await self.contract.get_contract_info()
        yield event.plain_result(
            "tcompanion_core "
            f"api_version={info['api_version']} "
            f"schema_version={info['schema_version']} "
            f"plugin_version={info['plugin_version']}"
        )

    # -- Contract surface (cross-plugin boundary) --------------------------
    # Downstream plugins (kanjyou) resolve this Star via
    # ``context.get_registered_star(name).star_cls`` and ``getattr``. The
    # frozen contract must therefore live on the Star instance too, not only on
    # the private ``self.contract``; each method below is a thin delegate.
    def _contract(self) -> ContractV1:
        if self.contract is None:
            raise RuntimeError("tcompanion_core contract not initialized")
        return self.contract

    async def get_contract_info(self) -> dict:
        return await self._contract().get_contract_info()

    async def get_life_state(self, persona_id: str) -> dict | None:
        return await self._contract().get_life_state(persona_id)

    async def get_relationship(self, umo: str, persona_id: str | None = None) -> dict:
        return await self._contract().get_relationship(umo, persona_id)

    async def get_proactive_context(self, umo: str, persona_id: str | None = None) -> dict:
        return await self._contract().get_proactive_context(umo, persona_id)

    async def on_proactive_outcome(
        self,
        umo: str,
        *,
        sent: bool,
        reason_code: str,
        replied: bool = False,
        persona_id: str | None = None,
        event_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        return await self._contract().on_proactive_outcome(
            umo,
            sent=sent,
            reason_code=reason_code,
            replied=replied,
            persona_id=persona_id,
            event_id=event_id,
            now=now,
        )

    async def record_open_thread(
        self,
        umo: str,
        *,
        label: str,
        kind: str,
        reason: str = "",
        dedupe_key: str | None = None,
        confidence: float = 1.0,
        source: str = "",
        now: datetime | None = None,
    ) -> dict:
        return await self._contract().record_open_thread(
            umo,
            label=label,
            kind=kind,
            reason=reason,
            dedupe_key=dedupe_key,
            confidence=confidence,
            source=source,
            now=now,
        )

    async def get_open_threads(
        self, umo: str, limit: int = 3, persona_id: str | None = None
    ) -> list[dict]:
        return await self._contract().get_open_threads(umo, limit=limit, persona_id=persona_id)

    async def close_open_thread(self, umo: str, thread_id: str, reason: str = "") -> dict:
        return await self._contract().close_open_thread(umo, thread_id, reason=reason)

    async def mark_thread_followup(
        self, umo: str, thread_id: str, now: datetime | None = None
    ) -> dict:
        return await self._contract().mark_thread_followup(umo, thread_id, now=now)

    async def record_emotion_event(
        self,
        umo: str,
        *,
        event_type: str,
        reason: str = "",
        dedupe_key: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        return await self._contract().record_emotion_event(
            umo,
            event_type=event_type,
            reason=reason,
            dedupe_key=dedupe_key,
            now=now,
        )

    async def get_emotion_context(self, umo: str, persona_id: str | None = None) -> dict:
        return await self._contract().get_emotion_context(umo, persona_id)

    async def expression_decision(self, umo: str, persona_id: str | None = None) -> dict:
        return await self._contract().expression_decision(umo, persona_id)

    async def record_group_activity(
        self,
        umo: str,
        *,
        member_id: str | None = None,
        topic: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        return await self._contract().record_group_activity(
            umo, member_id=member_id, topic=topic, now=now
        )

    async def get_group_context(
        self, umo: str, persona_id: str | None = None, *, member_id: str | None = None
    ) -> dict:
        return await self._contract().get_group_context(
            umo, persona_id, member_id=member_id
        )

    async def get_growth_context(self, umo: str, persona_id: str | None = None) -> dict:
        return await self._contract().get_growth_context(umo, persona_id)

    async def get_life_line(self, umo: str, day: str | None = None) -> dict:
        return await self._contract().get_life_line(umo, day=day)

    async def get_diary(self, umo: str, day: str | None = None) -> dict | None:
        return await self._contract().get_diary(umo, day=day)

    async def migrate_person(
        self,
        person_id: str,
        aliases: list[str] | None = None,
        *,
        backup_dir: str | None = None,
    ) -> dict:
        """One-time merge of per-adapter private keys onto a Person key (v1.5)."""
        if self._store is None:
            return {"ok": False, "reason": "store_not_ready"}
        return self._store.migrate_person_keys(
            person_id, aliases or [], backup_dir=backup_dir
        )

    async def rollback_person_migration(self, backup_path: str | None = None) -> dict:
        """Restore the pre-migration rows from a migration JSON backup (v1.5)."""
        if self._store is None:
            return {"ok": False, "reason": "store_not_ready"}
        return self._store.rollback_person_migration(backup_path)

    # -- Web API handlers (read-only panel) --------------------------------
    async def api_life_state(self):
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        day = datetime.now(timezone.utc).date().isoformat()
        rows = self._store.list_life_states(day)
        return json_response({"day": day, "items": rows})

    async def api_relationships(self):
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        rows = self._store.list_relationships()
        return json_response({"items": rows})

    async def api_motivation_log(self):
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        rows = self._store.list_motivation_log(limit=100)
        return json_response({"items": rows})

    async def api_emotion_state(self):
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        now = datetime.now(timezone.utc)
        since = (now - timedelta(hours=VALENCE_WINDOW_HOURS)).isoformat()
        day = now.date().isoformat()
        items = []
        for rel in self._store.list_relationships():
            persona_id = str(rel.get("persona_id") or "")
            user_id = str(rel.get("user_id") or "")
            streak = self._store.get_interaction_dynamics(persona_id, user_id).unanswered_streak
            events = self._store.list_emotion_events(
                persona_id, user_id, since_iso=since, limit=200
            )
            snapshot = emotion_snapshot(events, now=now, unanswered_streak=streak)
            life = self._store.get_life_state(persona_id, day) or {}
            decision = expression_for(
                state=snapshot["state"],
                valence=snapshot["valence"],
                stage=str(rel.get("stage") or STAGE_STRANGER),
                bond=bool(rel.get("bond")),
                energy=float(life.get("energy") or 0.0),
                unanswered_streak=streak,
            )
            items.append(
                {
                    "persona_id": persona_id,
                    "user_id": user_id,
                    "state": snapshot["state"],
                    "valence": snapshot["valence"],
                    "last_event": snapshot["last_event"],
                    "mode": decision["mode"],
                    "as_of": snapshot["as_of"],
                }
            )
        return json_response({"items": items})

    async def api_group_state(self):
        """Flat group activity + advisory gate; a pure read (never stamps)."""
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        return json_response({"items": self._contract().list_group_states()})

    async def api_growth_state(self):
        """Flat derived growth per private relationship (read-only)."""
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        return json_response({"items": self._contract().list_growth_states()})

    async def _json_body(self) -> dict:
        if _web_request is None:
            return {}
        try:
            body = await _web_request.json(default={})
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    async def api_person_keys(self):
        """Read-only list of legacy private keys, to pick migration aliases."""
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        return json_response({"items": self._store.list_person_key_candidates()})

    async def api_person_migrate(self):
        """POST body ``{person_id, aliases[]}`` → idempotent merge (+ backup)."""
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        body = await self._json_body()
        person_id = str(body.get("person_id") or "").strip()
        aliases = body.get("aliases") or body.get("adapter_user_ids") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if not person_id or not isinstance(aliases, (list, tuple)):
            return json_response(
                {"ok": False, "reason": "invalid_args"}, status_code=400
            )
        result = await self.migrate_person(person_id, list(aliases))
        return json_response(result, status_code=200 if result.get("ok") else 400)

    async def api_person_migrate_rollback(self):
        """POST body ``{backup_path?}`` → restore the pre-migration rows."""
        if self._store is None:
            return json_response({"error": "store not ready"}, status_code=503)
        body = await self._json_body()
        backup_path = str(body.get("backup_path") or "").strip() or None
        result = await self.rollback_person_migration(backup_path)
        return json_response(result, status_code=200 if result.get("ok") else 400)

    async def terminate(self):
        if self._store is not None:
            self._store.close()
            self._store = None
            self.contract = None
            self._memory_bridge = None
            logger.info("[tcompanion_core] terminated.")
