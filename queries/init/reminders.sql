CREATE TABLE IF NOT EXISTS reminders
(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER   NOT NULL,
    channel_id INTEGER   NOT NULL,
    message_id INTEGER,
    author_id  INTEGER   NOT NULL,
    note       TEXT      NOT NULL,
    trigger_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    triggered  INTEGER   NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending
    ON reminders (triggered, trigger_at);

CREATE TABLE IF NOT EXISTS reminder_subscribers
(
    reminder_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    PRIMARY KEY (reminder_id, user_id)
);
