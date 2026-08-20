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
);

CREATE TABLE IF NOT EXISTS guild_operators (
    guild_id INTEGER NOT NULL,
    operator_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, operator_id),
    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guild_channel_whitelist (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id),
    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id) ON DELETE CASCADE
);
