# Route vs Rush — the open-window clock

## Run

```bash
./run.sh
```

That installs the requirements, fetches the Big Data Bowl data if `data/` is missing (or links `$RVR_DATA`), builds the outputs if they are not there yet, and opens the dashboard at http://localhost:8501.

## The story

Week 1, Cowboys at Buccaneers, 8:16 left in the first quarter: Dak Prescott drops back, CeeDee Lamb is open from 1.3 seconds after the snap until the ball leaves the hand, Michael Gallup is open for one second and then Jamel Dean closes on him, the Tampa rush gets home at 3.0 seconds, and at 5.2 seconds Prescott throws deep to a covered Gallup, incomplete. Every dropback is that race between the routes getting open and the rush getting home, and Route vs Rush measures it for all 8,086 dropbacks of the 2021 season's first eight weeks from Next Gen Stats tracking: when each WR, TE or RB first gets open, how long the window stays open, when pressure arrives, what coverage the defense ran, who was covering whom, and whether the throw went into an open window. The dashboard is what a coach wants on Monday morning: one clock drives the field, the open-window timeline and the separation curves, so a QB coach sees in five seconds who was open when and why the ball went elsewhere (an open man is ignored on 10 % of throws), a scout grades route running by time-to-open instead of targets, and a coordinator sees which coverages make routes lose the race (against man, nobody gets open on 15–17 % of plays, against zone on under 1 %). Click any player and he lights up everywhere; drag the clock and the whole play follows.

![Play Explorer](figures/1_play_explorer.png)

## What is inside

- **Play Explorer** — linked viewer for any dropback: field, open-window Gantt, separation and pressure curves, the defense's coverage call, rushers and who was covering whom.
- **Receivers** — time-to-open, open share of the dropback, open-but-ignored count; filter by position, team, minimum routes.
- **Quarterbacks** — throws into open windows, open man ignored, time to throw, pressure rate.
- **Coverages** — race margin and "nobody open" rate by coverage, man vs zone.
- **Method** — definitions and tunables (open = 3 yd from the nearest coverage defender and past the line of scrimmage; pressure = rusher within 2 yd of the QB; sliders re-run the engine live on the selected play).

| Receivers | Quarterbacks | Coverages |
|---|---|---|
| ![](figures/2_receivers.png) | ![](figures/3_quarterbacks.png) | ![](figures/4_coverages.png) |

Code: `rvr/engine.py` is the race engine, `build.py` runs it over all weeks into `outputs/`, `app.py` is the Streamlit dashboard. Limits: separation is to the nearest defender, not the assigned one; tracking ends at the throw, so no catch point or YAC; targets are parsed from play text (95 % matched); eight weeks only.
