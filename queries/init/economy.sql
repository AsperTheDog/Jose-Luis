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

CREATE TABLE IF NOT EXISTS economy_balance_log
(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    delta        INTEGER NOT NULL,
    prev_balance INTEGER NOT NULL,
    new_balance  INTEGER NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_balance_log_user_time
    ON economy_balance_log (user_id, id DESC);

CREATE TRIGGER IF NOT EXISTS economy_balance_log_trigger
AFTER UPDATE OF balance ON economy_users
WHEN OLD.balance != NEW.balance
BEGIN
    INSERT INTO economy_balance_log (user_id, delta, prev_balance, new_balance)
    VALUES (
        NEW.user_id,
        NEW.balance - OLD.balance,
        OLD.balance,
        NEW.balance
    );
END;

CREATE TABLE IF NOT EXISTS economy_phrases
(
    phrase TEXT NOT NULL,
    category TEXT NOT NULL,
    tag TEXT,
    PRIMARY KEY (phrase)
);
