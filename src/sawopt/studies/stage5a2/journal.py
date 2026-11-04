"""Append-only, hash-chained SQLite primitives for Stage 5A-2."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .codec import decode_typed, encode_typed

JOURNAL_SCHEMA = "stage5a2_txn_journal_v1"


class JournalError(RuntimeError):
    """A journal is malformed, conflicting, or cannot safely advance."""


@dataclass(frozen=True, slots=True)
class JournalEvent:
    sequence: int
    event_id: str
    event_type: str
    payload: Any
    previous_hash: str
    event_hash: str


class SQLiteJournal:
    """One SQLite journal; transactions are atomic only within this database."""

    def __init__(
        self,
        path: str | Path,
        journal_uuid: str,
        owner_kind: str,
        *,
        create: bool = True,
    ) -> None:
        self.path = Path(path)
        self.journal_uuid = journal_uuid
        self.owner_kind = owner_kind
        self._verified_tail: tuple[int, str] = (0, "")
        self._integrity_error: str | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True) if create else None
        if not self.path.exists() and not create:
            raise JournalError(f"journal does not exist: {self.path}")
        self._initialize(create=create)

    @staticmethod
    def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = f"file:{path.resolve().as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30.0)
        else:
            connection = sqlite3.connect(path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self, *, create: bool) -> None:
        if not self.path.exists() and not create:
            raise JournalError(f"journal does not exist: {self.path}")
        connection = self._connect(self.path)
        try:
            if create:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.executescript(
                    "BEGIN IMMEDIATE;"
                    "CREATE TABLE IF NOT EXISTS journal_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                    "CREATE TABLE IF NOT EXISTS immutable_records ("
                    " record_type TEXT NOT NULL, record_id TEXT NOT NULL, canonical_bytes BLOB NOT NULL,"
                    " digest TEXT NOT NULL, PRIMARY KEY(record_type, record_id));"
                    "CREATE TABLE IF NOT EXISTS events ("
                    " sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,"
                    " payload BLOB NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);"
                    "COMMIT;"
                )
                self._insert_or_validate_meta(connection, "schema", JOURNAL_SCHEMA)
                self._insert_or_validate_meta(connection, "journal_uuid", self.journal_uuid)
                self._insert_or_validate_meta(connection, "owner_kind", self.owner_kind)
            else:
                connection.execute("PRAGMA query_only=ON")
            self._verify_header(connection, self.journal_uuid, self.owner_kind)
            self._verify_immutable_record_digests(connection)
            self._verified_tail = self._verify_event_chain(connection)
        except (sqlite3.Error, JournalError) as exc:
            if isinstance(exc, JournalError):
                raise
            raise JournalError(f"cannot initialize/read journal {self.path}: {exc}") from exc
        finally:
            connection.close()

    @staticmethod
    def _insert_or_validate_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
        row = connection.execute("SELECT value FROM journal_meta WHERE key=?", (key,)).fetchone()
        if row is None:
            connection.execute("INSERT INTO journal_meta(key,value) VALUES(?,?)", (key, value))
        elif row["value"] != value:
            raise JournalError(f"journal metadata conflict for {key}")

    @staticmethod
    def _verify_header(connection: sqlite3.Connection, journal_uuid: str, owner_kind: str) -> None:
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {"journal_meta", "immutable_records", "events"}
        if tables != required:
            raise JournalError("journal schema tables are incomplete or contain unrecognized tables")
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key,value FROM journal_meta").fetchall()
        }
        expected = {"schema": JOURNAL_SCHEMA, "journal_uuid": journal_uuid, "owner_kind": owner_kind}
        if set(metadata) != set(expected):
            raise JournalError("journal metadata fields are incomplete or unrecognized")
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise JournalError(f"journal metadata mismatch for {key}")

    @staticmethod
    def _verify_immutable_record_digests(connection: sqlite3.Connection) -> None:
        for row in connection.execute("SELECT canonical_bytes,digest FROM immutable_records").fetchall():
            if hashlib.sha256(bytes(row["canonical_bytes"])).hexdigest() != row["digest"]:
                raise JournalError("immutable record digest mismatch")

    @classmethod
    def _verify_event_chain(cls, connection: sqlite3.Connection) -> tuple[int, str]:
        previous_hash = ""
        expected_sequence = 1
        for row in connection.execute("SELECT * FROM events ORDER BY sequence"):
            sequence = int(row["sequence"])
            payload = bytes(row["payload"])
            if sequence != expected_sequence or row["previous_hash"] != previous_hash:
                raise JournalError("journal event sequence or predecessor hash mismatch")
            try:
                decode_typed(payload)
                expected_hash = cls._event_hash(
                    sequence, row["event_id"], row["event_type"], payload, previous_hash,
                )
            except (TypeError, ValueError) as exc:
                raise JournalError("journal event payload or hash metadata is malformed") from exc
            if row["event_hash"] != expected_hash:
                raise JournalError("journal event hash mismatch")
            previous_hash = expected_hash
            expected_sequence += 1
        return expected_sequence - 1, previous_hash

    @classmethod
    def inspect(
        cls, path: str | Path, *, journal_uuid: str, owner_kind: str,
    ) -> tuple[str, dict[str, int] | None]:
        """Inspect without creating a file; return absent/pristine/active.

        Any existing but unreadable or unrecognized file raises and is not
        overwritten, even if it has zero length or no known journal rows.
        """
        target = Path(path)
        if not target.exists():
            return "absent", None
        try:
            connection = cls._connect(target, readonly=True)
            try:
                cls._verify_header(connection, journal_uuid, owner_kind)
                cls._verify_immutable_record_digests(connection)
                cls._verify_event_chain(connection)
                counts = {
                    name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                    for name in ("immutable_records", "events")
                }
            finally:
                connection.close()
        except (sqlite3.Error, JournalError) as exc:
            raise JournalError(f"existing journal is malformed/incompatible: {target}: {exc}") from exc
        return ("pristine" if not any(counts.values()) else "active"), counts

    def _connection(self) -> sqlite3.Connection:
        connection = self._connect(self.path)
        connection.execute("PRAGMA synchronous=FULL")
        self._verify_header(connection, self.journal_uuid, self.owner_kind)
        return connection

    def _assert_verified_tail(self, connection: sqlite3.Connection) -> None:
        """Reject stale or corrupted tails before a transaction extends the chain.

        The complete chain is verified when this object opens. A transaction
        validates that its append point is still that verified prefix, without
        rescanning the entire journal on every append.
        """
        if self._integrity_error is not None:
            raise JournalError(f"journal is unusable after an integrity failure: {self._integrity_error}")
        row = connection.execute("SELECT * FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        actual = (0, "") if row is None else (int(row["sequence"]), str(row["event_hash"]))
        if actual != self._verified_tail:
            raise JournalError("journal tail changed since its verified read")
        if row is not None:
            payload = bytes(row["payload"])
            try:
                decode_typed(payload)
                expected_hash = self._event_hash(
                    actual[0], row["event_id"], row["event_type"], payload, row["previous_hash"],
                )
            except (TypeError, ValueError) as exc:
                raise JournalError("journal tail payload or hash metadata is malformed") from exc
            if expected_hash != actual[1]:
                raise JournalError("journal tail hash mismatch")

    def is_pristine(self) -> bool:
        connection = self._connection()
        try:
            return (
                connection.execute("SELECT COUNT(*) FROM immutable_records").fetchone()[0] == 0
                and connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
            )
        finally:
            connection.close()

    def immutable_records(self) -> tuple[tuple[str, str, bytes], ...]:
        connection = self._connection()
        try:
            rows = connection.execute(
                "SELECT record_type,record_id,canonical_bytes,digest FROM immutable_records "
                "ORDER BY record_type,record_id"
            ).fetchall()
            records = []
            for row in rows:
                canonical = bytes(row["canonical_bytes"])
                if hashlib.sha256(canonical).hexdigest() != row["digest"]:
                    raise JournalError("immutable record digest mismatch")
                records.append((row["record_type"], row["record_id"], canonical))
            return tuple(records)
        finally:
            connection.close()

    def get_immutable_record(self, record_type: str, record_id: str) -> bytes | None:
        connection = self._connection()
        try:
            row = connection.execute(
                "SELECT canonical_bytes,digest FROM immutable_records WHERE record_type=? AND record_id=?",
                (record_type, record_id),
            ).fetchone()
            if row is None:
                return None
            canonical = bytes(row["canonical_bytes"])
            if hashlib.sha256(canonical).hexdigest() != row["digest"]:
                raise JournalError("immutable record digest mismatch")
            return canonical
        finally:
            connection.close()

    @staticmethod
    def _event_hash(
        sequence: int, event_id: str, event_type: str, payload: bytes, previous_hash: str,
    ) -> str:
        body = (
            b"sawopt-stage5a2-journal-event-v1\0"
            + sequence.to_bytes(8, "big")
            + bytes.fromhex(previous_hash) if previous_hash else b"sawopt-stage5a2-journal-event-v1\0" + sequence.to_bytes(8, "big")
        )
        body += event_id.encode("utf-8") + b"\0" + event_type.encode("utf-8") + b"\0" + payload
        return hashlib.sha256(body).hexdigest()

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        event_id: str,
        event_type: str,
        payload: Any,
    ) -> JournalEvent:
        encoded = encode_typed(payload)
        existing = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if existing is not None:
            if existing["event_type"] != event_type or bytes(existing["payload"]) != encoded:
                raise JournalError(f"event idempotency conflict for {event_id}")
            return JournalEvent(
                int(existing["sequence"]), event_id, event_type,
                decode_typed(bytes(existing["payload"])), existing["previous_hash"], existing["event_hash"],
            )
        tail = connection.execute(
            "SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if tail is None else int(tail["sequence"]) + 1
        previous_hash = "" if tail is None else str(tail["event_hash"])
        event_hash = SQLiteJournal._event_hash(sequence, event_id, event_type, encoded, previous_hash)
        connection.execute(
            "INSERT INTO events(sequence,event_id,event_type,payload,previous_hash,event_hash)"
            " VALUES(?,?,?,?,?,?)",
            (sequence, event_id, event_type, encoded, previous_hash, event_hash),
        )
        return JournalEvent(sequence, event_id, event_type, payload, previous_hash, event_hash)

    def commit_records(
        self,
        records: Iterable[tuple[str, str, bytes]],
        events: Iterable[tuple[str, str, Any]],
    ) -> tuple[JournalEvent, ...]:
        """Atomically insert immutable records and their event envelope(s)."""
        record_rows = tuple(records)
        event_rows = tuple(events)
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_verified_tail(connection)
            self._verify_immutable_record_digests(connection)
            for record_type, record_id, canonical in record_rows:
                digest = hashlib.sha256(canonical).hexdigest()
                existing = connection.execute(
                    "SELECT canonical_bytes,digest FROM immutable_records WHERE record_type=? AND record_id=?",
                    (record_type, record_id),
                ).fetchone()
                if existing is not None:
                    if bytes(existing["canonical_bytes"]) != canonical or existing["digest"] != digest:
                        raise JournalError(f"immutable record conflict for {record_type}/{record_id}")
                else:
                    connection.execute(
                        "INSERT INTO immutable_records(record_type,record_id,canonical_bytes,digest) VALUES(?,?,?,?)",
                        (record_type, record_id, canonical, digest),
                    )
            committed = tuple(
                self._insert_event(connection, event_id, event_type, payload)
                for event_id, event_type, payload in event_rows
            )
            tail = connection.execute(
                "SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            verified_tail = (0, "") if tail is None else (int(tail["sequence"]), str(tail["event_hash"]))
            connection.execute("COMMIT")
            self._verified_tail = verified_tail
            return committed
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def commit_identity_and_roster(self, pair, roster) -> None:
        self.commit_records(
            (
                ("pair_identity", pair.identity_id, pair.canonical_bytes),
                ("genesis_roster", roster.roster_hash, roster.canonical_bytes),
            ),
            (
                (f"PAIR_IDENTITY_COMMITTED:{pair.identity_id}", "PAIR_IDENTITY_COMMITTED", pair.record()),
                (f"GENESIS_ROSTER_COMMITTED:{roster.roster_hash}", "GENESIS_ROSTER_COMMITTED", roster.record()),
            ),
        )

    def commit_identity(self, cell) -> None:
        self.commit_records(
            (("cell_identity", cell.identity_id, cell.canonical_bytes),),
            ((f"CELL_IDENTITY_COMMITTED:{cell.identity_id}", "CELL_IDENTITY_COMMITTED", cell.record()),),
        )

    def append_event(self, event_id: str, event_type: str, payload: Any) -> JournalEvent:
        return self.commit_records((), ((event_id, event_type, payload),))[0]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        connection = self._connection()
        try:
            row = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return None
            return {
                "sequence": int(row["sequence"]),
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": decode_typed(bytes(row["payload"])),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
            }
        finally:
            connection.close()

    def events_after(self, sequence: int, previous_hash: str) -> tuple[JournalEvent, ...]:
        """Verify and read only the append-only tail after a verified prefix."""
        if type(sequence) is not int or sequence < 0:
            raise JournalError("journal prefix sequence is invalid")
        if sequence and (len(previous_hash) != 64 or any(c not in "0123456789abcdef" for c in previous_hash)):
            raise JournalError("journal prefix hash is invalid")
        if not sequence and previous_hash:
            raise JournalError("empty journal prefix must have an empty hash")
        connection = self._connection()
        try:
            count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            tail = connection.execute("SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
            max_sequence = 0 if tail is None else int(tail["sequence"])
            if count != max_sequence or max_sequence < sequence:
                raise JournalError("journal tail was truncated or has a sequence gap")
            if max_sequence == sequence:
                if ("" if tail is None else tail["event_hash"]) != previous_hash:
                    raise JournalError("journal prefix head changed")
                return ()
            rows = connection.execute("SELECT * FROM events WHERE sequence>? ORDER BY sequence", (sequence,)).fetchall()
            result: list[JournalEvent] = []
            expected_sequence = sequence + 1
            head = previous_hash
            for row in rows:
                current = int(row["sequence"])
                payload = bytes(row["payload"])
                if current != expected_sequence or row["previous_hash"] != head:
                    raise JournalError("journal appended tail sequence or predecessor mismatch")
                decode_typed(payload)
                digest = self._event_hash(current, row["event_id"], row["event_type"], payload, head)
                if row["event_hash"] != digest:
                    raise JournalError("journal appended tail hash mismatch")
                result.append(JournalEvent(
                    current, row["event_id"], row["event_type"], decode_typed(payload), head, digest,
                ))
                expected_sequence += 1
                head = digest
            if expected_sequence - 1 != max_sequence:
                raise JournalError("journal appended tail is incomplete")
            return tuple(result)
        finally:
            connection.close()

    def iter_events(self) -> Iterable[JournalEvent]:
        """Verify events in order without materializing the complete journal.

        Consumers must exhaust the iterator before trusting the complete chain;
        the appendable verified tail advances only after full verification.
        """
        connection = self._connection()
        try:
            previous_hash = ""
            expected_sequence = 1
            for row in connection.execute("SELECT * FROM events ORDER BY sequence"):
                sequence = int(row["sequence"])
                payload = bytes(row["payload"])
                if sequence != expected_sequence or row["previous_hash"] != previous_hash:
                    raise JournalError("journal event sequence or predecessor hash mismatch")
                expected_hash = self._event_hash(
                    sequence, row["event_id"], row["event_type"], payload, previous_hash,
                )
                if row["event_hash"] != expected_hash:
                    raise JournalError("journal event hash mismatch")
                yield JournalEvent(
                    sequence, row["event_id"], row["event_type"], decode_typed(payload),
                    previous_hash, expected_hash,
                )
                previous_hash = expected_hash
                expected_sequence += 1
            self._verified_tail = (expected_sequence - 1, previous_hash)
        except (JournalError, ValueError, TypeError, sqlite3.Error) as exc:
            self._integrity_error = str(exc)
            if isinstance(exc, JournalError):
                raise
            raise JournalError(f"journal event chain is malformed: {exc}") from exc
        finally:
            connection.close()

    def events(self) -> tuple[JournalEvent, ...]:
        return tuple(self.iter_events())

    def verify_genesis_records(self, pair, roster) -> None:
        if self.get_immutable_record("pair_identity", pair.identity_id) != pair.canonical_bytes:
            raise JournalError("pair identity read-back mismatch")
        if self.get_immutable_record("genesis_roster", roster.roster_hash) != roster.canonical_bytes:
            raise JournalError("genesis roster read-back mismatch")
        for _ in self.iter_events():  # verify genesis, barrier and complete tail
            pass


__all__ = ["JOURNAL_SCHEMA", "JournalError", "JournalEvent", "SQLiteJournal"]
