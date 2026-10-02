"""st.session_state のキーを一か所で定義する（app/AGENTS.md）。"""

from __future__ import annotations

from typing import Final

# 参加者セッション（cogexp.service.ParticipantSession）
SESSION: Final = "participant_session"
# テスト用：FakeClock を注入するためのキー（本番では設定しない）
TEST_CLOCK: Final = "_test_clock"
# 実験者画面の認証済みフラグ
ADMIN_AUTHED: Final = "admin_authed"
