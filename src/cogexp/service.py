"""参加者セッションの進行（アプリケーションサービス層）。

app/ はこのモジュールの関数だけを呼び、画面を描画する。採点・時間切れ判定・保存行の組み立ては
すべてここで行う。セッション状態（``ParticipantSession``）は呼び出し側（st.session_state）が保持する。

Streamlit の再実行・二重クリックに備え、各操作は現在の段階と項目番号を確認し、
想定外の呼び出しは何もせず False を返す（重複送信は記録上 submission_id でも検出される）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

from cogexp.config.loader import Catalog
from cogexp.domain.assignment import assign_condition, new_seed
from cogexp.domain.clock import Clock
from cogexp.domain.flow import Event, FlowState, Stage, advance
from cogexp.domain.models import Condition, Experiment, Outcome, ResponseFormat, TaskVariant
from cogexp.domain.plan import PlannedItem, build_plan
from cogexp.domain.scoring import score
from cogexp.domain.timing import Deadline
from cogexp.storage.repository import SqliteRepository

CONFIDENCE_TIMING = "after"  # フェーズ1は回答後のみ


def app_version() -> str:
    try:
        return version("cogexp")
    except PackageNotFoundError:
        return "unknown"


@dataclass
class ActiveItem:
    """表示中の項目。初めて描画したときに作成し、時刻の基準とする。"""

    item_index: int
    trial_id: str
    submission_id: str
    shown_at: datetime
    deadline: Deadline
    changes: int = 0  # 回答欄の変更回数（最初の入力を含む）


@dataclass
class ParticipantSession:
    experiment_id: str
    participant_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    flow: FlowState = field(default_factory=FlowState)
    seed: int | None = None
    condition: Condition | None = None
    plan: tuple[PlannedItem, ...] = ()
    active: ActiveItem | None = None
    last_trial_id: str | None = None


class ParticipantService:
    def __init__(self, catalog: Catalog, repo: SqliteRepository, clock: Clock) -> None:
        self.catalog = catalog
        self.repo = repo
        self.clock = clock

    # --- 参照 -------------------------------------------------------------

    def experiment(self, s: ParticipantSession) -> Experiment:
        return self.catalog.experiments[s.experiment_id]

    def current(self, s: ParticipantSession) -> tuple[PlannedItem, TaskVariant]:
        item = s.plan[s.flow.item_index]
        return item, self.catalog.variant(item.ref)

    def _cond(self, s: ParticipantSession) -> Condition:
        if s.condition is None:
            raise RuntimeError("条件が割り当てられていない")
        return s.condition

    # --- 同意前 -------------------------------------------------------------

    def start(self, s: ParticipantSession) -> bool:
        if s.flow.stage is not Stage.INTRO:
            return False
        s.flow = advance(s.flow, Event.START)
        return True

    def decline(self, s: ParticipantSession) -> bool:
        """同意しない。何も保存しない。"""
        if s.flow.stage is not Stage.CONSENT:
            return False
        s.flow = advance(s.flow, Event.DECLINE)
        return True

    def agree(self, s: ParticipantSession) -> bool:
        """同意。ここで初めて条件を割り当て、参加者レコードを作成する。"""
        if s.flow.stage is not Stage.CONSENT:
            return False
        exp = self.experiment(s)
        seed = new_seed()
        cond = assign_condition(exp, seed)
        plan = build_plan(exp, cond)
        now = self.clock.now()
        self.repo.create_participant(
            {
                "participant_id": s.participant_id,
                "experiment_id": exp.experiment_id,
                "condition_id": cond.condition_id,
                "assignment_seed": seed,
                "consent_status": "agreed",
                "consented_at": now,
                "status": "in_progress",
                "created_at": now,
                "completed_at": None,
                "app_version": app_version(),
                "config_hash": self.catalog.config_hash(exp.experiment_id),
            }
        )
        s.seed, s.condition, s.plan = seed, cond, plan
        s.flow = advance(s.flow, Event.AGREE).configure(
            n_items=len(plan),
            n_practice=sum(i.is_practice for i in plan),
            collect_confidence=cond.collect_confidence,
        )
        return True

    def proceed(self, s: ParticipantSession) -> bool:
        """操作説明・遷移画面から次へ。"""
        if s.flow.stage not in (Stage.INSTRUCTIONS, Stage.TRANSITION):
            return False
        s.flow = advance(s.flow, Event.CONTINUE)
        return True

    # --- 課題 ---------------------------------------------------------------

    def ensure_shown(self, s: ParticipantSession) -> ActiveItem:
        """課題画面の描画時に呼ぶ。最初の呼び出し時刻を表示開始とする。"""
        if s.flow.stage is not Stage.TRIAL:
            raise RuntimeError("課題画面ではない")
        if s.active is None or s.active.item_index != s.flow.item_index:
            s.active = ActiveItem(
                item_index=s.flow.item_index,
                trial_id=uuid.uuid4().hex,
                submission_id=uuid.uuid4().hex,
                shown_at=self.clock.now(),
                deadline=Deadline(self.clock.monotonic_ms(), self._cond(s).time_limit_sec),
            )
        return s.active

    def remaining_sec(self, s: ParticipantSession) -> float | None:
        return self.ensure_shown(s).deadline.remaining_sec(self.clock.monotonic_ms())

    def is_expired(self, s: ParticipantSession) -> bool:
        return self.ensure_shown(s).deadline.expired(self.clock.monotonic_ms())

    def note_change(self, s: ParticipantSession) -> None:
        if s.flow.stage is Stage.TRIAL and s.active is not None:
            s.active.changes += 1

    def submit(
        self, s: ParticipantSession, choice_id: str | None = None, value: float | None = None
    ) -> Outcome | None:
        """回答を確定する。制限時間を過ぎていた場合は時間切れとして記録する。"""
        if s.flow.stage is not Stage.TRIAL or s.active is None:
            return None
        if s.active.item_index != s.flow.item_index:
            return None
        if self.is_expired(s):
            return self.timeout(s)
        self._finish(s, Outcome.ANSWERED, choice_id, value)
        return Outcome.ANSWERED

    def timeout(self, s: ParticipantSession) -> Outcome | None:
        if s.flow.stage is not Stage.TRIAL:
            return None
        self.ensure_shown(s)
        self._finish(s, Outcome.TIMEOUT, None, None)
        return Outcome.TIMEOUT

    def _finish(
        self, s: ParticipantSession, outcome: Outcome, choice_id: str | None, value: float | None
    ) -> None:
        active = self.ensure_shown(s)
        item, variant = self.current(s)
        cond = self._cond(s)
        answered = outcome is Outcome.ANSWERED
        if variant.response_format is ResponseFormat.CHOICE:
            value = None
        else:
            choice_id = None
        if not answered:
            choice_id, value = None, None
        is_correct = score(variant, outcome, choice_id, value)
        now_ms = self.clock.monotonic_ms()
        self.repo.save_trial(
            {
                "trial_id": active.trial_id,
                "submission_id": active.submission_id,
                "participant_id": s.participant_id,
                "experiment_id": s.experiment_id,
                "condition_id": cond.condition_id,
                "task_id": item.ref.task_id,
                "variant_id": item.ref.variant_id,
                "task_version": item.ref.version,
                "presentation_order": item.presentation_order,
                "is_practice": item.is_practice,
                "response_format": variant.response_format.value,
                "time_limit_sec": cond.time_limit_sec,
                "show_countdown": cond.show_countdown,
                "attempt": "initial",
                "shown_at_server": active.shown_at,
                "submitted_at_server": self.clock.now() if answered else None,
                "shown_at_client_ms": None,
                "submitted_at_client_ms": None,
                "response_time_ms": active.deadline.elapsed_ms(now_ms) if answered else None,
                "outcome": outcome.value,
                "choice_id": choice_id,
                "response_value": value,
                "is_correct": is_correct,
                "confidence": None,
                "confidence_timing": None,
                # 数値入力式はフォーム送信のため途中の変更を観測できない（空にする）
                "revision_count": (
                    max(0, active.changes - 1)
                    if variant.response_format is ResponseFormat.CHOICE
                    else None
                ),
                "duplicate_submission_count": 0,
            }
        )
        s.last_trial_id = active.trial_id
        s.flow = advance(s.flow, Event.ANSWER if answered else Event.TIMEOUT)
        self._complete_if_end(s)

    def rate(self, s: ParticipantSession, confidence: int) -> bool:
        if s.flow.stage is not Stage.CONFIDENCE or s.last_trial_id is None:
            return False
        levels = self.experiment(s).confidence_levels
        if not 1 <= confidence <= levels:
            raise ValueError(f"確信度は 1..{levels}")
        self.repo.set_confidence(s.last_trial_id, confidence, CONFIDENCE_TIMING)
        s.flow = advance(s.flow, Event.RATE)
        self._complete_if_end(s)
        return True

    def _complete_if_end(self, s: ParticipantSession) -> None:
        if s.flow.stage is Stage.END:
            self.repo.set_participant_status(s.participant_id, "completed", self.clock.now())
