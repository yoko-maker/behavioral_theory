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
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version

from cogexp.config.loader import Catalog
from cogexp.domain.assignment import ASSIGNMENT_METHOD, Cell, choose_cell, new_seed
from cogexp.domain.client_log import ClientEvent, ClientSubmission, parse_submission
from cogexp.domain.clock import Clock
from cogexp.domain.flow import Event, FlowState, Stage, advance
from cogexp.domain.models import Condition, Experiment, Outcome, ResponseFormat, TaskVariant
from cogexp.domain.plan import PlannedItem, build_plan
from cogexp.domain.scoring import parse_numeric, score
from cogexp.domain.timing import Deadline
from cogexp.storage.repository import CellCounts, ParticipantAbortedError, SqliteRepository

CONFIDENCE_TIMING = "after"  # 回答後のみ
ABORT_REASON_RELOAD = "reload"
# 期限後、ブラウザからの時間切れ通知（操作ログ付き）を待つ猶予。過ぎたらログなしで時間切れにする
CLIENT_GRACE_MS = 2_000
# 確信度の画面の部品に渡す画面ID（評価対象の trial_id + この接尾辞）
CONFIDENCE_SCREEN_SUFFIX = "-conf"


class ClientResult(StrEnum):
    ACCEPTED = "accepted"  # 回答として記録した
    TIMEOUT = "timeout"  # 時間切れとして記録した
    INVALID = "invalid"  # 入力を受け付けなかった（画面にエラーを表示して再送を待つ）
    WAITING = "waiting"  # ブラウザの時間切れ通知がサーバーの期限より早かった（期限を待つ）
    IGNORED = "ignored"  # 古い画面・想定外の段階からの送信


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
    # ブラウザから届いたイベント（送信が複数回に分かれた場合も含めて蓄積する）
    pending_events: list[ClientEvent] = field(default_factory=list)
    client: ClientSubmission | None = None  # 最後に届いた送信（端末情報・表示時刻など）
    error: str | None = None  # 画面に表示する入力エラー
    error_seq: int = 0  # エラーを出すたびに増やす（ブラウザが再送を許可する合図）


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
    # 確信度の画面で、受け付けなかった送信のイベント（再送時に合わせて保存する）
    confidence_pending: list[ClientEvent] = field(default_factory=list)
    confidence_error: str | None = None
    confidence_error_seq: int = 0


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

    def timeout_due(self, s: ParticipantSession) -> bool:
        """サーバー側で時間切れを確定すべきか。

        期限を過ぎていても、ブラウザから何も届いていなければ CLIENT_GRACE_MS だけ待つ
        （ブラウザの時間切れ通知に操作ログが含まれるため）。
        """
        active = self.ensure_shown(s)
        now_ms = self.clock.monotonic_ms()
        limit = active.deadline.time_limit_sec
        if limit is None or not active.deadline.expired(now_ms):
            return False
        waited = active.deadline.elapsed_ms(now_ms) - limit * 1000.0
        return active.client is not None or waited >= CLIENT_GRACE_MS

    def handle_client(self, s: ParticipantSession, raw: object) -> ClientResult:
        """問題画面の部品から届いた送信値（未検証）を処理する。"""
        if s.flow.stage not in (Stage.TRIAL, Stage.REVIEW) or s.active is None:
            return ClientResult.IGNORED
        client = parse_submission(raw)
        if client is None:
            return self._reject(s, "送信に失敗しました。もう一度「回答する」を押してください。")
        if client.trial_id != s.active.trial_id:
            return ClientResult.IGNORED
        if client.kind == "timeout":
            if self.client_timeout(s, client) is Outcome.TIMEOUT:
                return ClientResult.TIMEOUT
            return ClientResult.WAITING
        _, variant = self.current(s)
        choice_id: str | None = None
        value: float | None = None
        if variant.response_format is ResponseFormat.CHOICE:
            choice_id = client.choice_id
            if choice_id not in {c.id for c in variant.choices}:
                self.receive_client(s, client)
                return self._reject(s, "選択肢を選んでください。")
        else:
            value = parse_numeric(client.raw_value or "")
            if value is None and not self.is_expired(s):
                self.receive_client(s, client)
                return self._reject(s, "数字で入力してください。")
        outcome = self.submit(s, choice_id, value, client)
        if outcome is Outcome.ANSWERED:
            return ClientResult.ACCEPTED
        if outcome is Outcome.TIMEOUT:
            return ClientResult.TIMEOUT
        return ClientResult.IGNORED

    def _reject(self, s: ParticipantSession, message: str) -> ClientResult:
        if s.active is not None:
            s.active.error = message
            s.active.error_seq += 1
        return ClientResult.INVALID

    def receive_client(self, s: ParticipantSession, client: ClientSubmission) -> bool:
        """ブラウザからのイベントを表示中の試行に蓄積する。別の試行宛て（古い画面）なら捨てる。"""
        if s.active is None or client.trial_id != s.active.trial_id:
            return False
        s.active.pending_events.extend(client.events)
        s.active.client = client
        return True

    def submit(
        self,
        s: ParticipantSession,
        choice_id: str | None = None,
        value: float | None = None,
        client: ClientSubmission | None = None,
    ) -> Outcome | None:
        """回答を確定する。制限時間を過ぎていた場合は時間切れとして記録する。"""
        stage = s.flow.stage
        if stage not in (Stage.TRIAL, Stage.REVIEW) or s.active is None:
            return None
        if (s.active.stage, s.active.item_index) != (stage, s.flow.current_item_index):
            return None
        if client is not None and not self.receive_client(s, client):
            return None
        if self.is_expired(s):
            return self.timeout(s)
        self._finish(s, Outcome.ANSWERED, choice_id, value)
        return Outcome.ANSWERED

    def client_timeout(self, s: ParticipantSession, client: ClientSubmission) -> Outcome | None:
        """ブラウザ側で制限時間に達した通知。判定はサーバーの期限で行う（docs/plans/phase3.md）。

        サーバーの期限前なら、イベントだけ保持してサーバー側の時間切れ処理を待つ。
        """
        if s.flow.stage is not Stage.TRIAL or not self.receive_client(s, client):
            return None
        return self.timeout(s) if self.is_expired(s) else None

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
        answered = outcome is Outcome.ANSWERED
        if variant.response_format is ResponseFormat.CHOICE:
            value = None
        else:
            choice_id = None
        if not answered:
            choice_id, value = None, None
        is_correct = score(variant, outcome, choice_id, value)
        reviewing = s.flow.reviewing
        initial = s.initial_answers.get(active.item_index) if reviewing else None
        try:
            self.repo.save_trial(
                self._trial_row(
                    s, active, item, variant, outcome, choice_id, value, is_correct, initial
                ),
                self._event_rows(s, active.trial_id, active.pending_events, "answer"),
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

    def _event_rows(
        self, s: ParticipantSession, trial_id: str, events: list[ClientEvent], phase: str
    ) -> list[dict[str, object]]:
        return [
            {
                "event_id": uuid.uuid4().hex,
                "trial_id": trial_id,
                "participant_id": s.participant_id,
                "phase": phase,
                "event_type": e.type,
                "t_client_ms": e.t,
                "x_norm": e.x,
                "y_norm": e.y,
                "target_id": e.target,
                "payload": e.payload,
            }
            for e in sorted(events, key=lambda e: e.t)
        ]

    def _trial_row(
        self,
        s: ParticipantSession,
        active: ActiveItem,
        item: PlannedItem,
        variant: TaskVariant,
        outcome: Outcome,
        choice_id: str | None,
        value: float | None,
        is_correct: bool | None,
        initial: InitialAnswer | None,
    ) -> dict[str, object]:
        cond = self._cond(s)
        reviewing = s.flow.reviewing
        answered = outcome is Outcome.ANSWERED
        client = active.client
        info = client.client if client else None
        return {
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
            "shown_at_client_ms": client.shown_ms if client else None,
            "submitted_at_client_ms": client.sent_ms if client and answered else None,
            "response_time_ms": (
                active.deadline.elapsed_ms(self.clock.monotonic_ms()) if answered else None
            ),
            "outcome": outcome.value,
            "choice_id": choice_id,
            "response_value": value,
            "is_correct": is_correct,
            "confidence": None,
            "confidence_timing": None,
            # 確信度の画面の記録は rate() で後から設定する
            "confidence_rt_client_ms": None,
            "confidence_revision_count": None,
            "confidence_client_log_status": None,
            "confidence_n_events": None,
            # ブラウザで数えた変更回数（定義は docs/data_dictionary.md）。届かなければ空
            "revision_count": client.revision_count if client else None,
            "duplicate_submission_count": 0,
            "client_log_status": "ok" if client else "missing",
            "n_events": len(active.pending_events),
            "browser_family": info.browser if info else None,
            "os_family": info.os if info else None,
            "pointer_types": ",".join(info.pointer_types) if info else None,
            "viewport_w": info.viewport_w if info else None,
            "viewport_h": info.viewport_h if info else None,
            "panel_w": info.panel_w if info else None,
            "panel_h": info.panel_h if info else None,
            "device_pixel_ratio": info.dpr if info else None,
        }

    def confidence_screen_id(self, s: ParticipantSession) -> str:
        if s.last_trial_id is None:
            raise RuntimeError("確信度の対象の試行がない")
        return f"{s.last_trial_id}{CONFIDENCE_SCREEN_SUFFIX}"

    def handle_confidence(self, s: ParticipantSession, raw: object) -> ClientResult:
        """確信度の画面の部品から届いた送信値（未検証）を処理する。"""
        if s.flow.stage is not Stage.CONFIDENCE or s.last_trial_id is None:
            return ClientResult.IGNORED
        client = parse_submission(raw)
        if client is None:
            return self._reject_confidence(
                s, "送信に失敗しました。もう一度「次へ」を押してください。"
            )
        if client.trial_id != self.confidence_screen_id(s) or client.kind != "submit":
            return ClientResult.IGNORED
        levels = self.experiment(s).confidence_levels
        raw_level = client.choice_id or ""
        level = int(raw_level) if raw_level.isdigit() else 0
        if not 1 <= level <= levels:
            s.confidence_pending.extend(client.events)
            return self._reject_confidence(s, "いずれかを選んでください。")
        return ClientResult.ACCEPTED if self.rate(s, level, client) else ClientResult.IGNORED

    def _reject_confidence(self, s: ParticipantSession, message: str) -> ClientResult:
        s.confidence_error = message
        s.confidence_error_seq += 1
        return ClientResult.INVALID

    def rate(
        self, s: ParticipantSession, confidence: int, client: ClientSubmission | None = None
    ) -> bool:
        """確信度を記録する。client はブラウザからの送信（操作ログ・回答時間）。"""
        if s.flow.stage is not Stage.CONFIDENCE or s.last_trial_id is None:
            return False
        levels = self.experiment(s).confidence_levels
        if not 1 <= confidence <= levels:
            raise ValueError(f"確信度は 1..{levels}")
        events = [*s.confidence_pending, *(client.events if client else ())]
        try:
            self.repo.set_confidence(
                s.last_trial_id,
                confidence,
                CONFIDENCE_TIMING,
                rt_client_ms=client.sent_ms - client.shown_ms if client else None,
                revision_count=client.revision_count if client else None,
                log_status="ok" if client else "missing",
                events=self._event_rows(s, s.last_trial_id, events, "confidence"),
            )
        except ParticipantAbortedError:
            s.flow = FlowState(stage=Stage.ABORTED)
            return False
        s.confidence_pending, s.confidence_error = [], None
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
