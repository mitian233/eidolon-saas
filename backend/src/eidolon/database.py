"""Connections and SQL for the users' data, with a shared Postgres database in
production and SQLite files for local use.

`data_access.Database` runs storage callbacks on worker threads. Postgres retains
their DB-API contract and translates their SQLite dialect here, so storage modules
keep one set of queries. Each module creates its own tables. `USER_DATA` and
`ANONYMIZED_USER_DATA` list what is deleted or anonymized when a user leaves;
`NOT_USER_DATA` lists the rest.

SQLite uses secure deletion and truncates its WAL after account deletion.
Postgres commits deletions normally: its WAL, old row versions and external dumps
follow the database operator's retention policy. SQLite file exports and restores
do not apply to Postgres; use Postgres's own tools.
"""

import os
import re
import secrets
import sqlite3
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, LiteralString, cast

import psycopg
from psycopg.pq import TransactionStatus
from sqlglot import exp, parse_one

USER_DATA = [
    ("memory_vectors", "user_id = ?"),
    ("memories", "user_id = ?"),
    ("jobs", "turn_id IN (SELECT id FROM messages WHERE conversation_id IN"
     " (SELECT id FROM conversations WHERE user_id = ?))"),
    ("photos", "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("messages", "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("conversation_events",
     "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("reach_outs", "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("reach_out_schedules",
     "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("calls", "conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)"),
    ("conversations", "user_id = ?"),
    ("document_vectors", "passage_id IN (SELECT p.id FROM document_passages p JOIN documents d ON d.id = p.document_id JOIN characters c ON c.id = d.character_id WHERE c.owner_id = ?)"),
    ("document_passages", "document_id IN (SELECT d.id FROM documents d JOIN characters c ON c.id = d.character_id WHERE c.owner_id = ?)"),
    ("documents", "character_id IN (SELECT id FROM characters WHERE owner_id = ?)"),
    ("characters", "owner_id = ?"),
    ("producer_profiles", "user_id = ?"),
    ("affinities", "user_id = ?"),
    ("schedule_placements", "user_id = ?"),
    ("visit_records", "user_id = ?"),
    ("gift_balances", "user_id = ?"),
    ("gift_backpacks", "user_id = ?"),
    ("gift_rewards", "user_id = ?"),
    ("achievement_progress", "user_id = ?"),
    ("achievement_stages", "user_id = ?"),
    ("usage", "user_id = ?"),
    ("user_limits", "user_id = ?"),
    ("reach_outs_off", "user_id = ?"),
    ("moment_circle", "moment_id IN (SELECT id FROM moments WHERE user_id = ?)"),
    ("moment_images", "moment_id IN (SELECT id FROM moments WHERE user_id = ?)"),
    ("moment_likes", "moment_id IN (SELECT id FROM moments WHERE user_id = ?)"),
    ("moment_comments", "moment_id IN (SELECT id FROM moments WHERE user_id = ?)"),
    ("moments", "user_id = ?"),
    ("moment_plans", "user_id = ?"),
    ("moment_users", "user_id = ?"),
    ("moments_off", "user_id = ?"),
    ("letter_voices", "letter_id IN (SELECT id FROM letters WHERE user_id = ?)"),
    ("letters", "user_id = ?"),
    ("letters_due", "user_id = ?"),
    ("letter_users", "user_id = ?"),
    ("cycles_off", "user_id = ?"),
    ("cycle_records", "user_id = ?"),
    ("data_package_imports", "user_id = ?"),
    ("invited_users", "user_id = ?"),
    ("sessions", "user_id = ?"),
    ("sign_in_methods", "user_id = ?"),
    ("users", "id = ?"),
]
"""Every table holding a user's data, and which rows are theirs, in an order that deletes
what refers to a row before the row."""

CONVERSATION_DATA = [
    ("jobs", "turn_id IN (SELECT id FROM messages WHERE conversation_id = ?)"),
    ("photos", "conversation_id = ?"),
    ("messages", "conversation_id = ?"),
    ("conversation_events", "conversation_id = ?"),
    ("reach_outs", "conversation_id = ?"),
    ("reach_out_schedules", "conversation_id = ?"),
    ("calls", "conversation_id = ?"),
]
"""Every table holding a conversation's record, or kept under it as the calls in it are and
when she is to reach out in it next, which is deleted with it, and which rows are its."""

FROM_CONVERSATION = [
    ("memories", "conversation_id = NULL", "conversation_id = ?"),
]
"""Every table whose rows say which conversation they came from, kept when it is deleted: how
they are made to say so no longer, and which rows they are."""

ANONYMIZED_USER_DATA = [
    ("activity_records", "user_id = NULL, anonymous_id = :anonymous", "user_id = :user"),
    ("user_rollups", "who = :anonymous", "who = :user"),
]
"""Every table holding a user's data that is kept when the user is deleted: how its rows
of theirs are made no one's, and which rows they are. `:anonymous` is an id made up anew
for each deleted user, the same for all their rows, so that they still count as one."""

NOT_USER_DATA = frozenset(
    {
        "episodes", "episode_cast", "episode_lines", "episode_passages",
        "story_corpus_version", "embedded_texts", "user_passage_vectors",
        "service_calls", "config_overrides", "price_overrides", "price_catalog",
        "price_catalog_thinking", "price_catalog_hosts", "price_catalog_providers",
        "price_catalog_offers", "price_catalog_state", "banned_identities", "announcements",
        "sponsor", "gifts_opened", "reset_card_grants", "backup_runs", "record_rollups",
        "taken_rollups", "call_rollups", "spread_rollups", "achievements_launched",
        "weekly_jobs", "invites",
    }
)
"""Every other table: the story corpus, the embedded text set, the calls to outside
services, which say whose turn they were made in only through its activity record, the
configuration and the prices the admin console overrides, the price catalogs fetched
online, the ban list, hashes of the identities banned users since deleted signed in
with, which say whose they were to no one, the announcements admins write, which say
nothing of who wrote them, the sponsor code admins upload, when gifts last opened, which
is no one's, and the reset cards admins have given every user, which say nothing of who
gave them or to whom, the record of each backup run, which says nothing of anyone's, and
when the achievements launched, which is no one's, each week's jobs, the same for
everyone, and the invite links admins make, which say nothing of who made them, those who
signed up through each being the users' own."""


HEALTH_READ_TIMEOUT = 2.0
"""How long, in seconds, the health check waits to read the database."""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the configured Postgres database, or a local SQLite file.

    The connection keeps the synchronous callback contract used by `data_access`;
    that layer runs every callback on a worker thread.
    """
    if url := postgres_url(path):
        return cast(sqlite3.Connection, _PostgresConnection(url))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    try:
        # Readers need not wait for a writer: the data access layer's readers, the health
        # check and the backup, and the command line in another process, each have a
        # connection to this database.
        db.execute("PRAGMA journal_mode = WAL")
        # In WAL mode a commit need not wait for the disk: losing power may lose the last
        # commits, never corrupt the database.
        db.execute("PRAGMA synchronous = NORMAL")
        # What is deleted is overwritten, not just freed: deleting a user is for good.
        db.execute("PRAGMA secure_delete = ON")
        db.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:  # not a database: closed, so that the file can be deleted
        db.close()
        raise
    return db


def read_only(path: Path | str, timeout: float = 5.0) -> sqlite3.Connection:
    """A separate read-only connection for the health endpoint."""
    if url := postgres_url(path):
        conn = _PostgresConnection(url, timeout=timeout)
        conn.execute("PRAGMA query_only = ON")
        return cast(sqlite3.Connection, conn)
    path = Path(path)
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=timeout)


def readable(path: Path | str) -> bool:
    """Whether the database at `path` can be read now, on a `read_only` connection; for
    the health check."""
    try:
        db = read_only(path, HEALTH_READ_TIMEOUT)
        try:
            db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return False
    return True


def delete_user_data(db: sqlite3.Connection, user_id: str) -> None:
    """Delete the user and everything of theirs, for good, but what is only made no one's,
    through `db`, in the caller's transaction; the write-ahead log still holds the pages as
    they were until it is checkpointed. A table not created yet (by a module this process
    has not opened) is passed over."""
    present = tables(db)
    names = {"user": user_id, "anonymous": secrets.token_hex(16)}
    for table, anonymize, where in ANONYMIZED_USER_DATA:
        if table in present:
            db.execute(f"UPDATE {table} SET {anonymize} WHERE {where}", names)
    for table, where in USER_DATA:
        if table in present:
            db.execute(f"DELETE FROM {table} WHERE {where}", (user_id,))


def delete_conversation_data(db: sqlite3.Connection, conversation_id: str) -> None:
    """Delete the conversation and its record, for good, through `db`, in the caller's
    transaction; what only says it came from it is kept, saying so no longer. A table not
    created yet (by a module this process has not opened) is passed over."""
    present = tables(db)
    for table, unlink, where in FROM_CONVERSATION:
        if table in present:
            db.execute(f"UPDATE {table} SET {unlink} WHERE {where}", (conversation_id,))
    for table, where in CONVERSATION_DATA:
        if table in present:
            db.execute(f"DELETE FROM {table} WHERE {where}", (conversation_id,))
    db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def by_name(db: sqlite3.Connection) -> sqlite3.Cursor:
    """A cursor on `db` whose rows are read by name, leaving the connection's, which other
    modules share, as they are."""
    cursor = db.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor


def tables(db: sqlite3.Connection) -> set[str]:
    """The tables in the database, whichever module made them."""
    return {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def postgres_url(path: Path | str) -> str | None:
    """An explicit URL takes precedence; DATABASE_URL routes existing path callers."""
    supplied = str(path)
    if supplied.startswith(("postgres://", "postgresql://")):
        return supplied
    url = os.environ.get("DATABASE_URL")
    if url and not url.startswith(("postgres://", "postgresql://")):
        raise ValueError("DATABASE_URL must be a postgres:// or postgresql:// URL")
    return url or None


class _Row(tuple):
    """The tuple-and-name access existing callbacks use from sqlite3.Row."""

    names: list[str]

    def __new__(cls, values, names):
        row = super().__new__(cls, values)
        row.names = names
        return row

    def keys(self):
        return self.names

    def __getitem__(self, key):
        return super().__getitem__(self.names.index(key) if isinstance(key, str) else key)


class _PostgresCursor:
    def __init__(self, connection: "_PostgresConnection") -> None:
        self.connection = connection
        self.row_factory = None
        self.lastrowid: int | None = None
        self.rowcount = -1
        self._rows = iter(())
        self.description = None

    def execute(self, statement: str, parameters=()):
        rows, names, self.rowcount, self.lastrowid = self.connection._execute(statement, parameters)
        self._rows = iter(rows)
        self.description = [(name, None, None, None, None, None, None) for name in names]
        self._names = names
        return self

    def executemany(self, statement: str, parameters: Iterable[Sequence[Any]]):
        count = 0
        for values in parameters:
            self.execute(statement, values)
            count += self.rowcount
        self.rowcount = count
        return self

    def executescript(self, script: str):
        for statement in _statements(script):
            self.execute(statement)
        return self

    def fetchone(self):
        row = next(self._rows, None)
        return _Row(row, self._names) if row is not None and self.row_factory else row

    def fetchall(self):
        return list(self)

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row

    def close(self):
        self._rows = iter(())


def _statements(script: str) -> Iterable[str]:
    """Split scripts with SQLite's parser, including a trigger's BEGIN/END body."""
    pending = ""
    for character in script:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            yield pending.strip()
            pending = ""
    if pending.strip():
        yield pending.strip()


class _PostgresConnection:
    """Postgres behind the existing thread-owned DB-API callback contract.

    SQLite SQL is translated at this one boundary so every storage module retains
    one query and local SQLite databases remain usable. Values are always bound by
    psycopg, never interpolated into the translated SQL.
    """

    def __init__(self, url: str, timeout: float = 30) -> None:
        try:
            self._conn = psycopg.connect(url, autocommit=True, connect_timeout=max(1, int(timeout)))
            self._conn.execute("SELECT set_config('statement_timeout', %s, false)", (str(int(timeout * 1000)),))
        except psycopg.Error as error:
            raise sqlite3.OperationalError(str(error)) from error
        self._read_only = False
        self._columns: dict[str, list[tuple]] = {}
        self._translated: dict[str, tuple[str, str | None]] = {}

    def cursor(self):
        return _PostgresCursor(self)

    def execute(self, statement: str, parameters=()):
        return self.cursor().execute(statement, parameters)

    def executemany(self, statement: str, parameters):
        return self.cursor().executemany(statement, parameters)

    def executescript(self, script: str):
        return self.cursor().executescript(script)

    def __enter__(self):
        if self._conn.info.transaction_status == TransactionStatus.IDLE:
            self.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self._conn.commit()
        else:
            self._conn.rollback()

    def rollback(self):
        self._conn.rollback()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def create_function(self, name, arity, implementation, *, deterministic=False):
        # These are the only Python SQL functions in the running SaaS backend.
        # Postgres runs the equivalent expression itself, on every connection.
        if name != "spread_bucket" or arity != 1:
            raise NotImplementedError(f"Postgres SQL function {name}/{arity}")
        if self._read_only:
            return  # The writer installed it in the database, visible to all readers.
        self._conn.execute("""
            CREATE OR REPLACE FUNCTION spread_bucket(double precision) RETURNS integer
            LANGUAGE SQL IMMUTABLE STRICT AS $$
                SELECT CASE WHEN $1 > 0 THEN floor(ln($1) / ln(2.0) * 16)::integer
                            ELSE -2147483648 END
            $$
        """)

    def _metadata(self, table: str) -> list[tuple]:
        if table not in self._columns:
            self._columns[table] = self._conn.execute("""
                SELECT a.attnum - 1, a.attname, format_type(a.atttypid, a.atttypmod),
                       a.attnotnull::integer, pg_get_expr(d.adbin, d.adrelid),
                       COALESCE(array_position(i.indkey::smallint[], a.attnum), -1) + 1
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
                LEFT JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary
                WHERE n.nspname = current_schema() AND c.relname = %s
                      AND a.attnum > 0 AND NOT a.attisdropped
                      AND a.attname <> '_eidolon_rowid'
                ORDER BY a.attnum
            """, (table,)).fetchall()
        return self._columns[table]

    def _execute(self, statement: str, parameters):
        raw = statement.strip().rstrip(";")
        upper = raw.upper()
        try:
            if upper == "BEGIN IMMEDIATE":
                try:
                    self._conn.execute("BEGIN")
                    # Preserve callbacks' read-then-write atomicity across API processes.
                    self._conn.execute("SELECT pg_advisory_xact_lock(1936287820)")
                except psycopg.Error:
                    # The access layer has not entered its transaction context yet.
                    self._conn.rollback()
                    raise
                return [], [], -1, None
            if upper == "BEGIN":
                self._conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return [], [], -1, None
            if upper == "PRAGMA QUERY_ONLY = ON":
                self._conn.execute("SET default_transaction_read_only = on")
                self._read_only = True
                return [], [], -1, None
            if match := re.fullmatch(r"PRAGMA table_info\((\w+)\)", raw, re.I):
                return self._metadata(match[1]), ["cid", "name", "type", "notnull", "dflt_value", "pk"], -1, None
            if upper.startswith("CREATE TRIGGER"):
                self._trigger(raw)
                return [], [], -1, None
            if upper.startswith("VACUUM"):
                raise sqlite3.OperationalError("Postgres exports require pg_dump; SQLite VACUUM INTO is unavailable")
            if upper.startswith("PRAGMA"):
                raise sqlite3.OperationalError(f"Unsupported Postgres statement: {raw}")
            translated, returning = self._translate(raw)
            bound = parameters if isinstance(parameters, Mapping) else tuple(
                int(value) if isinstance(value, bool) else value.isoformat() if hasattr(value, "isoformat") else value
                for value in parameters
            )
            # SQLite permits catching an INSERT error and continuing the write. A
            # savepoint gives Postgres that same behavior without aborting the transaction.
            with self._conn.transaction():
                cursor = self._conn.execute(cast(LiteralString, translated), bound or None)
                names = [c.name for c in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if cursor.description else []
                count = cursor.rowcount
            inserted = rows[0][0] if returning and rows else None
            if returning:
                rows, names = [], []
            if "_eidolon_rowid" in names:
                kept = [i for i, name in enumerate(names) if name != "_eidolon_rowid"]
                rows = [tuple(row[i] for i in kept) for row in rows]
                names = [names[i] for i in kept]
            if upper.startswith(("CREATE", "ALTER", "DROP")):
                self._columns.clear()
                self._translated.clear()
            return rows, names, count, inserted
        except psycopg.IntegrityError as error:
            raise sqlite3.IntegrityError(str(error)) from error
        except psycopg.Error as error:
            raise sqlite3.OperationalError(str(error)) from error

    def _translate(self, statement: str) -> tuple[str, str | None]:
        if statement in self._translated:
            return self._translated[statement]
        tree = parse_one(statement, read="sqlite")
        if isinstance(tree, exp.Create) and tree.args.get("kind") == "TABLE":
            schema = tree.this
            tree.set("properties", None)  # SQLite's WITHOUT ROWID has no Postgres clause.
            # An insertion-order id survives updates, unlike Postgres's physical ctid.
            schema.append("expressions", parse_one(
                "CREATE TABLE t (_eidolon_rowid BIGINT GENERATED BY DEFAULT AS IDENTITY)",
                read="postgres",
            ).this.expressions[0])
            for column in schema.find_all(exp.ColumnDef):
                if column.kind.this == exp.DataType.Type.INT and any(
                    isinstance(c.kind, exp.PrimaryKeyColumnConstraint) for c in column.constraints
                ) and not any(isinstance(c.kind, exp.AutoIncrementColumnConstraint) for c in column.constraints):
                    column.append("constraints", exp.ColumnConstraint(kind=exp.AutoIncrementColumnConstraint()))
        for table in list(tree.find_all(exp.Table)):
            if table.name == "sqlite_master":
                view = parse_one("SELECT tablename AS name, 'table' AS type FROM pg_tables WHERE schemaname = current_schema()", read="postgres")
                table.replace(exp.Subquery(this=view, alias=exp.TableAlias(this=exp.to_identifier("sqlite_master"))))
        for column in tree.find_all(exp.Column):
            if column.name.lower() == "rowid":
                column.set("this", exp.to_identifier("_eidolon_rowid"))
        returning = None
        if isinstance(tree, exp.Insert):
            destination = tree.this
            table = destination.this if isinstance(destination, exp.Schema) else destination
            metadata = self._metadata(table.name)
            columns = [row[1] for row in metadata]
            keys = [row[1] for row in sorted(metadata, key=lambda r: r[5]) if row[5]]
            if not isinstance(destination, exp.Schema):
                tree.set("this", exp.Schema(this=destination, expressions=[exp.to_identifier(c) for c in columns]))
                destination = tree.this
            alternative = tree.args.get("alternative")
            if alternative in ("REPLACE", "IGNORE"):
                tree.set("alternative", None)
                if alternative == "IGNORE":
                    conflict = exp.OnConflict(action=exp.Var(this="DO NOTHING"))
                else:
                    updates = [exp.EQ(this=exp.column(c.name), expression=exp.column(c.name, table="excluded"))
                               for c in destination.expressions if c.name not in keys]
                    conflict = exp.OnConflict(action=exp.Var(this="DO UPDATE"), expressions=updates,
                                              conflict_keys=[exp.to_identifier(k) for k in keys])
                tree.set("conflict", conflict)
            conflict = tree.args.get("conflict")
            if conflict and conflict.args["action"].name == "DO UPDATE":
                if not conflict.args.get("conflict_keys"):
                    conflict.set("conflict_keys", [exp.to_identifier(k) for k in keys])
                for assignment in conflict.expressions:
                    for column in assignment.expression.find_all(exp.Column):
                        if not column.table:
                            column.set("table", exp.to_identifier(table.name))
            if not tree.args.get("returning"):
                integer_key = next((r[1] for r in metadata if r[5] and r[2] in ("integer", "bigint")), None)
                returning = integer_key if len(keys) == 1 and integer_key else "_eidolon_rowid"
                tree.set("returning", exp.Returning(expressions=[exp.column(returning)]))
        for select in tree.find_all(exp.Select):
            group = select.args.get("group")
            extrema = [item for item in select.expressions if isinstance(item, (exp.Max, exp.Min))]
            if group and len(extrema) == 1:
                grouped = {item.sql() for item in group.expressions}
                for position, item in enumerate(list(select.expressions), 1):
                    if isinstance(item, exp.Column) and item.sql() not in grouped and str(position) not in grouped:
                        extreme = extrema[0]
                        order = "DESC" if isinstance(extreme, exp.Max) else "ASC"
                        # SQLite's bare column accompanies its one MIN/MAX row.
                        item.replace(parse_one(
                            f"(ARRAY_AGG({item.sql(dialect='postgres')} ORDER BY "
                            f"{extreme.this.sql(dialect='postgres')} {order}))[1]",
                            read="postgres",
                        ))
        for converted in list(tree.find_all(exp.Cast)):
            if converted.to.this in (exp.DataType.Type.INT, exp.DataType.Type.BIGINT):
                converted.set("this", exp.Anonymous(this="TRUNC", expressions=[converted.this]))
        for rounded in tree.find_all(exp.Round):
            if rounded.args.get("decimals"):
                rounded.set("this", exp.Cast(this=rounded.this, to=exp.DataType.build("NUMERIC")))
        for null_test in tree.find_all(exp.Is):
            if isinstance(null_test.this, exp.Placeholder) and isinstance(null_test.expression, exp.Null):
                # An isolated NULL test gives server-side parameters no inferred type.
                null_test.set("this", exp.Cast(this=null_test.this, to=exp.DataType.build("TEXT")))
        self._boolean_values(tree)
        if tree.find(exp.Placeholder):
            for literal in tree.find_all(exp.Literal):
                if literal.is_string:
                    literal.set("this", literal.this.replace("%", "%%"))
        result = tree.sql(dialect="postgres")
        self._translated[statement] = (result, returning)
        return result, returning

    @staticmethod
    def _boolean_values(tree):
        # SQLite uses 0/1 both for stored flags and selected predicates. Postgres
        # distinguishes integers and booleans, including SUM/MAX of a predicate.
        boolean = (exp.Predicate, exp.And, exp.Or, exp.Not)
        for node in reversed(list(tree.walk())):
            if isinstance(node, exp.Not) and isinstance(node.this, exp.Column):
                node.set("this", exp.NEQ(this=node.this, expression=exp.Literal.number(0)))
            if isinstance(node, (exp.Where, exp.Having, exp.If)) and isinstance(node.this, exp.Column):
                node.set("this", exp.NEQ(this=node.this, expression=exp.Literal.number(0)))
            if isinstance(node, (exp.And, exp.Or)):
                for key in ("this", "expression"):
                    operand = node.args[key]
                    while isinstance(operand, exp.Paren):
                        operand = operand.this
                    if isinstance(operand, exp.Column):
                        operand.replace(exp.NEQ(this=operand.copy(), expression=exp.Literal.number(0)))
            if isinstance(node, boolean):
                parent = node.parent
                while isinstance(parent, (exp.Paren, exp.Alias)):
                    parent = parent.parent
                if isinstance(parent, (exp.Select, exp.Tuple, exp.Sum, exp.Max, exp.Min,
                                       exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
                    node.replace(exp.Cast(this=node.copy(), to=exp.DataType.build("INT")))

    def _trigger(self, statement):
        match = re.fullmatch(
            r"CREATE TRIGGER IF NOT EXISTS (\w+) AFTER UPDATE OF (\w+) ON (\w+) WHEN (.+?) BEGIN (.*) END",
            statement, re.I | re.S,
        )
        if match is None:
            raise sqlite3.OperationalError("Unsupported Postgres trigger")
        name, column, table, condition, body = match.groups()
        translated = []
        for part in _statements(body):
            sql, _ = self._translate(part.rstrip(";"))
            # Trigger INSERTs have no consumer for their generated id.
            translated.append(sql.split(" RETURNING ")[0] + ";")
        condition = re.sub(r"\bIS NOT\b", "IS DISTINCT FROM", condition, flags=re.I)
        function = (f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                    + " ".join(translated) + " RETURN NEW; END $$")
        self._conn.execute(cast(LiteralString, function))
        self._conn.execute(cast(LiteralString, f"DROP TRIGGER IF EXISTS {name} ON {table}"))
        trigger = (f"CREATE TRIGGER {name} AFTER UPDATE OF {column} ON {table} FOR EACH ROW "
                   f"WHEN ({condition}) EXECUTE FUNCTION {name}_fn()")
        self._conn.execute(cast(LiteralString, trigger))
