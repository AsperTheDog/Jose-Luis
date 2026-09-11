CREATE TABLE IF NOT EXISTS dungeon_users
(
    user_id         INTEGER PRIMARY KEY,
    floor           INTEGER   NOT NULL DEFAULT 1,
    highest_floor   INTEGER   NOT NULL DEFAULT 0,
    floor_kills     INTEGER   NOT NULL DEFAULT 0,
    auto_advance    INTEGER   NOT NULL DEFAULT 1,
    level           INTEGER   NOT NULL DEFAULT 1,
    xp              INTEGER   NOT NULL DEFAULT 0,
    gold            INTEGER   NOT NULL DEFAULT 0,
    hp              INTEGER   NOT NULL DEFAULT 0,
    max_hp          INTEGER   NOT NULL DEFAULT 0,
    energy          INTEGER   NOT NULL DEFAULT 100,
    max_energy      INTEGER   NOT NULL DEFAULT 100,
    potions         INTEGER   NOT NULL DEFAULT 3,
    active_skill    TEXT      NOT NULL DEFAULT '',
    dust            INTEGER   NOT NULL DEFAULT 0,
    boss_coins      INTEGER   NOT NULL DEFAULT 0,
    boss_tier       INTEGER   NOT NULL DEFAULT 0,
    last_boss_at    TIMESTAMP,
    last_boss_floor INTEGER   NOT NULL DEFAULT 0,
    upgrades        TEXT      NOT NULL DEFAULT '{}',
    shifts          TEXT      NOT NULL DEFAULT '[]',
    alt_floor       TEXT,
    last_alt_at     TIMESTAMP,
    conversion_date TEXT,
    conversion_used INTEGER   NOT NULL DEFAULT 0,
    training_enabled INTEGER   NOT NULL DEFAULT 0,
    training_since   TIMESTAMP,
    runs            INTEGER   NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dungeon_inventory
(
    item_uid    TEXT PRIMARY KEY,
    user_id     INTEGER   NOT NULL,
    name        TEXT      NOT NULL,
    slot        TEXT      NOT NULL,
    rarity      TEXT      NOT NULL,
    stats       TEXT      NOT NULL DEFAULT '{}',
    sockets     TEXT      NOT NULL DEFAULT '[]',
    is_equipped INTEGER   NOT NULL DEFAULT 0,
    floor_found INTEGER   NOT NULL DEFAULT 1,
    acquired_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dungeon_inventory_user
    ON dungeon_inventory (user_id, is_equipped DESC);

CREATE TABLE IF NOT EXISTS dungeon_mutations
(
    user_id     INTEGER NOT NULL,
    mutation_id TEXT    NOT NULL,
    level       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, mutation_id)
);

CREATE TABLE IF NOT EXISTS dungeon_active_fight
(
    user_id    INTEGER PRIMARY KEY,
    state      TEXT      NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dungeon_cosmetics
(
    user_id     INTEGER NOT NULL,
    cosmetic_id TEXT    NOT NULL,
    equipped    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, cosmetic_id)
);

CREATE TABLE IF NOT EXISTS dungeon_echoes
(
    user_id INTEGER NOT NULL,
    echo_id TEXT    NOT NULL,
    level   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, echo_id)
);

CREATE TABLE IF NOT EXISTS dungeon_log
(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dungeon_log_user
    ON dungeon_log (user_id, id DESC);

CREATE TABLE IF NOT EXISTS dungeon_automation
(
    user_id     INTEGER PRIMARY KEY,
    enabled     INTEGER NOT NULL DEFAULT 0,
    sims        INTEGER NOT NULL DEFAULT 0,
    last_tick   TIMESTAMP,
    last_report TEXT
);
