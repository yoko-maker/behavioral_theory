"""Claude Code の PostToolUse フック：編集された .py ファイルを ruff で整形する。

stdin に渡される JSON の tool_input.file_path を対象にする。整形の失敗で作業を止めない。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        file_path = Path(payload["tool_input"]["file_path"])
    except (ValueError, KeyError, TypeError):
        return 0
    if file_path.suffix != ".py" or not file_path.exists():
        return 0
    subprocess.call([sys.executable, "-m", "ruff", "format", "--quiet", str(file_path)])
    subprocess.call(
        [sys.executable, "-m", "ruff", "check", "--fix", "--quiet", "--exit-zero", str(file_path)]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
