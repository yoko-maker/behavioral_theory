@AGENTS.md

## Claude Code 固有

- `.py` ファイルの編集後は PostToolUse フックで自動整形される（`scripts/hooks/format_changed.py`）。それでも完了前には `dev.py check` を実行する。
- コードレビューを頼まれたら `.claude/skills/review/SKILL.md` に従う。
- 問題・言い換え版・条件を追加するときは `.claude/skills/add-task-variant/SKILL.md` に従う。
