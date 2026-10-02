"""制限時間の判定。時刻は単調増加ミリ秒（Clock.monotonic_ms）で受け取る。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Deadline:
    started_ms: float
    time_limit_sec: float | None

    def elapsed_ms(self, now_ms: float) -> float:
        return max(0.0, now_ms - self.started_ms)

    def remaining_sec(self, now_ms: float) -> float | None:
        """制限なしなら None。"""
        if self.time_limit_sec is None:
            return None
        return max(0.0, self.time_limit_sec - self.elapsed_ms(now_ms) / 1000.0)

    def expired(self, now_ms: float) -> bool:
        """制限時間ちょうどを含めて時間切れとする。"""
        if self.time_limit_sec is None:
            return False
        return self.elapsed_ms(now_ms) >= self.time_limit_sec * 1000.0
