"""All charts. One semantic palette, declared once."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .engine import FPS, PRESSURE_DIST, _runs

OPEN = "#2ECC71"
COVERED = "#3A4654"
TARGET = "#3B82F6"
PRESSURE = "#EF4444"
THROW = "#E6EDF3"
OFFENSE = "#3B82F6"
DEFENSE = "#EF4444"
BALL = "#F5C542"
TURF = "#13251B"
BG = "#0B1117"
PANEL = "#141C26"
TEXT = "#E6EDF3"
MUTED = "#8B98A5"
POS_ORDER = {"WR": 0, "TE": 1, "RB": 2, "FB": 3}
POS_COLORS = {"WR": "#2ECC71", "TE": "#F5C542", "RB": "#3B82F6"}


def base_layout(fig, **kw):
    kw.setdefault("margin", dict(l=10, r=10, t=40, b=10))
    fig.update_layout(paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=TEXT, family="sans-serif", size=12), **kw)
    fig.update_xaxes(showgrid=False, zeroline=False, color=MUTED)
    fig.update_yaxes(showgrid=False, zeroline=False, color=MUTED)
    return fig


def receiver_order(res):
    first = [w[0][0] if w else 99 for w in res.windows]
    return sorted(range(len(res.rec_ids)), key=lambda j: (POS_ORDER.get(res.rec_pos[j], 9), first[j]))


def gantt(res, title="", pressure_dist=PRESSURE_DIST):
    """Open windows per receiver vs the pressure clock vs the throw."""
    t_end = res.t[-1]
    order = receiver_order(res)[::-1]   # first row at the top
    labels = [f"{res.rec_names[j]} ({res.rec_pos[j]})" + ("  ◀ target" if j == res.target_idx else "") for j in order]
    fig = go.Figure()
    fig.add_bar(y=["Pressure"] + labels, x=[t_end + 1 / FPS] * (len(labels) + 1), base=0, orientation="h",
                marker_color=COVERED, opacity=0.35, hoverinfo="skip", width=0.6)
    for lab, j in zip(labels, order):
        w = res.windows[j]
        if not w:
            continue
        col = TARGET if j == res.target_idx else OPEN
        maxsep = [float(np.nanmax(np.where(np.isfinite(res.sep[int(round(a * FPS)):int(round(b * FPS)) + 1, j]),
                                           res.sep[int(round(a * FPS)):int(round(b * FPS)) + 1, j], np.nan)))
                  for a, b in w]
        fig.add_bar(y=[lab] * len(w), x=[b - a + 1 / FPS for a, b in w], base=[a for a, _ in w], orientation="h",
                    marker_color=col, width=0.6,
                    customdata=[[res.rec_names[j], res.rec_pos[j], a, b + 1 / FPS, m] for (a, b), m in zip(w, maxsep)],
                    hovertemplate="%{customdata[0]} (%{customdata[1]})<br>open %{customdata[2]:.1f}–%{customdata[3]:.1f} s"
                                  "<br>max separation %{customdata[4]:.1f} yd<extra></extra>")
    pr = _runs(res.pressure_dist <= pressure_dist)
    if pr:
        fig.add_bar(y=["Pressure"] * len(pr), x=[(e - s + 1) / FPS for s, e in pr], base=[res.t[s] for s, _ in pr],
                    orientation="h", marker_color=PRESSURE, width=0.6,
                    hovertemplate="rusher within %.1f yd of QB<br>%%{base:.1f} s<extra></extra>" % pressure_dist)
    fig.add_vline(x=t_end, line=dict(color=THROW, dash="dash", width=2))
    fig.add_annotation(x=t_end, y=1.02, yref="paper", text="sack" if res.summary["throw_source"] == "sack" else "throw",
                       showarrow=False, font=dict(color=THROW, size=11))
    base_layout(fig, barmode="overlay", showlegend=False, height=90 + 46 * (len(labels) + 1),
                title=dict(text=title, font=dict(size=13)), bargap=0.3)
    fig.update_xaxes(title="seconds after snap", showgrid=True, gridcolor="#1E2833", range=[0, t_end + 0.3], dtick=0.5)
    fig.update_yaxes(categoryorder="array", categoryarray=["Pressure"] + labels)
    return fig


def _field_shapes(los_x, x0, x1):
    sh = [dict(type="rect", x0=x0, x1=x1, y0=0, y1=53.3, fillcolor=TURF, line_width=0, layer="below")]
    for x in range(10, 111, 10):
        if x0 <= x <= x1:
            sh.append(dict(type="line", x0=x, x1=x, y0=0, y1=53.3, line=dict(color="white", width=1), opacity=0.25,
                           layer="below"))
    sh.append(dict(type="line", x0=los_x, x1=los_x, y0=0, y1=53.3, line=dict(color=TARGET, width=2, dash="dot"),
                   layer="below"))
    return sh


def field_animation(res, open_mask=None, pressure_dist=PRESSURE_DIST):
    """All 22 + ball, snap -> throw, offense left -> right, 10 fps."""
    f = res.frames.copy()
    open_mask = res.open if open_mask is None else open_mask
    frames = np.sort(f.frameId.unique())
    snap = frames[0]
    off_team = f.loc[f.nflId == res.qb_id, "team"].iloc[0]
    rec_idx = {nid: j for j, nid in enumerate(res.rec_ids)}
    x0 = max(0, res.los_x - 15)
    x1 = min(120, res.los_x + 45)

    def traces(fid):
        k = int(fid - snap)
        d = f[f.frameId == fid]
        ball = d[d.nflId.isna()]
        off = d[(d.team == off_team) & d.nflId.notna()]
        dfn = d[(d.team != off_team) & d.nflId.notna() & (d.team != "football")]
        line = [OPEN if (n in rec_idx and open_mask[k, rec_idx[n]]) else OFFENSE for n in off.nflId]
        lw = [3 if n in rec_idx and open_mask[k, rec_idx[n]] else 0 for n in off.nflId]
        qb = d[d.nflId == res.qb_id]
        hot = res.pressure_dist[k] <= pressure_dist

        def hov(s):
            base = (s.player.fillna("") + " #" + s.jerseyNumber.fillna(0).astype(int).astype(str)).tolist()
            extra = []
            for n in s.nflId:
                if n in rec_idx:
                    extra.append(f"<br>separation {res.sep[k, rec_idx[n]]:.1f} yd")
                elif n == res.qb_id and np.isfinite(res.pressure_dist[k]):
                    extra.append(f"<br>nearest rusher {res.pressure_dist[k]:.1f} yd")
                else:
                    extra.append("")
            return [a + b for a, b in zip(base, extra)]
        return [
            go.Scatter(x=dfn.x, y=dfn.y, mode="markers", marker=dict(size=11, color=DEFENSE), hovertext=hov(dfn),
                       hoverinfo="text", name="defense"),
            go.Scatter(x=off.x, y=off.y, mode="markers", marker=dict(size=11, color=OFFENSE, line=dict(color=line, width=lw)),
                       hovertext=hov(off), hoverinfo="text", name="offense"),
            go.Scatter(x=qb.x, y=qb.y, mode="markers", marker=dict(size=22, color="rgba(0,0,0,0)",
                       line=dict(color=PRESSURE if hot else THROW, width=2.5)), hoverinfo="skip", name="QB"),
            go.Scatter(x=ball.x, y=ball.y, mode="markers", marker=dict(size=8, color=BALL, symbol="diamond"),
                       hoverinfo="skip", name="ball"),
        ]

    fig = go.Figure(data=traces(frames[0]),
                    frames=[go.Frame(data=traces(fid), name=f"{(fid - snap) / FPS:.1f}") for fid in frames])
    steps = [dict(method="animate", label=f"{(fid - snap) / FPS:.1f}",
                  args=[[f"{(fid - snap) / FPS:.1f}"], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                                             transition=dict(duration=0))]) for fid in frames]
    base_layout(fig, showlegend=False, height=430, shapes=_field_shapes(res.los_x, x0, x1),
                margin=dict(l=10, r=10, t=10, b=10),
                updatemenus=[dict(type="buttons", showactive=False, x=0, y=-0.02, xanchor="left", yanchor="top",
                                  bgcolor=PANEL, font=dict(color=TEXT),
                                  buttons=[dict(label="▶ play", method="animate",
                                                args=[None, dict(frame=dict(duration=1000 / FPS, redraw=True),
                                                                 fromcurrent=True, transition=dict(duration=0))]),
                                           dict(label="❚❚", method="animate",
                                                args=[[None], dict(mode="immediate", frame=dict(duration=0))])])],
                sliders=[dict(steps=steps, x=0.18, len=0.82, y=-0.02, yanchor="top", currentvalue=dict(
                    prefix="t = ", suffix=" s", font=dict(color=TEXT)), font=dict(color=MUTED), bgcolor=PANEL)])
    fig.update_xaxes(range=[x0, x1], showticklabels=False)
    fig.update_yaxes(range=[0, 53.3], showticklabels=False, scaleanchor="x", scaleratio=1)
    return fig


def distance_curves(res, open_sep=3.0, pressure_dist=PRESSURE_DIST):
    """Top: each receiver's separation (yd to nearest coverage defender). Bottom: nearest rusher -> QB distance."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.08,
                        subplot_titles=["Separation from nearest coverage defender (yd)", "Nearest rusher to QB (yd)"])
    t = res.t
    for j in receiver_order(res):
        y = np.where(np.isfinite(res.sep[:, j]), res.sep[:, j], np.nan)
        y = np.minimum(y, 15)
        is_t = j == res.target_idx
        name = res.rec_names[j].split()[-1]
        fig.add_scatter(x=t, y=y, mode="lines", name=name, row=1, col=1,
                        line=dict(color=TARGET if is_t else POS_COLORS.get(res.rec_pos[j], OPEN), width=3.5 if is_t else 1.6),
                        opacity=1 if is_t else 0.75,
                        hovertemplate=f"{res.rec_names[j]} ({res.rec_pos[j]})<br>%{{x:.1f}} s: %{{y:.1f}} yd<extra></extra>")
        fig.add_annotation(x=t[-1], y=y[-1], text=name, showarrow=False, xanchor="left", xshift=4, row=1, col=1,
                           font=dict(size=10, color=TARGET if is_t else MUTED))
    fig.add_hline(y=open_sep, line=dict(color=OPEN, dash="dot", width=1), row=1, col=1,
                  annotation_text=f"open ≥ {open_sep:g} yd", annotation_font=dict(color=OPEN, size=10),
                  annotation_position="top left")
    pdist = np.where(np.isfinite(res.pressure_dist), res.pressure_dist, np.nan)
    fig.add_scatter(x=t, y=np.minimum(pdist, 15), mode="lines", line=dict(color=PRESSURE, width=2.5), row=2, col=1,
                    name="rusher", hovertemplate="%{x:.1f} s: nearest rusher %{y:.1f} yd from QB<extra></extra>")
    fig.add_hline(y=pressure_dist, line=dict(color=PRESSURE, dash="dot", width=1), row=2, col=1,
                  annotation_text=f"pressure ≤ {pressure_dist:g} yd", annotation_font=dict(color=PRESSURE, size=10),
                  annotation_position="bottom left")
    for r in (1, 2):
        fig.add_vline(x=t[-1], line=dict(color=THROW, dash="dash", width=1.5), row=r, col=1)
    base_layout(fig, showlegend=False, height=460, margin=dict(l=10, r=70, t=40, b=10))
    fig.update_annotations(font_size=11, selector=dict(text="Separation from nearest coverage defender (yd)"))
    fig.update_xaxes(showgrid=True, gridcolor="#1E2833", dtick=0.5, range=[0, t[-1] + 0.1])
    fig.update_xaxes(title="seconds after snap", row=2, col=1)
    fig.update_yaxes(rangemode="tozero")
    return fig


