"""実験者画面（概要書 §9）。パスワードで保護し、参加者フローからは到達できない URL に置く。

条件そのものの変更は YAML で行う（版管理のため）。この画面では閲覧と受付の開始・停止のみ行う。
"""

from __future__ import annotations

import hmac
import json

import charts
import pandas as pd
import resources
import state
import streamlit as st

from cogexp.analysis.summary import (
    answer_distribution,
    cell_summary,
    condition_summary,
    participation_summary,
    revision_crosstab,
    revision_summary,
    to_csv_bytes,
    to_frame,
    variant_summary,
)
from cogexp.analysis.trajectory import (
    choice_metrics,
    confidence_metrics,
    layout_of,
    log_quality,
    moves_of,
    numeric_metrics,
    phase_events,
)
from cogexp.config.loader import Catalog
from cogexp.domain.assignment import cells
from cogexp.storage.repository import SqliteRepository


def _login(password: str) -> bool:
    if st.session_state.get(state.ADMIN_AUTHED):
        return True
    # フォームにして、パスワード欄で Enter を押してもログインできるようにする
    with st.form("admin_login_form"):
        entered = st.text_input("パスワード", type="password", key="admin_pw")
        submitted = st.form_submit_button("ログイン")
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
            st.session_state[state.ADMIN_AUTHED] = True
            st.rerun()
        st.error("パスワードが違います。")
    return False


def _status_tab(participants: pd.DataFrame, trials: pd.DataFrame, events: pd.DataFrame) -> None:
    summary = participation_summary(participants)
    for col, (label, value) in zip(st.columns(len(summary)), summary.items(), strict=True):
        col.metric(label, value)

    st.subheader("条件別（練習を除く・初回回答）")
    st.caption("正答率の分母は判定可能な回答。時間切れは誤答に含めず、時間切れ率として示す。")
    st.dataframe(condition_summary(trials), hide_index=True)

    st.subheader("問題・版別")
    st.dataframe(variant_summary(trials), hide_index=True)

    st.subheader("回答分布")
    st.dataframe(answer_distribution(trials), hide_index=True)

    st.subheader("エクスポート")
    st.caption("生データ（練習・見直しを含む）。直接識別情報は保存していない。")
    for col, (name, df) in zip(
        st.columns(3),
        [("participants", participants), ("trials", trials), ("events", events)],
        strict=True,
    ):
        col.download_button(
            f"{name}.csv",
            data=to_csv_bytes(df),
            file_name=f"{name}.csv",
            mime="text/csv",
            key=f"dl_{name}",
        )


def _revision_tab(trials: pd.DataFrame) -> None:
    st.caption("見直しあり条件のみ。同一参加者の初回回答と見直し後の回答を対にしている。")
    st.subheader("回答変化率")
    st.dataframe(revision_summary(trials), hide_index=True)
    st.subheader("初回 × 見直し後（正誤）")
    st.dataframe(revision_crosstab(trials))


def _trial_label(t: pd.Series) -> str:
    attempt = "見直し" if t["attempt"] == "revised" else "初回"
    return (
        f"{str(t['participant_id'])[:6]} / {t['presentation_order']}. "
        f"{t['task_id']}/{t['variant_id']} / {attempt} / {t['outcome']}"
    )


def _answer_label(t: pd.Series) -> str:
    if t["outcome"] != "answered":
        return f"（{t['outcome']}）"
    if pd.notna(t["choice_id"]):
        return str(t["choice_id"])
    return f"{t['response_value']:g}"


def _aspect(t: pd.Series) -> float:
    w, h = t["panel_w"], t["panel_h"]
    return float(h) / float(w) if pd.notna(w) and pd.notna(h) and w else 0.6


