from __future__ import annotations

from pathlib import Path

import pytest

from cogexp.config.loader import load_catalog
from cogexp.domain.clock import FakeClock
from cogexp.domain.flow import Stage
from cogexp.domain.models import Outcome
from cogexp.service import ParticipantService, ParticipantSession
from cogexp.storage.repository import SqliteRepository
from tests.conftest import MakeExperiments, open_experiment


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
    # 数値入力式は変更回数を計測しない（0 ではなく空）
    assert [t["revision_count"] for t in trials] == [0, None, 0, None]


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


def test_revision_count(make_experiments: MakeExperiments, tmp_path: Path) -> None:
    svc, s, _ = _setup(make_experiments, tmp_path, practice=(), collect_confidence=False)
    _to_first_trial(svc, s)
    for _ in range(3):
        svc.note_change(s)
    svc.submit(s, "single")
    assert svc.repo.read_table("trials")[0]["revision_count"] == 2


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
