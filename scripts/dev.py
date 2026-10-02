"""開発コマンドの単一入口（Codex の justfile に相当）。

人間・エージェント・CI が同じコマンドで同じ検証を行うためのもの。
Windows / macOS / Linux で動くよう Python だけで書く。

    uv run python scripts/dev.py <command> [args...]
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.checks import architecture, data_dictionary, experiments  # noqa: E402

PY = sys.executable


def _sh(*cmd: str) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.call(list(cmd), cwd=ROOT)


def fmt(_: list[str]) -> int:
    return _sh(PY, "-m", "ruff", "format", ".") or _sh(PY, "-m", "ruff", "check", "--fix", ".")


def fmt_check(_: list[str]) -> int:
    return _sh(PY, "-m", "ruff", "format", "--check", ".")


def lint(_: list[str]) -> int:
    return _sh(PY, "-m", "ruff", "check", ".")


def typecheck(_: list[str]) -> int:
    return _sh(PY, "-m", "mypy")


def test(args: list[str]) -> int:
    return _sh(PY, "-m", "pytest", *args)


def lock(_: list[str]) -> int:
    errors = experiments.update_lock()
    for e in errors:
        print(e)
    return 1 if errors else 0


def app(args: list[str]) -> int:
    return _sh(PY, "-m", "streamlit", "run", "app/main.py", *args)


def check(_: list[str]) -> int:
    """完了前の必須ゲート。途中で止めずに全項目を実行し、最後に一覧で結果を出す。"""
    steps: list[tuple[str, Callable[[], int]]] = [
        ("fmt-check", lambda: fmt_check([])),
        ("lint", lambda: lint([])),
        ("typecheck", lambda: typecheck([])),
        ("architecture", architecture.main),
        ("experiments", experiments.main),
        ("data-dictionary", data_dictionary.main),
        ("test", lambda: test([])),
    ]
    results: list[tuple[str, int]] = []
    for name, step in steps:
        print(f"\n=== {name} ===", flush=True)
        results.append((name, step()))

    print("\n=== summary ===")
    for name, code in results:
        print(f"  {'PASS' if code == 0 else 'FAIL'}  {name}")
    failed = [n for n, c in results if c != 0]
    if failed:
        print(f"\ncheck: FAIL ({', '.join(failed)})。`dev.py fmt` で直るものは先に実行する。")
        return 1
    print("\ncheck: PASS")
    return 0


COMMANDS: dict[str, tuple[Callable[[list[str]], int], str]] = {
    "fmt": (fmt, "整形と lint の自動修正"),
    "fmt-check": (fmt_check, "整形の確認のみ"),
    "lint": (lint, "ruff lint"),
    "typecheck": (typecheck, "mypy (strict)"),
    "test": (test, "pytest（引数はそのまま渡す）"),
    "check": (check, "完了前の必須ゲート（全検証）"),
    "lock": (lock, "新しい問題文バージョンを versions.lock.json に登録"),
    "app": (app, "Streamlit アプリを起動"),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print("usage: uv run python scripts/dev.py <command> [args...]\n")
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:<10} {desc}")
        return 2
    fn, _ = COMMANDS[argv[0]]
    return fn(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