def _log_tab(trials: pd.DataFrame, events: pd.DataFrame) -> None:
    st.caption(
        "マウス軌跡は視線や思考を直接表すものではない（概要書 §6.4）。"
        "指標の定義は docs/plans/phase3.md。"
    )
    st.subheader("ログ取得状況")
    st.dataframe(log_quality(trials), hide_index=True)

    ok = trials[trials["client_log_status"] == "ok"].sort_values("shown_at_server")
    if ok.empty:
        st.info("操作ログのある試行はまだありません。")
        return

    keys = [
        "trial_id",
        "participant_id",
        "condition_id",
        "presentation_order",
        "task_id",
        "variant_id",
        "attempt",
        "outcome",
        "choice_id",
        "response_value",
        "pointer_types",
    ]

    st.subheader("選択式：マウス軌跡の指標")
    choice_table = ok[keys].merge(choice_metrics(ok, events), on="trial_id")
    choice_table["participant_id"] = choice_table["participant_id"].str[:6]
    st.dataframe(choice_table.drop(columns=["trial_id", "response_value"]), hide_index=True)

    st.subheader("数値入力式：キー操作の時間の指標")
    st.caption(
        "数値入力式ではカーソルは入力欄に向かうだけなので、軌跡ではなくキー操作の時間を見る。"
    )
    numeric_table = ok[keys].merge(numeric_metrics(ok, events), on="trial_id")
    numeric_table["participant_id"] = numeric_table["participant_id"].str[:6]
    st.dataframe(numeric_table.drop(columns=["trial_id", "choice_id"]), hide_index=True)

    st.subheader("確信度の画面の指標")
    st.caption(
        "確信度を決めるまでの時間・選び直し・他の段階への出入りは迷いと関係しうる手がかりで、"
        "迷いそのものではない。"
    )
    conf_table = ok[keys].merge(confidence_metrics(ok, events), on="trial_id")
    conf_table["participant_id"] = conf_table["participant_id"].str[:6]
    st.dataframe(conf_table.drop(columns=["trial_id", "pointer_types"]), hide_index=True)

    # 以降の軌跡の図は回答の画面・選択式のみ
    events = phase_events(events, "answer")
    ok = ok[ok["response_format"] == "choice"]
    if ok.empty:
        st.info("操作ログのある選択式の試行はまだありません。")
        return

    st.subheader("軌跡（選択式・1試行）")
    labels = {r["trial_id"]: _trial_label(r) for _, r in ok.iterrows()}
    trial_id = st.selectbox("試行", list(labels), format_func=labels.__getitem__, key="log_trial")
    t = ok[ok["trial_id"] == trial_id].iloc[0]
    trial_events = events[events["trial_id"] == trial_id]
    moves = moves_of(events, trial_id)
    clicks = trial_events[trial_events["event_type"] == "pointerdown"].dropna(
        subset=["x_norm", "y_norm"]
    )
    shown = float(t["shown_at_client_ms"])
    end = float(trial_events["t_client_ms"].max()) - shown if len(trial_events) else 0.0
    upto = st.slider(
        "表示開始からの時間（ms）までを表示（動かすと再生）",
        0,
        max(int(end), 1),
        max(int(end), 1),
        step=100,
        key=f"log_upto_{trial_id}",
    )
    st.plotly_chart(
        charts.trajectory_figure(
            moves, clicks, layout_of(events, trial_id), shown, upto, _aspect(t)
        ),
        width="stretch",
        theme=None,  # 検証済みの配色を Streamlit のテーマで上書きさせない
    )

    st.subheader("軌跡の重ね合わせ（回答別）")
    tasks = sorted({(r["task_id"], r["variant_id"], r["attempt"]) for _, r in ok.iterrows()})
    task = st.selectbox(
        "問題・版",
        tasks,
        format_func=lambda k: f"{k[0]}/{k[1]}（{'見直し' if k[2] == 'revised' else '初回'}）",
        key="log_overlay_task",
    )
    subset = ok[
        (ok["task_id"] == task[0]) & (ok["variant_id"] == task[1]) & (ok["attempt"] == task[2])
    ]
    conditions = sorted(subset["condition_id"].unique())
    chosen = st.multiselect("条件", conditions, default=conditions, key="log_overlay_cond")
    subset = subset[subset["condition_id"].isin(chosen)]
    if subset.empty:
        st.info("該当する試行がありません。")
        return
    by_answer: dict[str, list[pd.DataFrame]] = {}
    for _, r in subset.iterrows():
        by_answer.setdefault(_answer_label(r), []).append(moves_of(events, r["trial_id"]))
    groups = sorted(by_answer.items(), key=lambda kv: -len(kv[1]))
    first = subset.iloc[0]
    st.plotly_chart(
        charts.overlay_figure(groups, layout_of(events, first["trial_id"]), _aspect(first)),
        width="stretch",
        theme=None,  # 検証済みの配色を Streamlit のテーマで上書きさせない
    )
    st.caption("要素の枠は1件目の試行の配置。画面の大きさにより試行ごとに多少ずれる。")


