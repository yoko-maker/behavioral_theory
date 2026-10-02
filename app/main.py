"""Streamlit エントリポイント。

フェーズ1の参加者フローは docs/plans/phase1_mvp.md の M3 で実装する。
現時点では実験定義の読み込みのみを行うプレースホルダ。
"""

from __future__ import annotations

import streamlit as st

from cogexp.config.loader import load_catalog

st.set_page_config(page_title="認知課題", layout="centered")

catalog = load_catalog()

st.title("認知課題")
st.write("準備中です。")
st.caption(
    f"読み込んだ実験定義: {len(catalog.experiments)} 件 / 問題の版: {len(catalog.variants)} 件"
)
