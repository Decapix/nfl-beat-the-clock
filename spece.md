# Route vs Rush — build spec

> **Prompt for Claude Code (paste first):** Read this file and `route_vs_rush.py` (a tested reference implementation of the engine, keep its vectorized separation/pressure logic). Build milestone M1, run the sanity checks, show me the output, then continue to M2 → M4 in order. Hard deadline: a public repo must be submitted at 16:00 Paris; stop adding features at 15:35 whatever state we're in and spend the rest on README + screenshots. Ask me only if a check fails; otherwise keep going.

## 0. The idea in one paragraph

Every dropback is a race: routes trying to get open vs. the pass rush trying to get home. For each pass play we compute, frame by frame from snap to throw, when each WR/TE/RB first becomes **open** (≥ 3 yd from the nearest coverage defender, at least 1 yd past the line of scrimmage), how long that **window** stays open, when **pressure** reaches the QB (a rusher within 2 yd), and where the **throw** lands on that timeline. Three audiences: a QB coach (per-play timeline for film review: "Lamb open from 1.3 s, pressure at 3.0 s, ball to covered Gallup at 5.2 s"), a scout (time-to-open and open-share as a route-running grade independent of targets), a coordinator/broadcaster (which coverages make routes lose the race; "he had him open the whole time").

Judging rubric (1–5 each): football understanding, technical execution, communication, originality. Design decisions below are made to score on all four, not to maximize model complexity.

## 1. Deliverables (what "done" means)

Submission needs: working Python code, the result (screenshots/demo of the tool), README of 3–5 sentences, public repo.

1. `rvr/` package + `build.py` producing, for all 8 weeks, `outputs/race_by_play.parquet` (+ `.csv`), `outputs/windows_by_receiver.parquet`, `outputs/receiver_leaderboard.csv`, `outputs/qb_leaderboard.csv`, `outputs/coverage_table.csv`.
2. `app.py` — a Streamlit dashboard (spec in §5) that opens in < 3 s and lets a non-technical person browse plays, receivers, QBs, coverages.
3. `figures/` — 4 screenshots of the app + the matplotlib Gantt PNG, referenced from the README.
4. `README.md` — 3–5 sentences (draft in §8), then a "How to run" block and a "Definitions" table.

Priority if time runs out: 1 → the Play Explorer tab of 2 → README → everything else.

## 2. Data facts (verified on the files; do not re-verify)

Source: `https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data` → `data/` (git-ignored locally).

- `games.csv` (122 games, 2021 weeks 1–8), `plays.csv` (8,557 dropbacks), `players.csv`, `pffScoutingData.csv`, `tracking/tracking_<gameId>.csv` (one file per game, ~7 MB, 10 fps).
- `plays.csv` has `pff_passCoverage` (Cover-3 2665, Cover-1 2011, Cover-2 1085, Quarters 1033, Cover-6 805, …) and `pff_passCoverageType` (Zone 5588 / Man 2481 / Other 488), `passResult` (C 4620, I 2755, S 543, R 449, IN 190), `dropBackType`, `down`, `yardsToGo`, `absoluteYardlineNumber`, `playDescription`.
- `pffScoutingData.csv` → `pff_role` per (gameId, playId, nflId): exact strings `Pass`, `Pass Route`, `Pass Block`, `Pass Rush`, `Coverage` (capital R in "Pass Route"). Mean 4.62 route runners per play; route runners are WR 23k / TE 9k / RB 7k / FB 385.
- Tracking columns: `gameId, playId, nflId, frameId, time, jerseyNumber, team, playDirection, x, y, s, a, dis, o, dir, event`. Ball rows have `nflId = NaN`, `team = "football"`.
- Frames run from before the snap to **3–5 frames after the throw**. There is no catch frame; nothing after release is usable.
- Event spellings: snap = `ball_snap` **or** `autoevent_ballsnap`; throw = `pass_forward` **or** `autoevent_passforward` (in one game 851 of 2,967 throw tags were the autoevent spelling). Sack = `qb_sack` / `qb_strip_sack`. Scrambles may have `run`.
- **No targeted-receiver column.** Parse from `playDescription`; the simple regex `(?:to|for)\s+([A-Z]\.\s?[A-Za-z'\-]+)` already matches 94.9 % of C/I/IN plays. ~5 % stay unmatched: that's fine, keep them with `targetNflId = NaN`.
- `playId` is not unique across games: always key on `(gameId, playId)`.
- Field: x 0–120, y 0–53.3. If `playDirection == "left"`, flip `x = 120 - x`, `y = 53.3 - y` (ball rows too). Line of scrimmage after flipping = ball `x` at the snap frame.

## 3. Definitions (these go verbatim into the README and the app's "Method" expander)

