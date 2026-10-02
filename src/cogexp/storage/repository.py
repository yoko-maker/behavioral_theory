"""SQLite リポジトリ。

- 書き込む行は ``schema.TABLES`` と完全一致することを検証する（列の過不足・型・欠損）。
- 同意済み（consent_status = agreed）でない参加者の trial/event は保存しない。
- trial は ``submission_id`` で冪等。同じ送信の再送は行を増やさず、重複回数を数える。
- 生データは追記のみ。更新は明示した列（参加者の状態・確信度）に限る。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from cogexp.storage.schema import TABLES, Column

_SQL_TYPES = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
    "datetime": "TEXT",
    "json": "TEXT",
}
_PRIMARY_KEYS = {"participants": "participant_id", "trials": "trial_id", "events": "event_id"}
_UNIQUE = {"trials": ("submission_id",)}

Row = Mapping[str, object]


class ConsentRequiredError(Exception):
    """同意済みでない参加者のデータを保存しようとした。"""


class SchemaMismatchError(ValueError):
    pass


class SaveResult(StrEnum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"


def _encode_value(table: str, col: Column, value: object) -> object:
    where = f"{table}.{col.name}"
    if value is None:
        if not col.nullable:
            raise SchemaMismatchError(f"{where} は欠損不可")
        return None
    is_bool = isinstance(value, bool)
    match col.dtype:
        case "str" if isinstance(value, str):
            return value
        case "int" if isinstance(value, int) and not is_bool:
            return value
        case "float" if isinstance(value, int | float) and not is_bool:
            return float(value)
        case "bool" if isinstance(value, bool):
            return int(value)
        case "datetime" if isinstance(value, datetime) and value.tzinfo is not None:
            return value.isoformat()
        case "json":
            return json.dumps(value, ensure_ascii=False)
    raise SchemaMismatchError(f"{where}: {col.dtype} が必要（値: {value!r}）")


def _decode_value(col: Column, value: object) -> object:
    if value is None:
        return None
    match col.dtype:
        case "bool":
            return bool(value)
        case "datetime":
            return datetime.fromisoformat(str(value))
        case "json":
            return json.loads(str(value))
    return value


def encode_row(table: str, row: Row) -> dict[str, object]:
    columns = TABLES[table]
    names = {c.name for c in columns}
    if missing := names - row.keys():
        raise SchemaMismatchError(f"{table}: 列が不足 {sorted(missing)}")
    if extra := row.keys() - names:
        raise SchemaMismatchError(f"{table}: 未定義の列 {sorted(extra)}")
    return {c.name: _encode_value(table, c, row[c.name]) for c in columns}


class SqliteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as conn:
            for table, columns in TABLES.items():
                defs = [
                    f"{c.name} {_SQL_TYPES[c.dtype]}{'' if c.nullable else ' NOT NULL'}"
                    + (" PRIMARY KEY" if _PRIMARY_KEYS[table] == c.name else "")
                    for c in columns
                ]
                defs += [f"UNIQUE ({', '.join(u)})" for u in [_UNIQUE.get(table, ())] if u]
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(defs)})")
                self._verify_existing(conn, table, columns)

    @staticmethod
    def _verify_existing(conn: sqlite3.Connection, table: str, columns: tuple[Column, ...]) -> None:
        """既存のDBファイルが現在のスキーマと一致するか確認する（実験途中の保存失敗を防ぐ）。"""
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        actual = [(name, _sql_type, bool(notnull)) for _, name, _sql_type, notnull, *_ in info]
        expected = [(c.name, _SQL_TYPES[c.dtype], not c.nullable) for c in columns]
        if actual != expected:
            raise SchemaMismatchError(
                f"既存のデータベース（{table}）のスキーマが現在の定義と異なる。"
                "スキーマ変更前に作成されたファイルの可能性がある。"
                "対処: 既存ファイルを退避（名前を変えて保存）し、新しいファイルで開始する。"
                "本番データが入っている場合は移行手順を用意してから切り替える。"
            )

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        # Streamlit はスレッドをまたぐため、操作ごとに接続を開く
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, row: Row) -> None:
        encoded = encode_row(table, row)
        cols = ", ".join(encoded)
        marks = ", ".join("?" for _ in encoded)
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(encoded.values()))

    @staticmethod
    def _require_consent(conn: sqlite3.Connection, participant_id: object) -> None:
        cur = conn.execute(
            "SELECT consent_status FROM participants WHERE participant_id = ?", (participant_id,)
        )
        found = cur.fetchone()
        if found is None or found[0] != "agreed":
            raise ConsentRequiredError(f"参加者 {participant_id} は同意済みでない")

    def create_participant(self, row: Row) -> None:
        if row.get("consent_status") != "agreed":
            raise ConsentRequiredError("参加者レコードは同意時にのみ作成する")
        with self._tx() as conn:
            self._insert(conn, "participants", row)

    def set_participant_status(
        self, participant_id: str, status: str, completed_at: datetime | None
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE participants SET status = ?, completed_at = ? WHERE participant_id = ?",
                (status, completed_at.isoformat() if completed_at else None, participant_id),
            )

    def save_trial(self, row: Row) -> SaveResult:
        with self._tx() as conn:
            self._require_consent(conn, row.get("participant_id"))
            try:
                self._insert(conn, "trials", row)
            except sqlite3.IntegrityError:
                cur = conn.execute(
                    "UPDATE trials SET duplicate_submission_count = duplicate_submission_count + 1"
                    " WHERE submission_id = ?",
                    (row["submission_id"],),
                )
                if cur.rowcount == 0:
                    raise
                return SaveResult.DUPLICATE
        return SaveResult.INSERTED

    def set_confidence(self, trial_id: str, confidence: int, timing: str) -> bool:
        """確信度を一度だけ設定する。既に設定済みなら False（上書きしない）。"""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE trials SET confidence = ?, confidence_timing = ?"
                " WHERE trial_id = ? AND confidence IS NULL",
                (confidence, timing, trial_id),
            )
            return cur.rowcount == 1

    def save_events(self, rows: Iterable[Row]) -> int:
        rows = list(rows)
        with self._tx() as conn:
            for pid in {r.get("participant_id") for r in rows}:
                self._require_consent(conn, pid)
            for r in rows:
                self._insert(conn, "events", r)
        return len(rows)

    def read_table(self, table: str) -> list[dict[str, object]]:
        columns = TABLES[table]
        with self._tx() as conn:
            cur = conn.execute(f"SELECT {', '.join(c.name for c in columns)} FROM {table}")
            return [
                {c.name: _decode_value(c, v) for c, v in zip(columns, rec, strict=True)}
                for rec in cur.fetchall()
            ]
