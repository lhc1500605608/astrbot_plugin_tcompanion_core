from __future__ import annotations

from datetime import datetime, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.web import json_response

from .core.contract import PLUGIN_NAME, PLUGIN_VERSION, ContractV1
from .core.paths import get_db_path
from .core.store import Store


@register(
    PLUGIN_NAME,
    "tcompanion",
    "TCompanion 核心基座：冻结契约 v1 + SQLite 存储 + LifeState/Schedule（Phase 1）。",
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

    async def terminate(self):
        if self._store is not None:
            self._store.close()
            self._store = None
            self.contract = None
            logger.info("[tcompanion_core] terminated.")
