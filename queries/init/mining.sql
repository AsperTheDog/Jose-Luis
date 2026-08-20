CREATE TABLE IF NOT EXISTS mining_users
(
    user_id          INTEGER PRIMARY KEY,
    xp               INTEGER DEFAULT 0,
    level            INTEGER DEFAULT 1,
    energy           INTEGER DEFAULT 100,
    current_depth_id TEXT    DEFAULT 'superficie',
    refills          INTEGER DEFAULT 0,
    last_basic_pick  DATETIME
);
CREATE TABLE IF NOT EXISTS mining_inv_materials
(
    user_id     INTEGER,
    material_id TEXT,
    amount      INTEGER,
    PRIMARY KEY (user_id, material_id)
);
CREATE TABLE IF NOT EXISTS mining_inv_valuables
(
    user_id     INTEGER,
    valuable_id TEXT,
    amount      INTEGER,
    PRIMARY KEY (user_id, valuable_id)
);
CREATE TABLE IF NOT EXISTS mining_inv_pickaxes
(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    pickaxe_id  TEXT,
    durability  INTEGER,
    is_equipped INTEGER DEFAULT 0
);