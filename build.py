"""Batch: every dropback in the chosen weeks -> outputs/.   python build.py [--weeks 1 2 ...] [--workers N]"""
import argparse
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from rvr import io, metrics, plots
from rvr.engine import analyze_play

OUT = "outputs"
KEEP_RESULTS = {"C", "I", "IN", "S"}   # scrambles (R) dropped

PLAY_COLS = ["gameId", "playId", "week", "possessionTeam", "defensiveTeam", "qb", "down", "yardsToGo",
             "passResult", "is_sack", "yards", "coverage", "covType", "dropBackType", "t_throw", "throw_source",
             "t_first_open", "t_pressure", "t_pressure_eff", "race_margin", "routes_won", "n_receivers",
             "n_open_at_throw", "targetNflId", "target", "target_pos", "target_sep_at_throw",
             "target_open_at_throw", "best_alt_sep_at_throw", "best_alt_name", "open_man_ignored",
             "playDescription"]
WIN_COLS = ["gameId", "playId", "nflId", "player", "pos", "team", "targeted", "t_open", "open_share", "n_windows",
            "longest_window_start", "longest_window_end", "longest_window_len", "sep_at_throw", "open_at_throw",
            "max_sep"]


def process_game(args):
    gid, plays_g, pff_g, players = args
    trk = io.load_game(gid)
    roles_all = io.roles_for(pff_g, players)
    team_of = trk.dropna(subset=["nflId"]).drop_duplicates("nflId").set_index("nflId").team
    rows, recs = [], []
    by_play = dict(tuple(trk.groupby("playId", sort=False)))
    for pr in plays_g.itertuples(index=False):
        tp = by_play.get(pr.playId)
        if tp is None:
            continue
        roles = roles_all[roles_all.playId == pr.playId][["nflId", "pff_role", "player", "pos"]]
        res = analyze_play(tp, roles, pr.targetNflId)
        if res is None:
            continue
        rows.append(dict(gameId=gid, playId=pr.playId, **res.summary))
        for r in res.receivers:
            recs.append(dict(gameId=gid, playId=pr.playId, team=team_of.get(r["nflId"]), **r))
    return rows, recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, nargs="+", default=list(range(1, 9)))
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    t0 = time.time()

    games, plays, players, pff = io.load_meta()
    targets, rate = io.parse_targets(plays, players, pff)
    plays = plays.merge(targets, on=["gameId", "playId"], how="left")
    plays = plays[plays.passResult.isin(KEEP_RESULTS) & plays.week.isin(a.weeks)]
    gids = games.loc[games.week.isin(a.weeks), "gameId"].tolist()
    tasks = [(g, plays[plays.gameId == g], pff[pff.gameId == g], players) for g in gids]
    logging.info("%d games, %d dropbacks, %d workers", len(gids), len(plays), a.workers)

    rows, recs = [], []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for r, w in ex.map(process_game, tasks):
            rows += r
            recs += w
    race = pd.DataFrame(rows)
    meta = plays[["gameId", "playId", "week", "possessionTeam", "defensiveTeam", "down", "yardsToGo", "passResult",
                  "playResult", "pff_passCoverage", "pff_passCoverageType", "dropBackType", "playDescription"]]
    race = race.merge(meta, on=["gameId", "playId"], how="left").rename(
        columns={"playResult": "yards", "pff_passCoverage": "coverage", "pff_passCoverageType": "covType"})
    race["is_sack"] = race.passResult.eq("S")
    race.loc[race.is_sack, ["targetNflId", "target", "target_pos"]] = np.nan
    race = race[PLAY_COLS + ["qbNflId"]]
    win = pd.DataFrame(recs)[WIN_COLS]

    os.makedirs(OUT, exist_ok=True)
    race.to_parquet(f"{OUT}/race_by_play.parquet", index=False)
    race.to_csv(f"{OUT}/race_by_play.csv", index=False)
    win.to_parquet(f"{OUT}/windows_by_receiver.parquet", index=False)
    metrics.receiver_leaderboard(win, race).to_csv(f"{OUT}/receiver_leaderboard.csv", index=False)
    metrics.qb_leaderboard(race).to_csv(f"{OUT}/qb_leaderboard.csv", index=False)
    metrics.coverage_table(race).to_csv(f"{OUT}/coverage_table.csv", index=False)
    logging.info("wrote %d plays, %d receiver-plays in %.0f s", len(race), len(win), time.time() - t0)
    sanity(race, rate)


def sanity(race, rate):
    trad = race[race.dropBackType == "TRADITIONAL"]
    ns = race[~race.is_sack]
    thr = ns[ns.target.notna()]
    checks = [
        ("median t_throw TRADITIONAL (2.5-2.9 s)", trad.t_throw.median()),
        ("throw_source=='pass' on non-sacks (>=90%)", ns.throw_source.eq("pass").mean()),
        ("target match rate C/I/IN (>=90%)", rate),
        ("target open at throw (40-60%)", thr.target_open_at_throw.astype(float).mean()),
        ("pressure before throw (30-45%)", race.t_pressure.notna().mean()),
        ("open_man_ignored on throws (8-15%)", thr.open_man_ignored.mean()),
    ]
    print("\n== sanity checks ==")
    for k, v in checks:
        print(f"  {k:45s} {v:.3f}")


if __name__ == "__main__":
    main()
