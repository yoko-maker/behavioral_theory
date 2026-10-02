"""レイヤ間の依存ルールと、時刻・乱数の取得箇所を検査する。

Codex の ``verify_tui_core_boundary.py`` と同じ考え方で、AGENTS.md の文章ルールを
機械的に強制する。エラーには必ず「対処」を書き、エージェントが自力で直せるようにする。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("src", "app")


@dataclass(frozen=True)
class ImportRule:
    rule_id: str
    scope: str  # ROOT からの相対パス接頭辞（posix）
    forbidden: tuple[str, ...]  # 禁止するモジュール接頭辞
    remedy: str


IMPORT_RULES: tuple[ImportRule, ...] = (
    ImportRule(
        "domain-purity",
        "src/cogexp/domain/",
        (
            "streamlit",
            "pandas",
            "numpy",
            "plotly",
            "yaml",
            "sqlite3",
            "cogexp.config",
            "cogexp.storage",
            "cogexp.analysis",
        ),
        "domain は標準ライブラリと pydantic のみに依存する。I/O や UI が必要な処理は "
        "config/storage/app 側に置き、domain には値を引数で渡す。",
    ),
    ImportRule(
        "no-ui-in-core",
        "src/cogexp/",
        ("streamlit",),
        "streamlit を使う処理は app/ に移す。コア層は UI なしでテストできる状態を保つ。",
    ),
    ImportRule(
        "storage-independent",
        "src/cogexp/storage/",
        ("cogexp.analysis", "cogexp.config"),
        "storage は保存のみを担う。集計は analysis、設定読込は config から"
        "呼び出し側で組み合わせる。",
    ),
    ImportRule(
        "app-uses-repository",
        "app/",
        ("sqlite3", "csv"),
        "app/ から直接ファイル・DB に書かない。cogexp.storage のリポジトリ関数を追加して呼ぶ。",
    ),
)

# 現在時刻の直接取得。domain/clock.py 以外では Clock を注入して使う
WALL_CLOCK_CALLS = frozenset(
    {
        "time.time",
        "time.time_ns",
        "time.perf_counter",
        "time.monotonic",
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "date.today",
    }
)
CLOCK_ALLOWED = frozenset({"src/cogexp/domain/clock.py"})

# 乱数は seed を保存できる割当モジュールに閉じ込める
RANDOM_MODULES = ("random", "numpy.random")
RANDOM_ALLOWED = frozenset({"src/cogexp/domain/assignment.py"})


def _module_of(rel: str) -> list[str]:
    parts = Path(rel).with_suffix("").parts
    if parts[0] == "src":
        parts = parts[1:]
    return list(parts)


def _resolve(rel: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    base = _module_of(rel)[: -node.level]
    return ".".join([*base, node.module] if node.module else base)


def _imports(rel: str, tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve(rel, node)
            found.append((node.lineno, module))
            # `from numpy import random` のような形も検出する
            found.extend((node.lineno, f"{module}.{alias.name}") for alias in node.names)
    return found


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def check_file(rel: str, source: str) -> list[str]:
    tree = ast.parse(source, filename=rel)
    errors: list[str] = []

    for lineno, module in _imports(rel, tree):
        for rule in IMPORT_RULES:
            if rel.startswith(rule.scope) and any(_matches(module, f) for f in rule.forbidden):
                errors.append(
                    f"{rel}:{lineno}: [{rule.rule_id}] '{module}' は import 禁止\n"
                    f"    対処: {rule.remedy}"
                )
        if rel not in RANDOM_ALLOWED and any(_matches(module, m) for m in RANDOM_MODULES):
            errors.append(
                f"{rel}:{lineno}: [seeded-random] '{module}' は割当モジュール以外で使えない\n"
                "    対処: 乱数が必要な処理は src/cogexp/domain/assignment.py に seed を引数に取る"
                "関数として置き、seed を participants.assignment_seed に保存する。"
            )

    if rel not in CLOCK_ALLOWED:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name in WALL_CLOCK_CALLS:
                    errors.append(
                        f"{rel}:{node.lineno}: [injected-clock] '{name}()' の直接呼び出し\n"
                        "    対処: cogexp.domain.clock.Clock を引数で受け取り clock.now() / "
                        "clock.monotonic_ms() を使う（テストでは FakeClock を渡す）。"
                    )
    return errors


def run(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for top in SCAN_DIRS:
        for path in sorted((root / top).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            errors.extend(check_file(rel, path.read_text(encoding="utf-8")))
    return errors


def main() -> int:
    errors = run()
    for e in errors:
        print(e)
    print(f"architecture: {'OK' if not errors else f'{len(errors)} 件の違反'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
