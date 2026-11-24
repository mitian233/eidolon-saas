"""Characters kept in the database: each user's own characters (D13), persisted across a
restart and private to their owner.

`CharacterRepository` owns the `characters` table and reads the engine's `Character`
view on demand. Every character read and write names the owner.

The platform stores only the avatar URL, never the file (D11); a character needs nothing
but a name and a persona sheet. Deleting a character deletes its owner's conversations
with her (`database.delete_conversation_data`), and no one else's.
"""

import sqlite3
import uuid
from datetime import UTC, datetime

from eidolon.characters import Character, Greeting
from eidolon.data_access import Database
from eidolon.database import by_name, delete_conversation_data, tables
from eidolon.producer import Birthday, is_day_of_the_year

MAX_CHARACTERS_PER_USER = 50


class CharacterLimitReached(Exception):
    """The owner has no room for another character."""


_SCHEMA = """
-- A character a user created: `owner_id` whose she is (a user; account deletion removes her
-- rows through `database.USER_DATA`); `sheet` her persona text; `greeting` plain text;
-- `avatar_url` an external address the platform only stores; `birthday` "MM-DD" and `age`
-- NULL when unset; `language_mode` 'single' or 'bilingual'.
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    intro TEXT NOT NULL DEFAULT '',
    sheet TEXT NOT NULL,
    avatar_url TEXT,
    greeting TEXT NOT NULL DEFAULT '',
    voice_id TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#64748b',
    user_address TEXT NOT NULL DEFAULT '你',
    language_mode TEXT NOT NULL DEFAULT 'single',
    birthday TEXT,
    age INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS characters_by_owner ON characters(owner_id, created_at);
"""

_COLUMNS = (
    "id, owner_id, name, intro, sheet, avatar_url, greeting, voice_id, color,"
    " user_address, language_mode, birthday, age, created_at"
)

_SETTINGS = (
    "name", "intro", "sheet", "avatar_url", "greeting", "voice_id", "color",
    "user_address", "language_mode", "birthday", "age",
)
"""The settings a character has, each a column of the table."""


class CharacterRepository:
    def __init__(self, database: Database) -> None:
        self._db = database
        database.prepare(lambda conn: conn.executescript(_SCHEMA))

    async def create(
        self,
        owner_id: str,
        *,
        name: str,
        sheet: str,
        intro: str = "",
        avatar_url: str | None = None,
        greeting: str = "",
        voice_id: str = "",
        color: str = "#64748b",
        user_address: str = "你",
        language_mode: str = "single",
        birthday: Birthday | None = None,
        age: int | None = None,
    ) -> Character:
        """A new character of `owner_id`, with a fresh id; only `name` and `sheet` are needed."""
        cols = _columns(
            dict(
                name=name, sheet=sheet, intro=intro, avatar_url=avatar_url, greeting=greeting,
                voice_id=voice_id, color=color, user_address=user_address,
                language_mode=language_mode, birthday=birthday, age=age,
            )
        )
        character = Character(
            id=uuid.uuid4().hex,
            owner_id=owner_id,
            name=name,
            intro=intro,
            sheet=sheet,
            voice_id=voice_id,
            color=color,
            avatar_url=avatar_url,
            greeting=Greeting(greeting, "") if greeting else None,
            user_address=user_address,
            language_mode="bilingual" if language_mode == "bilingual" else "single",
            birthday=birthday,
            age=age,
        )
        await self._db.write(_insert, character.id, owner_id, cols, _now())
        return character

    async def update(
        self, owner_id: str, character_id: str, **settings: object
    ) -> Character | None:
        """Change the given settings of the owner's character, leaving the rest; None if she
        is not the owner's (or not there)."""
        cols = _columns(settings)
        return await self._db.write(_update, owner_id, character_id, cols)

    async def delete(self, owner_id: str, character_id: str) -> bool:
        """Delete the owner's character and their conversations with her, for good; False if
        she is not the owner's (or not there)."""
        return await self._db.write(_delete, owner_id, character_id)

    async def other_birthdays(self, owner_id: str, character_id: str) -> list[tuple[str, Birthday]]:
        """Names and birthdays of the owner's other characters, oldest characters first."""
        return await self._db.read(_other_birthdays, owner_id, character_id)

    async def list(self, owner_id: str) -> list[Character]:
        """The owner's characters, the earliest created first."""
        return await self._db.read(_by_owner, owner_id)

    async def get(self, owner_id: str, character_id: str) -> Character | None:
        """The owner's character, or None if she is not the owner's (or not there)."""
        return await self._db.read(_one, owner_id, character_id)


def read_character_names(conn: sqlite3.Connection, owner_id: str) -> dict[str, str]:
    """The owner's character names in the caller's transaction."""
    return dict(conn.execute("SELECT id, name FROM characters WHERE owner_id = ?", (owner_id,)))


