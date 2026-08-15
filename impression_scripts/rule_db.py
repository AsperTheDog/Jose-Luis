import json
import sqlite3
import time
import asyncio
from collections import defaultdict
from typing import Dict, List, Type, Any, Optional

from impression_scripts.base_rule import EventHook, EventRule


class RuleDB:
    _registry: Dict[str, Type[EventRule]] = {}

    @classmethod
    def register_rule(cls, rule_type: str):
        def decorator(subclass: Type[EventRule]):
            cls._registry[rule_type] = subclass
            return subclass
        return decorator

    def __init__(self, db_path: str = "bot_data.db", config_path: Optional[str] = None):
        self.db_path = db_path
        self.hook_buckets: Dict[EventHook, List[EventRule]] = defaultdict(list)
        self.all_rules: List[EventRule] = []
        self._init_sqlite()

        if config_path:
            self.load_from_config(config_path)

    def _init_sqlite(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rule_cooldowns (
                    channel_id INTEGER NOT NULL,
                    rule_id TEXT NOT NULL,
                    last_triggered REAL NOT NULL,
                    PRIMARY KEY (channel_id, rule_id)
                )
            """)
            conn.commit()

    def load_from_config(self, config_path: str) -> None:
        self.hook_buckets.clear()
        self.all_rules.clear()

        with open(config_path, "r", encoding="utf-8") as f:
            rules_config = json.load(f)

        for rule_cfg in rules_config:
            rule_type = rule_cfg.get("type")
            if rule_type not in self._registry:
                print(f"[RuleDB Warning] Unknown rule type '{rule_type}'. Skipping.")
                continue

            rule_class = self._registry[rule_type]
            rule_instance = rule_class(**rule_cfg)

            self.all_rules.append(rule_instance)

            for hook in rule_instance.EVENT_HOOKS:
                self.hook_buckets[hook].append(rule_instance)

    async def is_rule_on_cooldown(self, channel_id: int, rule: EventRule) -> bool:
        if rule.cooldown_seconds <= 0:
            return False

        def query():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT last_triggered FROM rule_cooldowns WHERE channel_id = ? AND rule_id = ?",
                    (channel_id, rule.rule_id)
                )
                row = cursor.fetchone()
                if not row:
                    return False
                return (time.time() - row[0]) < rule.cooldown_seconds

        return await asyncio.to_thread(query)

    async def update_rule_cooldown(self, channel_id: int, rule_id: str):
        def query():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO rule_cooldowns (channel_id, rule_id, last_triggered)
                    VALUES (?, ?, ?)
                    ON CONFLICT(channel_id, rule_id) DO UPDATE SET last_triggered = excluded.last_triggered
                """, (channel_id, rule_id, time.time()))
                conn.commit()

        await asyncio.to_thread(query)

    async def get_eligible_rules(self, hook: EventHook, context: Any, tracker: Any = None) -> List[EventRule]:
        candidates = []
        channel_id = getattr(context, "id", None) or getattr(getattr(context, "channel", None), "id", 0)

        for rule in self.hook_buckets.get(hook, []):
            if rule.check_eligibility(context, tracker):
                if channel_id and await self.is_rule_on_cooldown(channel_id, rule):
                    continue
                candidates.append(rule)

        return candidates