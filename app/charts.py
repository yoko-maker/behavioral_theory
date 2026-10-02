"""実験者画面の軌跡の図（plotly）。

色は dataviz の参照パレット（検証済み）：軌跡は青、クリックは橙、重ね合わせの回答別は
カテゴリ色の先頭3色（全組み合わせで色覚多様性の基準を満たす）。4つ目以降は「その他」の灰色にまとめる。
文字・軸は色を持たないインク色。y 軸は画面と同じく下向き。
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CATEGORICAL = ("#2a78d6", "#eb6834", "#1baf7a")
OTHER = "#898781"
PATH = CATEGORICAL[0]
CLICK = CATEGORICAL[1]

_LAYOUT_LABELS = {"prompt": "問題文", "submit": "回答する", "input": "入力欄"}


def _base(fig: go.Figure, aspect: float, extent: tuple[float, float, float, float]) -> go.Figure:
    x0, x1, y0, y1 = extent
    axis = {
        "showgrid": True,
        "gridcolor": GRID,
        "gridwidth": 1,
        "zeroline": False,
        "linecolor": AXIS,
        "tickfont": {"color": MUTED},
        "title": {"font": {"color": INK_SECONDARY}},
    }
    fig.update_layout(
        plot_bgcolor=SURFACE,
        paper_bgcolor=SURFACE,
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "color": INK},
        margin={"l": 48, "r": 16, "t": 16, "b": 40},
        height=460,
        legend={"orientation": "h", "y": -0.15, "font": {"color": INK_SECONDARY}},
        hoverlabel={"bgcolor": SURFACE, "font": {"color": INK}},
        xaxis={
            **axis,
            "range": [x0, x1],
            "title": {**axis["title"], "text": "x（問題領域の幅 = 1）"},
        },
        yaxis={
            **axis,
            "range": [y1, y0],  # 画面と同じく下向き
            "title": {**axis["title"], "text": "y（問題領域の高さ = 1）"},
            "scaleanchor": "x",
            "scaleratio": aspect,
        },
    )
    return fig


def _extent(frames: Sequence[pd.DataFrame]) -> tuple[float, float, float, float]:
    xs = [0.0, 1.0] + [v for f in frames for v in f["x_norm"].tolist()]
    ys = [0.0, 1.0] + [v for f in frames for v in f["y_norm"].tolist()]
    pad = 0.05
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


def _layout_shapes(fig: go.Figure, rects: dict[str, list[float]]) -> None:
    for name, (x0, y0, x1, y1) in rects.items():
        label = (
            f"選択肢 {name.split(':', 1)[1]}"
            if name.startswith("choice:")
            else _LAYOUT_LABELS.get(name, name)
        )
        fig.add_shape(
            type="rect",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            line={"color": AXIS, "width": 1},
            fillcolor="rgba(0,0,0,0)",
            layer="below",
        )
        fig.add_annotation(
            x=x0,
            y=y0,
            text=label,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font={"size": 11, "color": MUTED},
        )


def trajectory_figure(
    moves: pd.DataFrame,
    clicks: pd.DataFrame,
    rects: dict[str, list[float]],
    shown_ms: float,
    upto_ms: float,
    aspect: float,
) -> go.Figure:
    """1試行の軌跡。upto_ms（表示開始からの ms）までを描く（スライダーで簡易再生）。"""
    mv = moves[moves["t_client_ms"] - shown_ms <= upto_ms]
    ck = clicks[clicks["t_client_ms"] - shown_ms <= upto_ms]
    fig = go.Figure()
    _layout_shapes(fig, rects)
    rel = (mv["t_client_ms"] - shown_ms).round()
    fig.add_trace(
        go.Scatter(
            x=mv["x_norm"],
            y=mv["y_norm"],
            mode="lines",
            name="軌跡",
            line={"color": PATH, "width": 2, "shape": "linear"},
            customdata=rel,
            hovertemplate="%{customdata:,} ms<br>x=%{x:.3f} y=%{y:.3f}<extra></extra>",
        )
    )
    if len(mv):
        last = mv.iloc[[-1]]
        fig.add_trace(
            go.Scatter(
                x=last["x_norm"],
                y=last["y_norm"],
                mode="markers",
                name="現在位置",
                marker={"size": 10, "color": PATH, "line": {"color": SURFACE, "width": 2}},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    if len(ck):
        fig.add_trace(
            go.Scatter(
                x=ck["x_norm"],
                y=ck["y_norm"],
                mode="markers",
                name="クリック",
                marker={"size": 10, "color": CLICK, "line": {"color": SURFACE, "width": 2}},
                customdata=(ck["t_client_ms"] - shown_ms).round(),
                hovertemplate="クリック %{customdata:,} ms<extra></extra>",
            )
        )
    return _base(fig, aspect, _extent([moves]))


def overlay_figure(
    groups: Sequence[tuple[str, Sequence[pd.DataFrame]]],
    rects: dict[str, list[float]],
    aspect: float,
) -> go.Figure:
    """複数試行の軌跡を回答別に重ねる。

    groups は (回答のラベル, 各試行の移動点) の並び（件数の多い順）。
    """
    fig = go.Figure()
    _layout_shapes(fig, rects)
    shown: list[tuple[str, Sequence[pd.DataFrame]]] = list(groups[: len(CATEGORICAL)])
    rest = [f for _, frames in groups[len(CATEGORICAL) :] for f in frames]
    if rest:
        shown.append(("その他", rest))
    all_frames: list[pd.DataFrame] = []
    for i, (label, frames) in enumerate(shown):
        color = CATEGORICAL[i] if i < len(CATEGORICAL) else OTHER
        for j, f in enumerate(frames):
            all_frames.append(f)
            fig.add_trace(
                go.Scatter(
                    x=f["x_norm"],
                    y=f["y_norm"],
                    mode="lines",
                    opacity=0.6,
                    line={"color": color, "width": 2},
                    name=f"{label}（{len(frames)}件）",
                    legendgroup=label,
                    showlegend=j == 0,
                    hovertemplate=f"{label}<br>x=%{{x:.3f}} y=%{{y:.3f}}<extra></extra>",
                )
            )
    return _base(fig, aspect, _extent(all_frames))
