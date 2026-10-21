"""Route vs Rush — the open-window clock.   streamlit run app.py"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


from rvr import defense, engine, io, metrics, plots as P, viz_html

st.set_page_config(page_title="Route vs Rush", page_icon="⏱️", layout="wide")

DEFINITIONS = """
| Term | Definition | Why this choice |
|---|---|---|
| Receiver | `pff_role == "Pass Route"` | PFF tag, no guessing |
| Separation | distance to nearest `Coverage` defender, per frame | the standard NGS quantity |
| Open | separation ≥ 3.0 yd **and** ≥ 1.0 yd past the line of scrimmage | 3 yd is the NGS "open" threshold; the LOS filter kills "everyone is open at the snap" |
| Window | consecutive open frames; all stored, longest reported | |
| Time to open | seconds after snap of the first open frame (blank if never) | |
| Pressure | any `Pass Rush` player within 2.0 yd of the QB | simple, honest geometry; pass blockers never count |
| Pressure at | first pressure frame in seconds (blank if none before the throw) | |
| Time to throw | throw frame − snap frame, in seconds; sacks: sack frame | |
| Target open at throw | target's separation ≥ 3 yd and past the LOS at the throw frame | |
| Open man ignored | target covered (separation < 1.5 yd) at the throw while ≥ 1 other receiver is open | the "open but not targeted" question |
| Race margin | pressure time (or throw time if the rush never got home) − first open time | positive = routes won; the headline per-play number |
"""
LIMITS = """
- **Proximity ≠ assignment.** Separation is to the *nearest* coverage defender, not the one responsible for the receiver.
- **8 weeks** of the 2021 season (122 games); small samples for some players.
- **No post-throw frames.** Tracking ends 3–5 frames after release, so catch point and YAC are out of scope.
- **Targets are parsed from play text** (~95 % matched); unmatched throws keep a blank target.
- **Open ≠ throwable.** There is no QB field-of-view or throwing-lane model; a receiver can be "open" behind the QB's back.
"""


def fmt_s(v, none="—"):
    return none if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.1f} s"


# ---------------------------------------------------------------- data
@st.cache_data
def load_outputs():
    race = pd.read_parquet("outputs/race_by_play.parquet")
    win = pd.read_parquet("outputs/windows_by_receiver.parquet")
    return race, win


@st.cache_data
def load_meta():
    games, plays, players, pff = io.load_meta()
    return games, players, pff


@st.cache_data(max_entries=8)
def load_game(gid):
    return io.load_game(gid)


@st.cache_data
def load_defense_meta():
    """play-level defensive context + the full PFF rows (lined-up spots, hits/hurries/sacks)."""
    plays = pd.read_csv(io.DATA / "plays.csv",
                        usecols=["gameId", "playId", "pff_passCoverage", "pff_passCoverageType", "personnelD",
                                 "defendersInBox", "personnelO", "offenseFormation", "pff_playAction", "dropBackType"])
    pff_full = pd.read_csv(io.DATA / "pffScoutingData.csv",
                           usecols=["gameId", "playId", "nflId", "pff_role", "pff_positionLinedUp",
                                    "pff_hit", "pff_hurry", "pff_sack"])
    return plays.set_index(["gameId", "playId"]), pff_full


def run_play(gid, pid, target, open_sep, min_depth, pressure_dist):
    _, players, pff = load_meta()
    trk = load_game(gid)
    roles = io.roles_for(pff[(pff.gameId == gid) & (pff.playId == pid)], players)[["nflId", "pff_role", "player", "pos"]]
    return engine.analyze_play(trk[trk.playId == pid], roles, target, open_sep=open_sep, min_depth=min_depth,
                               pressure_dist=pressure_dist)


try:
    race, win = load_outputs()
    games, players, pff = load_meta()
except Exception as e:  # never a traceback
    st.error(f"Could not load data: run `python build.py` first and make sure `data/` exists ({type(e).__name__}).")
    st.stop()

glabel = games.set_index("gameId").label.to_dict()
desc = race.set_index(["gameId", "playId"]).playDescription.to_dict()

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("Route vs Rush")
    st.markdown("*the open-window clock*")
    st.caption(f"{len(race):,} dropbacks · 2021 weeks 1–8 · NGS tracking + PFF roles")
    open_sep = st.slider("Open if separation ≥ (yd)", 1.5, 5.0, engine.OPEN_SEP, 0.5)
    min_depth = st.slider("…and past the LOS by ≥ (yd)", 0.0, 5.0, engine.MIN_DEPTH, 0.5)
    pressure_dist = st.slider("Pressure if rusher within (yd)", 1.0, 4.0, engine.PRESSURE_DIST, 0.5)
    st.caption("Sliders only change the single-play view in Play Explorer. "
               "Leaderboards and coverage tables use the fixed defaults (3.0 / 1.0 / 2.0).")
    with st.expander("Method"):
        st.markdown(DEFINITIONS)


# ---------------------------------------------------------------- story picks
def pick(gid, pid):
    st.session_state.week = int(race.loc[(race.gameId == gid) & (race.playId == pid), "week"].iat[0])
    st.session_state.game = int(gid)
    st.session_state.play = int(pid)


comp = race[race.passResult == "C"]
ign = race[race.open_man_ignored & race.t_pressure.notna()]
STORIES = {
    "Most obvious open man ignored": ign.loc[ign.best_alt_sep_at_throw.idxmax()],
    "Longest race won": comp.loc[comp.race_margin.idxmax()],
    "Fastest window": comp.sort_values(["t_first_open", "race_margin"], ascending=[True, False]).iloc[0],
}
if "play" not in st.session_state:
    s = STORIES["Most obvious open man ignored"]
    pick(s.gameId, s.playId)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Play Explorer", "Receivers", "Quarterbacks", "Coverages", "Method"])

# ---------------------------------------------------------------- tab 1
with tab1:
    cols = st.columns(3)
    for c, (name, row) in zip(cols, STORIES.items()):
        c.button(name, on_click=pick, args=(row.gameId, row.playId), width="stretch")

    c1, c2, c3 = st.columns([1, 2, 5])
    weeks = sorted(race.week.unique())
    week = c1.selectbox("Week", weeks, key="week")
    game_opts = sorted(race.loc[race.week == week, "gameId"].unique())
    if st.session_state.get("game") not in game_opts:
        st.session_state.game = int(game_opts[0])
    gid = c2.selectbox("Game", game_opts, key="game", format_func=lambda g: glabel.get(g, str(g)))
    play_opts = race.loc[race.gameId == gid].sort_values("playId").playId.tolist()
    if st.session_state.get("play") not in play_opts:
        st.session_state.play = int(play_opts[0])
    pid = c3.selectbox("Play", play_opts, key="play",
                       format_func=lambda p: (lambda d: d if len(d) <= 80 else d[:79] + "…")(desc.get((gid, p), str(p))))

    row = race[(race.gameId == gid) & (race.playId == pid)].iloc[0]
    try:
        res = run_play(gid, pid, row.targetNflId, open_sep, min_depth, pressure_dist)
    except Exception as e:
        res = None
        st.error(f"Could not compute this play ({type(e).__name__}).")
    if res is None:
        st.info("This play has no usable tracking between snap and throw. Pick another one.")
    else:
        S = res.summary
        m = st.columns(5)
        m[0].metric("Time to throw", fmt_s(S["t_throw"]), "sack" if S["throw_source"] == "sack" else None,
                    delta_color="inverse")
        m[1].metric("First open at", fmt_s(S["t_first_open"], "never"),
                    f"{S['n_open_at_throw']} of {S['n_receivers']} open at throw", delta_color="off")
        m[2].metric("Pressure at", fmt_s(S["t_pressure"], "none"),
                    "rush never got home" if np.isnan(S["t_pressure"]) else "rusher within %.1f yd" % pressure_dist,
                    delta_color="off")
        rm = S["race_margin"]
        m[3].metric("Race margin", "—" if np.isnan(rm) else f"{rm:+.1f} s",
                    None if np.isnan(rm) else (f"routes won by {rm:.1f} s" if rm > 0 else f"rush won by {-rm:.1f} s"),
                    delta_color="normal" if not np.isnan(rm) and rm != 0 else "off")
        ts = S["target_sep_at_throw"]
        m[4].metric("Target separation at throw", "—" if np.isnan(ts) else f"{ts:.1f} yd",
                    None if S["target"] is None else ("open" if S["target_open_at_throw"] else
                                                      ("covered" if ts < engine.TIGHT_SEP else "contested")),
                    delta_color="normal" if S["target_open_at_throw"] is True else "inverse")
        sentence = engine.story(res)
        if S["open_man_ignored"]:
            sentence += f" Open alternative: {S['best_alt_name']} at {S['best_alt_sep_at_throw']:.1f} yd."
        st.markdown(f"**{sentence}**")

        # ---- the other side of the race: what the defense ran, and who was on whom
        try:
            dplays, pff_full = load_defense_meta()
            dp = dplays.loc[(gid, pid)]
            pff_play = pff_full[(pff_full.gameId == gid) & (pff_full.playId == pid)]
            rs = defense.rush_summary(pff_play, players)
            cov_call = dp.pff_passCoverage if isinstance(dp.pff_passCoverage, str) else "unknown"
            cov_type = dp.pff_passCoverageType if isinstance(dp.pff_passCoverageType, str) else ""
            box = "" if pd.isna(dp.defendersInBox) else f" · {int(dp.defendersInBox)} in the box"
            line = (f"**Defense ({row.defensiveTeam}): {cov_call}**" + (f" ({cov_type})" if cov_type else "")
                    + (f" · personnel {dp.personnelD}" if isinstance(dp.personnelD, str) else "") + box
                    + f" · {rs['n_rush']} rushers" + (f" ({', '.join(rs['spots'])})" if rs["spots"] else "")
                    + f" vs {rs['n_cov']} in coverage"
                    + (" · " + ", ".join(rs["credit"]) if rs["credit"] else ""))
            st.markdown(line)
            mu = defense.matchups(res, pff_play)
            if not mu.empty:
                with st.expander("Who was covering whom", expanded=True):
                    st.dataframe(
                        mu.drop(columns=["nflId"]), hide_index=True, width="stretch",
                        column_config={
                            "receiver": "Receiver", "rec_pos": "Pos",
                            "defender": "Covered by (most of the route)", "def_pos": "Pos", "lined_up": "Lined up as",
                            "share_nearest": st.column_config.ProgressColumn("Share of frames nearest",
                                                                             format="percent", min_value=0, max_value=1),
                            "defender_at_throw": "Nearest at the throw",
                            "sep_at_throw": st.column_config.NumberColumn("Sep at throw", format="%.1f yd"),
                            "open_at_throw": "Open", "targeted": "Target",
                            "shared": "Same defender on 2+",
                        })
                    st.caption("Covering = the coverage defender who was nearest to the receiver most often from "
                               "0.5 s after the snap to the throw. A proximity proxy, not the real assignment: "
                               "in zone the nearest man changes as the route crosses zones, which is what the "
                               "'share of frames' column shows.")
        except Exception as e:
            st.caption(f"Defensive details unavailable for this play ({type(e).__name__}).")
        try:
            _, players_, pff_ = load_meta()
            trk_ = load_game(gid)
            roles_ = io.roles_for(pff_[(pff_.gameId == gid) & (pff_.playId == pid)],
                                  players_)[["nflId", "pff_role", "player", "pos"]]
            data = viz_html.payload(res, trk_[trk_.playId == pid], roles_, open_sep, pressure_dist)
            st.iframe(viz_html.render(data), height=150 + 34 * (len(res.rec_ids) + 1) + 110 + 340)
            st.caption(f"{row.possessionTeam} (blue) → right vs {row.defensiveTeam} (red), "
                       f"{row.coverage if isinstance(row.coverage, str) else 'unknown coverage'}. "
                       "One clock drives every chart: press play, drag the slider, or click/drag on the timeline "
                       "or distance chart (← → keys step one frame). Click any player to highlight him everywhere. "
                       "Ball positions after release are tracked for 0.5 s; the dotted rest of the flight is a "
                       "straight-line projection to the target, not tracking data.")
        except Exception as e:
            st.info(f"Interactive viewer unavailable for this play ({type(e).__name__}).")
        j = res.target_idx if res.target_idx is not None else int(np.nanargmax(np.where(np.isfinite(res.sep[-1]), res.sep[-1], -1)))
        who = res.rec_names[j].split()[-1]
        pd_min = res.pressure_dist[np.isfinite(res.pressure_dist)]
        st.caption(f"{'Target' if res.target_idx is not None else 'Most open receiver'} {who} peaked at "
                   f"{np.nanmax(np.where(np.isfinite(res.sep[:, j]), res.sep[:, j], np.nan)):.1f} yd of separation and had "
                   f"{res.sep[-1, j]:.1f} yd at the throw; the closest any rusher got to the QB was "
                   + (f"{pd_min.min():.1f} yd." if len(pd_min) else "— (no rushers tracked).")
                   + " Distances capped at 15 yd for readability.")

# ---------------------------------------------------------------- tab 2
with tab2:
    rt = metrics.receiver_table(win, race)
    f1, f2, f3 = st.columns([2, 2, 2])
    pos_sel = f1.multiselect("Position", ["WR", "TE", "RB"], default=["WR", "TE", "RB"])
    min_routes = f2.slider("Min routes", 10, 300, 40, 10)
    team = f3.selectbox("Team", ["All"] + sorted(rt.team.dropna().unique()))
    v = rt[rt.pos.isin(pos_sel) & (rt.routes >= min_routes)]
    if team != "All":
        v = v[v.team == team]
    if v.empty:
        st.info("No receiver matches these filters.")
    else:
        v = v.sort_values(["median_t_open", "open_share"], ascending=[True, False])
        st.dataframe(
            v.drop(columns=["nflId"]), hide_index=True, width="stretch", height=360,
            column_config={
                "player": "Player", "pos": "Pos", "team": "Team", "routes": "Routes", "targets": "Targets",
                "median_t_open": st.column_config.NumberColumn("Median time to open", format="%.1f s"),
                "open_share": st.column_config.ProgressColumn("Open share of dropback", format="percent",
                                                              min_value=0, max_value=1),
                "open_at_throw_rate": st.column_config.ProgressColumn("Open at throw", format="percent",
                                                                      min_value=0, max_value=1),
                "open_ignored": st.column_config.NumberColumn("Open but ignored", format="%d"),
                "open_ignored_rate": st.column_config.NumberColumn("Ignored / route", format="percent"),
            })
        zs = lambda c: v.groupby("pos")[c].transform(lambda x: (x - x.mean()) / (x.std() or 1))
        z = zs("open_share") - zs("median_t_open")   # extremes within each position: early + often open, or neither
        top = z.groupby(v.pos).nlargest(2).index.get_level_values(-1).union(
            z.groupby(v.pos).nsmallest(2).index.get_level_values(-1))
        lab = v.assign(label=np.where(v.index.isin(top[:10]), v.player, ""))
        fig = px.scatter(lab, x="median_t_open", y="open_share", size="routes", color="pos", text="label",
                         color_discrete_map=P.POS_COLORS, hover_name="player",
                         hover_data={"routes": True, "team": True, "label": False, "pos": False},
                         labels={"median_t_open": "median time to first open (s)", "open_share": "share of dropback open"})
        fig.update_traces(textposition="top center", textfont=dict(size=10, color=P.TEXT), marker=dict(opacity=0.75))
        P.base_layout(fig, height=480, legend=dict(title="", orientation="h", y=1.05))
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        early = v[v.median_t_open <= v.median_t_open.quantile(0.25)].nlargest(3, "open_share").player.tolist()
        late = v[v.median_t_open >= v.median_t_open.quantile(0.75)].nlargest(3, "open_share").player.tolist()
        st.caption(f"Early separators (left, high): {', '.join(early)}. "
                   f"Late bloomers (right, still open often): {', '.join(late)}.")

        who = st.selectbox("Player detail", v.player.tolist())
        me = v[v.player == who].iloc[0]
        mine = win[win.nflId == me.nflId]
        same = win[win.pos.replace({"FB": "RB"}) == me.pos]
        a, b = st.columns(2)
        with a:
            h = go.Figure()
            h.add_histogram(x=same.t_open.dropna(), histnorm="probability", name=f"all {me.pos}",
                            marker_color=P.COVERED, xbins=dict(size=0.2))
            h.add_histogram(x=mine.t_open.dropna(), histnorm="probability", name=who, marker_color=P.OPEN,
                            opacity=0.8, xbins=dict(size=0.2))
            P.base_layout(h, barmode="overlay", height=300, legend=dict(orientation="h", y=1.1),
                          title=dict(text="Time to first open", font=dict(size=13)))
            h.update_xaxes(title="seconds after snap", range=[0, 5])
            h.update_yaxes(tickformat=".0%")
            st.plotly_chart(h, width="stretch", config={"displayModeBar": False})
            st.caption(f"{who}: median {me.median_t_open:.1f} s vs {same.t_open.median():.1f} s for all {me.pos}s.")
        with b:
            st.markdown(f"**{who}'s most ignored plays** (open at the throw, ball went to a covered teammate)")
            ig = (mine[mine.open_at_throw & ~mine.targeted]
                  .merge(race[race.open_man_ignored][["gameId", "playId", "target", "target_sep_at_throw"]],
                         on=["gameId", "playId"]).nlargest(5, "sep_at_throw"))
            if ig.empty:
                st.caption("Never open-and-ignored in this sample.")
            for r in ig.itertuples():
                st.button(f"{glabel.get(r.gameId, r.gameId)} · {r.sep_at_throw:.1f} yd open, ball to {r.target} "
                          f"({r.target_sep_at_throw:.1f} yd)", key=f"ig{r.gameId}{r.playId}",
                          on_click=pick, args=(r.gameId, r.playId), width="stretch")
            if not ig.empty:
                st.caption("Click a play, then open the Play Explorer tab.")

# ---------------------------------------------------------------- tab 3
with tab3:
    qb = metrics.qb_leaderboard(race)
    st.dataframe(qb.drop(columns=["qbNflId"]), hide_index=True, width="stretch", height=380,
                 column_config={
                     "qb": "QB", "team": "Team", "dropbacks": "Dropbacks",
                     "mean_t_throw": st.column_config.NumberColumn("Mean time to throw", format="%.2f s"),
                     "pct_into_open_window": st.column_config.ProgressColumn("Throws into open window", format="percent",
                                                                             min_value=0, max_value=1),
                     "pct_open_man_ignored": st.column_config.NumberColumn("Open man ignored", format="percent"),
                     "pct_races_won": st.column_config.NumberColumn("Races won", format="percent"),
                     "pct_pressured": st.column_config.NumberColumn("Pressured", format="percent"),
                 })
    fig = px.scatter(qb, x="pct_into_open_window", y="mean_t_throw", size="dropbacks", text="qb",
                     hover_name="qb", labels={"pct_into_open_window": "throws into an open window",
                                              "mean_t_throw": "mean time to throw (s)"})
    fig.update_traces(marker=dict(color=P.TARGET, opacity=0.7), textposition="top center",
                      textfont=dict(size=10, color=P.TEXT))
    P.base_layout(fig, height=480)
    fig.update_xaxes(tickformat=".0%")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    fast = qb[qb.mean_t_throw <= qb.mean_t_throw.median()].nlargest(3, "pct_into_open_window").qb.tolist()
    slow = qb[qb.mean_t_throw > qb.mean_t_throw.median()].nsmallest(3, "pct_into_open_window").qb.tolist()
    st.caption(f"Bottom-right gets rid of it on time and into open windows ({', '.join(fast)}); "
               f"top-left holds the ball and still throws into coverage ({', '.join(slow)}).")

# ---------------------------------------------------------------- tab 4
with tab4:
    curves = metrics.race_curves(race)
    st.subheader("The race, by coverage")
    st.plotly_chart(P.race_curves(curves), width="stretch", config={"displayModeBar": False})
    at2 = curves[np.isclose(curves.t, 2.0)].set_index("coverage")
    worst = at2.p_open.idxmin()
    st.caption(f"Green = share of plays with at least one receiver open by t; red = share with pressure by t. "
               f"At 2.0 s, {worst} has the fewest plays with someone open ({at2.p_open.min():.0%}), "
               f"{at2.p_open.idxmax()} the most ({at2.p_open.max():.0%}).")
    cov = metrics.coverage_table(race)
    fig = px.bar(cov.sort_values("median_race_margin"), x="median_race_margin", y="coverage", color="covType",
                 orientation="h", color_discrete_map={"Man": P.TARGET, "Zone": P.OPEN, "Other": P.COVERED},
                 labels={"median_race_margin": "median race margin (s): routes ahead of the rush", "coverage": ""})
    P.base_layout(fig, height=360, legend=dict(title="", orientation="h", y=1.08))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    man = cov[cov.covType == "Man"].median_race_margin.median()
    zone = cov[cov.covType == "Zone"].median_race_margin.median()
    st.caption(f"Man coverages leave routes {man:.1f} s ahead of the rush (median), zone coverages {zone:.1f} s.")
    st.dataframe(cov, hide_index=True, width="stretch", column_config={
        "median_race_margin": st.column_config.NumberColumn("Median race margin", format="%.2f s"),
        "pct_routes_won": st.column_config.NumberColumn("Routes won", format="percent"),
        "median_t_first_open": st.column_config.NumberColumn("Median first open", format="%.1f s"),
        "pct_never_open": st.column_config.NumberColumn("Nobody open", format="percent"),
        "pct_pressured": st.column_config.NumberColumn("Pressured", format="percent"),
        "median_t_throw": st.column_config.NumberColumn("Median time to throw", format="%.1f s"),
        "pct_target_open": st.column_config.NumberColumn("Target open at throw", format="percent")})

# ---------------------------------------------------------------- tab 5
with tab5:
    st.subheader("Definitions")
    st.markdown(DEFINITIONS)
    st.subheader("Tunables")
    st.markdown(f"Open separation **{engine.OPEN_SEP} yd**, covered below **{engine.TIGHT_SEP} yd**, "
                f"min depth past LOS **{engine.MIN_DEPTH} yd**, pressure radius **{engine.PRESSURE_DIST} yd**, "
                f"**{engine.FPS} fps** tracking. Sidebar sliders re-run the engine on the selected play only.")
    st.subheader("Limitations")
    st.markdown(LIMITS)
