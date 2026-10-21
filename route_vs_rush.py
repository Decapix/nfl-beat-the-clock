"""
ROUTE vs RUSH — open-window clock for every dropback (BDB regional event data, 2021 wk1-8).

For each pass play, frame by frame from snap to throw:
  * each route runner's separation = distance to nearest Coverage defender
  * "open window" = separation >= OPEN_SEP and receiver past the line of scrimmage
  * pressure clock  = first frame a Pass Rusher is within PRESSURE_DIST of the QB
Outputs: per-play race table, per-receiver and per-QB leaderboards, one Gantt chart per play.

Usage:  python route_vs_rush.py            (edit WEEKS below; start with [1], scale to range(1, 9))
"""
import re, glob
import numpy as np, pandas as pd
import matplotlib.pyplot as plt

DATA = "data"
WEEKS = [1]                 # start small, then range(1, 9)
OPEN_SEP = 3.0              # yds: NGS calls >= 3 yds "open"
TIGHT_SEP = 1.5             # yds: "covered"
PRESSURE_DIST = 2.0         # yds rusher->QB
FPS = 10

games = pd.read_csv(f"{DATA}/games.csv")
plays = pd.read_csv(f"{DATA}/plays.csv")
players = pd.read_csv(f"{DATA}/players.csv")
pff = pd.read_csv(f"{DATA}/pffScoutingData.csv")[["gameId", "playId", "nflId", "pff_role", "pff_blockType"]]

# ---------- 1. tracking for the chosen weeks, flipped so offense always goes left -> right ----------
gids = games.loc[games.week.isin(WEEKS), "gameId"].tolist()
trk = pd.concat([pd.read_csv(f"{DATA}/tracking/tracking_{g}.csv") for g in gids], ignore_index=True)
left = trk.playDirection.eq("left")
trk.loc[left, "x"] = 120 - trk.loc[left, "x"]
trk.loc[left, "y"] = 53.3 - trk.loc[left, "y"]
trk = trk.merge(pff, on=["gameId", "playId", "nflId"], how="left")
trk = trk.merge(players[["nflId", "displayName", "officialPosition"]], on="nflId", how="left")

# ---------- 2. targeted receiver, parsed from the play description (~95% of pass plays) ----------
def short_name(n):
    parts = str(n).replace(".", "").split()
    last = parts[-1] if parts[-1] not in {"Jr", "Sr", "II", "III", "IV"} else parts[-2]
    return f"{parts[0][0]}.{last}".lower()
players["short"] = players.displayName.map(short_name)
plays["target_short"] = (plays.playDescription
                         .str.extract(r"(?:to|for)\s+([A-Z]\.\s?[A-Za-z'\-]+)")[0]
                         .str.replace(" ", "").str.lower())

# ---------- 3. per-play engine ----------
rows, rec_rows = [], []
for (gid, pid), g in trk.groupby(["gameId", "playId"], sort=False):
    ev = g.groupby("frameId").event.first()
    snap = ev[ev.isin(["ball_snap", "autoevent_ballsnap"])].index.min()
    throw = ev[ev.isin(["pass_forward", "autoevent_passforward", "qb_sack", "qb_strip_sack", "run"])].index.min()
    if pd.isna(snap) or pd.isna(throw) or throw <= snap:
        continue
    g = g[(g.frameId >= snap) & (g.frameId <= throw)]
    frames = np.arange(snap, throw + 1)
    nF = len(frames)

    def mat(sub):  # -> (nF, n, 2) array of x,y for players in sub, aligned on frames
        piv = sub.pivot(index="frameId", columns="nflId", values=["x", "y"]).reindex(frames)
        ids = piv["x"].columns.to_numpy()
        return np.stack([piv["x"].to_numpy(), piv["y"].to_numpy()], axis=-1), ids

    R, rid = mat(g[g.pff_role == "Pass Route"])
    C, _ = mat(g[g.pff_role == "Coverage"])
    Q, _ = mat(g[g.pff_role == "Pass"])
    P, _ = mat(g[g.pff_role == "Pass Rush"])
    if len(rid) == 0 or C.shape[1] == 0 or Q.shape[1] == 0:
        continue
    ball = g[g.nflId.isna() & (g.frameId == snap)]
    los_x = ball.x.iloc[0] if len(ball) else Q[0, 0, 0]

    sep = np.linalg.norm(R[:, :, None, :] - C[:, None, :, :], axis=-1).min(axis=2)   # (nF, nRoutes)
    depth = R[:, :, 0] - los_x
    is_open = (sep >= OPEN_SEP) & (depth > 1.0)   # >1 yd past LOS kills the "open at the snap" artifact
    pressure = (np.linalg.norm(P[:, :, None, :] - Q[:, None, :, :], axis=-1).min(axis=(1, 2))
                if P.shape[1] else np.full(nF, 99.0))
    t = (frames - snap) / FPS

    def first_time(mask):
        i = np.argmax(mask) if mask.any() else -1
        return t[i] if i >= 0 else np.nan

    t_open = first_time(is_open.any(axis=1))
    t_press = first_time(pressure <= PRESSURE_DIST)
    t_press_eff = t_press if not np.isnan(t_press) else t[-1]      # no pressure before the throw = rush lost the race
    pr = plays.loc[(plays.gameId == gid) & (plays.playId == pid)].iloc[0]
    tgt_short = pr.target_short
    names = players.set_index("nflId").loc[rid]
    tgt_idx = np.where(names.short.to_numpy() == tgt_short)[0]
    tgt_idx = tgt_idx[0] if len(tgt_idx) else None
    sep_throw, open_throw = sep[-1], is_open[-1]
    best_alt = np.nanmax(np.where(np.arange(len(rid)) != tgt_idx, sep_throw, -1)) if tgt_idx is not None else np.nan

    rows.append(dict(gameId=gid, playId=pid, qb=pr.playDescription.split(" pass")[0].split(" ")[-1] if " pass" in pr.playDescription else None,
                     possessionTeam=pr.possessionTeam, coverage=pr.pff_passCoverage, covType=pr.pff_passCoverageType,
                     passResult=pr.passResult, yards=pr.prePenaltyPlayResult, time_to_throw=t[-1],
                     t_first_open=t_open, t_first_pressure=t_press, race_margin=t_press_eff - t_open,
                     n_open_at_throw=int(open_throw.sum()),
                     target=names.displayName.iloc[tgt_idx] if tgt_idx is not None else None,
                     target_sep_at_throw=sep_throw[tgt_idx] if tgt_idx is not None else np.nan,
                     best_alt_sep_at_throw=best_alt,
                     open_man_ignored=bool(tgt_idx is not None and sep_throw[tgt_idx] < TIGHT_SEP and open_throw.sum() > 0)))
    for j, nid in enumerate(rid):
        rec_rows.append(dict(gameId=gid, playId=pid, nflId=nid, player=names.displayName.iloc[j], pos=names.officialPosition.iloc[j],
                             targeted=(j == tgt_idx), t_first_open=first_time(is_open[:, j]),
                             open_share=is_open[:, j].mean(), sep_at_throw=sep_throw[j],
                             open_at_throw=bool(open_throw[j]), sep_curve=sep[:, j], open_curve=is_open[:, j], t=t,
                             pressure_curve=pressure))