def shown_character(character: Character) -> dict:
    """As the browser is told her: her settings, the greeting as plain text without delivery
    cues, the birthday as "MM-DD" (None when unset), and the avatar URL, never a local file."""
    return {
        "id": character.id,
        "name": character.name,
        "intro": character.intro,
        "sheet": character.sheet,
        "avatar_url": character.avatar_url,
        "greeting": character.greeting.ja if character.greeting else "",
        "voice_id": character.voice_id,
        "color": character.color,
        "user_address": character.user_address,
        "language_mode": character.language_mode,
        "birthday": (
            f"{character.birthday.month:02d}-{character.birthday.day:02d}"
            if character.birthday
            else None
        ),
        "age": character.age,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _columns(settings: dict[str, object]) -> dict[str, object]:
    """The settings as column values, checked: only known settings, a language mode of
    `single` or `bilingual`, a birthday some year has, a positive whole age or None."""
    if unknown := set(settings) - set(_SETTINGS):
        raise ValueError(f"未知的角色设置：{'、'.join(sorted(unknown))}")
    cols: dict[str, object] = {}
    for key, value in settings.items():
        if key == "language_mode":
            if value not in ("single", "bilingual"):
                raise ValueError(f"language_mode 应为 single 或 bilingual，现在是 {value!r}")
            cols[key] = value
        elif key == "birthday":
            if value is not None and not isinstance(value, Birthday):
                raise ValueError("birthday 应为 Birthday 或 None")
            cols[key] = _birthday_text(value)
        elif key == "age":
            # bool is an int in Python, but `age = True` is a mistake all the same.
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"age 应为正整数或 None，现在是 {value!r}")
            cols[key] = value
        else:
            cols[key] = value
    return cols


def _birthday_text(birthday: Birthday | None) -> str | None:
    if birthday is None:
        return None
    if not is_day_of_the_year(birthday.month, birthday.day):
        raise ValueError(f"birthday 应为一年中有的一天（例如 04-25），现在是 {birthday!r}")
    return f"{birthday.month:02d}-{birthday.day:02d}"


def _character(row: sqlite3.Row) -> Character:
    birthday = row["birthday"]
    greeting = row["greeting"]
    return Character(
        id=row["id"],
        owner_id=row["owner_id"],
        name=row["name"],
        intro=row["intro"],
        sheet=row["sheet"],
        voice_id=row["voice_id"],
        color=row["color"],
        avatar_url=row["avatar_url"],
        greeting=Greeting(greeting, "") if greeting else None,
        user_address=row["user_address"],
        language_mode=row["language_mode"],
        birthday=_birthday(birthday) if birthday else None,
        age=row["age"],
    )


def _insert(
    conn: sqlite3.Connection,
    character_id: str,
    owner_id: str,
    cols: dict[str, object],
    created_at: str,
) -> None:
    count = conn.execute("SELECT COUNT(*) FROM characters WHERE owner_id = ?", (owner_id,)).fetchone()[0]
    if count >= MAX_CHARACTERS_PER_USER:
        raise CharacterLimitReached(f"每个账号最多创建 {MAX_CHARACTERS_PER_USER} 个角色，请先删除不需要的角色")

    values = {"id": character_id, "owner_id": owner_id, **cols, "created_at": created_at}
    names = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO characters ({names}) VALUES ({marks})", tuple(values.values()))


def _birthday(text: str) -> Birthday:
    return Birthday(int(text[:2]), int(text[3:]))


def _other_birthdays(
    conn: sqlite3.Connection, owner_id: str, character_id: str,
) -> list[tuple[str, Birthday]]:
    rows = conn.execute(
        "SELECT name, birthday FROM characters WHERE owner_id = ? AND id <> ?"
        " AND birthday IS NOT NULL ORDER BY created_at, rowid",
        (owner_id, character_id),
    )
    return [(name, _birthday(birthday)) for name, birthday in rows]


def _by_owner(conn: sqlite3.Connection, owner_id: str) -> list[Character]:
    rows = by_name(conn).execute(
        f"SELECT {_COLUMNS} FROM characters WHERE owner_id = ? ORDER BY created_at, rowid",
        (owner_id,),
    )
    return [_character(row) for row in rows]


def _one(conn: sqlite3.Connection, owner_id: str, character_id: str) -> Character | None:
    row = by_name(conn).execute(
        f"SELECT {_COLUMNS} FROM characters WHERE id = ? AND owner_id = ?",
        (character_id, owner_id),
    ).fetchone()
    return _character(row) if row else None


def _update(
    conn: sqlite3.Connection, owner_id: str, character_id: str, cols: dict[str, object]
) -> Character | None:
    if cols:
        sets = ", ".join(f"{name} = ?" for name in cols)
        conn.execute(
            f"UPDATE characters SET {sets} WHERE id = ? AND owner_id = ?",
            (*cols.values(), character_id, owner_id),
        )
    return _one(conn, owner_id, character_id)


def _delete(conn: sqlite3.Connection, owner_id: str, character_id: str) -> bool:
    # The conversations table is made by the store; without it there is nothing to delete.
    if "conversations" in tables(conn):
        rows = conn.execute(
            "SELECT id FROM conversations WHERE user_id = ? AND character_id = ?",
            (owner_id, character_id),
        ).fetchall()
        for (conversation_id,) in rows:
            delete_conversation_data(conn, conversation_id)
    return conn.execute(
        "DELETE FROM characters WHERE id = ? AND owner_id = ?", (character_id, owner_id)
    ).rowcount > 0