| Term | Definition | Why this choice |
|---|---|---|
| Receiver | `pff_role == "Pass Route"` | PFF tag, no guessing |
| Separation `sep` | distance to nearest `Coverage` defender, per frame | the standard NGS quantity |
| Open | `sep ≥ OPEN_SEP (3.0)` **and** `x ≥ LOS + MIN_DEPTH (1.0)` | 3 yd is the NGS "open" threshold; the LOS filter kills "everyone is open at the snap" |
| Window | consecutive open frames; store all, report the longest | |
| `t_open` | seconds after snap of the first open frame (NaN if never) | |
| Pressure | any `Pass Rush` player within `PRESSURE_DIST (2.0)` yd of the `Pass` player | simple, honest geometry; never count `Pass Block` |
| `t_pressure` | first pressure frame in seconds (NaN if none before the throw) | |
| `t_throw` | throw frame − snap frame, in seconds; sacks: sack frame (or last frame) and `is_sack = True` | |
| Target open at throw | target's `sep ≥ 3` and past LOS at the throw frame | |
| Open man ignored | target **not** open (`sep < TIGHT_SEP (1.5)`) at the throw while ≥ 1 other receiver **is** open | the "open but not targeted" question |
| Race margin | `t_pressure_eff − min(t_open)`; `t_pressure_eff = t_pressure` if pressure arrived else `t_throw` (rush never got home) | positive = routes won; headline per-play number |

Constants live at the top of `rvr/engine.py` with a one-line reason each: `OPEN_SEP = 3.0`, `TIGHT_SEP = 1.5`, `MIN_DEPTH = 1.0`, `PRESSURE_DIST = 2.0`, `FPS = 10`.

Scope: keep `passResult ∈ {C, I, IN, S}`; drop scrambles (`R`). Sacks keep `t_throw` as the sack time and `targetNflId = NaN`.

## 4. Architecture

```
route-vs-rush/
  README.md  requirements.txt  .gitignore (data/, __pycache__, .streamlit/secrets.toml)
  rvr/
    io.py       load_meta(), load_game(gameId), flip(), parse_targets(plays, players, pff)
    engine.py   analyze_play(trk_play, roles) -> PlayResult   (single source of truth)
    metrics.py  leaderboards + coverage table from the two long tables
    plots.py    plotly: gantt(), race_curves(), field_animation(); matplotlib: gantt_png()
  build.py      batch over weeks (ProcessPoolExecutor, one task per game) -> outputs/
  app.py        Streamlit UI, reads outputs/ and calls engine on demand for one play
  outputs/  figures/  (committed, small)      data/ (ignored)
```

**Single source of truth.** `analyze_play` is used by both `build.py` (batch) and `app.py` (on demand, for the field animation and Gantt of the selected play), so numbers on screen always equal numbers in the CSVs.

**`PlayResult`** (dataclass): `t` (seconds array), per-receiver arrays `sep[nF, nR]`, `open[nF, nR]`, `depth[nF, nR]`, `pressure_dist[nF]`, `frames` with x/y of every player + ball for animation, and a `summary` dict = one row of `race_by_play`.

**Engine logic (already correct in `route_vs_rush.py`, port it):**
1. find `snap` = min frame with a snap event, `throw` = min frame with a throw event, else sack event, else last frame (`throw_source` column: `pass|sack|last`); drop play if snap missing or `throw ≤ snap`.
2. cut to `[snap, throw]`, pivot to `(nF, n, 2)` arrays per role with `pivot(index=frameId, columns=nflId, values=[x, y]).reindex(frames)`.
3. `sep = ||R[:, :, None] − C[:, None, :]||.min(axis=2)`; `pressure = ||P[:, :, None] − Q[:, None, :]||.min(axis=(1, 2))`; `depth = R[..., 0] − los_x`.
4. windows: run-length encode `open[:, j]`.

**Target parsing** (`io.parse_targets`): regex above on `playDescription`; normalize to `first_initial.lastname` lowercased, strip suffixes (Jr, Sr, II, III, IV); match against route runners **of the possession team on that play**; if 0 or ≥ 2 matches → NaN. Log the match rate.

**Performance:** week 1 ≈ 1 min single-process; all 8 weeks with `ProcessPoolExecutor(max_workers=os.cpu_count())`, one game per task, should take 2–5 min. `build.py --weeks 1` for dev, `build.py` for all. Start the full run in a second terminal as soon as week 1 passes the checks.

**Dependencies:** `pandas numpy pyarrow matplotlib plotly streamlit` (+ `nflreadpy` for the optional M5). No new library may be created for the event (rules), so `rvr/` stays an in-repo package, not published.

## 5. The app (`app.py`) — useful and beautiful

