"""Linked play viewer: one shared clock drives the Gantt, the distance chart and the field.
Click a player anywhere (chip, Gantt row, distance line, field dot) to highlight him everywhere;
click or drag on the Gantt / distance chart (or the slider) to move the clock."""
import json

import numpy as np
import pandas as pd

from . import plots as P
from .engine import FPS

MAX_FLIGHT = 3.0      # s: cap on the projected ball flight
MIN_BALL_SPEED = 12   # yd/s: floor when the measured release speed is noisy


def _r(a, nd=2):
    return [None if (v is None or not np.isfinite(v)) else round(float(v), nd) for v in a]


def _project(X, Y, ball, tgt_col, n_real):
    """Extend positions past the last tracked frame: everyone keeps his last velocity, the ball flies
    in a straight line to where the target will be. Returns extra frames (players, ball)."""
    vx = (X[-1] - X[-2]) * FPS
    vy = (Y[-1] - Y[-2]) * FPS
    b0 = ball[-1]
    vb = max(np.hypot(*(ball[-1] - ball[-2])) * FPS, MIN_BALL_SPEED)
    T = 1.0
    for _ in range(5):   # solve |target(T) - ball0| = vb * T
        tx, ty = X[-1, tgt_col] + vx[tgt_col] * T, Y[-1, tgt_col] + vy[tgt_col] * T
        T = min(np.hypot(tx - b0[0], ty - b0[1]) / vb, MAX_FLIGHT)
    n = max(int(np.ceil(T * FPS)), 1)
    s = np.arange(1, n + 1) / FPS
    PX = X[-1][None, :] + vx[None, :] * s[:, None]
    PY = Y[-1][None, :] + vy[None, :] * s[:, None]
    end = np.array([X[-1, tgt_col] + vx[tgt_col] * T, Y[-1, tgt_col] + vy[tgt_col] * T])
    B = b0[None, :] + (end - b0)[None, :] * (np.arange(1, n + 1) / n)[:, None]
    return np.nan_to_num(PX, nan=np.nan), PY, B


def payload(res, trk_play, roles, open_sep, pressure_dist, project=True):
    snap = int(res.frames.frameId.min())
    g = trk_play[trk_play.frameId >= snap].merge(roles, on="nflId", how="left")
    frames = np.sort(g.frameId.unique())
    nE = len(res.t)                                         # engine frames: snap..throw
    people = g[g.nflId.notna()]
    X = people.pivot_table(index="frameId", columns="nflId", values="x", aggfunc="first").reindex(frames)
    Y = people.pivot_table(index="frameId", columns="nflId", values="y", aggfunc="first").reindex(frames)
    ids = X.columns.to_numpy()
    X, Y = X.to_numpy(), Y.to_numpy()
    b = g[g.nflId.isna()].groupby("frameId")[["x", "y"]].first().reindex(frames)
    ball = b.to_numpy()
    if np.isnan(ball).all():
        ball = np.full((len(frames), 2), np.nan)
    ball = pd.DataFrame(ball).ffill().bfill().to_numpy()

    info = people.drop_duplicates("nflId").set_index("nflId")
    off_team = info.team.get(res.qb_id)
    t = list((frames - snap) / FPS)
    n_real = len(frames)
    tgt_id = res.rec_ids[res.target_idx] if res.target_idx is not None else None
    if project and tgt_id is not None and n_real >= 2 and res.summary["throw_source"] == "pass":
        col = int(np.where(ids == tgt_id)[0][0])
        PX, PY, PB = _project(X, Y, ball, col, n_real)
        X, Y, ball = np.vstack([X, PX]), np.vstack([Y, PY]), np.vstack([ball, PB])
        t += [t[-1] + (i + 1) / FPS for i in range(len(PX))]

    rec_col = {nid: j for j, nid in enumerate(res.rec_ids)}
    players = []
    for i, nid in enumerate(ids):
        side = "off" if info.team.get(nid) == off_team else "def"
        role = str(info.pff_role.get(nid, ""))
        j = rec_col.get(nid)
        players.append(dict(
            id=int(nid), name=str(info.player.get(nid, "")), pos=str(info.pos.get(nid, "")),
            jersey=int(info.jerseyNumber.get(nid, 0) or 0), side=side, role=role,
            x=_r(X[:, i]), y=_r(Y[:, i]),
            rec=j, qb=bool(nid == res.qb_id), target=bool(nid == tgt_id),
        ))
    order = P.receiver_order(res)
    receivers = [dict(j=j, id=int(res.rec_ids[j]), name=res.rec_names[j], pos=res.rec_pos[j],
                      target=(j == res.target_idx), windows=res.windows[j],
                      sep=_r(np.where(np.isfinite(res.sep[:, j]), np.minimum(res.sep[:, j], 15), np.nan), 2),
                      open=[bool(v) for v in res.open[:, j]]) for j in order]
    prs = [(float(res.t[s]), float(res.t[e])) for s, e in P._runs(res.pressure_dist <= pressure_dist)]
    return dict(
        t=_r(t, 1), n_engine=nE, n_real=n_real, t_throw=float(res.t[-1]),
        throw_source=res.summary["throw_source"], los=round(res.los_x, 2),
        ball=dict(x=_r(ball[:, 0]), y=_r(ball[:, 1])),
        players=players, receivers=receivers, pressure=prs,
        pdist=_r(np.where(np.isfinite(res.pressure_dist), np.minimum(res.pressure_dist, 15), np.nan)),
        open_sep=open_sep, pressure_dist=pressure_dist, qb_id=int(res.qb_id),
        target_id=int(tgt_id) if tgt_id is not None else None,
        colors=dict(open=P.OPEN, covered=P.COVERED, target=P.TARGET, pressure=P.PRESSURE, throw=P.THROW,
                    off=P.OFFENSE, deff=P.DEFENSE, ball=P.BALL, turf=P.TURF, bg=P.BG, panel=P.PANEL,
                    text=P.TEXT, muted=P.MUTED, hi="#F5C542"),
    )


