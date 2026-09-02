CREATE TABLE IF NOT EXISTS gacha_unit_definitions
(
    unit_id     TEXT    NOT NULL PRIMARY KEY,
    name        TEXT    NOT NULL,
    phrase      TEXT    NOT NULL,
    interpreter TEXT    NOT NULL,
    rarity      INTEGER NOT NULL,
    emoji       TEXT,
    source      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS gacha_users
(
    user_id INTEGER NOT NULL PRIMARY KEY,
    dust    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gacha_shards
(
    user_id INTEGER NOT NULL,
    unit_id TEXT    NOT NULL,
    amount  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, unit_id)
);

CREATE TABLE IF NOT EXISTS gacha_units_owned
(
    user_id INTEGER NOT NULL,
    unit_id TEXT    NOT NULL,
    amount  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, unit_id)
);
