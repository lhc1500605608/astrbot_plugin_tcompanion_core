from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.web import json_response

from .core.contract import PLUGIN_NAME, PLUGIN_VERSION, ContractV1
from .core.emotion import VALENCE_WINDOW_HOURS, emotion_snapshot, expression_for
from .core.paths import get_db_path
from .core.relationship import STAGE_STRANGER
from .core.store import Store


@register(
    PLUGIN_NAME,
    "tcompanion",
    "TCompanion 核心基座：为 AstrBot 提供关系好感度、生活状态与情绪表达档位的持久化数据。",
    PLUGIN_VERSION,
)
class TCompanionCore(Star):
    """Phase 1 Star skeleton.

    Holds the AstrBot ``context``, owns the SQLite store, and exposes the
    frozen contract. It intentionally does NOT start a scheduler and never
    sends messages on its own; the only reply is a user-triggered diagnostic.
    """

    def __init__(self, context: Context):
        super().__init__(context)
        self._store: Store | None = None
        self.contract: ContractV1 | None = None
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

    async def initialize(self):
        db_path = get_db_path()
        self._store = Store.open(db_path)
        self.contract = ContractV1(self._store)
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

    async def terminate(self):
        if self._store is not None:
            self._store.close()
            self._store = None
            self.contract = None
            logger.info("[tcompanion_core] terminated.")
