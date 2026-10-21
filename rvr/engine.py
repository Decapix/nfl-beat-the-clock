"""The race engine: one play in, every clock out. Used by build.py (batch) and app.py (on demand)."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

OPEN_SEP = 3.0       # yd to nearest coverage defender: the NGS "open" threshold
TIGHT_SEP = 1.5      # yd: below this the target is "covered"
MIN_DEPTH = 1.0      # yd past the LOS: kills "everyone is open at the snap"
PRESSURE_DIST = 2.0  # yd rusher -> QB: simple, honest geometry
FPS = 10             # tracking frame rate

SNAP_EVENTS = {"ball_snap", "autoevent_ballsnap"}
THROW_EVENTS = {"pass_forward", "autoevent_passforward"}
SACK_EVENTS = {"qb_sack", "qb_strip_sack"}


@dataclass
class PlayResult:
    t: np.ndarray                   # (nF,) seconds after snap
    rec_ids: np.ndarray             # (nR,) nflId of route runners
    rec_names: list
    rec_pos: list
    sep: np.ndarray                 # (nF, nR) yd to nearest Coverage defender
    open: np.ndarray                # (nF, nR) bool
    depth: np.ndarray               # (nF, nR) yd past LOS
    pressure_dist: np.ndarray       # (nF,) yd nearest rusher -> QB
    windows: list                   # per receiver: list of (start_s, end_s)
    frames: pd.DataFrame            # frameId, nflId, x, y, team, jerseyNumber, role, player for animation
    los_x: float
    qb_id: float
    qb_name: str
    target_idx: int | None
    summary: dict
    receivers: list = field(default_factory=list)   # rows of windows_by_receiver


def _first_time(t, mask):
    return float(t[np.argmax(mask)]) if mask.any() else np.nan


def _runs(mask):
    """Run-length encode a bool vector -> list of (start_idx, end_idx) inclusive."""
    m = np.r_[0, mask.astype(np.int8), 0]
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def _mat(sub, frames):
    """-> (nF, n, 2) x/y array aligned on frames, plus the nflId order."""
    if sub.empty:
        return np.empty((len(frames), 0, 2)), np.array([])
    piv = sub.pivot_table(index="frameId", columns="nflId", values=["x", "y"], aggfunc="first").reindex(frames)
    ids = piv["x"].columns.to_numpy()
    return np.stack([piv["x"].to_numpy(), piv["y"].to_numpy()], axis=-1), ids


def _min_dist(A, B):
    """(nF, a, 2), (nF, b, 2) -> (nF, a) distance from each A to its nearest B (NaN-safe)."""
    d = np.linalg.norm(A[:, :, None, :] - B[:, None, :, :], axis=-1)
    d = np.where(np.isnan(d), np.inf, d)
    return d.min(axis=2) if d.shape[2] else np.full(d.shape[:2], np.inf)


def analyze_play(trk_play, roles, target_nflId=None, open_sep=OPEN_SEP, min_depth=MIN_DEPTH,
                 pressure_dist=PRESSURE_DIST, tight_sep=TIGHT_SEP):
    """trk_play: flipped tracking of ONE play (all frames, ball included).
    roles: DataFrame nflId, pff_role, player, pos for that play.
    Returns PlayResult, or None if the play can't be timed (no snap, throw <= snap, no QB/receivers/coverage)."""
    ev = trk_play.loc[trk_play.event.notna(), ["frameId", "event"]]
    snap = ev.frameId[ev.event.isin(SNAP_EVENTS)].min()
    if pd.isna(snap):
        return None
    after = ev[ev.frameId > snap]
    throw = after.frameId[after.event.isin(THROW_EVENTS)].min()
    source = "pass"
    if pd.isna(throw):
        throw, source = after.frameId[after.event.isin(SACK_EVENTS)].min(), "sack"
    if pd.isna(throw):
        throw, source = trk_play.frameId.max(), "last"
    snap, throw = int(snap), int(throw)
    if throw <= snap:
        return None

    g = trk_play[(trk_play.frameId >= snap) & (trk_play.frameId <= throw)]
    g = g.merge(roles, on="nflId", how="left")
    frames = np.arange(snap, throw + 1)
    nF = len(frames)
    t = (frames - snap) / FPS

    R, rid = _mat(g[g.pff_role == "Pass Route"], frames)
    C, _ = _mat(g[g.pff_role == "Coverage"], frames)
    Q, qid = _mat(g[g.pff_role == "Pass"], frames)
    P, _ = _mat(g[g.pff_role == "Pass Rush"], frames)
    if len(rid) == 0 or C.shape[1] == 0 or Q.shape[1] == 0:
        return None
    Q, qb_id = Q[:, :1], qid[0]   # two "Pass" players (trick play): take the first

    ball = g[g.nflId.isna() & (g.frameId == snap)]
    los_x = float(ball.x.iloc[0]) if len(ball) else float(Q[0, 0, 0])

    sep = _min_dist(R, C)                                   # (nF, nR)
    depth = R[:, :, 0] - los_x
    is_open = (sep >= open_sep) & (depth >= min_depth)
    pdist = _min_dist(Q, P)[:, 0] if P.shape[1] else np.full(nF, np.inf)

    info = roles.set_index("nflId")
    names = [str(info.player.get(i, i)) for i in rid]
    pos = [str(info.pos.get(i, "")) for i in rid]
    qb_name = str(info.player.get(qb_id, ""))

    t_open_each = np.array([_first_time(t, is_open[:, j]) for j in range(len(rid))])
    t_first_open = float(np.nanmin(t_open_each)) if np.isfinite(t_open_each).any() else np.nan
    t_pressure = _first_time(t, pdist <= pressure_dist)
    t_throw = float(t[-1])
    t_pressure_eff = t_pressure if not np.isnan(t_pressure) else t_throw
    race_margin = t_pressure_eff - t_first_open

    sep_throw, open_throw = sep[-1], is_open[-1]
    tgt = None
    if target_nflId is not None and not pd.isna(target_nflId):
        hit = np.where(rid == target_nflId)[0]
        tgt = int(hit[0]) if len(hit) else None
    if tgt is not None:
        others = np.arange(len(rid)) != tgt
        if (others & open_throw).any():   # best alternative = most separated OPEN teammate, else most separated one
            others = others & open_throw
        alt_sep = np.where(others, np.where(np.isfinite(sep_throw), sep_throw, -1), -1)
        a = int(np.argmax(alt_sep))
        best_alt_sep = float(alt_sep[a]) if others.any() and alt_sep[a] >= 0 else np.nan
        best_alt_name = names[a] if not np.isnan(best_alt_sep) else None
        ignored = bool(sep_throw[tgt] < tight_sep and (open_throw & others).any())
    else:
        best_alt_sep, best_alt_name, ignored = np.nan, None, False

    windows = []
    receivers = []
    for j, nid in enumerate(rid):
        runs = [(float(t[s]), float(t[e])) for s, e in _runs(is_open[:, j])]
        windows.append(runs)
        longest = max(runs, key=lambda w: w[1] - w[0], default=(np.nan, np.nan))
        receivers.append(dict(
            nflId=nid, player=names[j], pos=pos[j], targeted=(j == tgt),
            t_open=t_open_each[j], open_share=float(is_open[:, j].mean()), n_windows=len(runs),
            longest_window_start=longest[0], longest_window_end=longest[1],
            longest_window_len=(longest[1] - longest[0] + 1 / FPS) if runs else 0.0,
            sep_at_throw=float(sep_throw[j]) if np.isfinite(sep_throw[j]) else np.nan,
            open_at_throw=bool(open_throw[j]),
            max_sep=float(np.nanmax(np.where(np.isfinite(sep[:, j]), sep[:, j], np.nan))) if np.isfinite(sep[:, j]).any() else np.nan,
        ))

    summary = dict(
        t_throw=t_throw, throw_source=source, is_sack=source == "sack",
        t_first_open=t_first_open, t_pressure=t_pressure, t_pressure_eff=t_pressure_eff,
        race_margin=race_margin, routes_won=bool(race_margin > 0) if not np.isnan(race_margin) else False,
        n_receivers=len(rid), n_open_at_throw=int(open_throw.sum()),
        qbNflId=qb_id, qb=qb_name,
        targetNflId=rid[tgt] if tgt is not None else np.nan,
        target=names[tgt] if tgt is not None else None,
        target_pos=pos[tgt] if tgt is not None else None,
        target_sep_at_throw=float(sep_throw[tgt]) if tgt is not None and np.isfinite(sep_throw[tgt]) else np.nan,
        target_open_at_throw=bool(open_throw[tgt]) if tgt is not None else np.nan,
        best_alt_sep_at_throw=best_alt_sep, best_alt_name=best_alt_name,
        open_man_ignored=ignored,
    )
    keep = ["frameId", "nflId", "x", "y", "team", "jerseyNumber", "pff_role", "player", "pos"]
    return PlayResult(t=t, rec_ids=rid, rec_names=names, rec_pos=pos, sep=sep, open=is_open, depth=depth,
                      pressure_dist=pdist, windows=windows, frames=g[[c for c in keep if c in g]].copy(),
                      los_x=los_x, qb_id=qb_id, qb_name=qb_name, target_idx=tgt, summary=summary,
                      receivers=receivers)


