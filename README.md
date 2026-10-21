# nfl-beat-the-clock

**Every dropback is a race: routes trying to get open, the rush trying to reach the quarterback. This dashboard (Route vs Rush) puts a clock on that race, for every play.**

```bash
python run.py      # or ./run.sh (macOS/Linux), run.bat (Windows): installs, fetches the data, builds, opens http://localhost:8501
```

![Play Explorer](figures/1_play_explorer.png)

## What it does

For all 8,086 dropbacks of 2021 weeks 1–8 (Next Gen Stats tracking + PFF roles) it measures, per play:

- when each receiver first gets **open** (3 yd from the nearest coverage defender, past the line of scrimmage) and how long that window lasts,
- when **pressure** arrives (a rusher within 2 yd of the QB),
- the coverage call, who was covering whom, and whether the throw went into an open window.

One clock drives the field, the open-window timeline and the separation curves. Drag it and the whole play follows; click a player and he lights up everywhere.

## Why a coach needs it

- **QB coach** · Film review in five seconds: who was open when, and why the ball went elsewhere. An open man is ignored on 10 % of throws.
- **Receivers coach / scout** · Route running graded by time to open and share of the dropback spent open, independent of targets. A receiver nobody throws to still shows up.
- **Coordinator** · Which coverages make routes lose the race. Against man coverage nobody gets open on 15–17 % of plays; against zone, under 1 %.

## Inside

**Tabs** · Play Explorer (field, timeline, separation and pressure curves, defense call and matchups) · Receivers · Quarterbacks · Coverages · Method.
**Code** · `rvr/engine.py` race engine · `build.py` batch over all weeks into `outputs/` · `app.py` dashboard · `rvr/teams.py` official club colors and logos.
**Limits** · nearest defender, not the assigned one · tracking ends at the throw · targets parsed from play text (95 % matched) · eight weeks.