Run: `streamlit run app.py`. Theme in `.streamlit/config.toml`: `base="dark"`, `primaryColor="#2ECC71"`, `backgroundColor="#0B1117"`, `secondaryBackgroundColor="#141C26"`, `textColor="#E6EDF3"`, `font="sans serif"`. Wide layout. Every chart uses the same semantic palette, declared once in `plots.py`:

- open window **#2ECC71**, covered/not open **#3A4654**, target receiver **#3B82F6**, pressure **#EF4444**, throw marker **#E6EDF3** dashed, offense dots **#3B82F6**, defense dots **#EF4444**, ball **#F5C542**, turf **#13251B** with white yard lines every 10 yd (opacity 0.25).
- No chartjunk: no gridlines except x on timelines, no legends where color is explained by the caption, axis labels in seconds. Each chart gets a one-sentence takeaway caption written from the data (`st.caption`).

Sidebar: logo-free title "Route vs Rush", subtitle "the open-window clock", three sliders for the tunables (defaults 3.0 / 1.0 / 2.0) that **only** affect the on-demand play view (batch outputs are fixed; say so in a caption), and a "Method" expander with the §3 table.

### Tab 1 — Play Explorer (ship this first)
- Selectors: week → game (e.g. "TB @ DAL") → play, with the play's description as the dropdown label truncated to 80 chars. Above them, three **story quick-picks** as buttons: "Most obvious open man ignored" (max `best_alt_sep_at_throw` among `open_man_ignored & pressure arrived`), "Longest race won" (max race margin, complete pass), "Fastest window" (min `t_first_open`, complete pass).
- Row of 5 `st.metric`: Time to throw, First open at, Pressure at, Race margin (+/-), Target separation at throw. Delta text under each in words ("routes won by 1.3 s").
- Left (60 %): **Gantt timeline** (plotly `go.Bar` horizontal, barmode overlay): one row per receiver sorted by position then `t_open`; green bars = windows; target row in blue; faint grey bar = covered time; red shaded band at the bottom = pressure; white dashed vertical = throw/sack. Hover: receiver, position, window start–end, max separation in window. Title = play description.
- Right (40 %): **field animation** (plotly frames, built-in play/pause + slider): all 22 players + ball, offense/defense colors, receivers' marker outline turns green while open, QB marked with a ring that turns red under pressure, LOS line, flipped so offense goes left→right, aspect ratio fixed (`scaleanchor`), 10 fps. Jersey numbers as text on hover only.
- Below: one sentence auto-generated, e.g. "Gallup was open 1.2–2.3 s; Lamb was open from 1.3 s to the throw; pressure arrived at 3.0 s; Prescott threw to a covered Gallup at 5.2 s." Build it from the arrays, keep it factual.

### Tab 2 — Receivers (scout view)
- Filters: position multiselect (WR/TE/RB), min routes slider (default 40), team.
- Table (`st.dataframe` with column config: progress bars for open share, number formats): player, pos, team, routes, targets, median `t_open`, open share, open at throw rate, **open-but-ignored** count and rate.
- Chart: scatter `median t_open` (x) vs `open share` (y), bubble = routes, color = position, label the 10 extremes. Caption names the "early separators" (bottom-left) and "late bloomers".
- Click/select a player (selectbox) → small histogram of his `t_open` vs the position average, and his 5 most "ignored" plays (links switch Tab 1 selection via `st.session_state`).

### Tab 3 — Quarterbacks (coach view)
- Table: QB, dropbacks, mean time to throw, % throws into an open window, % plays with an open man ignored, % races won, (+ mean EPA split if M5 done).
- Scatter: % throws into open window (x) vs mean time to throw (y), bubble = dropbacks. Caption: who gets rid of it before the window closes.

### Tab 4 — Coverages (coordinator view)
- **Race curves**: for each `pff_passCoverage` with ≥ 150 plays, two step curves vs seconds after snap: P(at least one receiver open by t) in green, P(pressure arrived by t) in red; small multiples, one panel per coverage, shared axes. This is the chart that explains the whole tool in one look.
- Bar chart: median race margin per coverage, Man vs Zone split as two colors. Table underneath.

### Tab 5 — Method
- The §3 table, the tunables, the limitations in plain words: proximity ≠ assignment; 8 weeks; no post-throw frames; targets parsed from text (~95 %); open ≠ throwable (no QB field-of-view model).

UX rules: nothing requires typing; every number has a unit; first paint of Tab 1 with a default story play, never an empty state; `st.cache_data` on outputs and on `load_game`; errors never show a traceback, show a one-line message.

## 6. Outputs schema

