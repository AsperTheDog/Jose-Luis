import random
from typing import Optional

import aiosqlite

from db.repositories.base import BaseRepository


class PhraseRepository(BaseRepository):
    """economy_phrases (random action phrases), text_lists and eightball_phrases."""

    async def get_random_phrase(self, category: str, tag: Optional[str] = None, add_enter: bool = True) -> str:
        async with self._db.execute("SELECT phrase FROM economy_phrases WHERE category = ? AND (tag IS NULL OR tag = '') ORDER BY RANDOM() LIMIT 1", (category,)) as cursor:
            no_tag_row = await cursor.fetchone()
            no_tag_phrase = no_tag_row[0] if no_tag_row else None

        phrases = [no_tag_phrase]

        if tag:
            async with self._db.execute("SELECT phrase FROM economy_phrases WHERE category = ? AND tag = ? ORDER BY RANDOM() LIMIT 1", (category, tag)) as cursor:
                tagged_row = await cursor.fetchone()
                if tagged_row:
                    if no_tag_phrase is None:
                        return "*" + tagged_row[0] + ("*\n\n" if add_enter else "*")
                    phrases.append(tagged_row[0])

        choice = random.choice(phrases)
        if choice is None:
            return ""
        return "*" + choice + ("*\n\n" if add_enter else "*")

    async def add_phrase(self, phrase: str, category: str, tag: str) -> None:
        await self._db.execute("INSERT INTO economy_phrases (phrase, category, tag) VALUES (?, ?, ?)", (phrase, category, tag))
        await self._db.commit()

    # --- text_lists (frases/chistes) ---

    async def pick_random(self, category: str) -> list[str] | None:
        async with self._db.execute("SELECT content FROM text_lists WHERE category = ?", (category,)) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return None

        return [row[0] for row in rows]

    async def add_new(self, category: str, content: str) -> bool:
        try:
            await self._db.execute("INSERT INTO text_lists (category, content) VALUES (?, ?)", (category, content))
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove(self, category: str, content: str) -> bool:
        cursor = await self._db.execute("DELETE FROM text_lists WHERE category = ? AND content = ?", (category, content))
        deleted = cursor.rowcount > 0
        await self._db.commit()
        return deleted

    # --- eightball ---

    async def eightball_get_all(self) -> list[tuple[str, str]]:
        async with self._db.execute("SELECT phrase, category FROM eightball_phrases") as cursor:
            return await cursor.fetchall()

    async def eightball_add(self, phrase: str, category: str = "neutral") -> None:
        await self._db.execute("INSERT INTO eightball_phrases (phrase, category) VALUES (?, ?)", (phrase, category))
        await self._db.commit()

    async def eightball_remove(self, phrase: str, category: str) -> bool:
        async with self._db.execute("DELETE FROM eightball_phrases WHERE phrase = ? AND category = ?", (phrase, category)) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0
