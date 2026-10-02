"""AppTest による画面フローの検証（参加者が実際に操作する経路）。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cogexp.domain.clock import FakeClock
from cogexp.storage.repository import SqliteRepository
from tests.conftest import MakeExperiments

APP = Path(__file__).resolve().parents[2] / "app" / "main.py"
TEST_CLOCK = "_test_clock"  # app/state.py と一致させる

Setup = Callable[..., Path]


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make_experiments: MakeExperiments
) -> Setup:
    def _setup(**kwargs: object) -> Path:
        monkeypatch.setenv("COGEXP_EXPERIMENTS_DIR", str(make_experiments(**kwargs)))
        monkeypatch.setenv("COGEXP_DATA_DIR", str(tmp_path / "data"))
        return tmp_path / "data" / "cogexp.sqlite"

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


def test_complete_flow(setup: Setup) -> None:
    db = setup()
    at = _to_first_trial(_start())
    # 練習1（選択）→ 確信度
    at.radio[0].set_value("apple").run()
    _click(at, "回答する")
    at.radio[0].set_value(4).run()
    _click(at, "次へ")
    # 練習2（数値）→ 確信度 → 遷移画面
    at.text_input[0].input("７").run()
    _click(at, "回答する")
    at.radio[0].set_value(5).run()
    _click(at, "次へ")
    assert "練習は以上です" in _text(at)
    _click(at, "次へ")
    # 本課題
    at.radio[0].set_value("conjunction").run()
    _click(at, "回答する")
    at.radio[0].set_value(2).run()
    _click(at, "次へ")
    at.text_input[0].input("100").run()
    _click(at, "回答する")
    at.radio[0].set_value(3).run()
    _click(at, "次へ")

    assert not at.exception
    assert "ご協力ありがとうございました" in _text(at)
    repo = SqliteRepository(db)
    assert repo.read_table("participants")[0]["status"] == "completed"
    trials = sorted(repo.read_table("trials"), key=lambda r: int(str(r["presentation_order"])))
    assert [t["is_correct"] for t in trials] == [True, True, False, False]
    assert [t["confidence"] for t in trials] == [4, 5, 2, 3]


def test_numeric_input_submits_on_enter(setup: Setup) -> None:
    """数値入力欄がフォーム内にあること（ブラウザは Enter でフォームを送信する）。"""
    setup(practice=(), variants=("bat_ball/standard@1",))
    at = _to_first_trial(_start())
    [field] = at.text_input
    [submit] = [b for b in at.button if b.label == "回答する"]
    assert field.form_id and field.form_id == submit.form_id


def test_invalid_numeric_is_not_saved(setup: Setup) -> None:
    db = setup(practice=(), variants=("bat_ball/standard@1",))
    at = _to_first_trial(_start())
    at.text_input[0].input("ごじゅう").run()
    _click(at, "回答する")
    assert any("数字で入力" in w.value for w in at.warning)
    assert SqliteRepository(db).read_table("trials") == []


def test_timeout_advances_without_answer(setup: Setup) -> None:
    db = setup(time_limit_sec=15, show_countdown=True, practice=())
    clock = FakeClock()
    at = _to_first_trial(_start(clock))
    assert any("残り 15 秒" in (p.proto.text or "") for p in at.get("progress"))
    clock.advance_ms(15_000)
    at.run()
    assert not at.exception
    [t] = SqliteRepository(db).read_table("trials")
    assert (t["outcome"], t["is_correct"]) == ("timeout", None)
    # 確信度を飛ばして次の問題へ
    assert at.caption[0].value == "問題 2 / 2"
