from __future__ import annotations

from pathlib import Path

import pytest

from cogexp.config.loader import load_catalog
from cogexp.domain.clock import FakeClock
from cogexp.domain.flow import Stage
from cogexp.domain.models import Outcome
from cogexp.service import ClientResult, ParticipantService, ParticipantSession
from cogexp.storage.repository import SqliteRepository
from tests.conftest import MakeExperiments, client_payload, open_experiment


def _setup(
    make_experiments: MakeExperiments, tmp_path: Path, **kwargs: object
) -> tuple[ParticipantService, ParticipantSession, FakeClock]:
    catalog = load_catalog(make_experiments(**kwargs))
    clock = FakeClock()
    svc = ParticipantService(catalog, SqliteRepository(tmp_path / "db.sqlite"), clock)
    open_experiment(svc.repo)
    return svc, ParticipantSession(experiment_id="test_exp"), clock


def _to_first_trial(svc: ParticipantService, s: ParticipantSession) -> None:
    assert svc.start(s) and svc.agree(s) and svc.proceed(s)
    svc.ensure_shown(s)


def test_decline_saves_nothing(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path)
    svc.start(s)
    assert svc.decline(s)
    assert s.flow.stage is Stage.DECLINED
    assert svc.repo.read_table("participants") == []


def test_complete_run(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, clock = _setup(make_experiments, tmp_path)
    _to_first_trial(svc, s)
    answers = iter([("apple", None), (None, 7.0), ("conjunction", None), (None, 100.0)])
    while s.flow.stage is not Stage.END:
        if s.flow.stage is Stage.TRIAL:
            svc.ensure_shown(s)
            clock.advance_ms(2_000)
            choice, value = next(answers)
            assert svc.submit(s, choice, value) is Outcome.ANSWERED
        elif s.flow.stage is Stage.CONFIDENCE:
            assert svc.rate(s, 3)
        else:
            assert svc.proceed(s)

    [p] = svc.repo.read_table("participants")
    assert p["status"] == "completed"
    trials = sorted(svc.repo.read_table("trials"), key=lambda r: int(str(r["presentation_order"])))
    assert [t["is_practice"] for t in trials] == [True, True, False, False]
    assert [t["is_correct"] for t in trials] == [True, True, False, False]
    assert all(t["confidence"] == 3 and t["response_time_ms"] == 2_000 for t in trials)
    assert trials[2]["response_value"] is None and trials[3]["choice_id"] is None
    # ブラウザから何も届かない送信は、変更回数・端末情報を空にしてログ欠損として記録する
    assert {t["revision_count"] for t in trials} == {None}
    assert {t["client_log_status"] for t in trials} == {"missing"}


def test_timeout_is_not_an_error(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, clock = _setup(make_experiments, tmp_path, time_limit_sec=15, practice=())
    _to_first_trial(svc, s)
    clock.advance_ms(15_000)
    assert svc.is_expired(s)
    # 制限時間後の送信は回答として扱わない
    assert svc.submit(s, "single") is Outcome.TIMEOUT
    [t] = svc.repo.read_table("trials")
    assert (t["outcome"], t["is_correct"], t["choice_id"]) == ("timeout", None, None)
    assert t["response_time_ms"] is None
    # 時間切れでは確信度を尋ねない
    assert s.flow.stage is Stage.TRIAL and s.flow.item_index == 1


def test_double_submit_is_ignored(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path, practice=(), collect_confidence=False)
    _to_first_trial(svc, s)
    first = s.active
    assert svc.submit(s, "single") is Outcome.ANSWERED
    # 次の項目が表示される前の2回目の送信
    assert svc.submit(s, "single") is None
    assert len(svc.repo.read_table("trials")) == 1
    assert s.active is first  # 次項目は描画時に作られる


def test_client_submit_saves_events_and_device(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path, practice=(), collect_confidence=False)
    _to_first_trial(svc, s)
    assert s.active is not None
    raw = client_payload(s.active.trial_id, choice_id="single", revision_count=2)
    assert svc.handle_client(s, raw) is ClientResult.ACCEPTED
    [t] = svc.repo.read_table("trials")
    assert (t["choice_id"], t["is_correct"], t["revision_count"]) == ("single", True, 2)
    assert (t["shown_at_client_ms"], t["submitted_at_client_ms"]) == (1000.0, 3500.0)
    assert (t["client_log_status"], t["n_events"], t["browser_family"]) == ("ok", 4, "chrome")
    events = svc.repo.read_table("events")
    assert [
        e["event_type"] for e in sorted(events, key=lambda e: float(str(e["t_client_ms"])))
    ] == ["layout", "move", "move", "pointerdown"]
    assert {e["trial_id"] for e in events} == {t["trial_id"]}


def test_client_invalid_numeric_keeps_events(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    svc, s, _ = _setup(
        make_experiments,
        tmp_path,
        practice=(),
        collect_confidence=False,
        variants=("bat_ball/standard@1",),
    )
    _to_first_trial(svc, s)
    assert s.active is not None
    tid = s.active.trial_id
    assert svc.handle_client(s, client_payload(tid, raw_value="ごじゅう")) is ClientResult.INVALID
    assert s.active.error == "数字で入力してください。" and s.active.error_seq == 1
    assert svc.repo.read_table("trials") == []
    # 再送では最初の送信分のイベントも合わせて保存する
    assert svc.handle_client(s, client_payload(tid, raw_value="５０")) is ClientResult.ACCEPTED
    [t] = svc.repo.read_table("trials")
    assert (t["response_value"], t["n_events"]) == (50.0, 8)


def test_client_payload_for_old_screen_is_ignored(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path, practice=(), collect_confidence=False)
    _to_first_trial(svc, s)
    assert svc.handle_client(s, client_payload("other", choice_id="single")) is ClientResult.IGNORED
    assert svc.handle_client(s, {"kind": "submit"}) is ClientResult.INVALID
    assert svc.repo.read_table("trials") == []


def test_client_timeout_waits_for_server_deadline(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    svc, s, clock = _setup(make_experiments, tmp_path, practice=(), time_limit_sec=15)
    _to_first_trial(svc, s)
    assert s.active is not None
    tid = s.active.trial_id
    clock.advance_ms(14_900)  # ブラウザの時計が少し進んでいた
    assert svc.handle_client(s, client_payload(tid, kind="timeout")) is ClientResult.WAITING
    assert svc.repo.read_table("trials") == []
    clock.advance_ms(100)
    assert svc.timeout_due(s)  # ブラウザから届いているので猶予を待たない
    svc.timeout(s)
    [t] = svc.repo.read_table("trials")
    assert (t["outcome"], t["client_log_status"], t["n_events"]) == ("timeout", "ok", 4)
    assert t["submitted_at_client_ms"] is None


def test_server_timeout_after_grace_is_missing(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    from cogexp.service import CLIENT_GRACE_MS

    svc, s, clock = _setup(make_experiments, tmp_path, practice=(), time_limit_sec=15)
    _to_first_trial(svc, s)
    clock.advance_ms(15_000)
    assert svc.is_expired(s) and not svc.timeout_due(s)
    clock.advance_ms(CLIENT_GRACE_MS)
    assert svc.timeout_due(s)
    svc.timeout(s)
    [t] = svc.repo.read_table("trials")
    assert (t["outcome"], t["client_log_status"], t["n_events"]) == ("timeout", "missing", 0)


def test_rate_rejects_out_of_range(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path, practice=())
    _to_first_trial(svc, s)
    svc.submit(s, "single")
    with pytest.raises(ValueError):
        svc.rate(s, 6)


def test_config_hash_recorded(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path)
    svc.start(s)
    svc.agree(s)
    [p] = svc.repo.read_table("participants")
    assert p["config_hash"] == svc.catalog.config_hash("test_exp")
    assert p["condition_id"] == "only"


def test_closed_experiment_blocks_consent(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    catalog = load_catalog(make_experiments())
    svc = ParticipantService(catalog, SqliteRepository(tmp_path / "c.sqlite"), FakeClock())
    s = ParticipantSession(experiment_id="test_exp")
    assert not svc.start(s)
    assert s.flow.stage is Stage.CLOSED
    # 説明画面を開いた後に受付が停止された場合も同意できない
    open_experiment(svc.repo)
    s2 = ParticipantSession(experiment_id="test_exp")
    assert svc.start(s2)
    from cogexp.service import ExperimenterService

    ExperimenterService(svc.repo, FakeClock()).set_accepting("test_exp", False)
    svc.clock = FakeClock()
    assert not svc.agree(s2)
    assert s2.flow.stage is Stage.CLOSED
    assert svc.repo.read_table("participants") == []


def test_counterbalanced_orders_alternate(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    svc, _, _ = _setup(make_experiments, tmp_path, counterbalance_order=True)
    firsts = []
    for _ in range(4):
        s = ParticipantSession(experiment_id="test_exp")
        svc.start(s)
        svc.agree(s)
        firsts.append(s.plan[s.flow.n_practice].ref.task_id)
    assert sorted(firsts) == ["bat_ball", "bat_ball", "linda", "linda"]
    orders = [p["order_index"] for p in svc.repo.read_table("participants")]
    assert sorted(orders) == [0, 0, 1, 1]


def test_review_saves_revised_rows(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, clock = _setup(
        make_experiments, tmp_path, practice=(), allow_revision=True, time_limit_sec=15
    )
    _to_first_trial(svc, s)
    clock.advance_ms(16_000)  # 1問目は時間切れ
    svc.timeout(s)
    svc.ensure_shown(s)
    assert svc.submit(s, value=100.0) is Outcome.ANSWERED
    svc.rate(s, 4)
    assert s.flow.stage is Stage.REVIEW_INTRO
    svc.proceed(s)

    # 見直し1問目：初回は時間切れ。見直しには制限時間がない
    svc.ensure_shown(s)
    initial = svc.initial_answer(s)
    assert initial is not None and initial.outcome is Outcome.TIMEOUT
    clock.advance_ms(60_000)
    assert not svc.is_expired(s)
    assert svc.submit(s, "single") is Outcome.ANSWERED
    svc.rate(s, 5)
    # 見直し2問目：100 → 50 に変更
    svc.ensure_shown(s)
    svc.submit(s, value=50.0)
    svc.rate(s, 5)
    assert s.flow.stage is Stage.END

    rows = svc.repo.read_table("trials")
    initial_rows = {r["trial_id"]: r for r in rows if r["attempt"] == "initial"}
    revised = [r for r in rows if r["attempt"] == "revised"]
    assert len(initial_rows) == 2 and len(revised) == 2
    for r in revised:
        first = initial_rows[str(r["initial_trial_id"])]
        assert first["task_id"] == r["task_id"]
        assert r["time_limit_sec"] is None and r["show_countdown"] is False
    # 初回の行は見直しで変更されない
    assert {r["outcome"] for r in initial_rows.values()} == {"timeout", "answered"}
    assert sorted(r["is_correct"] for r in revised) == [True, True]
    assert svc.repo.read_table("participants")[0]["status"] == "completed"


def test_restore_marks_in_progress_as_aborted(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path)
    _to_first_trial(svc, s)
    restored = svc.restore(s.participant_id)
    assert restored is not None and restored.flow.stage is Stage.ABORTED
    [p] = svc.repo.read_table("participants")
    assert (p["status"], p["abort_reason"]) == ("aborted", "reload")
    assert svc.restore("unknown") is None


def test_old_tab_cannot_continue_after_abort(
    make_experiments: MakeExperiments, tmp_path: Path
) -> None:
    """別タブで同じURLが開かれた後、元のタブからの送信は保存せず中断画面にする。"""
    svc, s, _ = _setup(make_experiments, tmp_path, practice=(), collect_confidence=False)
    _to_first_trial(svc, s)
    svc.restore(s.participant_id)
    svc.submit(s, "single")
    assert s.flow.stage is Stage.ABORTED
    assert svc.repo.read_table("trials") == []
    assert svc.repo.read_table("participants")[0]["status"] == "aborted"


def test_restore_keeps_completed(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(
        make_experiments,
        tmp_path,
        practice=(),
        collect_confidence=False,
        variants=("linda/standard@1",),
    )
    _to_first_trial(svc, s)
    svc.submit(s, "single")
    restored = svc.restore(s.participant_id)
    assert restored is not None and restored.flow.stage is Stage.END
    assert svc.repo.read_table("participants")[0]["status"] == "completed"


def test_confidence_from_client(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    from cogexp.service import CONFIDENCE_SCREEN_SUFFIX

    svc, s, _ = _setup(make_experiments, tmp_path, practice=())
    _to_first_trial(svc, s)
    assert s.active is not None
    svc.handle_client(s, client_payload(s.active.trial_id, choice_id="single"))
    assert s.flow.stage is Stage.CONFIDENCE
    screen = f"{s.last_trial_id}{CONFIDENCE_SCREEN_SUFFIX}"
    assert svc.confidence_screen_id(s) == screen
    # 古い画面・範囲外の段階は受け付けない
    assert (
        svc.handle_confidence(s, client_payload("other-conf", choice_id="3"))
        is ClientResult.IGNORED
    )
    assert svc.handle_confidence(s, client_payload(screen, choice_id="9")) is ClientResult.INVALID
    assert s.confidence_error == "いずれかを選んでください。"
    raw = client_payload(screen, choice_id="4", revision_count=1, shown_ms=500.0, sent_ms=2700.0)
    assert svc.handle_confidence(s, raw) is ClientResult.ACCEPTED
    [t] = svc.repo.read_table("trials")
    assert (t["confidence"], t["confidence_rt_client_ms"], t["confidence_revision_count"]) == (
        4,
        2200.0,
        1,
    )
    # 受け付けなかった送信のイベントも合わせて保存する
    assert (t["confidence_client_log_status"], t["confidence_n_events"]) == ("ok", 8)
    phases = [e["phase"] for e in svc.repo.read_table("events")]
    assert phases.count("answer") == 4 and phases.count("confidence") == 8


def test_rate_without_client_is_missing(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path, practice=())
    _to_first_trial(svc, s)
    svc.submit(s, "single")
    svc.rate(s, 3)
    [t] = svc.repo.read_table("trials")
    assert (t["confidence"], t["confidence_client_log_status"], t["confidence_n_events"]) == (
        3,
        "missing",
        0,
    )
