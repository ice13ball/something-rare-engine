# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Server-drawn track sketch for /cruise/{EXPOCODE}: an equirectangular SVG fitted to the cruise. No tiles, no JS.

Coastline: Natural Earth 1:110m land (public domain), outer rings in ne_110m_land.json.
⛔ Antimeridian: when a cruise's longitudes span less taken in 0..360 than in -180..180, the frame is drawn in 0..360
(`Frame.shifted`) — a Pacific crossing is then one short track, not two halves at the map edges joined by a line
across the world. `folded()` brings frame longitudes back for the JSON-LD box and the map camera.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path

import ocean_basin

W, H = 640, 360
MAX_DOTS = 2000
BREAK_DEG = 20.0          # a jump this large between consecutive track vertices is a data gap, never a line
MIN_SPAN_DEG = 3.0
_LAND = Path(__file__).with_name("ne_110m_land.json")
_SHORT = {"Atlantic Ocean": "Atlantic", "Pacific Ocean": "Pacific"}


def folded(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


@dataclass(frozen=True)
class Frame:
    d_west: float
    d_east: float
    d_south: float
    d_north: float
    west: float
    east: float
    south: float
    north: float
    shifted: bool

    def lon(self, lon: float) -> float:
        return lon + 360.0 if self.shifted and lon < 0 else lon

    def x(self, lon: float) -> float:
        return (lon - self.west) / (self.east - self.west) * W

    def y(self, lat: float) -> float:
        return (self.north - lat) / (self.north - self.south) * H

    def bbox(self) -> dict:
        west, east = (folded(self.d_west), folded(self.d_east)) if self.shifted else (self.d_west, self.d_east)
        return {"west": round(west, 4), "east": round(east, 4), "south": round(self.d_south, 4),
                "north": round(self.d_north, 4), "crosses_antimeridian": self.shifted}


def frame_for(points: list[tuple[float, float]]) -> Frame:
    if not points:
        raise ValueError("a cruise with no positions has no sketch")
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    alt = [x + 360.0 if x < 0 else x for x in lons]
    shifted = (max(alt) - min(alt)) < (max(lons) - min(lons))
    xs = alt if shifted else lons
    dw, de, ds, dn = min(xs), max(xs), min(lats), max(lats)
    w, e = dw - max((de - dw) * 0.1, 1.0), de + max((de - dw) * 0.1, 1.0)
    s, n = max(-90.0, ds - max((dn - ds) * 0.1, 1.0)), min(90.0, dn + max((dn - ds) * 0.1, 1.0))
    if e - w < MIN_SPAN_DEG:
        mid = (w + e) / 2
        w, e = mid - MIN_SPAN_DEG / 2, mid + MIN_SPAN_DEG / 2
    k = max(math.cos(math.radians((s + n) / 2)), 0.2)      # a degree of longitude is drawn cos(lat) wide
    want_lat = (e - w) * k * H / W
    if n - s < want_lat:
        mid = (s + n) / 2
        s, n = mid - want_lat / 2, mid + want_lat / 2
        if s < -90.0:
            s, n = -90.0, n + (-90.0 - s)
        if n > 90.0:
            s, n = max(-90.0, s - (n - 90.0)), 90.0
    else:
        mid, want_lon = (w + e) / 2, (n - s) / k * W / H
        w, e = mid - want_lon / 2, mid + want_lon / 2
    if e - w > 360.0:
        mid = (w + e) / 2
        w, e = mid - 180.0, mid + 180.0
    return Frame(dw, de, ds, dn, w, e, s, n, shifted)


def _lat_text(lat: float) -> str:
    return f"{abs(round(lat))}°{'N' if lat >= 0 else 'S'}"


def lat_range_text(south: float, north: float) -> str:
    a, b = round(south), round(north)
    if a >= 0:
        return f"{a}°N" if a == b else f"{a}–{b}°N"
    if b <= 0:
        return f"{-a}°S" if a == b else f"{-b}–{-a}°S"
    return f"{_lat_text(south)}–{_lat_text(north)}"


def region_label(frame: Frame, points: list[tuple[float, float]]) -> str:
    """Basin(s) in words + the latitude band. ocean_basin abstains (None) rather than guess; so do we."""
    step = max(1, len(points) // 200)
    basins = Counter(b for lon, lat in points[::step] if (b := ocean_basin.basin_for(lat, folded(lon))))
    band = lat_range_text(frame.d_south, frame.d_north)
    if not basins:
        return band
    names = []
    for name, _ in basins.most_common(2):
        hemi = "North " if frame.d_south >= 0 else "South " if frame.d_north <= 0 else ""
        names.append(f"{hemi}{_SHORT[name]}" if hemi and name in _SHORT else name)
    return f"{' and '.join(names)}, {band}"


@lru_cache(maxsize=1)
def _land() -> list[tuple[tuple[float, float, float, float], list[list[float]]]]:
    rings = json.loads(_LAND.read_text(encoding="utf-8"))["rings"]
    return [((min(p[0] for p in r), min(p[1] for p in r), max(p[0] for p in r), max(p[1] for p in r)), r)
            for r in rings]


def _pts(frame: Frame, coords) -> str:
    return " ".join(f"{frame.x(x):.1f},{frame.y(y):.1f}" for x, y in coords)


def render_svg(frame: Frame, dots: list[tuple[float, float]], track: list[tuple[float, float]], label: str) -> str:
    """Presentation attributes only (no style=), so no CSP rule can strip the drawing."""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" '
           f'aria-label="{escape(label)}"><title>{escape(label)}</title>',
           f'<rect width="{W}" height="{H}" fill="#0b1726"/>']
    for (x0, y0, x1, y1), ring in _land():
        if y1 < frame.south or y0 > frame.north:
            continue
        for off in (-360.0, 0.0, 360.0):
            if x1 + off < frame.west or x0 + off > frame.east:
                continue
            out.append(f'<polygon points="{_pts(frame, [(x + off, y) for x, y in ring])}" '
                       'fill="#1e293b" stroke="#334155" stroke-width="0.6"/>')
    run: list[tuple[float, float]] = []
    prev = None

    def flush():
        if len(run) > 1:
            out.append(f'<polyline points="{_pts(frame, run)}" fill="none" stroke="#38bdf8" stroke-width="1.6" '
                       'stroke-linejoin="round"/>')

    for lon, lat in track:
        p = (frame.lon(lon), lat)
        if prev is not None and (abs(p[0] - prev[0]) > BREAK_DEG or abs(p[1] - prev[1]) > BREAK_DEG):
            flush()
            run = []
        run.append(p)
        prev = p
    flush()
    step = max(1, math.ceil(len(dots) / MAX_DOTS))
    for lon, lat in dots[::step]:
        out.append(f'<circle cx="{frame.x(frame.lon(lon)):.1f}" cy="{frame.y(lat):.1f}" r="2.6" fill="#f59e0b" '
                   'stroke="#0b1726" stroke-width="0.6"/>')
    out.append(f'<text x="6" y="{H - 6}" fill="#94a3b8" font-size="11" font-family="system-ui,sans-serif">'
               f'{escape(lat_range_text(frame.d_south, frame.d_north))} · equirectangular · Natural Earth</text></svg>')
    return "".join(out)


def camera(frame: Frame) -> list[float]:
    lon = folded((frame.d_west + frame.d_east) / 2)
    lat = (frame.d_south + frame.d_north) / 2
    span = max(frame.d_east - frame.d_west, (frame.d_north - frame.d_south) * 1.6, 0.5)
    zoom = min(7.0, max(1.0, math.log2(360.0 / span) - 0.5))
    return [round(lon, 4), round(lat, 4), round(zoom, 2)]