def race_curves(curves, ncols=4):
    covs = curves.groupby("coverage").n.first().sort_values(ascending=False).index.tolist()
    nrows = int(np.ceil(len(covs) / ncols))
    fig = make_subplots(rows=nrows, cols=ncols, shared_xaxes=True, shared_yaxes=True,
                        subplot_titles=[f"{c} (n={curves[curves.coverage == c].n.iat[0]})" for c in covs],
                        horizontal_spacing=0.03, vertical_spacing=0.12)
    for i, c in enumerate(covs):
        d = curves[curves.coverage == c]
        r, k = i // ncols + 1, i % ncols + 1
        fig.add_scatter(x=d.t, y=d.p_open, line=dict(color=OPEN, shape="hv", width=2.5), row=r, col=k,
                        name="≥1 receiver open", hovertemplate="%{x:.1f} s: %{y:.0%} open<extra></extra>")
        fig.add_scatter(x=d.t, y=d.p_pressure, line=dict(color=PRESSURE, shape="hv", width=2.5), row=r, col=k,
                        name="pressure arrived", hovertemplate="%{x:.1f} s: %{y:.0%} pressured<extra></extra>")
    base_layout(fig, showlegend=False, height=260 * nrows)
    fig.update_yaxes(range=[0, 1.02], tickformat=".0%", dtick=0.5)
    fig.update_xaxes(showgrid=True, gridcolor="#1E2833", dtick=1)
    for k in range(1, ncols + 1):
        fig.update_xaxes(title_text="s after snap", row=nrows, col=k)
    return fig


