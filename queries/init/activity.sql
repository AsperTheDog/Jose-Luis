CREATE TABLE IF NOT EXISTS user_stats
(
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    messages INTEGER DEFAULT 0,
    xp INTEGER DEFAULT 0,
    words INTEGER DEFAULT 0,
    chars INTEGER DEFAULT 0,
    attachments INTEGER DEFAULT 0,
    emojis INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)