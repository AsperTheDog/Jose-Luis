CREATE TABLE IF NOT EXISTS eightball_phrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT NOT NULL,
    category TEXT DEFAULT 'neutral'
);