def gantt_png(res, path, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = receiver_order(res)[::-1]
    t_end = res.t[-1]
    fig, ax = plt.subplots(figsize=(10, 0.6 * (len(order) + 1) + 1.6), facecolor=BG)
    ax.set_facecolor(BG)
    for k, j in enumerate(order, start=1):
        ax.broken_barh([(0, t_end + 0.1)], (k - 0.3, 0.6), color=COVERED, alpha=0.35)
        ax.broken_barh([(a, b - a + 0.1) for a, b in res.windows[j]], (k - 0.3, 0.6),
                       color=TARGET if j == res.target_idx else OPEN)
        ax.text(-0.08, k, f"{res.rec_names[j]} ({res.rec_pos[j]})" + ("  ◀ target" if j == res.target_idx else ""),
                ha="right", va="center", color=TEXT, fontsize=9)
    ax.broken_barh([(0, t_end + 0.1)], (-0.3, 0.6), color=COVERED, alpha=0.35)
    ax.broken_barh([(res.t[s], (e - s + 1) / FPS) for s, e in _runs(res.pressure_dist <= PRESSURE_DIST)],
                   (-0.3, 0.6), color=PRESSURE)
    ax.text(-0.08, 0, "Pressure", ha="right", va="center", color=PRESSURE, fontsize=9)
    ax.axvline(t_end, color=THROW, ls="--", lw=1.5)
    ax.set_xlim(0, t_end + 0.3)
    ax.set_ylim(-0.7, len(order) + 0.7)
    ax.set_yticks([])
    ax.set_xlabel("seconds after snap", color=MUTED)
    ax.tick_params(colors=MUTED)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.grid(axis="x", color="#1E2833")
    ax.set_axisbelow(True)
    ax.set_title(title, color=TEXT, fontsize=10, loc="left")
    plt.subplots_adjust(left=0.3, right=0.97)
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)
