"""Streamlit エントリポイント。

- 参加者画面: ``/``（複数の実験定義がある場合は ``/?exp=<experiment_id>``）
- 実験者画面: ``/admin``（ナビゲーションには表示しない。パスワード保護）
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run app/main.py` で app/ 内のモジュールを import できるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent))

import admin
import participant
import streamlit as st

st.set_page_config(page_title="認知課題", layout="centered")

page = st.navigation(
    [
        st.Page(participant.render, title="認知課題", default=True),
        st.Page(admin.render, title="実験者画面", url_path="admin"),
    ],
    position="hidden",
)
page.run()