def story(res, desc_target=None):
    """One factual sentence built from the arrays."""
    bits = []
    t_end = res.t[-1]
    order = sorted(range(len(res.rec_ids)), key=lambda j: (res.windows[j][0][0] if res.windows[j] else 99))
    for j in order:
        w = res.windows[j]
        if not w:
            continue
        last = res.rec_names[j].split()[-1]
        spans = [f"from {a:.1f} s to the throw" if abs(b - t_end) < 1e-6 else f"{a:.1f}–{b:.1f} s" for a, b in w[:2]]
        bits.append(f"{last} was open " + " and ".join(spans))
        if len(bits) == 3:
            break
    if not bits:
        bits.append("no receiver got open before the throw")
    S = res.summary
    bits.append(f"pressure arrived at {S['t_pressure']:.1f} s" if not np.isnan(S["t_pressure"]) else "pressure never arrived")
    qb = res.qb_name.split()[-1] if res.qb_name else "the QB"
    if S["throw_source"] == "sack":
        bits.append(f"{qb} was sacked at {S['t_throw']:.1f} s")
    elif res.target_idx is not None:
        j = res.target_idx
        state = "an open" if res.open[-1, j] else ("a covered" if res.sep[-1, j] < TIGHT_SEP else "a tightly-contested")
        bits.append(f"{qb} threw to {state} {res.rec_names[j].split()[-1]} at {S['t_throw']:.1f} s")
    else:
        bits.append(f"{qb} released the ball at {S['t_throw']:.1f} s")
    return "; ".join(bits[:-1]) + "; " + bits[-1] + "."
