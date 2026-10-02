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


def client_payload(trial_id: str, kind: str = "submit", **overrides: object) -> dict[str, object]:
    """問題画面の部品がブラウザから送る値（tests/domain/test_client_log.py と同じ形）。"""
    base: dict[str, object] = {
        "kind": kind,
        "trial_id": trial_id,
        "choice_id": None,
        "raw_value": None,
        "shown_ms": 1000.0,
        "sent_ms": 3500.0,
        "revision_count": 0,
        "client": {
            "browser": "chrome",
            "os": "windows",
            "pointer_types": ["mouse"],
            "viewport_w": 1280,
            "viewport_h": 720,
            "panel_w": 700,
            "panel_h": 400,
            "dpr": 1.0,
        },
        "events": [
            {"t": 1001.0, "type": "layout", "payload": {"rects": {"submit": [0, 0.8, 0.2, 0.9]}}},
            {"t": 1200.0, "type": "move", "x": 0.2, "y": 0.3},
            {"t": 1300.0, "type": "move", "x": 0.4, "y": 0.5},
            {"t": 3400.0, "type": "pointerdown", "x": 0.1, "y": 0.85, "target": "submit"},
        ],
    }
    return base | overrides
