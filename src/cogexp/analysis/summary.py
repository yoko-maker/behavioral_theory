"""実験者画面の基本集計（概要書 §9.1）と CSV 出力。

練習試行は集計から除外する。正答率の分母は「判定可能な回答」（is_correct が空でないもの）。
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
        "未完了（中断を含む）": int((status != "completed").sum()),
    }


def _main_trials(trials: pd.DataFrame) -> pd.DataFrame:
    return trials[~trials["is_practice"].astype(bool)]


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


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Excel でも文字化けしないよう BOM 付き UTF-8 で出力する。"""
    return df.to_csv(index=False).encode("utf-8-sig")
