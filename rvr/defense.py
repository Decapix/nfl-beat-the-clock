"""Defensive side of one play: coverage call, personnel, who rushed, and who was actually covering whom.
'Covering' is a proximity proxy: the coverage defender who was nearest to the receiver most often from 0.5 s
after the snap until the throw (the first half second is everyone standing on the line)."""
import numpy as np
import pandas as pd

SETTLE_S = 0.5   # ignore the first half second when deciding who covers whom


def _mat(sub, frames):
    piv = sub.pivot_table(index="frameId", columns="nflId", values=["x", "y"], aggfunc="first").reindex(frames)
    ids = piv["x"].columns.to_numpy()
    return np.stack([piv["x"].to_numpy(), piv["y"].to_numpy()], axis=-1), ids


def matchups(res, pff_play):
    """res: engine.PlayResult. pff_play: pffScoutingData rows of this play (needs nflId, pff_positionLinedUp).
    -> DataFrame, one row per receiver: primary defender, share of frames he was nearest, defender at the throw."""
    fr = res.frames
    frames = np.sort(fr.frameId.unique())
    R, rid = _mat(fr[fr.pff_role == "Pass Route"], frames)
    C, cid = _mat(fr[fr.pff_role == "Coverage"], frames)
    if len(cid) == 0 or len(rid) == 0:
        return pd.DataFrame()
    d = np.linalg.norm(R[:, :, None, :] - C[:, None, :, :], axis=-1)      # (nF, nR, nC)
    d = np.where(np.isnan(d), np.inf, d)
    nearest = d.argmin(axis=2)                                            # (nF, nR)
    settle = res.t >= SETTLE_S
    if not settle.any():
        settle[:] = True

    who = fr.drop_duplicates("nflId").set_index("nflId")
    lined = pff_play.drop_duplicates("nflId").set_index("nflId").get("pff_positionLinedUp", pd.Series(dtype=object))
    rows = []
    order = {n: j for j, n in enumerate(res.rec_ids)}
    for j, r in enumerate(rid):
        counts = np.bincount(nearest[settle, j], minlength=len(cid))
        k = int(counts.argmax())
        prim, share = cid[k], counts[k] / counts.sum()
        at_throw = cid[nearest[-1, j]]
        jj = order.get(r)
        rows.append(dict(
            nflId=r,
            receiver=str(who.player.get(r, r)), rec_pos=str(who.pos.get(r, "")),
            defender=str(who.player.get(prim, prim)), def_pos=str(who.pos.get(prim, "")),
            lined_up=str(lined.get(prim, "")) if len(lined) else "",
            share_nearest=float(share),
            defender_at_throw=str(who.player.get(at_throw, at_throw)),
            sep_at_throw=float(res.sep[-1, jj]) if jj is not None and np.isfinite(res.sep[-1, jj]) else np.nan,
            open_at_throw=bool(res.open[-1, jj]) if jj is not None else False,
            targeted=(jj == res.target_idx),
        ))
    out = pd.DataFrame(rows)
    # same defender nearest to two receivers = zone / bracket territory, flag it
    out["shared"] = out.defender.duplicated(keep=False)
    return out.sort_values(["targeted", "sep_at_throw"], ascending=[False, False])


def rush_summary(pff_play, players):
    """Who rushed (lined-up spots) and who got credited with a hit / hurry / sack."""
    p = pff_play.merge(players[["nflId", "displayName"]], on="nflId", how="left")
    rush = p[p.pff_role == "Pass Rush"]
    spots = rush.pff_positionLinedUp.dropna().tolist() if "pff_positionLinedUp" in rush else []
    credit = []
    for col, word in [("pff_sack", "sack"), ("pff_hit", "hit"), ("pff_hurry", "hurry")]:
        if col in rush:
            for n in rush.loc[rush[col] == 1, "displayName"]:
                credit.append(f"{word} by {n}")
    return dict(n_rush=len(rush), spots=spots, credit=credit,
                n_cov=int((p.pff_role == "Coverage").sum()))
