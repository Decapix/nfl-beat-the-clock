"""Loading + cleaning: metadata, per-game tracking (flipped left->right), targets parsed from play text."""
import logging
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("RVR_DATA", Path(__file__).resolve().parent.parent / "data"))
log = logging.getLogger("rvr")

TARGET_RE = r"(?:to|for)\s+([A-Z]\.\s?[A-Za-z'\-]+)"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def short_name(n):
    """'Amari Cooper' -> 'a.cooper', 'Odell Beckham Jr.' -> 'o.beckham', 'D.K. Metcalf' -> 'd.metcalf'."""
    parts = [p for p in str(n).replace(".", " ").split() if p]
    while len(parts) > 1 and parts[-1].lower() in SUFFIXES:
        parts = parts[:-1]
    if not parts:
        return ""
    return f"{parts[0][0]}.{parts[-1]}".lower()


def load_meta():
    games = pd.read_csv(DATA / "games.csv")
    plays = pd.read_csv(DATA / "plays.csv")
    players = pd.read_csv(DATA / "players.csv")
    pff = pd.read_csv(DATA / "pffScoutingData.csv", usecols=["gameId", "playId", "nflId", "pff_role"])
    players["short"] = players.displayName.map(short_name)
    games["label"] = games.visitorTeamAbbr + " @ " + games.homeTeamAbbr
    plays = plays.merge(games[["gameId", "week"]], on="gameId", how="left")
    return games, plays, players, pff


def flip(trk):
    """Offense always moves left -> right: flip x AND y when playDirection == 'left' (ball rows too)."""
    trk = trk.copy()
    left = trk.playDirection.eq("left")
    trk.loc[left, "x"] = 120 - trk.loc[left, "x"]
    trk.loc[left, "y"] = 53.3 - trk.loc[left, "y"]
    return trk


def load_game(gameId):
    trk = pd.read_csv(DATA / "tracking" / f"tracking_{int(gameId)}.csv",
                      usecols=["gameId", "playId", "nflId", "frameId", "jerseyNumber", "team",
                               "playDirection", "x", "y", "event"])
    trk["event"] = trk.event.replace("None", np.nan)
    return flip(trk)


def roles_for(pff_play, players):
    """pff rows of one play/game -> nflId, pff_role, player, pos (+ gameId/playId)."""
    r = pff_play.merge(players[["nflId", "displayName", "officialPosition"]], on="nflId", how="left")
    return r.rename(columns={"displayName": "player", "officialPosition": "pos"})


def parse_targets(plays, players, pff):
    """targetNflId per (gameId, playId): regex on playDescription, matched against that play's route runners.
    0 or >= 2 matches -> NaN."""
    tok = (plays.playDescription.str.extract(TARGET_RE)[0]
           .str.replace(" ", "", regex=False).str.lower())
    tok = tok.str.replace(r"\.(jr|sr|ii|iii|iv)$", "", regex=True)
    cand = (pff[pff.pff_role == "Pass Route"][["gameId", "playId", "nflId"]]
            .merge(players[["nflId", "short", "displayName"]], on="nflId", how="left"))
    # fallback key for multi-word last names ('A.St. Brown' -> token 'a.st'): first initial + first word after it
    cand["short2"] = cand.displayName.map(
        lambda n: (lambda p: f"{p[0][0]}.{p[1]}".lower() if len(p) > 1 else "")(str(n).replace(".", " ").split()))
    q = plays[["gameId", "playId"]].assign(tok=tok.values)
    m = q.dropna(subset=["tok"]).merge(cand, on=["gameId", "playId"], how="inner")
    m = m[(m.short == m.tok) | ((m.short2 == m.tok) & (m.short != m.tok))]
    exact = m[m.short == m.tok]
    m = pd.concat([exact, m[~m.set_index(["gameId", "playId"]).index.isin(exact.set_index(["gameId", "playId"]).index)]])
    counts = m.groupby(["gameId", "playId"]).nflId.transform("size")
    m = m[counts == 1]
    out = q.merge(m[["gameId", "playId", "nflId"]], on=["gameId", "playId"], how="left").rename(columns={"nflId": "targetNflId"})
    pas = plays.passResult.isin(["C", "I", "IN"]).values
    rate = out.targetNflId[pas].notna().mean()
    log.info("target match rate on C/I/IN plays: %.1f%%", 100 * rate)
    return out[["gameId", "playId", "targetNflId"]], rate
