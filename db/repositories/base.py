from db.connection import Database


class BaseRepository:
    """Common constructor for all repositories: a reference to the Database."""

    def __init__(self, db: Database):
        self._db = db
