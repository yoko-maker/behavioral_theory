"""実験定義の検証と、問題文バージョンのロック。

``experiments/versions.lock.json`` に ``task/variant@version -> 内容ハッシュ`` を記録し、
既存版の内容が書き換えられていないこと・版が削除されていないことを保証する。
保存済みデータの task_version から、提示した問題文を常に復元できるようにするための仕組み。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cogexp.config.loader import load_catalog

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS = ROOT / "experiments"
LOCK_NAME = "versions.lock.json"


def _read_lock(root: Path) -> dict[str, str]:
    path = root / LOCK_NAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: オブジェクト形式である必要がある")
    return {str(k): str(v) for k, v in data.items()}


def _current_hashes(root: Path) -> dict[str, str]:
    catalog = load_catalog(root)
    return {str(ref): v.content_hash() for ref, v in catalog.variants.items()}


def run(root: Path = EXPERIMENTS) -> list[str]:
    try:
        current = _current_hashes(root)
    except Exception as exc:  # 検証エラーはすべて報告対象
        return [
            f"experiments/: 読み込み・検証に失敗: {exc}\n"
            "    対処: エラー箇所の YAML を修正する。"
            "項目の定義は src/cogexp/domain/models.py を参照。"
        ]

    lock = _read_lock(root)
    errors: list[str] = []
    for key, digest in sorted(current.items()):
        if key not in lock:
            errors.append(
                f"experiments/: {key} がロックに未登録\n"
                "    対処: 内容を確認したうえで `uv run python scripts/dev.py lock` を実行する。"
            )
        elif lock[key] != digest:
            errors.append(
                f"experiments/: {key} の内容が既存のロックと異なる（公開済みの版の書き換え）\n"
                "    対処: この版の内容を元に戻し、変更内容は version を上げた新しいエントリとして"
                "追加する。"
            )
    for key in sorted(lock.keys() - current.keys()):
        errors.append(
            f"experiments/: ロック済みの {key} が YAML から削除されている\n"
            "    対処: 過去の版は削除しない。使わない版は実験定義の参照から外すだけにする。"
        )
    return errors


def update_lock(root: Path = EXPERIMENTS) -> list[str]:
    """未登録の版をロックに追加する。既存版の変更・削除がある場合は何も書かない。"""
    current = _current_hashes(root)
    lock = _read_lock(root)
    conflicts = [e for e in run(root) if "ロックに未登録" not in e]
    if conflicts:
        return conflicts
    added = sorted(current.keys() - lock.keys())
    lock.update({k: current[k] for k in added})
    (root / LOCK_NAME).write_text(
        json.dumps(dict(sorted(lock.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for k in added:
        print(f"lock: 追加 {k}")
    if not added:
        print("lock: 追加なし")
    return []


def main() -> int:
    errors = run()
    for e in errors:
        print(e)
    print(f"experiments: {'OK' if not errors else f'{len(errors)} 件の違反'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
