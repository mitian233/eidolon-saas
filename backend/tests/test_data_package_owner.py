"""Data packages keep characters private (D13): a package tells only the exporting user's
own character names, and an import adds only references to the importing user's own
characters — another owner's are skipped, telling neither that they exist nor their name."""

import json
import zipfile
from pathlib import Path
from datetime import UTC, datetime

from eidolon.characters import Character
from eidolon.data_access import Database
from eidolon.data_package import DataPackages, Skipped
from eidolon.memory import Memories
from eidolon.store import Store


def _message(conn, conversation_id: str) -> None:
    conn.execute(
        "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, "user", "你好", "2026-11-12T00:00:00+00:00"),
    )


async def test_export_tells_only_the_owners_names_and_import_skips_other_owners(tmp_path: Path):
    db = Database(tmp_path / "eidolon.db")
    try:
        store = Store(db)
        alice = (await store.create_user("alice")).id
        bob = (await store.create_user("bob")).id
        characters = {
            "ca": Character("ca", "爱丽丝", "", "", "人设", owner_id=alice),
            "cb": Character("cb", "鲍勃", "", "", "人设", owner_id=bob),
        }
        def clock():
            return datetime(2026, 11, 12, tzinfo=UTC)
        memories = Memories(db, characters, clock)
        packages = DataPackages(db, store, memories, characters, {}, clock)
        ca_conv = await store.create_conversation(alice, "ca")
        # A reference to bob's character in alice's data (as an earlier import could leave).
        cb_conv = await store.create_conversation(alice, "cb")
        await db.write(_message, ca_conv.id)
        await db.write(_message, cb_conv.id)

        out = tmp_path / "package.zip"
        await packages.export(alice, ["conversations"], out)
        with zipfile.ZipFile(out) as zipped:
            data = json.loads(zipped.read("data.json"))
        names = {c["character_id"]: c["character_name"] for c in data["conversations"]}
        assert names == {"ca": "爱丽丝", "cb": None}  # bob's name is not told to alice

        imported = await packages.import_(bob, out, ["conversations"], None)
        assert imported.conversations == 1  # only bob's own cb
        assert imported.skipped == [Skipped("爱丽丝", 1)]  # alice's ca skipped, named from the package
        assert await store.list_conversations(bob, "cb")
        assert await store.list_conversations(bob, "ca") == []
    finally:
        await db.close()