def render(data):
    return HTML.replace("__DATA__", json.dumps(data, allow_nan=False))


HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
:root{--bg:#0B1117;--panel:#141C26;--text:#E6EDF3;--muted:#8B98A5;--line:#1E2833;--hi:#F5C542;--open:#2ECC71}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 "Source Sans Pro",system-ui,sans-serif}
.bar{display:flex;align-items:center;gap:12px;padding:8px 10px;background:var(--panel);border-radius:8px;position:sticky;top:0;z-index:5}
button{background:#1E2833;color:var(--text);border:1px solid #2A3644;border-radius:6px;padding:5px 12px;cursor:pointer;font:inherit}
button:hover{border-color:var(--open)}
#play{min-width:74px}
#slider{flex:1;accent-color:var(--open);height:22px}
#tlabel{font-variant-numeric:tabular-nums;min-width:150px;text-align:right}
.phase{font-size:11px;padding:2px 8px;border-radius:10px;background:#1E2833;color:var(--muted);white-space:nowrap}
.phase.air{background:#3a3212;color:var(--hi)} .phase.proj{background:#2a2335;color:#C4B5FD}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{font-size:12px;padding:3px 10px;border-radius:14px;border:1px solid #2A3644;background:transparent}
.chip.on{border-color:var(--hi);color:var(--hi);background:#2a2410}
.chip .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.grid{display:grid;grid-template-columns:3fr 2fr;gap:12px}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:4px}
#info{min-height:22px;margin:4px 2px 0;color:var(--muted)} #info b{color:var(--text)}
.scrub{cursor:ew-resize}
.hint{font-size:11px;color:var(--muted);margin:2px 4px}
</style></head><body>
<div class="bar">
  <button id="play">▶ play</button>
  <input id="slider" type="range" min="0" value="0" step="1">
  <span id="phase" class="phase">routes developing</span>
  <span id="tlabel">t = 0.0 s</span>
</div>
<div class="chips" id="chips"></div>
<div id="info">Click a player (chip, timeline row, distance line or dot on the field) to follow him.</div>
<div class="grid">
  <div>
    <div class="card"><div id="gantt" class="scrub"></div></div>
    <div class="hint">Click or drag on either chart to move the clock.</div>
    <div class="card" style="margin-top:6px"><div id="dist" class="scrub"></div></div>
  </div>
  <div><div class="card"><div id="field"></div></div>
    <div class="hint" id="fieldhint"></div></div>
</div>
<script>
const D = __DATA__;
const C = D.colors, N = D.t.length, tEnd = D.t[N-1];
let k = 0, sel = null, timer = null;
const cfg = {displayModeBar:false, responsive:true};
const byId = {}; D.players.forEach(p => byId[p.id] = p);
const recs = D.receivers;
const fmt = v => (v==null ? "—" : v.toFixed(1));
const last = s => s.split(" ").slice(-1)[0];
const baseLayout = (h, extra) => Object.assign({paper_bgcolor:C.bg, plot_bgcolor:C.bg, height:h,
  font:{color:C.text, family:"Source Sans Pro, sans-serif", size:12}, showlegend:false, dragmode:false,
  hovermode:"closest", margin:{l:10,r:10,t:30,b:36}}, extra);
const cursor = x => ({type:"line", xref:"x", yref:"paper", x0:x, x1:x, y0:0, y1:1, line:{color:C.hi, width:2}});

// ---------- chips
const chips = document.getElementById("chips");
function chip(p, label, color){
  const b = document.createElement("button"); b.className = "chip"; b.dataset.id = p.id;
  b.innerHTML = `<span class="dot" style="background:${color}"></span>${label}`;
  b.onclick = () => select(sel === p.id ? null : p.id); chips.appendChild(b);
}
const qb = byId[D.qb_id];
if (qb) chip(qb, `${last(qb.name)} (QB)`, C.off);
recs.forEach(r => chip(byId[r.id] || r, `${last(r.name)} (${r.pos})${r.target ? " ◀ target" : ""}`, r.target ? C.target : C.open));

// ---------- Gantt
const rows = ["Pressure"].concat(recs.map(r => `${last(r.name)} (${r.pos})${r.target ? " ◀" : ""}`)).reverse();
function ganttTraces(){
  const tr = [];
  const labels = recs.map(r => `${last(r.name)} (${r.pos})${r.target ? " ◀" : ""}`);
  tr.push({type:"bar", orientation:"h", y:labels.concat(["Pressure"]), x:labels.map(()=>D.t_throw+0.1).concat([D.t_throw+0.1]),
    base:0, marker:{color:C.covered}, opacity:0.35, width:0.6, customdata:recs.map(r=>r.id).concat([D.qb_id]),
    hoverinfo:"skip"});
  recs.forEach((r, i) => {
    if (!r.windows.length) return;
    const on = sel === null || sel === r.id;
    tr.push({type:"bar", orientation:"h", y:r.windows.map(()=>labels[i]), base:r.windows.map(w=>w[0]),
      x:r.windows.map(w=>w[1]-w[0]+0.1), width:0.6, customdata:r.windows.map(()=>r.id),
      marker:{color:r.target ? C.target : C.open, line:{color:C.hi, width: sel===r.id ? 2 : 0}}, opacity: on ? 1 : 0.3,
      hovertemplate:`${r.name} (${r.pos})<br>open from %{base:.1f} s<extra></extra>`});
  });
  if (D.pressure.length) tr.push({type:"bar", orientation:"h", y:D.pressure.map(()=>"Pressure"),
    base:D.pressure.map(w=>w[0]), x:D.pressure.map(w=>w[1]-w[0]+0.1), width:0.6, marker:{color:C.pressure},
    customdata:D.pressure.map(()=>D.qb_id), hovertemplate:"rusher within "+D.pressure_dist+" yd of QB from %{base:.1f} s<extra></extra>"});
  return tr;
}
function ganttLayout(){
  const sh = [cursor(D.t[k]),
    {type:"line", xref:"x", yref:"paper", x0:D.t_throw, x1:D.t_throw, y0:0, y1:1, line:{color:C.throw, dash:"dash", width:1.5}}];
  if (tEnd > D.t_throw) sh.push({type:"rect", xref:"x", yref:"paper", x0:D.t_throw, x1:tEnd+0.05, y0:0, y1:1,
    fillcolor:C.hi, opacity:0.06, line:{width:0}, layer:"below"});
  return baseLayout(110 + 34*(recs.length+1), {barmode:"overlay", bargap:0.3, shapes:sh,
    title:{text:"Open windows vs pressure clock", font:{size:13}, x:0.01},
    annotations:[{x:D.t_throw, y:1, yref:"paper", yanchor:"bottom", text:D.throw_source==="sack"?"sack":"throw",
      showarrow:false, font:{size:11, color:C.throw}}],
    xaxis:{range:[0, tEnd+0.1], fixedrange:true, showgrid:true, gridcolor:"#1E2833", dtick:0.5, color:C.muted,
      title:{text:"seconds after snap", font:{size:11}}, zeroline:false},
    yaxis:{fixedrange:true, categoryorder:"array", categoryarray:rows, color:C.muted, automargin:true}});
}

// ---------- distance chart
function distTraces(){
  const tr = recs.map(r => {
    const on = sel === null || sel === r.id;
    return {type:"scatter", mode:"lines", x:D.t.slice(0, D.n_engine), y:r.sep, customdata:r.sep.map(()=>r.id),
      line:{color:r.target ? C.target : C.open, width: sel===r.id ? 4 : (r.target ? 3 : 1.6)}, opacity: on ? 1 : 0.2,
      hovertemplate:`${r.name}<br>%{x:.1f} s: %{y:.1f} yd<extra></extra>`, xaxis:"x", yaxis:"y"};
  });
  tr.push({type:"scatter", mode:"lines", x:D.t.slice(0, D.n_engine), y:D.pdist, line:{color:C.pressure, width:2.5},
    customdata:D.pdist.map(()=>D.qb_id), hovertemplate:"nearest rusher %{y:.1f} yd from QB<extra></extra>", xaxis:"x", yaxis:"y2"});
  return tr;
}
function distLayout(){
  const sh = [cursor(D.t[k]),
    {type:"line", xref:"x", yref:"y", x0:0, x1:tEnd, y0:D.open_sep, y1:D.open_sep, line:{color:C.open, dash:"dot", width:1}},
    {type:"line", xref:"x", yref:"y2", x0:0, x1:tEnd, y0:D.pressure_dist, y1:D.pressure_dist, line:{color:C.pressure, dash:"dot", width:1}},
    {type:"line", xref:"x", yref:"paper", x0:D.t_throw, x1:D.t_throw, y0:0, y1:1, line:{color:C.throw, dash:"dash", width:1.5}}];
  return baseLayout(330, {shapes:sh, margin:{l:34,r:10,t:30,b:36},
    title:{text:"Separation from nearest defender (yd) · nearest rusher to QB (yd)", font:{size:13}, x:0.01},
    xaxis:{range:[0, tEnd+0.1], fixedrange:true, showgrid:true, gridcolor:"#1E2833", dtick:0.5, color:C.muted, zeroline:false,
      anchor:"y2", title:{text:"seconds after snap", font:{size:11}}},
    yaxis:{domain:[0.38,1], fixedrange:true, rangemode:"tozero", color:C.muted, zeroline:false},
    yaxis2:{domain:[0,0.28], fixedrange:true, rangemode:"tozero", color:C.muted, zeroline:false}});
}

// ---------- field
const xs = D.players.flatMap(p => p.x).concat(D.ball.x).filter(v => v != null);
const fx0 = Math.max(0, Math.min(D.los - 12, ...xs) - 3), fx1 = Math.min(120, Math.max(D.los + 30, ...xs) + 3);
function fieldShapes(){
  const sh = [{type:"rect", x0:fx0, x1:fx1, y0:0, y1:53.3, fillcolor:C.turf, line:{width:0}, layer:"below"}];
  for (let x = 10; x <= 110; x += 10) if (x >= fx0 && x <= fx1)
    sh.push({type:"line", x0:x, x1:x, y0:0, y1:53.3, line:{color:"white", width:1}, opacity:0.25, layer:"below"});
  sh.push({type:"line", x0:D.los, x1:D.los, y0:0, y1:53.3, line:{color:C.target, width:2, dash:"dot"}, layer:"below"});
  return sh;
}
function openAt(p){ if (p.rec == null || k >= D.n_engine) return false;
  const r = recs.find(r => r.id === p.id); return r ? r.open[k] : false; }
function sepAt(p){ const r = recs.find(r => r.id === p.id); return (r && k < D.n_engine) ? r.sep[k] : null; }
function fieldTraces(){
  const off = D.players.filter(p => p.side === "off"), def = D.players.filter(p => p.side === "def");
  const hov = p => `${p.name} #${p.jersey} (${p.pos})` + (p.rec!=null && k < D.n_engine ? `<br>separation ${fmt(sepAt(p))} yd` : "");
  const dim = p => (sel === null || sel === p.id) ? 1 : 0.45;
  const tr = [
    {x:def.map(p=>p.x[k]), y:def.map(p=>p.y[k]), customdata:def.map(p=>p.id), text:def.map(hov),
     marker:{size:12, color:C.deff, opacity:def.map(dim)}},
    {x:off.map(p=>p.x[k]), y:off.map(p=>p.y[k]), customdata:off.map(p=>p.id), text:off.map(hov),
     marker:{size:12, color:off.map(p=>p.target ? C.target : C.off), opacity:off.map(dim),
       line:{color:off.map(p=>openAt(p) ? C.open : "rgba(0,0,0,0)"), width:3}}},
  ].map(t => Object.assign({type:"scatter", mode:"markers", hoverinfo:"text"}, t));
  const q = byId[D.qb_id], hot = k < D.n_engine && D.pdist[k] != null && D.pdist[k] <= D.pressure_dist;
  tr.push({type:"scatter", mode:"markers", x:[q.x[k]], y:[q.y[k]], hoverinfo:"skip",
    marker:{size:24, color:"rgba(0,0,0,0)", line:{color: hot ? C.pressure : C.throw, width:2.5}}});
  // ball flight trail after the throw
  const ti = D.t.findIndex(v => v >= D.t_throw - 1e-6);
  const from = Math.min(ti, k);
  tr.push({type:"scatter", mode:"lines", x:D.ball.x.slice(from, k+1), y:D.ball.y.slice(from, k+1), hoverinfo:"skip",
    line:{color:C.ball, width:2, dash: k >= D.n_real ? "dot" : "solid"}});
  tr.push({type:"scatter", mode:"markers", x:[D.ball.x[k]], y:[D.ball.y[k]], hoverinfo:"skip",
    marker:{size: k > ti ? 13 : 9, color:C.ball, symbol:"diamond", line:{color:"#000", width:1}}});
  if (sel !== null && byId[sel]) {
    const p = byId[sel];
    tr.push({type:"scatter", mode:"lines", x:p.x.slice(0, k+1), y:p.y.slice(0, k+1), hoverinfo:"skip",
      line:{color:C.hi, width:2}, opacity:0.8});
    tr.push({type:"scatter", mode:"markers+text", x:[p.x[k]], y:[p.y[k]], text:[last(p.name)], textposition:"top center",
      textfont:{color:C.hi, size:12}, hoverinfo:"skip", marker:{size:26, color:"rgba(0,0,0,0)", line:{color:C.hi, width:3}}});
  }
  return tr;
}
function fieldLayout(){
  const w = (F.clientWidth || 500) - 10;
  return baseLayout(Math.round(w * 53.3 / (fx1 - fx0)) + 8, {shapes:fieldShapes(), margin:{l:4,r:4,t:4,b:4},
    xaxis:{range:[fx0, fx1], visible:false, fixedrange:true},
    yaxis:{range:[0, 53.3], visible:false, fixedrange:true, scaleanchor:"x", scaleratio:1}});
}

// ---------- state + drawing
const G = document.getElementById("gantt"), Dd = document.getElementById("dist"), F = document.getElementById("field");
const slider = document.getElementById("slider"); slider.max = N - 1;
function drawAll(){
  Plotly.react(G, ganttTraces(), ganttLayout(), cfg);
  Plotly.react(Dd, distTraces(), distLayout(), cfg);
  drawTime();
}
function drawTime(){
  slider.value = k;
  const t = D.t[k];
  document.getElementById("tlabel").textContent = `t = ${t.toFixed(1)} s` + (k >= D.n_real ? " (projected)" : "");
  const ph = document.getElementById("phase");
  if (k >= D.n_real) { ph.className = "phase proj"; ph.textContent = "ball flight · projected"; }
  else if (t > D.t_throw + 1e-6) { ph.className = "phase air"; ph.textContent = "ball in the air · tracked"; }
  else if (t >= D.t_throw - 1e-6) { ph.className = "phase air"; ph.textContent = D.throw_source === "sack" ? "sack" : "release"; }
  else { ph.className = "phase"; ph.textContent = "routes vs rush"; }
  Plotly.relayout(G, {"shapes[0].x0":t, "shapes[0].x1":t});
  Plotly.relayout(Dd, {"shapes[0].x0":t, "shapes[0].x1":t});
  Plotly.react(F, fieldTraces(), fieldLayout(), cfg);
  info();
}
function info(){
  const el = document.getElementById("info");
  if (sel === null || !byId[sel]) { el.innerHTML = "Click a player (chip, timeline row, distance line or dot on the field) to follow him."; return; }
  const p = byId[sel], t = D.t[k];
  let s = `<b>${p.name}</b> #${p.jersey} · ${p.pos} · ${p.side === "off" ? "offense" : "defense"} · t = ${t.toFixed(1)} s`;
  if (p.rec != null && k < D.n_engine) {
    const r = recs.find(r => r.id === p.id), o = r.open[k];
    const st = o ? "OPEN" : (r.sep[k] != null && r.sep[k] >= D.open_sep ? "not past the LOS yet" : "covered");
    s += ` · separation <b>${fmt(r.sep[k])} yd</b> · <b style="color:${o ? C.open : C.muted}">${st}</b>`;
    if (r.windows.length) s += ` · windows ${r.windows.map(w => w[0].toFixed(1)+"–"+(w[1]+0.1).toFixed(1)+" s").join(", ")}`;
  } else if (p.qb && k < D.n_engine) {
    s += ` · nearest rusher <b>${fmt(D.pdist[k])} yd</b>`;
  }
  if (p.target) s += ` · <b style="color:${C.target}">targeted</b>`;
  el.innerHTML = s;
}
function select(id){
  sel = id;
  document.querySelectorAll(".chip").forEach(b => b.classList.toggle("on", +b.dataset.id === id));
  drawAll();
}
function setK(v){ k = Math.max(0, Math.min(N - 1, v)); drawTime(); }
function stop(){ clearInterval(timer); timer = null; document.getElementById("play").textContent = "▶ play"; }
document.getElementById("play").onclick = () => {
  if (timer) return stop();
  if (k >= N - 1) k = 0;
  document.getElementById("play").textContent = "❚❚ pause";
  timer = setInterval(() => { if (k >= N - 1) return stop(); setK(k + 1); }, 1000 / 10);
};
slider.oninput = () => { stop(); setK(+slider.value); };
document.addEventListener("keydown", e => {
  if (e.key === "ArrowRight") { stop(); setK(k + 1); } if (e.key === "ArrowLeft") { stop(); setK(k - 1); }
  if (e.key === " ") { e.preventDefault(); document.getElementById("play").click(); }
});

// click / drag on a chart = move the clock
function scrubber(div){
  let down = false;
  const go = ev => {
    const xa = div._fullLayout.xaxis, r = div.getBoundingClientRect();
    const px = ev.clientX - r.left - xa._offset;
    if (px < 0 || px > xa._length) return;
    const t = xa.p2l(px);
    let best = 0; D.t.forEach((v, i) => { if (Math.abs(v - t) < Math.abs(D.t[best] - t)) best = i; });
    stop(); setK(best);
  };
  div.addEventListener("mousedown", e => { down = true; go(e); });
  window.addEventListener("mousemove", e => { if (down) go(e); });
  window.addEventListener("mouseup", () => down = false);
}
// click a bar / line / dot = select the player
const pick = ev => { const p = ev.points && ev.points[0]; if (p && p.customdata != null) select(sel === p.customdata ? null : p.customdata); };

drawAll();
window.addEventListener("resize", () => Plotly.react(F, fieldTraces(), fieldLayout(), cfg));
scrubber(G); scrubber(Dd);
G.on("plotly_click", pick); Dd.on("plotly_click", pick); F.on("plotly_click", pick);
document.getElementById("fieldhint").textContent =
  "Offense (blue) → right, defense red, ball gold. Green outline = open receiver; QB ring turns red under pressure; " +
  (D.n_real < N ? "dotted gold = projected ball flight to the target after tracking ends." : "gold line = ball after release.");
if (D.target_id != null) select(D.target_id);
</script></body></html>"""
