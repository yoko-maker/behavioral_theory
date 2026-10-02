from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import MakeExperiments


def _admin_page() -> None:
    import sys
    from pathlib import Path

    app_dir = Path.cwd() / "app"
    sys.path.insert(0, str(app_dir))
    import admin

    admin.render()


@pytest.fixture(autouse=True)
def _env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make_experiments: MakeExperiments
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    monkeypatch.setenv("COGEXP_EXPERIMENTS_DIR", str(make_experiments()))
    monkeypatch.setenv("COGEXP_DATA_DIR", str(tmp_path / "data"))


def test_admin_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGEXP_ADMIN_PASSWORD", "secret")
    at = AppTest.from_function(_admin_page, default_timeout=30).run()
    assert not at.get("download_button")
    at.text_input[0].input("wrong").run()
    at.button[0].click().run()
    assert at.error
    at.text_input[0].input("secret").run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.get("download_button")) == 4


def test_admin_disabled_without_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COGEXP_ADMIN_PASSWORD", raising=False)
    at = AppTest.from_function(_admin_page, default_timeout=30)
    # 手元の .streamlit/secrets.toml に左右されないよう、空のパスワードを明示する
    at.secrets["admin_password"] = ""
    at.run()
    assert any("未設定" in w.value for w in at.warning)


def test_toggle_accepting_is_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cogexp.storage.repository import SqliteRepository

    monkeypatch.setenv("COGEXP_ADMIN_PASSWORD", "secret")
    at = AppTest.from_function(_admin_page, default_timeout=30).run()
    at.text_input[0].input("secret").run()
    at.button[0].click().run()
    [start] = [b for b in at.button if b.label == "受付を開始する"]
    start.click().run()
    repo = SqliteRepository(tmp_path / "data" / "cogexp.sqlite")
    assert repo.is_accepting("test_exp")
    [stop] = [b for b in at.button if b.label == "受付を停止する"]
    stop.click().run()
    assert not repo.is_accepting("test_exp")
    assert len(repo.read_table("experiment_status_log")) == 2


def test_log_tab_renders_with_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os

    from cogexp.config.loader import load_catalog
    from cogexp.domain.clock import FakeClock
    from cogexp.service import ParticipantService, ParticipantSession
    from cogexp.storage.repository import SqliteRepository
    from tests.conftest import client_payload, open_experiment

    repo = SqliteRepository(tmp_path / "data" / "cogexp.sqlite")
    open_experiment(repo)
    svc = ParticipantService(
        load_catalog(Path(os.environ["COGEXP_EXPERIMENTS_DIR"])), repo, FakeClock()
    )
    s = ParticipantSession(experiment_id="test_exp")
    svc.start(s)
    svc.agree(s)
    svc.proceed(s)
    svc.ensure_shown(s)
    assert s.active is not None
    svc.handle_client(s, client_payload(s.active.trial_id, choice_id="apple"))

    monkeypatch.setenv("COGEXP_ADMIN_PASSWORD", "secret")
    at = AppTest.from_function(_admin_page, default_timeout=30).run()
    at.text_input[0].input("secret").run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.get("plotly_chart")) == 2  # 1試行の軌跡・重ね合わせ
    at.slider(key=f"log_upto_{s.last_trial_id}").set_value(250).run()
    assert not at.exception


def test_analysis_tab_renders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, make_experiments: MakeExperiments
) -> None:
    from cogexp.config.loader import load_catalog
    from cogexp.domain.clock import FakeClock
    from cogexp.domain.flow import Stage
    from cogexp.service import ParticipantService, ParticipantSession
    from cogexp.storage.repository import SqliteRepository
    from tests.conftest import client_payload, open_experiment

    root = make_experiments(factors={"wording": "standard", "time_limit": "none"})
    monkeypatch.setenv("COGEXP_EXPERIMENTS_DIR", str(root))
    repo = SqliteRepository(tmp_path / "data" / "cogexp.sqlite")
    open_experiment(repo)
    svc = ParticipantService(load_catalog(root), repo, FakeClock())
    answers = {
        "practice/choice@1": {"choice_id": "apple"},
        "practice/numeric@1": {"raw_value": "7"},
        "linda/standard@1": {"choice_id": "single"},
        "bat_ball/standard@1": {"raw_value": "100"},
    }
    s = ParticipantSession(experiment_id="test_exp")
    svc.start(s)
    svc.agree(s)
    while s.flow.stage is not Stage.END:
        if s.flow.stage is Stage.TRIAL:
            svc.ensure_shown(s)
            item, _ = svc.current(s)
            assert s.active is not None
            svc.handle_client(s, client_payload(s.active.trial_id, **answers[str(item.ref)]))
        elif s.flow.stage is Stage.CONFIDENCE:
            svc.handle_confidence(s, client_payload(svc.confidence_screen_id(s), choice_id="4"))
        else:
            svc.proceed(s)

    monkeypatch.setenv("COGEXP_ADMIN_PASSWORD", "secret")
    at = AppTest.from_function(_admin_page, default_timeout=60).run()
    at.text_input[0].input("secret").run()
    at.button[0].click().run()
    assert not at.exception
    texts = " ".join(m.value for m in at.markdown)
    assert "問題：linda" in " ".join(h.value for h in at.subheader)
    assert "正答率・時間切れ率" in texts
    # 要因の水準が1つしかないため回帰は推定できない旨を表示する（例外で止まらない）
    assert any("推定できない" in c.value for c in at.caption)