`race_by_play` (one row per dropback): `gameId, playId, week, possessionTeam, defensiveTeam, qb, down, yardsToGo, passResult, is_sack, yards, coverage, covType, dropBackType, t_throw, throw_source, t_first_open, t_pressure, t_pressure_eff, race_margin, routes_won (bool), n_receivers, n_open_at_throw, targetNflId, target, target_pos, target_sep_at_throw, target_open_at_throw, best_alt_sep_at_throw, best_alt_name, open_man_ignored, playDescription`.

`windows_by_receiver` (one row per receiver-play): `gameId, playId, nflId, player, pos, team, targeted, t_open, open_share, n_windows, longest_window_start, longest_window_end, longest_window_len, sep_at_throw, open_at_throw, max_sep`.

Leaderboards: receivers (min 40 routes), QBs (min 60 dropbacks), coverage table (min 150 plays). CSVs sorted by the headline column.

## 7. Milestones and clock (Paris time; now ≈ 14:15)

| By | Milestone | Done when |
|---|---|---|
| 14:35 | **M1** engine + `build.py --weeks 1` | checks in §9 pass on week 1; print 3 plays vs their descriptions |
| 14:40 | launch full 8-week build in a second terminal | keep working on week-1 outputs |
| 15:05 | **M2** `app.py` Tab 1 (Gantt + metrics + field animation) and Tab 5 | opens with a story play, no empty states |
| 15:25 | **M3** Tabs 2–4 from the full outputs; leaderboards written | race curves render for ≥ 5 coverages |
| 15:35 | **M4** README, 4 screenshots in `figures/`, `.gitignore`, push public repo, submit form | link submitted |
| 15:35–15:55 | buffer; **M5 optional only if M4 is done**: `nflreadpy` join (`load_pbp([2021])`, join `old_game_id`(str→int)=`gameId`, `play_id`=`playId`; columns `epa, cpoe, air_yards, receiver_player_name`); add mean EPA for "threw into open window" vs "open man ignored" to Tab 3 and README | one extra sentence in the README |

Feature freeze at 15:35. No new ideas after that, only fixes and text.

## 8. README draft (rewrite in your own words, keep 3–5 sentences before the run block)

Route vs Rush measures, for every dropback in weeks 1–8 of the 2021 season, the race between the offense's routes and the defense's pass rush: the second each WR/TE/RB first gets open (≥ 3 yd from the nearest coverage defender, past the line of scrimmage), how long that window stays open, when pressure reaches the QB, and whether the throw landed inside an open window. It reveals which receivers win early vs late, how often an open receiver is ignored while the target is covered, and which coverages make routes lose the race. A QB coach uses the per-play timeline for film review, a scout uses time-to-open as a route-running grade independent of targets, and a broadcaster gets a five-second visual for "he had him open the whole time". Built on NFL Next Gen Stats tracking with PFF roles and coverage labels; targets parsed from play descriptions.

Then: `pip install -r requirements.txt` → `python build.py` → `streamlit run app.py`; the four screenshots; the §3 table; limitations.

## 9. Sanity checks (run after M1 and after the full build; judges ask)

- Median `t_throw` on `dropBackType == "TRADITIONAL"` ≈ 2.5–2.9 s. 0.3 s → wrong event; 6 s → throw not found and `last` used.
- `throw_source == "pass"` on ≥ 90 % of non-sack plays.
- Target match rate ≥ 90 % of C/I/IN plays.
- Target open at throw on roughly 40–60 % of throws. 0 % → flip or LOS wrong; 100 % → depth filter missing.
- Pressure arrives before the throw on ~30–45 % of plays. 90 % → `Pass Block` counted as rushers or threshold too loose.
- `open_man_ignored` on ~8–15 % of throws.
- One known deep incompletion eyeballed on the Gantt against its description (in game 2021090900: "(8:16) D.Prescott pass incomplete deep left to M.Gallup" — Gallup's window closes at 2.3 s, Lamb open 1.3 s → throw, pressure at 3.0 s, throw at 5.2 s).

## 10. Pitfalls checklist

- [ ] both snap and both throw spellings; sacks handled; scrambles dropped
- [ ] ball rows (`nflId` NaN) excluded from role merges but used for LOS
- [ ] flip `x` **and** `y`; LOS taken after the flip
- [ ] key everything on `(gameId, playId)`; `pff_role` strings exact (`Pass Route`)
- [ ] pressure uses `Pass Rush` only; QB = `Pass` (take the first if two)
- [ ] `pandas` `.name` clash: never store a column called `name` on rows you iterate with `itertuples`/`iterrows` (use `player`)
- [ ] `data/` git-ignored; `outputs/` and `figures/` committed; repo public before the form
- [ ] small commits as you go (one per milestone at least)
- [ ] app never shows a traceback; default play loads on first paint
