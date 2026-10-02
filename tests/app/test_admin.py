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
