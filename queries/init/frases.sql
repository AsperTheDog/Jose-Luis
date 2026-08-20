CREATE TABLE IF NOT EXISTS text_lists
(
   id       INTEGER PRIMARY KEY AUTOINCREMENT,
   category TEXT NOT NULL,
   content  TEXT NOT NULL,
   UNIQUE (category, content)
);