def _settings_tab(catalog: Catalog, repo: SqliteRepository, participants: pd.DataFrame) -> None:
    st.caption("条件の変更は experiments/ の YAML で行う（docs/plans/phase2.md）。")
    svc = resources.experimenter_service()
    for exp_id, exp in catalog.experiments.items():
        st.subheader(f"{exp.title}（{exp_id}）")
        accepting = repo.is_accepting(exp_id)
        left, right = st.columns([3, 1])
        left.markdown(f"受付状態：**{'受付中' if accepting else '停止中'}**")
        right.button(
            "受付を停止する" if accepting else "受付を開始する",
            key=f"toggle_{exp_id}",
            type="secondary" if accepting else "primary",
            on_click=svc.set_accepting,
            args=(exp_id, not accepting),
        )
        log = to_frame("experiment_status_log", repo.read_table("experiment_status_log"))
        log = log[log["experiment_id"] == exp_id].sort_values("changed_at", ascending=False)
        with st.expander("受付の切替履歴"):
            st.dataframe(log[["changed_at", "accepting"]], hide_index=True)

        st.markdown("**条件**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "condition_id": c.condition_id,
                        "制限時間(秒)": c.time_limit_sec,
                        "残り時間表示": c.show_countdown,
                        "確信度": c.collect_confidence,
                        "見直し": c.allow_revision,
                        "問題": ", ".join(c.variants),
                    }
                    for c in exp.conditions
                ]
            ),
            hide_index=True,
        )
        st.markdown(
            f"練習：{', '.join(exp.practice) or 'なし'} ／ "
            f"出題順の均等化：{'あり' if exp.counterbalance_order else 'なし'} ／ "
            f"放置とみなす時間：{exp.abandon_after_min} 分"
        )

        st.markdown("**セル（条件 × 出題順）別の人数**")
        planned = pd.DataFrame(
            [{"condition_id": c.condition_id, "order_index": c.order_index} for c in cells(exp)]
        )
        counts = cell_summary(participants[participants["experiment_id"] == exp_id])
        merged = planned.merge(counts, how="left", on=["condition_id", "order_index"])
        st.dataframe(merged.fillna(0), hide_index=True)

        refs = sorted(
            {*exp.practice_refs(), *(r for c in exp.conditions for r in c.variant_refs())},
            key=str,
        )
        with st.expander("問題文の版"):
            for ref in refs:
                v = catalog.variant(ref)
                st.markdown(f"**{ref}**（{v.response_format.value}）")
                st.text(v.prompt.strip())
                if v.choices:
                    st.text("選択肢: " + " / ".join(f"{c.id}: {c.text}" for c in v.choices))
        st.download_button(
            f"条件設定・問題文の版（{exp_id}.json）",
            data=json.dumps(catalog.snapshot(exp_id), ensure_ascii=False, indent=2),
            file_name=f"{exp_id}_config.json",
            mime="application/json",
            key=f"dl_config_{exp_id}",
        )


def render() -> None:
    st.title("実験者画面")
    password = resources.admin_password()
    if password is None:
        st.warning(
            "実験者パスワードが未設定です。環境変数 COGEXP_ADMIN_PASSWORD か "
            ".streamlit/secrets.toml の admin_password を設定してください。"
        )
        return
    if not _login(password):
        return

    repo = resources.repository()
    catalog = resources.catalog()
    participants = to_frame("participants", repo.read_table("participants"))
    trials = to_frame("trials", repo.read_table("trials"))
    events = to_frame("events", repo.read_table("events"))

    status_tab, revision_tab, log_tab, settings_tab = st.tabs(
        ["実施状況", "見直し", "操作ログ", "条件設定"]
    )
    with status_tab:
        _status_tab(participants, trials, events)
    with revision_tab:
        _revision_tab(trials)
    with log_tab:
        _log_tab(trials, events)
    with settings_tab:
        _settings_tab(catalog, repo, participants)
