from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from cogexp.domain.clock import FakeClock
from cogexp.service import ExperimenterService
from cogexp.storage.repository import SqliteRepository

REPO_EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"

MakeExperiments = Callable[..., Path]


@pytest.fixture
def make_experiments(tmp_path: Path) -> MakeExperiments:
    """リポジトリの experiments/ を複製し、条件を1つに絞った実験セットを作る。

    条件割当の乱数に依存せず、特定の条件でフローを検証するために使う。
    """

    def _make(
        *,
        time_limit_sec: float | None = None,
        show_countdown: bool = False,
        collect_confidence: bool = True,
        allow_revision: bool = False,
        counterbalance_order: bool = False,
        variants: tuple[str, ...] = ("linda/standard@1", "bat_ball/standard@1"),
        practice: tuple[str, ...] = ("practice/choice@1", "practice/numeric@1"),
    ) -> Path:
        root = tmp_path / "experiments"
        shutil.copytree(REPO_EXPERIMENTS, root, dirs_exist_ok=True)
        for p in root.glob("*.yaml"):
            p.unlink()
        exp = {
            "experiment_id": "test_exp",
            "title": "テスト",
            "practice": list(practice),
            "counterbalance_order": counterbalance_order,
            "conditions": [
                {
                    "condition_id": "only",
                    "time_limit_sec": time_limit_sec,
                    "show_countdown": show_countdown,
                    "collect_confidence": collect_confidence,
                    "allow_revision": allow_revision,
                    "variants": list(variants),
                }
            ],
        }
        (root / "test_exp.yaml").write_text(yaml.safe_dump(exp, allow_unicode=True), "utf-8")
        return root

    return _make


def open_experiment(repo: SqliteRepository, experiment_id: str = "test_exp") -> None:
    """受付を開始する（既定は受付停止）。"""
    ExperimenterService(repo, FakeClock()).set_accepting(experiment_id, True)
