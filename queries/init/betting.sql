CREATE TABLE IF NOT EXISTS horse_races (
    race_date TEXT,
    horse_id INTEGER,
    horse_name TEXT,
    speed INTEGER,
    stamina INTEGER,
    clutch INTEGER,
    distance REAL DEFAULT 0,
    finished INTEGER DEFAULT 0,
    finish_time REAL,
    PRIMARY KEY (race_date, horse_id)
);

CREATE TABLE IF NOT EXISTS horse_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    race_date TEXT,
    horse_id INTEGER,
    bet_amount INTEGER,
    payout INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,
    FOREIGN KEY (race_date, horse_id) REFERENCES horse_races (race_date, horse_id)
);