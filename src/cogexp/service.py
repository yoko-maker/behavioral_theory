"""参加者セッションの進行（アプリケーションサービス層）。

app/ はこのモジュールの関数だけを呼び、画面を描画する。採点・時間切れ判定・割当・保存行の組み立ては
すべてここで行う。セッション状態（``ParticipantSession``）は呼び出し側（st.session_state）が保持する。

Streamlit の再実行・二重クリックに備え、各操作は現在の段階と項目番号を確認し、
想定外の呼び出しは何もせず False / None を返す（重複送信は記録上 submission_id でも検出される）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version

from cogexp.config.loader import Catalog
from cogexp.domain.assignment import ASSIGNMENT_METHOD, Cell, choose_cell, new_seed
from cogexp.domain.clock import Clock
from cogexp.domain.flow import Event, FlowState, Stage, advance
from cogexp.domain.models import Condition, Experiment, Outcome, ResponseFormat, TaskVariant
from cogexp.domain.plan import PlannedItem, build_plan
from cogexp.domain.scoring import score
from cogexp.domain.timing import Deadline
from cogexp.storage.repository import CellCounts, ParticipantAbortedError, SqliteRepository

CONFIDENCE_TIMING = "after"  # 回答後のみ
ABORT_REASON_RELOAD = "reload"


def app_version() -> str:
    try:
        return version("cogexp")
    except PackageNotFoundError:
        return "unknown"


@dataclass
class ActiveItem:
    """表示中の項目。初めて描画したときに作成し、時刻の基準とする。"""

    stage: Stage
    item_index: int
    trial_id: str
    submission_id: str
    shown_at: datetime
    deadline: Deadline
    changes: int = 0  # 回答欄の変更回数（最初の入力を含む）


@dataclass(frozen=True)
class InitialAnswer:
    """見直し画面で表示する初回回答。"""

    trial_id: str
    outcome: Outcome
    choice_id: str | None
    value: float | None


@dataclass
class ParticipantSession:
    experiment_id: str
    participant_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    flow: FlowState = field(default_factory=FlowState)
    seed: int | None = None
    condition: Condition | None = None
    order_index: int = 0
    plan: tuple[PlannedItem, ...] = ()
    active: ActiveItem | None = None
    last_trial_id: str | None = None
    initial_answers: dict[int, InitialAnswer] = field(default_factory=dict)


class ParticipantService:
    def __init__(self, catalog: Catalog, repo: SqliteRepository, clock: Clock) -> None:
        self.catalog = catalog
        self.repo = repo
        self.clock = clock

    # --- 参照 -------------------------------------------------------------

    def experiment(self, s: ParticipantSession) -> Experiment:
        return self.catalog.experiments[s.experiment_id]

    def current(self, s: ParticipantSession) -> tuple[PlannedItem, TaskVariant]:
        item = s.plan[s.flow.current_item_index]
        return item, self.catalog.variant(item.ref)

    def initial_answer(self, s: ParticipantSession) -> InitialAnswer | None:
        return s.initial_answers.get(s.flow.current_item_index)

    def _cond(self, s: ParticipantSession) -> Condition:
        if s.condition is None:
            raise RuntimeError("条件が割り当てられていない")
        return s.condition

    def is_accepting(self, experiment_id: str) -> bool:
        return self.repo.is_accepting(experiment_id)

    # --- 再読み込み・別タブ -------------------------------------------------

    def restore(self, participant_id: str) -> ParticipantSession | None:
        """セッション状態を失った状態で参加者IDの URL が開かれたときに呼ぶ。

        進行中なら中断として記録する（再開はさせない）。完了者は終了画面を表示する。
        """
        row = self.repo.get_participant(participant_id)
        if row is None:
            return None
        if row["status"] == "in_progress":
            self.repo.mark_aborted(participant_id, self.clock.now(), ABORT_REASON_RELOAD)
        stage = Stage.END if row["status"] == "completed" else Stage.ABORTED
        return ParticipantSession(
            experiment_id=str(row["experiment_id"]),
            participant_id=participant_id,
            flow=FlowState(stage=stage),
        )

    # --- 同意前 -------------------------------------------------------------

    def start(self, s: ParticipantSession) -> bool:
        if s.flow.stage is not Stage.INTRO:
            return False
        event = Event.START if self.is_accepting(s.experiment_id) else Event.CLOSE
        s.flow = advance(s.flow, event)
        return event is Event.START

    def decline(self, s: ParticipantSession) -> bool:
        """同意しない。何も保存しない。"""
        if s.flow.stage is not Stage.CONSENT:
            return False
        s.flow = advance(s.flow, Event.DECLINE)
        return True

    def agree(self, s: ParticipantSession) -> bool:
        """同意。ここで初めてセルを割り当て、参加者レコードを作成する。"""
        if s.flow.stage is not Stage.CONSENT:
            return False
        if not self.is_accepting(s.experiment_id):
            s.flow = advance(s.flow, Event.CLOSE)
            return False
        exp = self.experiment(s)
        seed = new_seed()
        now = self.clock.now()

        def build_row(counts: CellCounts) -> dict[str, object]:
            cell = choose_cell(exp, {Cell(c, k): n for (c, k), n in counts.items()}, seed)
            return {
                "participant_id": s.participant_id,
                "experiment_id": exp.experiment_id,
                "condition_id": cell.condition_id,
                "order_index": cell.order_index,
                "assignment_method": ASSIGNMENT_METHOD,
                "assignment_seed": seed,
                "consent_status": "agreed",
                "consented_at": now,
                "status": "in_progress",
                "created_at": now,
                "completed_at": None,
                "aborted_at": None,
                "abort_reason": None,
                "app_version": app_version(),
                "config_hash": self.catalog.config_hash(exp.experiment_id),
            }

        row = self.repo.create_participant_assigned(
            exp.experiment_id, now - timedelta(minutes=exp.abandon_after_min), build_row
        )
        cond = exp.condition(str(row["condition_id"]))
        order_index = int(str(row["order_index"]))
        plan = build_plan(exp, cond, order_index)
        s.seed, s.condition, s.order_index, s.plan = seed, cond, order_index, plan
        s.flow = advance(s.flow, Event.AGREE).configure(
            n_items=len(plan),
            n_practice=sum(i.is_practice for i in plan),
            collect_confidence=cond.collect_confidence,
            allow_revision=cond.allow_revision,
        )
        return True

    def proceed(self, s: ParticipantSession) -> bool:
        """操作説明・遷移画面・見直しの説明から次へ。"""
        if s.flow.stage not in (Stage.INSTRUCTIONS, Stage.TRANSITION, Stage.REVIEW_INTRO):
            return False
        s.flow = advance(s.flow, Event.CONTINUE)
        return True

    # --- 課題・見直し -------------------------------------------------------

    def _time_limit(self, s: ParticipantSession) -> float | None:
        # 見直しには制限時間を設けない（docs/plans/phase2.md）
        return None if s.flow.reviewing else self._cond(s).time_limit_sec

    def ensure_shown(self, s: ParticipantSession) -> ActiveItem:
        """課題・見直し画面の描画時に呼ぶ。最初の呼び出し時刻を表示開始とする。"""
        stage = s.flow.stage
        if stage not in (Stage.TRIAL, Stage.REVIEW):
            raise RuntimeError("課題画面ではない")
        index = s.flow.current_item_index
        if s.active is None or (s.active.stage, s.active.item_index) != (stage, index):
            s.active = ActiveItem(
                stage=stage,
                item_index=index,
                trial_id=uuid.uuid4().hex,
                submission_id=uuid.uuid4().hex,
                shown_at=self.clock.now(),
                deadline=Deadline(self.clock.monotonic_ms(), self._time_limit(s)),
            )
        return s.active

    def remaining_sec(self, s: ParticipantSession) -> float | None:
        return self.ensure_shown(s).deadline.remaining_sec(self.clock.monotonic_ms())

    def is_expired(self, s: ParticipantSession) -> bool:
        return self.ensure_shown(s).deadline.expired(self.clock.monotonic_ms())

    def note_change(self, s: ParticipantSession) -> None:
        if s.flow.stage in (Stage.TRIAL, Stage.REVIEW) and s.active is not None:
            s.active.changes += 1

    def submit(
        self, s: ParticipantSession, choice_id: str | None = None, value: float | None = None
    ) -> Outcome | None:
        """回答を確定する。制限時間を過ぎていた場合は時間切れとして記録する。"""
        stage = s.flow.stage
        if stage not in (Stage.TRIAL, Stage.REVIEW) or s.active is None:
            return None
        if (s.active.stage, s.active.item_index) != (stage, s.flow.current_item_index):
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
        reviewing = s.flow.reviewing
        answered = outcome is Outcome.ANSWERED
        if variant.response_format is ResponseFormat.CHOICE:
            value = None
        else:
            choice_id = None
        if not answered:
            choice_id, value = None, None
        is_correct = score(variant, outcome, choice_id, value)
        initial = s.initial_answers.get(active.item_index) if reviewing else None
        prefilled = initial is not None and initial.outcome is Outcome.ANSWERED
        now_ms = self.clock.monotonic_ms()
        try:
            self._save_trial(
                s,
                active,
                item,
                variant,
                cond,
                outcome,
                choice_id,
                value,
                is_correct,
                initial,
                prefilled,
                now_ms,
            )
        except ParticipantAbortedError:
            # 別タブ・再読み込みで中断済み。このタブも中断画面に切り替え、以後は保存しない
            s.flow = FlowState(stage=Stage.ABORTED)
            return
        if not reviewing and not item.is_practice:
            s.initial_answers[active.item_index] = InitialAnswer(
                active.trial_id, outcome, choice_id, value
            )
        s.last_trial_id = active.trial_id
        s.flow = advance(s.flow, Event.ANSWER if answered else Event.TIMEOUT)
        self._complete_if_end(s)

    def _save_trial(
        self,
        s: ParticipantSession,
        active: ActiveItem,
        item: PlannedItem,
        variant: TaskVariant,
        cond: Condition,
        outcome: Outcome,
        choice_id: str | None,
        value: float | None,
        is_correct: bool | None,
        initial: InitialAnswer | None,
        prefilled: bool,
        now_ms: float,
    ) -> None:
        reviewing = s.flow.reviewing
        answered = outcome is Outcome.ANSWERED
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
                "time_limit_sec": active.deadline.time_limit_sec,
                "show_countdown": cond.show_countdown and not reviewing,
                "attempt": "revised" if reviewing else "initial",
                "initial_trial_id": initial.trial_id if initial else None,
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
                # 見直しで初回回答が既定値として選択済みの場合は、最初の変更から数える
                "revision_count": (
                    max(0, active.changes - (0 if prefilled else 1))
                    if variant.response_format is ResponseFormat.CHOICE
                    else None
                ),
                "duplicate_submission_count": 0,
            }
        )

    def rate(self, s: ParticipantSession, confidence: int) -> bool:
        if s.flow.stage is not Stage.CONFIDENCE or s.last_trial_id is None:
            return False
        levels = self.experiment(s).confidence_levels
        if not 1 <= confidence <= levels:
            raise ValueError(f"確信度は 1..{levels}")
        try:
            self.repo.set_confidence(s.last_trial_id, confidence, CONFIDENCE_TIMING)
        except ParticipantAbortedError:
            s.flow = FlowState(stage=Stage.ABORTED)
            return False
        s.flow = advance(s.flow, Event.RATE)
        self._complete_if_end(s)
        return True

    def _complete_if_end(self, s: ParticipantSession) -> None:
        if s.flow.stage is Stage.END:
            self.repo.set_participant_status(s.participant_id, "completed", self.clock.now())


class ExperimenterService:
    """実験者画面の操作（受付の切替）。"""

    def __init__(self, repo: SqliteRepository, clock: Clock) -> None:
        self.repo = repo
        self.clock = clock

    def set_accepting(self, experiment_id: str, accepting: bool) -> None:
        self.repo.append_status(
            {
                "log_id": uuid.uuid4().hex,
                "experiment_id": experiment_id,
                "accepting": accepting,
                "changed_at": self.clock.now(),
            }
        )
