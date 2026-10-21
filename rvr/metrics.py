"""Leaderboards + coverage table from the two long tables (race_by_play, windows_by_receiver)."""
import numpy as np
import pandas as pd

MIN_ROUTES, MIN_DROPBACKS, MIN_COV_PLAYS = 40, 60, 150
REC_POS = ["WR", "TE", "RB"]


def _with_ignored(win, race):
    """Flag receiver-plays where this receiver was open at the throw while the QB threw to a covered target."""
    w = win.merge(race[["gameId", "playId", "open_man_ignored"]], on=["gameId", "playId"], how="left")
    w["ignored_open"] = w.open_at_throw & ~w.targeted & w.open_man_ignored.fillna(False).astype(bool)
    return w


def receiver_table(win, race):
    w = _with_ignored(win, race)
    w = w.assign(pos=w.pos.replace({"FB": "RB"}))
    w = w[w.pos.isin(REC_POS)]
    lb = (w.groupby(["nflId", "player", "pos"])
          .agg(team=("team", lambda s: s.mode().iat[0] if s.notna().any() else ""),
               routes=("playId", "size"), targets=("targeted", "sum"),
               median_t_open=("t_open", "median"), open_share=("open_share", "mean"),
               open_at_throw_rate=("open_at_throw", "mean"),
               open_ignored=("ignored_open", "sum"))
          .reset_index())
    lb["open_ignored_rate"] = lb.open_ignored / lb.routes
    return lb


def receiver_leaderboard(win, race, min_routes=MIN_ROUTES):
    lb = receiver_table(win, race)
    return lb[lb.routes >= min_routes].sort_values("median_t_open")


def qb_leaderboard(race, min_dropbacks=MIN_DROPBACKS):
    r = race.dropna(subset=["qb"]).copy()
    thr = r.target.notna()
    r["into_open"] = np.where(thr, r.target_open_at_throw.astype(float), np.nan)
    r["ignored"] = np.where(thr, r.open_man_ignored.astype(float), np.nan)
    lb = (r.groupby(["qbNflId", "qb"])
          .agg(team=("possessionTeam", lambda s: s.mode().iat[0]), dropbacks=("playId", "size"),
               mean_t_throw=("t_throw", "mean"), pct_into_open_window=("into_open", "mean"),
               pct_open_man_ignored=("ignored", "mean"), pct_races_won=("routes_won", "mean"),
               pct_pressured=("t_pressure", lambda s: s.notna().mean()))
          .reset_index())
    return lb[lb.dropbacks >= min_dropbacks].sort_values("pct_into_open_window", ascending=False)


def coverage_table(race, min_plays=MIN_COV_PLAYS):
    r = race.dropna(subset=["coverage"])
    tb = (r.groupby("coverage")
          .agg(covType=("covType", lambda s: s.mode().iat[0] if s.notna().any() else ""),
               plays=("playId", "size"), median_race_margin=("race_margin", "median"),
               pct_routes_won=("routes_won", "mean"), median_t_first_open=("t_first_open", "median"),
               pct_never_open=("t_first_open", lambda s: s.isna().mean()),
               pct_pressured=("t_pressure", lambda s: s.notna().mean()),
               median_t_throw=("t_throw", "median"),
               pct_target_open=("target_open_at_throw", lambda s: s.dropna().astype(float).mean()))
          .reset_index())
    return tb[tb.plays >= min_plays].sort_values("median_race_margin", ascending=False)


def race_curves(race, min_plays=MIN_COV_PLAYS, t_max=5.0, step=0.1):
    """Long table: coverage, t, p_open (>=1 receiver open by t), p_pressure (pressure arrived by t)."""
    grid = np.round(np.arange(0, t_max + 1e-9, step), 2)
    out = []
    for cov, g in race.dropna(subset=["coverage"]).groupby("coverage"):
        if len(g) < min_plays:
            continue
        o = g.t_first_open.to_numpy()
        p = g.t_pressure.to_numpy()
        po = [(o <= x).mean() for x in grid]   # NaN compares False = never open
        pp = [(p <= x).mean() for x in grid]
        out.append(pd.DataFrame(dict(coverage=cov, t=grid, p_open=po, p_pressure=pp, n=len(g))))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
