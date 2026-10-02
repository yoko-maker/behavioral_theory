"""AppTest による画面フローの検証（参加者が実際に操作する経路）。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cogexp.domain.clock import FakeClock
from cogexp.storage.repository import SqliteRepository
from tests.app.panel import send, stage
from tests.conftest import MakeExperiments, open_experiment

APP = Path(__file__).resolve().parents[2] / "app" / "main.py"
TEST_CLOCK = "_test_clock"  # app/state.py と一致させる

Setup = Callable[..., Path]


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make_experiments: MakeExperiments
) -> Setup:
    def _setup(*, closed: bool = False, **kwargs: object) -> Path:
        monkeypatch.setenv("COGEXP_EXPERIMENTS_DIR", str(make_experiments(**kwargs)))
        kwargs["_closed"] = closed
        monkeypatch.setenv("COGEXP_DATA_DIR", str(tmp_path / "data"))
        db = tmp_path / "data" / "cogexp.sqlite"
        if kwargs.pop("_closed", False) is False:
            open_experiment(SqliteRepository(db))
        return db

    return _setup


def _start(clock: FakeClock | None = None) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=30)
    if clock is not None:
        at.session_state[TEST_CLOCK] = clock
    return at.run()


def _click(at: AppTest, label: str) -> AppTest:
    [button] = [b for b in at.button if b.label == label]
    return button.click().run()


def _to_first_trial(at: AppTest) -> AppTest:
    _click(at, "次へ")
    _click(at, "同意して参加する")
    return _click(at, "練習を始める")


def _text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_decline_saves_nothing(setup: Setup) -> None:
    db = setup()
    at = _click(_start(), "次へ")
    _click(at, "同意しない")
    assert not at.exception
    assert "データは保存されていません" in _text(at)
    assert SqliteRepository(db).read_table("participants") == []


def _rate_next(at: AppTest, value: int, revision: int = 0) -> None:
    """確信度の画面（部品）から送信が届いたものとして進める。"""
    assert stage(at) == "confidence"
    send(at, choice_id=str(value), revision_count=revision, sent_ms=2800.0)


def test_complete_flow(setup: Setup) -> None:
    db = setup()
    at = _to_first_trial(_start())
    # 練習1（選択）→ 確信度 → 練習2（数値）→ 確信度 → 遷移画面
    send(at, choice_id="apple")
    _rate_next(at, 4)
    send(at, raw_value="７")
    _rate_next(at, 5)
    assert "練習は以上です" in _text(at)
    _click(at, "次へ")
    # 本課題
    send(at, choice_id="conjunction", revision_count=1)
    _rate_next(at, 2, revision=2)
    send(at, raw_value="100")
    _rate_next(at, 3)

    assert not at.exception
    assert "ご協力ありがとうございました" in _text(at)
    repo = SqliteRepository(db)
    assert repo.read_table("participants")[0]["status"] == "completed"
    trials = sorted(repo.read_table("trials"), key=lambda r: int(str(r["presentation_order"])))
    assert [t["is_correct"] for t in trials] == [True, True, False, False]
    assert [t["confidence"] for t in trials] == [4, 5, 2, 3]
    assert [t["revision_count"] for t in trials] == [0, 0, 1, 0]
    assert {t["client_log_status"] for t in trials} == {"ok"}
    assert [t["confidence_revision_count"] for t in trials] == [0, 0, 2, 0]
    assert {t["confidence_rt_client_ms"] for t in trials} == {1800.0}
    assert {t["confidence_client_log_status"] for t in trials} == {"ok"}
    events = repo.read_table("events")
    assert len([e for e in events if e["phase"] == "answer"]) == 4 * 4
    assert len([e for e in events if e["phase"] == "confidence"]) == 4 * 4


def test_invalid_numeric_shows_error(setup: Setup) -> None:
    db = setup(practice=(), variants=("bat_ball/standard@1",))
    at = _to_first_trial(_start())
    send(at, raw_value="ごじゅう")
    assert not at.exception
    assert stage(at) == "trial"
    assert at.session_state["participant_session"].active.error == "数字で入力してください。"
    assert SqliteRepository(db).read_table("trials") == []


def test_timeout_from_browser(setup: Setup) -> None:
    db = setup(time_limit_sec=15, show_countdown=True, practice=())
    clock = FakeClock()
    at = _to_first_trial(_start(clock))
    clock.advance_ms(15_000)
    send(at, kind="timeout")
    assert not at.exception
    [t] = SqliteRepository(db).read_table("trials")
    assert (t["outcome"], t["is_correct"], t["client_log_status"]) == ("timeout", None, "ok")
    # 確信度を飛ばして次の問題へ
    s = at.session_state["participant_session"]
    assert (stage(at), s.flow.item_index) == ("trial", 1)


def test_timeout_without_browser_message(setup: Setup) -> None:
    from cogexp.service import CLIENT_GRACE_MS

    db = setup(time_limit_sec=15, practice=())
    clock = FakeClock()
    at = _to_first_trial(_start(clock))
    clock.advance_ms(15_000 + CLIENT_GRACE_MS)
    at.run()
    assert not at.exception
    [t] = SqliteRepository(db).read_table("trials")
    assert (t["outcome"], t["client_log_status"]) == ("timeout", "missing")


def test_closed_experiment_shows_notice(setup: Setup) -> None:
    db = setup(closed=True)
    at = _start()
    assert "受付を行っていません" in _text(at)
    assert not [b for b in at.button if b.label == "次へ"]
    assert SqliteRepository(db).read_table("participants") == []


def test_reload_is_recorded_as_abort(setup: Setup) -> None:
    db = setup()
    at = _to_first_trial(_start())
    pid = at.query_params["pid"][0]
    # 再読み込み相当：新しいセッションで同じ URL（?pid=）を開く
    reloaded = AppTest.from_file(str(APP), default_timeout=30)
    reloaded.query_params["pid"] = pid
    reloaded.run()
    assert not reloaded.exception
    assert "中断されました" in _text(reloaded)
    p = SqliteRepository(db).get_participant(pid)
    assert p is not None and (p["status"], p["abort_reason"]) == ("aborted", "reload")


def test_review_flow_shows_initial_answer(setup: Setup) -> None:
    db = setup(practice=(), allow_revision=True, collect_confidence=False)
    at = _to_first_trial(_start())
    send(at, choice_id="conjunction")
    send(at, raw_value="100")
    assert "回答の見直し" in _text(at)
    _click(at, "見直しを始める")
    s = at.session_state["participant_session"]
    assert s.flow.reviewing
    initial = s.initial_answers[s.flow.current_item_index]
    assert initial.choice_id == "conjunction"
    send(at, choice_id="single", revision_count=1)
    send(at, raw_value="50")
    assert "ご協力ありがとうございました" in _text(at)
    revised = [r for r in SqliteRepository(db).read_table("trials") if r["attempt"] == "revised"]
    assert sorted(r["is_correct"] for r in revised) == [True, True]
    assert {r["time_limit_sec"] for r in revised} == {None}
