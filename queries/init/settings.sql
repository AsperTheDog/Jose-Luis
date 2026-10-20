CREATE TABLE IF NOT EXISTS user_settings
(
    user_id             INTEGER NOT NULL PRIMARY KEY,
    scientific_notation INTEGER NOT NULL DEFAULT 0
);
