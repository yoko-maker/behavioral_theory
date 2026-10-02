"""SQLite リポジトリ。

- 書き込む行は ``schema.TABLES`` と完全一致することを検証する（列の過不足・型・欠損）。
- 同意済み（consent_status = agreed）でない参加者の trial/event は保存しない。
- trial は ``submission_id`` で冪等。同じ送信の再送は行を増やさず、重複回数を数える。
- 生データは追記のみ。更新は明示した列（参加者の状態・確信度）に限る。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping
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
_PRIMARY_KEYS = {
    "participants": "participant_id",
    "trials": "trial_id",
    "events": "event_id",
    "experiment_status_log": "log_id",
}
_UNIQUE = {"trials": ("submission_id",)}

Row = Mapping[str, object]
# (condition_id, order_index) -> 割当人数
CellCounts = dict[tuple[str, int], int]


class ConsentRequiredError(Exception):
    """同意済みでない参加者のデータを保存しようとした。"""


class ParticipantAbortedError(Exception):
    """中断済みの参加者のデータを保存しようとした（別タブ・再読み込み後の元のタブなど）。"""


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
    def _tx(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        # Streamlit はスレッドをまたぐため、操作ごとに接続を開く
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                if immediate:
                    # 読み取りから書き込みまでを他の書き込みと直列化する（割当の集計など）
                    conn.execute("BEGIN IMMEDIATE")
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
    def _insert_many(conn: sqlite3.Connection, table: str, rows: Iterable[Row]) -> None:
        encoded = [encode_row(table, r) for r in rows]
        if not encoded:
            return
        cols = ", ".join(encoded[0])
        marks = ", ".join("?" for _ in encoded[0])
        conn.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({marks})", [list(e.values()) for e in encoded]
        )

    @staticmethod
    def _require_consent(conn: sqlite3.Connection, participant_id: object) -> None:
        cur = conn.execute(
            "SELECT consent_status FROM participants WHERE participant_id = ?", (participant_id,)
        )
        found = cur.fetchone()
        if found is None or found[0] != "agreed":
            raise ConsentRequiredError(f"参加者 {participant_id} は同意済みでない")

    @classmethod
    def _require_active(cls, conn: sqlite3.Connection, participant_id: object) -> None:
        cls._require_consent(conn, participant_id)
        cur = conn.execute(
            "SELECT status FROM participants WHERE participant_id = ?", (participant_id,)
        )
        if cur.fetchone()[0] == "aborted":
            raise ParticipantAbortedError(f"参加者 {participant_id} は中断済み")

    def create_participant(self, row: Row) -> None:
        if row.get("consent_status") != "agreed":
            raise ConsentRequiredError("参加者レコードは同意時にのみ作成する")
        with self._tx() as conn:
            self._insert(conn, "participants", row)

    def create_participant_assigned(
        self,
        experiment_id: str,
        active_since: datetime,
        build_row: Callable[[CellCounts], Row],
    ) -> Row:
        """現在の割当人数を集計し、build_row が作った参加者行を同じトランザクションで保存する。

        数えるのは completed と、active_since 以降に開始した in_progress（中断者・放置者は除く）。
        """
        with self._tx(immediate=True) as conn:
            cur = conn.execute(
                "SELECT condition_id, order_index, COUNT(*) FROM participants"
                " WHERE experiment_id = ? AND (status = 'completed'"
                " OR (status = 'in_progress' AND created_at >= ?))"
                " GROUP BY condition_id, order_index",
                (experiment_id, active_since.isoformat()),
            )
            counts: CellCounts = {(c, int(k)): int(n) for c, k, n in cur.fetchall()}
            row = build_row(counts)
            if row.get("consent_status") != "agreed":
                raise ConsentRequiredError("参加者レコードは同意時にのみ作成する")
            self._insert(conn, "participants", row)
        return row

    def get_participant(self, participant_id: str) -> dict[str, object] | None:
        rows = self._select("participants", "participant_id = ?", (participant_id,))
        return rows[0] if rows else None

    def mark_aborted(self, participant_id: str, at: datetime, reason: str) -> bool:
        """進行中の参加者を中断にする。進行中でなければ何もせず False。"""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE participants SET status = 'aborted', aborted_at = ?, abort_reason = ?"
                " WHERE participant_id = ? AND status = 'in_progress'",
                (at.isoformat(), reason, participant_id),
            )
            return cur.rowcount == 1

    def append_status(self, row: Row) -> None:
        with self._tx() as conn:
            self._insert(conn, "experiment_status_log", row)

    def is_accepting(self, experiment_id: str) -> bool:
        """最新のログで判定する。ログがなければ受付停止（既定）。"""
        with self._tx() as conn:
            cur = conn.execute(
                "SELECT accepting FROM experiment_status_log WHERE experiment_id = ?"
                " ORDER BY changed_at DESC, rowid DESC LIMIT 1",
                (experiment_id,),
            )
            found = cur.fetchone()
        return bool(found[0]) if found else False

    def set_participant_status(
        self, participant_id: str, status: str, completed_at: datetime | None
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE participants SET status = ?, completed_at = ?"
                " WHERE participant_id = ? AND status = 'in_progress'",
                (status, completed_at.isoformat() if completed_at else None, participant_id),
            )

    def save_trial(self, row: Row, events: Iterable[Row] = ()) -> SaveResult:
        """試行とその操作イベントを同じトランザクションで保存する。

        重複送信（同じ submission_id）の場合はイベントも保存しない。
        """
        with self._tx() as conn:
            self._require_active(conn, row.get("participant_id"))
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
            # イベントの保存に失敗した場合は試行の行ごとロールバックされる
            self._insert_many(conn, "events", events)
        return SaveResult.INSERTED

    def set_confidence(
        self,
        trial_id: str,
        confidence: int,
        timing: str,
        *,
        rt_client_ms: float | None = None,
        revision_count: int | None = None,
        log_status: str | None = None,
        events: Iterable[Row] = (),
    ) -> bool:
        """確信度とその画面の操作ログを一度だけ保存する。

        既に設定済みなら何もせず False（上書きしない。イベントも保存しない）。
        """
        events = list(events)
        with self._tx() as conn:
            cur = conn.execute("SELECT participant_id FROM trials WHERE trial_id = ?", (trial_id,))
            if (found := cur.fetchone()) is not None:
                self._require_active(conn, found[0])
            cur = conn.execute(
                "UPDATE trials SET confidence = ?, confidence_timing = ?,"
                " confidence_rt_client_ms = ?, confidence_revision_count = ?,"
                " confidence_client_log_status = ?, confidence_n_events = ?"
                " WHERE trial_id = ? AND confidence IS NULL",
                (
                    confidence,
                    timing,
                    rt_client_ms,
                    revision_count,
                    log_status,
                    len(events) if log_status is not None else None,
                    trial_id,
                ),
            )
            if cur.rowcount != 1:
                return False
            self._insert_many(conn, "events", events)
            return True

    def save_events(self, rows: Iterable[Row]) -> int:
        rows = list(rows)
        with self._tx() as conn:
            for pid in {r.get("participant_id") for r in rows}:
                self._require_active(conn, pid)
            for r in rows:
                self._insert(conn, "events", r)
        return len(rows)

    def read_table(self, table: str) -> list[dict[str, object]]:
        return self._select(table)

    def _select(
        self, table: str, where: str | None = None, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        columns = TABLES[table]
        sql = f"SELECT {', '.join(c.name for c in columns)} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        with self._tx() as conn:
            cur = conn.execute(sql, params)
            return [
                {c.name: _decode_value(c, v) for c, v in zip(columns, rec, strict=True)}
                for rec in cur.fetchall()
            ]
