"""ブラウザ（問題画面の部品）から届くデータの検証。

ブラウザからの値は信頼できない入力として扱う。イベント種別は許可リストで制限し、
件数・文字列長・数値の範囲を検証する。座標は問題領域を基準に正規化した値（領域外は 0 未満・1 超）。
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

MAX_EVENTS = 100_000
MAX_PAYLOAD_CHARS = 2_000

EVENT_TYPES = frozenset(
    {
        "layout",  # 表示直後の各要素の位置（payload.rects）
        "move",  # マウス・ペン・タッチの移動（画面更新ごと）
        "pointerdown",  # 押下（target: 選択肢ID / input / submit / None）
        "choice_change",  # 選択の変更（target: 選択肢ID）
        "choice_enter",  # 選択肢の領域に入った
        "choice_leave",  # 選択肢の領域から出た
        "key",  # キー操作の種類（payload.class。キーの内容は記録しない）
        "input_edit",  # 数値入力欄の編集（payload.op: insert / delete / other）
        "invalid_submit",  # 数値として解釈できない入力で送信しようとした
        "visibility",  # タブ切替等（payload.state: hidden / visible）
        "window_blur",
        "window_focus",
        "submit",  # 回答確定
        "timeout",  # ブラウザ側で制限時間に到達
    }
)


def _finite(v: float) -> float:
    if not math.isfinite(v):
        raise ValueError("有限の数値が必要")
    return v


Finite = Annotated[float, AfterValidator(_finite)]
Ms = Annotated[float, AfterValidator(_finite), Field(ge=0, le=1e10)]
Coord = Annotated[float, AfterValidator(_finite), Field(ge=-100, le=100)]
ShortId = Annotated[str, Field(max_length=64, pattern=r"^[A-Za-z0-9_\-]*$")]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ClientEvent(_Strict):
    t: Ms  # performance.now()（ms）
    type: str
    x: Coord | None = None
    y: Coord | None = None
    target: ShortId | None = None
    payload: dict[str, Any] | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"未知のイベント種別: {v[:32]!r}")
        return v

    @field_validator("payload")
    @classmethod
    def _small_payload(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v, ensure_ascii=False)) > MAX_PAYLOAD_CHARS:
            raise ValueError("payload が大きすぎる")
        return v


class ClientInfo(_Strict):
    browser: ShortId = "unknown"
    os: ShortId = "unknown"
    pointer_types: tuple[Literal["mouse", "touch", "pen"], ...] = ()
    viewport_w: int = Field(ge=0, le=100_000)
    viewport_h: int = Field(ge=0, le=100_000)
    panel_w: int = Field(ge=0, le=100_000)
    panel_h: int = Field(ge=0, le=100_000)
    dpr: Finite = Field(gt=0, le=20)


class ClientSubmission(_Strict):
    """回答確定（kind=submit）または時間切れ（kind=timeout）の送信内容。"""

    kind: Literal["submit", "timeout"]
    trial_id: ShortId
    choice_id: ShortId | None = None
    raw_value: str | None = Field(default=None, max_length=64)
    shown_ms: Ms
    sent_ms: Ms
    revision_count: int | None = Field(default=None, ge=0, le=100_000)
    client: ClientInfo
    events: tuple[ClientEvent, ...] = Field(default=(), max_length=MAX_EVENTS)


def parse_submission(raw: object) -> ClientSubmission | None:
    """部品の送信値を検証する。形式が不正なら None（呼び出し側はログ欠損として扱う）。"""
    if not isinstance(raw, dict):
        return None
    try:
        return ClientSubmission.model_validate(raw)
    except ValueError:
        return None
