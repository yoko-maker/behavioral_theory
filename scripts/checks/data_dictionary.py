"""保存スキーマ（storage/schema.py）とデータ辞書（docs/data_dictionary.md）の同期を検査する。

あわせて、直接識別情報に見える列名がスキーマに入っていないことを確認する。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from cogexp.storage.schema import FORBIDDEN_COLUMN_PATTERNS, TABLES, Column

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = ROOT / "docs" / "data_dictionary.md"

_HEADING = re.compile(r"^##\s+`?(?P<table>\w+)`?\s*$")
_ROW = re.compile(
    r"^\|\s*`(?P<name>\w+)`\s*\|\s*(?P<dtype>\w+)\s*\|\s*(?P<nullable>可|不可)\s*\|(?P<desc>.*)\|\s*$"
)


def parse_dictionary(text: str) -> dict[str, dict[str, Column]]:
    tables: dict[str, dict[str, Column]] = {}
    current: str | None = None
    for line in text.splitlines():
        if h := _HEADING.match(line):
            current = h["table"] if h["table"] in TABLES else None
            if current is not None:
                tables.setdefault(current, {})
            continue
        if current is not None and (r := _ROW.match(line)):
            if not r["desc"].strip():
                raise ValueError(f"{current}.{r['name']}: 説明が空")
            tables[current][r["name"]] = Column(r["name"], r["dtype"], r["nullable"] == "可")
    return tables


def run(dictionary: Path = DICTIONARY) -> list[str]:
    errors: list[str] = []
    remedy = "    対処: docs/data_dictionary.md の該当表を storage/schema.py と一致させる。"

    for table, columns in TABLES.items():
        for col in columns:
            lowered = col.name.lower()
            if any(p in lowered for p in FORBIDDEN_COLUMN_PATTERNS):
                errors.append(
                    f"schema.py: {table}.{col.name} は直接識別情報の可能性がある列名\n"
                    "    対処: 分析データに直接識別情報を入れない。"
                    "必要なら別管理の対応表として設計し、ユーザーに確認する。"
                )

    try:
        documented = parse_dictionary(dictionary.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [*errors, f"data_dictionary.md: 読み込み失敗: {exc}\n{remedy}"]

    for table, columns in TABLES.items():
        doc = documented.get(table)
        if doc is None:
            errors.append(f"data_dictionary.md: '## {table}' の節がない\n{remedy}")
            continue
        for col in columns:
            d = doc.get(col.name)
            if d is None:
                errors.append(f"data_dictionary.md: {table}.{col.name} の記載がない\n{remedy}")
            elif d != col:
                errors.append(
                    f"data_dictionary.md: {table}.{col.name} の型/欠損が不一致 "
                    f"(schema: {col.dtype}/{'可' if col.nullable else '不可'}, "
                    f"doc: {d.dtype}/{'可' if d.nullable else '不可'})\n{remedy}"
                )
        schema_names = {c.name for c in columns}
        for name in sorted(doc.keys() - schema_names):
            errors.append(f"data_dictionary.md: {table}.{name} はスキーマに存在しない\n{remedy}")
    return errors


def main() -> int:
    errors = run()
    for e in errors:
        print(e)
    print(f"data-dictionary: {'OK' if not errors else f'{len(errors)} 件の違反'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
