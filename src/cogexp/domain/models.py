"""問題・条件・実験定義のモデル。

問題の版は ``task_id/variant_id@version`` で一意に識別する（``VariantRef``）。
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"[a-z][a-z0-9_]*"
_REF_PATTERN = re.compile(rf"^(?P<task>{_ID})/(?P<variant>{_ID})@(?P<version>[1-9][0-9]*)$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResponseFormat(StrEnum):
    CHOICE = "choice"
    NUMERIC = "numeric"


class Outcome(StrEnum):
    """試行の結末。時間切れ・未回答・中断は誤答と区別する。"""

    ANSWERED = "answered"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    ABORTED = "aborted"


class VariantRef(_Frozen):
    task_id: str
    variant_id: str
    version: int = Field(ge=1)

    @classmethod
    def parse(cls, text: str) -> VariantRef:
        m = _REF_PATTERN.match(text)
        if m is None:
            raise ValueError(f"版の参照は 'task/variant@version' 形式で書く: {text!r}")
        return cls(task_id=m["task"], variant_id=m["variant"], version=int(m["version"]))

    def __str__(self) -> str:
        return f"{self.task_id}/{self.variant_id}@{self.version}"


class Choice(_Frozen):
    id: str = Field(pattern=_ID)
    text: str


class TaskVariant(_Frozen):
    """問題の1つの版。公開後は内容を変更しない（変更は version を上げる）。"""

    task_id: str = Field(pattern=_ID)
    variant_id: str = Field(pattern=_ID)
    version: int = Field(ge=1)
    response_format: ResponseFormat
    prompt: str = Field(min_length=1)
    choices: tuple[Choice, ...] = ()
    unit: str | None = None
    # 正答を定義できない版（推定値の整合性で評価する等）は両方 None
    correct_choice_id: str | None = None
    correct_value: float | None = None
    tolerance: float = Field(default=0.0, ge=0)

    @property
    def ref(self) -> VariantRef:
        return VariantRef(task_id=self.task_id, variant_id=self.variant_id, version=self.version)

    def content_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _check_format(self) -> Self:
        choice_ids = [c.id for c in self.choices]
        if len(set(choice_ids)) != len(choice_ids):
            raise ValueError(f"{self.ref}: choice id が重複している")
        if self.response_format is ResponseFormat.CHOICE:
            if len(self.choices) < 2:
                raise ValueError(f"{self.ref}: 選択式には2つ以上の choices が必要")
            if self.correct_choice_id is not None and self.correct_choice_id not in choice_ids:
                raise ValueError(f"{self.ref}: correct_choice_id が choices にない")
            if self.correct_value is not None:
                raise ValueError(f"{self.ref}: 選択式に correct_value は指定できない")
        else:
            if self.choices:
                raise ValueError(f"{self.ref}: 数値入力式に choices は指定できない")
            if self.correct_choice_id is not None:
                raise ValueError(f"{self.ref}: 数値入力式に correct_choice_id は指定できない")
        return self


class Condition(_Frozen):
    condition_id: str = Field(pattern=_ID)
    # None は制限なし。表示の有無（show_countdown）とは独立に扱う（概要書 §6.3）
    time_limit_sec: float | None = Field(default=None, gt=0)
    show_countdown: bool = False
    collect_confidence: bool = True
    variants: tuple[str, ...] = Field(min_length=1)

    def variant_refs(self) -> tuple[VariantRef, ...]:
        return tuple(VariantRef.parse(v) for v in self.variants)


class Experiment(_Frozen):
    experiment_id: str = Field(pattern=_ID)
    title: str
    conditions: tuple[Condition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_conditions(self) -> Self:
        ids = [c.condition_id for c in self.conditions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.experiment_id}: condition_id が重複している")
        return self
