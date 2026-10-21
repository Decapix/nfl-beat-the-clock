"""NFL club colors and logos.

Palette: nflverse `teams_colors_logos`, which is the official club palette also published on the community
"NFL Colors" Figma board (figma.com/design/ZRAT8E2Kjomz7TQga4uyRn); where the board carries a newer shade the
board wins. Logos live in static/logos and are served by Streamlit's static file serving (app/static/...).

`pair()` is the one function the charts need: per play it picks, for each side, the first club color that is
visible on the dark turf and far enough from the other side's color, so MIA vs BUF is aqua vs royal blue and
HOU (navy) vs DAL (navy) does not become two navies on a dark green field."""
import csv
import functools
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
STATIC = Path(__file__).resolve().parent.parent / "static"

NFL_NAVY = "#013369"      # the shield
NFL_RED = "#D50A0A"
ALIAS = {"LAR": "LA", "STL": "LA", "OAK": "LV", "SD": "LAC", "WSH": "WAS"}
FALLBACK_OFF = "#3B82F6"
FALLBACK_DEF = "#EF4444"
NEUTRALS = ["#F5C542", "#E6EDF3", "#C4B5FD"]

MIN_L = 32          # L* below this disappears on the turf
MIN_DE_BG = 28      # distance from the turf (CIE76)
MIN_DE_PAIR = 30    # distance between the two sides
OK_DE_PAIR = 16     # still acceptable when nothing better exists


@functools.lru_cache(maxsize=None)
def table():
    out = {}
    with open(ASSETS / "team_colors.csv", newline="") as f:
        for r in csv.DictReader(f):
            cols = [c.upper() for c in (r["color1"], r["color2"], r["color3"], r["color4"]) if c]
            out[r["abbr"]] = dict(abbr=r["abbr"], name=r["name"], nick=r["nick"], conf=r["conf"], div=r["div"],
                                  colors=cols)
    return out


def norm(abbr):
    a = str(abbr or "").upper().strip()
    return ALIAS.get(a, a)


def team(abbr):
    a = norm(abbr)
    return table().get(a, dict(abbr=a, name=a, nick=a, conf="", div="", colors=[FALLBACK_OFF, "#E6EDF3"]))


def colors(abbr):
    return team(abbr)["colors"]


def primary(abbr):
    return colors(abbr)[0]


def secondary(abbr):
    c = colors(abbr)
    return c[1] if len(c) > 1 else c[0]


def logo(abbr):
    """URL as Streamlit serves it (needs server.enableStaticServing); '' when the file is missing."""
    a = norm(abbr)
    return f"app/static/logos/{a}.png" if (STATIC / "logos" / f"{a}.png").exists() else ""


# ------------------------------------------------------------------ contrast
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lab(h):
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    r, g, b = (lin(c) for c in _rgb(h))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a, b):
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


def visible(hex_, bg):
    return _lab(hex_)[0] >= MIN_L and delta_e(hex_, bg) >= MIN_DE_BG


def lighten(hex_, bg, step=0.12):
    """Mix toward white until the color reads on `bg` (NYJ green on green turf, IND navy on a dark page)."""
    r, g, b = _rgb(hex_)
    for _ in range(8):
        if visible(hex_, bg):
            return hex_
        r, g, b = (c + (1 - c) * step for c in (r, g, b))
        hex_ = "#%02X%02X%02X" % tuple(round(c * 255) for c in (r, g, b))
    return hex_


def pick(abbr, bg, avoid=(), fallback=FALLBACK_OFF):
    """First club color that reads on `bg` and is far enough from every color in `avoid`;
    a team with no readable color gets its primary lightened instead of a neutral."""
    cands = [c for c in colors(abbr) if visible(c, bg)] or [lighten(primary(abbr), bg)]
    for c in cands:
        if all(delta_e(c, a) >= MIN_DE_PAIR for a in avoid):
            return c
    if cands:
        best = max(cands, key=lambda c: min([delta_e(c, a) for a in avoid] or [999]))
        if min([delta_e(best, a) for a in avoid] or [999]) >= OK_DE_PAIR:
            return best
    for c in [fallback] + NEUTRALS:
        if all(delta_e(c, a) >= MIN_DE_PAIR for a in avoid):
            return c
    return fallback


def pair(off, deff, bg="#13251B"):
    """(offense color, defense color) for one play."""
    o = pick(off, bg, fallback=FALLBACK_OFF)
    d = pick(deff, bg, avoid=(o,), fallback=FALLBACK_DEF)
    return o, d
