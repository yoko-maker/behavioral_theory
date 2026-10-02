"""アプリ全体で共有する資源（実験定義・保存先・時計・実験者パスワード）。

環境変数:
- COGEXP_EXPERIMENTS_DIR: 実験定義のディレクトリ（既定: リポジトリの experiments/）
- COGEXP_DATA_DIR: 保存先ディレクトリ（既定: リポジトリの data/）
- COGEXP_ADMIN_PASSWORD: 実験者画面のパスワード（.streamlit/secrets.toml の admin_password でも可）
"""

from __future__ import annotations

import os
from pathlib import Path

import state
import streamlit as st

from cogexp.config.loader import Catalog, default_root, load_catalog
from cogexp.domain.clock import Clock, SystemClock
from cogexp.service import ParticipantService
from cogexp.storage.repository import SqliteRepository

ROOT = Path(__file__).resolve().parents[1]


@st.cache_resource
def _catalog(root: str) -> Catalog:
    return load_catalog(Path(root))


@st.cache_resource
def _repository(path: str) -> SqliteRepository:
    return SqliteRepository(Path(path))


def catalog() -> Catalog:
    return _catalog(str(default_root()))


def repository() -> SqliteRepository:
    data_dir = Path(os.environ.get("COGEXP_DATA_DIR", ROOT / "data"))
    return _repository(str(data_dir / "cogexp.sqlite"))


def clock() -> Clock:
    injected = st.session_state.get(state.TEST_CLOCK)
    return injected if injected is not None else SystemClock()


def service() -> ParticipantService:
    return ParticipantService(catalog(), repository(), clock())


def admin_password() -> str | None:
    if pw := os.environ.get("COGEXP_ADMIN_PASSWORD"):
        return pw
    try:
        value = st.secrets.get("admin_password")
    except Exception:  # secrets.toml がない場合
        return None
    return str(value) if value else None
