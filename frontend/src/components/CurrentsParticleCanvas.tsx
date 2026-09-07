// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef } from "react";
import { WebMercatorViewport } from "@deck.gl/core";

/**
 * Decoded velocity field: raw RGBA texels (u in R, v in G, alpha=0 on land),
 * plus the geographic bounds and the m/s range the 0..255 channel maps to.
 */
export interface VelocityField {
  data: Uint8ClampedArray;
  width: number;
  height: number;
  bounds: [number, number, number, number]; // [W, S, E, N]
  unscale: [number, number];                 // [min, max] m/s
}

interface ViewLike {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch?: number;
  bearing?: number;
}

/**
 * windy.com-style ocean-current particle animation, drawn on a 2D <canvas>
 * overlay. Particles are advected on the CPU through the velocity field each
 * frame and projected to the screen with deck.gl's WebMercatorViewport, so the
 * field stays locked to the map under pan/zoom. Runs entirely independently of
 * deck.gl's (MapLibre-interleaved) GPU render loop.
 */
export function CurrentsParticleCanvas({
  field,
  viewState,
  active,
  playing,
}: {
  field: VelocityField | null;
  viewState: ViewLike;
  active: boolean;
  /** True while the time-lapse is auto-advancing. When set, a field change does
   *  NOT reseed particles (keeps playback smooth). A manual date/depth scrub
   *  (playing falsy) reseeds so the new field is visibly redrawn. */
  playing?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Latest props for the rAF loop to read without re-subscribing each frame.
  const liveRef = useRef<{ field: VelocityField | null; viewState: ViewLike; active: boolean; playing?: boolean }>({
    field,
    viewState,
    active,
    playing,
  });
  liveRef.current = { field, viewState, active, playing };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const NUM_PARTICLES = 3500;
    const MAX_AGE = 120;       // frames before a particle respawns (longer = calmer)
    const STEP = 0.018;        // degrees of travel per (m/s) per frame (visual speed)
    const TRAIL_FADE = 0.07;   // higher = shorter trails

    type Particle = { lon: number; lat: number; age: number };
    const particles: Particle[] = Array.from({ length: NUM_PARTICLES }, () => ({
      lon: 0,
      lat: 0,
      age: 0,
    }));
    let seeded = false;
    // Tracks the field the loop last rendered, to detect manual date/depth scrubs.
    let lastField: VelocityField | null = null;

    // Bilinear-alpha cutoff (0-255). The land mask is only 0.5deg-precise, so a
    // hard alpha===0 test lets particles in coastal "water" cells (up to ~60%
    // land) draw over the shore. Interpolating alpha across the 4 surrounding
    // texels ramps it down toward coasts; dropping below this cutoff crops the
    // current back toward open water with sub-cell precision. Higher = stricter.
    const LAND_ALPHA_CUTOFF = 205;

    function sampleUV(f: VelocityField, lon: number, lat: number): [number, number] | null {
      const [W, S, E, N] = f.bounds;
      if (lon < W || lon > E || lat < S || lat > N) return null;
      const fx = ((lon - W) / (E - W)) * (f.width - 1);
      const fy = ((N - lat) / (N - S)) * (f.height - 1); // row 0 = north
      const x0 = Math.max(0, Math.min(f.width - 1, Math.floor(fx)));
      const y0 = Math.max(0, Math.min(f.height - 1, Math.floor(fy)));
      const x1 = Math.min(f.width - 1, x0 + 1);
      const y1 = Math.min(f.height - 1, y0 + 1);
      const tx = fx - x0;
      const ty = fy - y0;
      const corners: [number, number, number][] = [
        [x0, y0, (1 - tx) * (1 - ty)],
        [x1, y0, tx * (1 - ty)],
        [x0, y1, (1 - tx) * ty],
        [x1, y1, tx * ty],
      ];
      // Bilinear alpha includes land corners (alpha 0); velocity is averaged over
      // WATER corners only — land texels decode to a spurious -3 m/s and must not
      // pollute the flow near coasts.
      let sa = 0, su = 0, sv = 0, sw = 0;
      for (const [cx, cy, w] of corners) {
        const j = (cy * f.width + cx) * 4;
        const a = f.data[j + 3];
        sa += a * w;
        if (a !== 0) { su += f.data[j] * w; sv += f.data[j + 1] * w; sw += w; }
      }
      if (sa < LAND_ALPHA_CUTOFF || sw === 0) return null; // coast / land / no-data
      const [mn, mx] = f.unscale;
      const span = mx - mn;
      const u = (su / sw / 255) * span + mn;
      const v = (sv / sw / 255) * span + mn;
      return [u, v];
    }

    // Spawn a particle at a random point inside the current view extent.
    function spawn(p: Particle, b: [number, number, number, number]) {
      p.lon = b[0] + Math.random() * (b[2] - b[0]);
      p.lat = b[1] + Math.random() * (b[3] - b[1]);
      p.age = Math.floor(Math.random() * MAX_AGE);
    }

    let raf = 0;
    function frame() {
      raf = requestAnimationFrame(frame);
      const { field: f, viewState: vs, active: on, playing: play } = liveRef.current;
      const w = canvas!.clientWidth;
      const h = canvas!.clientHeight;
      if (!on || !f || w === 0 || h === 0) {
        if (canvas!.width !== 0) {
          canvas!.width = canvas!.height = 0; // release when inactive
          seeded = false;
        }
        return;
      }
      if (canvas!.width !== w || canvas!.height !== h) {
        canvas!.width = w;
        canvas!.height = h;
      }

      let vp: WebMercatorViewport;
      try {
        vp = new WebMercatorViewport({
          width: w,
          height: h,
          longitude: vs.longitude,
          latitude: vs.latitude,
          zoom: vs.zoom,
          pitch: vs.pitch ?? 0,
          bearing: vs.bearing ?? 0,
        });
      } catch {
        return;
      }
      const vb = vp.getBounds() as [number, number, number, number]; // [minLng,minLat,maxLng,maxLat]

      // A manual date/depth scrub swaps the field reference while NOT playing →
      // reseed so the new field is visibly redrawn. During the time-lapse
      // (play truthy) keep particles flowing for a smooth animation.
      if (f !== lastField) {
        if (lastField !== null && !play) seeded = false;
        lastField = f;
      }

      if (!seeded) {
        for (const p of particles) spawn(p, vb);
        seeded = true;
      }

      // Fade previous frame for trails.
      ctx!.globalCompositeOperation = "destination-out";
      ctx!.fillStyle = `rgba(0,0,0,${TRAIL_FADE})`;
      ctx!.fillRect(0, 0, w, h);
      ctx!.globalCompositeOperation = "source-over";
      ctx!.lineWidth = 1.3;
      ctx!.lineCap = "round";

      for (const p of particles) {
        p.age++;
        const uv = sampleUV(f, p.lon, p.lat);
        if (!uv || p.age > MAX_AGE) {
          spawn(p, vb);
          continue;
        }
        const [u, v] = uv;
        const speed = Math.hypot(u, v);
        const cosLat = Math.cos((p.lat * Math.PI) / 180) || 1e-3;
        const nlon = p.lon + (u * STEP) / cosLat;
        const nlat = p.lat + v * STEP;

        // Don't draw a segment that crosses onto land — respawn instead. Stops
        // the trailing streak a coastal particle would otherwise paint inland.
        if (!sampleUV(f, nlon, nlat)) {
          spawn(p, vb);
          continue;
        }

        const [px, py] = vp.project([p.lon, p.lat]) as [number, number];
        const [nx, ny] = vp.project([nlon, nlat]) as [number, number];

        // teal (slow) → amber (fast)
        const t = Math.min(speed / 1.5, 1);
        const r = Math.round(94 + t * 157);
        const g = Math.round(234 - t * 43);
        const bch = Math.round(212 - t * 176);
        ctx!.strokeStyle = `rgba(${r},${g},${bch},0.9)`;
        ctx!.beginPath();
        ctx!.moveTo(px, py);
        ctx!.lineTo(nx, ny);
        ctx!.stroke();

        p.lon = nlon;
        p.lat = nlat;
      }
    }
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 2,
      }}
    />
  );
}
