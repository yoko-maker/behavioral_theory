"""ハーネスの構造チェック自体のテスト。

チェックが「何も検出しなくなる」退行を防ぐため、違反例を与えて検出されることを確認する。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.checks import architecture, data_dictionary, experiments

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("rel", "source", "rule"),
    [
        ("src/cogexp/domain/x.py", "import streamlit as st\n", "domain-purity"),
        ("src/cogexp/domain/x.py", "from ..storage import schema\n", "domain-purity"),
        ("src/cogexp/analysis/x.py", "import streamlit\n", "no-ui-in-core"),
        ("app/x.py", "import sqlite3\n", "app-uses-repository"),
        ("app/x.py", "import time\nt = time.time()\n", "injected-clock"),
        (
            "src/cogexp/analysis/x.py",
            "from datetime import datetime\nd = datetime.now()\n",
            "injected-clock",
        ),
        ("src/cogexp/domain/flow.py", "import random\n", "seeded-random"),
    ],
)
def test_architecture_detects(rel: str, source: str, rule: str) -> None:
    errors = architecture.check_file(rel, source)
    assert any(f"[{rule}]" in e for e in errors), errors


def test_architecture_allows_clock_and_assignment() -> None:
    assert architecture.check_file("src/cogexp/domain/clock.py", "import time\ntime.time()\n") == []
    assert architecture.check_file("src/cogexp/domain/assignment.py", "import random\n") == []


def test_repository_passes_architecture() -> None:
    assert architecture.run() == []


@pytest.fixture
def experiments_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "experiments"
    shutil.copytree(REPO / "experiments", dst)
    return dst


def test_experiments_lock_detects_rewrite(experiments_copy: Path) -> None:
    assert experiments.run(experiments_copy) == []
    path = experiments_copy / "tasks" / "bat_ball.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("1,100円", "1,200円"), "utf-8")
    errors = experiments.run(experiments_copy)
    assert any("既存のロックと異なる" in e for e in errors), errors
    # 書き換えがある間はロックを更新しない
    assert experiments.update_lock(experiments_copy) != []


def test_experiments_lock_detects_deletion(experiments_copy: Path) -> None:
    lock_path = experiments_copy / experiments.LOCK_NAME
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["linda/removed@1"] = "0" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert any("削除されている" in e for e in experiments.run(experiments_copy))


def test_data_dictionary_detects_missing_column(tmp_path: Path) -> None:
    text = (REPO / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    broken = "\n".join(line for line in text.splitlines() if "`outcome`" not in line)
    path = tmp_path / "dd.md"
    path.write_text(broken, encoding="utf-8")
    errors = data_dictionary.run(path)
    assert any("trials.outcome の記載がない" in e for e in errors), errors


def test_repository_passes_data_dictionary() -> None:
    assert data_dictionary.run() == []
