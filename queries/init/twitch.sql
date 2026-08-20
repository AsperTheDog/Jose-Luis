CREATE TABLE IF NOT EXISTS tracked_streamers
(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    channel_id      INTEGER NOT NULL,
    twitch_username TEXT    NOT NULL,
    kick_username   TEXT,
    everyone        BOOL,
    UNIQUE (guild_id, twitch_username)
)