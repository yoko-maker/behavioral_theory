"""時刻の取得口。domain 層は時刻をこの Clock 経由でのみ受け取る。

テストでは ``FakeClock`` を注入し、時間切れなどの判定を決定的に検証する。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """タイムゾーン付きの現在時刻（記録用）。"""
        ...

    def monotonic_ms(self) -> float:
        """経過時間計測用の単調増加時刻（ミリ秒）。"""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> float:
        return time.perf_counter() * 1000.0


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._ms = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> float:
        return self._ms

    def advance_ms(self, ms: float) -> None:
        self._ms += ms
        self._now += timedelta(milliseconds=ms)
