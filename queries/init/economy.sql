CREATE TABLE IF NOT EXISTS economy_users
(
    user_id            INTEGER PRIMARY KEY,
    balance            INTEGER NOT NULL DEFAULT 100,
    daily_streak       INTEGER NOT NULL DEFAULT 0,
    last_daily         TIMESTAMP,
    active_job         TEXT,
    last_job_switch    TIMESTAMP,
    last_work          TIMESTAMP,
    crime_streak       INTEGER NOT NULL DEFAULT 0,
    jail_until         TIMESTAMP,
    unclaimed_interest INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS economy_jobs
(
    user_id INTEGER NOT NULL,
    job_id  TEXT    NOT NULL,
    level   INTEGER NOT NULL DEFAULT 1,
    xp      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, job_id)
);

CREATE TABLE IF NOT EXISTS economy_phrases
(
    phrase TEXT NOT NULL,
    category TEXT NOT NULL,
    tag TEXT,
    PRIMARY KEY (phrase)
);
