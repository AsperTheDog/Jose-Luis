import sqlite3
from typing import List, Optional


class GuildConfigManager:
    DEFAULT_CONFIG = {
        "admin_channel_id": 0,
        "log_channel_id": 0,
        "death_channel_id": 0,
        "death_grace_seconds": 60.0,
        "global_cooldown_seconds": 600.0,
        "event_mensajes": True,
        "event_miembros": True,
        "event_moderacion": True,
        "event_canales": True,
    }

    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            c = conn.cursor()

            # Main Guild Configuration Table
            c.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    admin_channel_id INTEGER NOT NULL DEFAULT 0,
                    log_channel_id INTEGER DEFAULT 0,
                    death_channel_id INTEGER NOT NULL DEFAULT 0,
                    death_grace_seconds REAL NOT NULL DEFAULT 60.0,
                    global_cooldown_seconds REAL NOT NULL DEFAULT 600.0,
                    event_mensajes INTEGER NOT NULL DEFAULT 1,
                    event_miembros INTEGER NOT NULL DEFAULT 1,
                    event_moderacion INTEGER NOT NULL DEFAULT 1,
                    event_canales INTEGER NOT NULL DEFAULT 1
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS guild_operators (
                    guild_id INTEGER NOT NULL,
                    operator_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, operator_id),
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS guild_channel_whitelist (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id),
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def ensure_guild_exists(self, guild_id: int) -> None:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT OR IGNORE INTO guild_config (
                    guild_id, admin_channel_id, log_channel_id, death_channel_id,
                    death_grace_seconds, global_cooldown_seconds, 
                    event_mensajes, event_miembros, event_moderacion, event_canales
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    guild_id,
                    self.DEFAULT_CONFIG["admin_channel_id"],
                    self.DEFAULT_CONFIG["log_channel_id"],
                    self.DEFAULT_CONFIG["death_channel_id"],
                    self.DEFAULT_CONFIG["death_grace_seconds"],
                    self.DEFAULT_CONFIG["global_cooldown_seconds"],
                    int(self.DEFAULT_CONFIG["event_mensajes"]),
                    int(self.DEFAULT_CONFIG["event_miembros"]),
                    int(self.DEFAULT_CONFIG["event_moderacion"]),
                    int(self.DEFAULT_CONFIG["event_canales"]),
                ),
            )
            conn.commit()

    def get_admin_channel_id(self, guild_id: int) -> int:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT admin_channel_id FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return res["admin_channel_id"] if res else 0

    def get_log_channel_id(self, guild_id: int) -> Optional[int]:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT log_channel_id FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return res["log_channel_id"] if res else None

    def get_death_channel_id(self, guild_id: int) -> int:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT death_channel_id FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return res["death_channel_id"] if res else 0

    def get_death_grace_seconds(self, guild_id: int) -> float:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT death_grace_seconds FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return res["death_grace_seconds"] if res else 60.0

    def get_global_cooldown_seconds(self, guild_id: int) -> float:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT global_cooldown_seconds FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return res["global_cooldown_seconds"] if res else 600.0

    def get_event_mensajes(self, guild_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT event_mensajes FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return bool(res["event_mensajes"]) if res else True

    def get_event_miembros(self, guild_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT event_miembros FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return bool(res["event_miembros"]) if res else True

    def get_event_moderacion(self, guild_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT event_moderacion FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return bool(res["event_moderacion"]) if res else True

    def get_event_canales(self, guild_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            res = conn.execute("SELECT event_canales FROM guild_config WHERE guild_id = ?", (guild_id,),).fetchone()
            return bool(res["event_canales"]) if res else True

    def set_admin_channel_id(self, guild_id: int, channel_id: int) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET admin_channel_id = ? WHERE guild_id = ?", (channel_id, guild_id),)
            conn.commit()

    def set_log_channel_id(self, guild_id: int, channel_id: Optional[int]) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET log_channel_id = ? WHERE guild_id = ?", (channel_id, guild_id),)
            conn.commit()

    def set_death_channel_id(self, guild_id: int, channel_id: int) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET death_channel_id = ? WHERE guild_id = ?", (channel_id, guild_id),)
            conn.commit()

    def set_death_grace_seconds(self, guild_id: int, seconds: float) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET death_grace_seconds = ? WHERE guild_id = ?", (seconds, guild_id),)
            conn.commit()

    def set_global_cooldown_seconds(self, guild_id: int, seconds: float) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET global_cooldown_seconds = ? WHERE guild_id = ?", (seconds, guild_id),)
            conn.commit()

    def set_event_mensajes(self, guild_id: int, enabled: bool) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET event_mensajes = ? WHERE guild_id = ?", (int(enabled), guild_id),)
            conn.commit()

    def set_event_miembros(self, guild_id: int, enabled: bool) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET event_miembros = ? WHERE guild_id = ?", (int(enabled), guild_id),)
            conn.commit()

    def set_event_moderacion(self, guild_id: int, enabled: bool) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET event_moderacion = ? WHERE guild_id = ?", (int(enabled), guild_id),)
            conn.commit()

    def set_event_canales(self, guild_id: int, enabled: bool) -> None:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            conn.execute("UPDATE guild_config SET event_canales = ? WHERE guild_id = ?", (int(enabled), guild_id),)
            conn.commit()

    def get_operators(self, guild_id: int) -> List[int]:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            rows = conn.execute("SELECT operator_id FROM guild_operators WHERE guild_id = ?", (guild_id,),).fetchall()
            return [row["operator_id"] for row in rows]

    def add_operator(self, guild_id: int, operator_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO guild_operators (guild_id, operator_id) VALUES (?, ?)", (guild_id, operator_id),)
            conn.commit()
            return c.rowcount > 0

    def remove_operator(self, guild_id: int, operator_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM guild_operators WHERE guild_id = ? AND operator_id = ?", (guild_id, operator_id),)
            conn.commit()
            return c.rowcount > 0

    def is_operator(self, guild_id: int, operator_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            row = conn.execute("SELECT 1 FROM guild_operators WHERE guild_id = ? AND operator_id = ?", (guild_id, operator_id),).fetchone()
            return row is not None

    def get_channel_whitelist(self, guild_id: int) -> List[int]:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            rows = conn.execute("SELECT channel_id FROM guild_channel_whitelist WHERE guild_id = ?", (guild_id,),).fetchall()
            return [row["channel_id"] for row in rows]

    def add_to_channel_whitelist(self, guild_id: int, channel_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO guild_channel_whitelist (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id),)
            conn.commit()
            return c.rowcount > 0

    def remove_from_channel_whitelist(self, guild_id: int, channel_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM guild_channel_whitelist WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id),)
            conn.commit()
            return c.rowcount > 0

    def is_channel_whitelisted(self, guild_id: int, channel_id: int) -> bool:
        self.ensure_guild_exists(guild_id)
        with self._get_connection() as conn:
            row = conn.execute("SELECT 1 FROM guild_channel_whitelist WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id),).fetchone()
            return row is not None