play_df = pd.DataFrame(rows)
rec_df = pd.DataFrame(rec_rows)

# ---------- 4. leaderboards ----------
rec_lb = (rec_df[rec_df.pos.isin(["WR", "TE", "RB"])]
          .groupby(["player", "pos"]).agg(routes=("playId", "size"), targets=("targeted", "sum"),
                                        median_t_open=("t_first_open", "median"),
                                        open_share=("open_share", "mean"),
                                        open_at_throw_rate=("open_at_throw", "mean"))
          .query("routes >= 15").sort_values("median_t_open"))
rec_lb["open_not_targeted"] = (rec_df[rec_df.open_at_throw & ~rec_df.targeted]
                               .groupby(["player", "pos"]).size().reindex(rec_lb.index).fillna(0).astype(int))
qb_lb = (play_df.groupby("qb").agg(dropbacks=("playId", "size"), avg_ttt=("time_to_throw", "mean"),
                                   routes_win_race=("race_margin", lambda s: (s > 0).mean()),
                                   threw_to_open=("target_sep_at_throw", lambda s: (s >= OPEN_SEP).mean()),
                                   open_man_ignored=("open_man_ignored", "mean"))
         .query("dropbacks >= 20").sort_values("open_man_ignored"))
play_df.to_csv("race_by_play.csv", index=False); rec_lb.to_csv("receiver_leaderboard.csv"); qb_lb.to_csv("qb_leaderboard.csv")
print(rec_lb.head(10).round(2)); print(qb_lb.round(2))

# ---------- 5. the chart a coach reads in 5 seconds: open windows vs pressure clock ----------
def plot_play(gid, pid, out=None):
    r = rec_df[(rec_df.gameId == gid) & (rec_df.playId == pid)].sort_values("pos")
    p = play_df[(play_df.gameId == gid) & (play_df.playId == pid)].iloc[0]
    fig, ax = plt.subplots(figsize=(10, 0.6 * len(r) + 1.8))
    for k, (_, row) in enumerate(r.iterrows()):
        t, o = row.t, row.open_curve
        starts = np.where(np.diff(np.r_[0, o.astype(int)]) == 1)[0]; ends = np.where(np.diff(np.r_[o.astype(int), 0]) == -1)[0]
        ax.broken_barh([(t[s], t[e] - t[s] + 0.1) for s, e in zip(starts, ends)], (k - 0.35, 0.7),
                       color="#2ca02c" if not row.targeted else "#1f77b4")
        ax.text(-0.05, k, f"{row.player} ({row.pos}){' ◀ target' if row.targeted else ''}", ha="right", va="center", fontsize=9)
    pr = r.iloc[0].pressure_curve; t = r.iloc[0].t
    ax.fill_between(t, -0.8, -0.5, where=pr <= PRESSURE_DIST, color="#d62728", step="post", label="pressure (rusher ≤ 2 yd)")
    ax.axvline(p.time_to_throw, color="k", ls="--", label="throw / sack")
    ax.set_ylim(-1, len(r) - 0.4); ax.set_yticks([]); ax.set_xlabel("seconds after snap"); ax.set_xlim(0, p.time_to_throw + 0.3)
    ax.set_title(f"{p.possessionTeam} vs {p.coverage} — open windows (green ≥ {OPEN_SEP} yd) vs pressure clock", fontsize=10)
    ax.legend(loc="lower right", fontsize=8); plt.subplots_adjust(left=0.28)
    if out: plt.savefig(out, dpi=150)
    return fig

# example: the play where the QB most clearly ignored an open man
ex = play_df[play_df.open_man_ignored].sort_values("best_alt_sep_at_throw", ascending=False).iloc[0]
plot_play(ex.gameId, ex.playId, out="example_play.png")
print("\nexample:", plays.set_index(["gameId", "playId"]).loc[(ex.gameId, ex.playId), "playDescription"])
