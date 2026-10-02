"""問題画面の部品（JavaScript）とサーバー側の取り決めが一致していることの検査。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cogexp.domain.client_log import EVENT_TYPES
from cogexp.domain.scoring import parse_numeric

JS = Path(__file__).resolve().parents[2] / "app" / "components" / "trial_panel.js"

CASES = [
    "50",
    "５０",
    "1,100",
    "50円",
    "-3.5",
    "+7",
    ".5",
    "5.",
    " 42 ",
    "−8",
    "",
    "abc",
    "5 0x",
    "nan",
    "inf",
    "1e3",
    "--1",
    "1.2.3",
    "５０ 円",
]


def test_event_types_are_allowed_by_server() -> None:
    source = JS.read_text(encoding="utf-8")
    emitted = set(re.findall(r'push\("(\w+)"', source)) | set(re.findall(r'send\("(\w+)"', source))
    assert emitted, "イベント種別を抽出できない（JS の書き方が変わった）"
    assert emitted <= EVENT_TYPES, f"サーバーの許可リストにない種別: {emitted - EVENT_TYPES}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js がない")
def test_numeric_parsing_matches_server(tmp_path: Path) -> None:
    module = tmp_path / "trial_panel.mjs"
    module.write_text(JS.read_text(encoding="utf-8"), encoding="utf-8")
    script = (
        "globalThis.window = {};"
        f"const m = await import({json.dumps(module.as_uri())});"
        f"const cases = {json.dumps(CASES, ensure_ascii=False)};"
        "console.log(JSON.stringify(cases.map((c) => m.parseNumeric(c))));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    from_js = json.loads(out.stdout)
    from_py = [parse_numeric(c) for c in CASES]
    assert from_js == from_py, list(zip(CASES, from_js, from_py, strict=True))
