CREATE TABLE IF NOT EXISTS waifu_users
(
    user_id INTEGER PRIMARY KEY,
    pronoun TEXT    NOT NULL DEFAULT 'waifu',
    value   INTEGER NOT NULL,
    claim   INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS waifu_blocks
(
    blocker_id INTEGER NOT NULL,
    blocked_id INTEGER NOT NULL,
    PRIMARY KEY (blocker_id, blocked_id)
);

CREATE TABLE IF NOT EXISTS waifu_gifts
(
    user_id    INTEGER NOT NULL,
    item_name  TEXT    NOT NULL,
    amount     INTEGER NOT NULL,
    PRIMARY KEY (user_id, item_name)
);
