"""実験者画面の基本集計（概要書 §9.1）と CSV 出力。

練習試行は集計から除外する。条件別・版別の集計は初回回答（attempt=initial）のみを対象にし、
見直し後の回答は ``revision_summary`` で初回回答と対にして扱う。
正答率の分母は「判定可能な回答」（is_correct が空でないもの）。
時間切れは正答率の分母に含めず、時間切れ率として別に示す。
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from cogexp.storage.schema import TABLES

Records = Sequence[dict[str, object]]


def to_frame(table: str, rows: Records) -> pd.DataFrame:
    columns = [c.name for c in TABLES[table]]
    return pd.DataFrame(list(rows), columns=columns)


def participation_summary(participants: pd.DataFrame) -> dict[str, int]:
    status = participants["status"]
    return {
        "参加（同意）": len(participants),
        "完了": int((status == "completed").sum()),
        "中断（再読み込み等）": int((status == "aborted").sum()),
        "進行中・放置": int((status == "in_progress").sum()),
    }


def cell_summary(participants: pd.DataFrame) -> pd.DataFrame:
    """条件 × 出題順（セル）ごとの状態別人数。割当の偏りの確認用。"""
    if participants.empty:
        return pd.DataFrame(
            columns=["condition_id", "order_index", "completed", "aborted", "in_progress"]
        )
    table = pd.crosstab(
        [participants["condition_id"], participants["order_index"]], participants["status"]
    )
    for col in ("completed", "aborted", "in_progress"):
        if col not in table.columns:
            table[col] = 0
    return table[["completed", "aborted", "in_progress"]].reset_index()


def _main_trials(trials: pd.DataFrame) -> pd.DataFrame:
    """本課題の初回回答のみ。"""
    return trials[~trials["is_practice"].astype(bool) & (trials["attempt"] == "initial")]


def _aggregate(trials: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    main = _main_trials(trials).copy()
    if main.empty:
        return pd.DataFrame(
            columns=[
                *keys,
                "試行数",
                "回答数",
                "時間切れ数",
                "時間切れ率",
                "判定可能数",
                "正答率",
                "回答時間中央値_ms",
                "確信度平均",
            ]
        )
    main["answered"] = main["outcome"] == "answered"
    main["timeout"] = main["outcome"] == "timeout"
    main["scorable"] = main["is_correct"].notna()
    main["correct"] = main["is_correct"].eq(True)
    g = main.groupby(keys, dropna=False)
    out = pd.DataFrame(
        {
            "試行数": g.size(),
            "回答数": g["answered"].sum(),
            "時間切れ数": g["timeout"].sum(),
            "判定可能数": g["scorable"].sum(),
            "正答数": g["correct"].sum(),
            "回答時間中央値_ms": g["response_time_ms"].median(),
            "確信度平均": g["confidence"].mean(),
        }
    )
    out["時間切れ率"] = out["時間切れ数"] / out["試行数"]
    out["正答率"] = out["正答数"] / out["判定可能数"].where(out["判定可能数"] > 0)
    cols = [
        "試行数",
        "回答数",
        "時間切れ数",
        "時間切れ率",
        "判定可能数",
        "正答率",
        "回答時間中央値_ms",
        "確信度平均",
    ]
    return out[cols].reset_index()


def condition_summary(trials: pd.DataFrame) -> pd.DataFrame:
    return _aggregate(trials, ["condition_id"])


def variant_summary(trials: pd.DataFrame) -> pd.DataFrame:
    return _aggregate(trials, ["task_id", "variant_id", "task_version", "condition_id"])


def answer_distribution(trials: pd.DataFrame) -> pd.DataFrame:
    """問題・版ごとの回答分布（選択肢ID または 数値）。"""
    main = _main_trials(trials)
    main = main[main["outcome"] == "answered"]
    answer = main["choice_id"].where(main["choice_id"].notna(), main["response_value"].astype(str))
    df = main.assign(answer=answer)
    return (
        df.groupby(["task_id", "variant_id", "task_version", "answer"])
        .size()
        .rename("件数")
        .reset_index()
    )


def _answer_text(df: pd.DataFrame) -> pd.Series:
    text = df["choice_id"].where(df["choice_id"].notna(), df["response_value"].astype(str))
    return text.where(df["outcome"] == "answered", "（" + df["outcome"].astype(str) + "）")


def revision_pairs(trials: pd.DataFrame) -> pd.DataFrame:
    """見直し後の回答と初回回答の対（1行 = 1対）。"""
    revised = trials[trials["attempt"] == "revised"]
    initial = trials[trials["attempt"] == "initial"].set_index("trial_id")
    if revised.empty:
        return pd.DataFrame(
            columns=[
                "condition_id",
                "task_id",
                "variant_id",
                "task_version",
                "初回",
                "見直し後",
                "初回正誤",
                "見直し後正誤",
                "変更",
            ]
        )
    first = initial.loc[revised["initial_trial_id"]]
    out = pd.DataFrame(
        {
            "condition_id": revised["condition_id"].to_numpy(),
            "task_id": revised["task_id"].to_numpy(),
            "variant_id": revised["variant_id"].to_numpy(),
            "task_version": revised["task_version"].to_numpy(),
            "初回": _answer_text(first).to_numpy(),
            "見直し後": _answer_text(revised).to_numpy(),
            "初回正誤": first["is_correct"].to_numpy(),
            "見直し後正誤": revised["is_correct"].to_numpy(),
        }
    )
    out["変更"] = out["初回"] != out["見直し後"]
    return out


def revision_summary(trials: pd.DataFrame) -> pd.DataFrame:
    """条件・版ごとの回答変化率（同一参加者内の初回 → 見直し後）。"""
    pairs = revision_pairs(trials)
    keys = ["condition_id", "task_id", "variant_id", "task_version"]
    if pairs.empty:
        return pd.DataFrame(columns=[*keys, "対の数", "変更数", "回答変化率"])
    g = pairs.groupby(keys)
    out = pd.DataFrame({"対の数": g.size(), "変更数": g["変更"].sum()})
    out["回答変化率"] = out["変更数"] / out["対の数"]
    return out.reset_index()


def revision_crosstab(trials: pd.DataFrame) -> pd.DataFrame:
    """初回正誤 × 見直し後正誤 のクロス集計（判定不能は「判定不能」）。"""
    pairs = revision_pairs(trials)
    label = {True: "正答", False: "誤答"}
    before = pairs["初回正誤"].map(label).fillna("判定不能").rename("初回")
    after = pairs["見直し後正誤"].map(label).fillna("判定不能").rename("見直し後")
    return pd.crosstab(before, after)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Excel でも文字化けしないよう BOM 付き UTF-8 で出力する。"""
    return df.to_csv(index=False).encode("utf-8-sig")
