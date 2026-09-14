// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { LayerId } from "../types/layers";
import type { PersistedViewState } from "./mapState";
import { VALID_LAYER_IDS } from "./layersParam";
import { isShareableFilterField } from "../types/filterRegistry";

// Bump on any incompatible envelope change. A version MISMATCH returns null
// from decode — never "best effort reinterpret an old shape as the new one".
// A link is a promise about a shape; guessing at a broken promise is how a
// camera position quietly turns into a page full of NaN.
export const SHARE_STATE_VERSION = 1;

// A `?s=` value this long is not a link a human copy-pasted or a button
// generated — it's either a corrupted paste or an attempt to make the app do
// expensive work parsing garbage. Checked BEFORE any base64/JSON work so a
// hostile value costs a string length check, not a parse.
export const MAX_PARAM_LENGTH = 4000;

export interface ShareCamera {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
}

/** What a link can carry, each field independently present-or-null. */
/**
 * One spot on a continuous field: `[layer, lon, lat]`, plus the one selector
 * value that layer's panel needs (`depth` in metres, or a decade index).
 *
 * ⛔ Longitude first, matching `c` and GeoJSON — and NOT matching the
 * `<lat>,<lon>` order of the synthetic selection id this eventually rebuilds.
 * The two orders genuinely differ; the range check below is what stops a swap
 * from passing silently, since a real latitude past ±90 is rejected.
 */
export type SharePoint = [LayerId, number, number, number?];

/** What a link can carry, each field independently present-or-null. */
export interface ShareState {
  camera: ShareCamera | null;
  layers: LayerId[] | null;
  filters: Record<string, string[]> | null;
  openObjects: Array<[LayerId, string]> | null;
  points: SharePoint[] | null;
}

// `o` is additive and optional, so it does NOT need a SHARE_STATE_VERSION
// bump: an older client decoding a link that carries it sees `v:1`, ignores
// the unknown `o` key entirely, and simply doesn't open a panel — the rest of
// the envelope still decodes normally. A version bump is reserved for
// INCOMPATIBLE shape changes (a field renamed/repurposed); adding an optional
// field a reader can safely ignore is not one.
interface ShareEnvelope {
  v: number;
  c?: [number, number, number, number, number];
  l?: string[];
  f?: Record<string, string[]>;
  o?: Array<[string, string]>; // [public layer id, feature id]
  p?: Array<[string, number, number] | [string, number, number, number]>;
}

/**
 * mapStore.ts caps open detail panels at 3 — a link must not promise a fourth
 * panel it can never actually open.
 *
 * ⛔ The cap is JOINT across `o` and `p`. They are separate fields but they
 * open panels from the same pool of three: a link claiming three records and
 * two points would have two of its five quietly never appear. A link this side
 * produces can never exceed three (both lists are built from one `≤3`
 * selection), so hitting the joint cap means the value was edited or corrupted
 * — `o` is honoured first and `p` gets what is left.
 */
export const MAX_OPEN_OBJECTS = 3;

// base64url, not base64 — the value rides in a query string, where `+`, `/`
// and `=` either get percent-encoded (harmless but ugly) or, if a caller ever
// concatenates the URL by hand instead of using URLSearchParams, silently
// corrupt the param. `-`/`_` never need encoding there.
function toBase64Url(json: string): string {
  const b64 = btoa(unescape(encodeURIComponent(json)));
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(s: string): string {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  return decodeURIComponent(escape(atob(padded)));
}

function isFiniteNumber(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

/** Camera validates independently of layers/filters — a bad layer list must
 * not cost the reader a good camera, and vice versa. */
function validateCamera(c: ShareEnvelope["c"]): ShareCamera | null {
  if (!Array.isArray(c) || c.length !== 5 || !c.every(isFiniteNumber)) return null;
  const [longitude, latitude, zoom, pitch, bearing] = c;
  return { longitude, latitude, zoom, pitch, bearing };
}

/**
 * ⛔ ONE unknown layer id rejects the WHOLE list — same rule as
 * `parseLayersParam`, deliberately re-run here rather than delegated to it,
 * because that function's job is parsing a comma string and this one already
 * has an array. Reusing its VALID-id source (not a second copy of the ids) is
 * what actually matters and is what happens via `VALID_LAYER_IDS`.
 */
function validateLayers(l: ShareEnvelope["l"]): LayerId[] | null {
  if (!Array.isArray(l) || l.length === 0) return null;
  for (const id of l) {
    if (typeof id !== "string" || !VALID_LAYER_IDS.has(id)) return null;
  }
  return l as LayerId[];
}

/** Unlike layers, a stray/malformed filter key just gets dropped — see the
 * rationale in filterRegistry.ts's `applyShareableFilters`. */
function validateFilters(f: ShareEnvelope["f"]): Record<string, string[]> | null {
  if (!f || typeof f !== "object") return null;
  const out: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(f)) {
    if (!isShareableFilterField(key)) continue;
    if (!Array.isArray(value) || !value.every((v) => typeof v === "string")) continue;
    if (value.length === 0) continue;
    out[key] = value;
  }
  return Object.keys(out).length > 0 ? out : null;
}

/**
 * Modeled on `validateFilters` (per-entry drop), NOT on `validateLayers`
 * (whole-list reject). `validateLayers` rejects wholesale because a typo
 * there would silently become "show zero layers" — it changes what the map
 * shows. One unopenable object here does not: the map still renders exactly
 * as requested, and rejecting the whole list would additionally cost the
 * reader the two objects that WERE fine, for no corresponding safety gain.
 */
function validateOpenObjects(o: ShareEnvelope["o"]): Array<[LayerId, string]> | null {
  if (!Array.isArray(o)) return null;

  const seen = new Set<string>();
  const out: Array<[LayerId, string]> = [];
  for (const entry of o) {
    if (out.length >= MAX_OPEN_OBJECTS) break;
    if (!Array.isArray(entry) || entry.length !== 2) continue;
    const [layer, id] = entry;
    if (typeof layer !== "string" || typeof id !== "string") continue;
    if (!VALID_LAYER_IDS.has(layer)) continue;
    const key = `${layer} ${id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push([layer as LayerId, id]);
  }
  return out.length > 0 ? out : null;
}

/**
 * Structural validation only — shape, types and geographic range. Whether the
 * named layer can actually be addressed by coordinate is NOT decided here.
 *
 * ⛔ That split is deliberate and mirrors `o`: a layer that has stopped being
 * point-addressable must reach the map as a request it can REPORT, not vanish
 * during parsing. Dropping it here would make a link to a retired layer look
 * exactly like a link that asked for nothing — the failure this feature exists
 * to end.
 */
function validatePoints(p: ShareEnvelope["p"], budget: number): SharePoint[] | null {
  if (!Array.isArray(p) || budget <= 0) return null;

  const seen = new Set<string>();
  const out: SharePoint[] = [];
  for (const entry of p) {
    if (out.length >= budget) break;
    if (!Array.isArray(entry) || entry.length < 3 || entry.length > 4) continue;
    const [layer, lon, lat, extra] = entry as [unknown, unknown, unknown, unknown];
    if (typeof layer !== "string" || !VALID_LAYER_IDS.has(layer)) continue;
    if (!isFiniteNumber(lon) || !isFiniteNumber(lat)) continue;
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) continue;
    if (entry.length === 4 && !isFiniteNumber(extra)) continue;
    // ⛔ Dedup on the extra too. The same spot at 0 m and at 1000 m are two
    // different readings, and the sender may well have had both open.
    const key = `${layer} ${lon} ${lat} ${entry.length === 4 ? extra : ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(entry.length === 4
      ? [layer as LayerId, lon, lat, extra as number]
      : [layer as LayerId, lon, lat]);
  }
  return out.length > 0 ? out : null;
}

export function encodeShareState(state: {
  camera: ShareCamera | PersistedViewState;
  layers: LayerId[];
  filters: Record<string, string[]>;
  /**
   * ⛔ Required, not optional. Making it optional kept the old call sites
   * compiling — and would have shipped a "Share view" button whose link
   * silently lacked the panel the address bar was already carrying. Every
   * place that builds a link must decide, even if the decision is `[]`.
   */
  openObjects: Array<[string, string]>;
  /** ⛔ Required for the same reason as `openObjects` — see above. */
  points: ReadonlyArray<readonly [string, number, number, number?]>;
}): string {
  const envelope: ShareEnvelope = { v: SHARE_STATE_VERSION };
  const { longitude, latitude, zoom, pitch, bearing } = state.camera;
  envelope.c = [longitude, latitude, zoom, pitch, bearing];
  if (state.layers.length > 0) envelope.l = state.layers;
  if (Object.keys(state.filters).length > 0) envelope.f = state.filters;
  if (state.openObjects && state.openObjects.length > 0) envelope.o = state.openObjects;
  if (state.points && state.points.length > 0) {
    // ⛔ A 4th slot is emitted only when there IS a value. Writing `null` to
    // keep the tuples uniform would cost bytes and, worse, make "this layer
    // has no selector" indistinguishable from "the selector was lost".
    envelope.p = state.points.map(([l, lon, lat, extra]) =>
      (extra === undefined
        ? [l, lon, lat]
        : [l, lon, lat, extra]) as [string, number, number] | [string, number, number, number],
    );
  }
  return toBase64Url(JSON.stringify(envelope));
}

/**
 * Decode and validate a `?s=` value. Returns null for the whole thing only
 * when nothing in it can be trusted (over length, not valid base64/JSON, or
 * version mismatch) — otherwise each field is validated on its own and a bad
 * one becomes `null` for THAT field, not for the others.
 */
export function decodeShareState(raw: string | null): ShareState | null {
  if (!raw) return null;
  if (raw.length > MAX_PARAM_LENGTH) return null;

  let envelope: ShareEnvelope;
  try {
    envelope = JSON.parse(fromBase64Url(raw));
  } catch {
    return null;
  }
  if (!envelope || envelope.v !== SHARE_STATE_VERSION) return null;

  const openObjects = validateOpenObjects(envelope.o);
  return {
    camera: validateCamera(envelope.c),
    layers: validateLayers(envelope.l),
    filters: validateFilters(envelope.f),
    openObjects,
    points: validatePoints(envelope.p, MAX_OPEN_OBJECTS - (openObjects?.length ?? 0)),
  };
}

export function buildShareUrl(
  origin: string,
  pathname: string,
  state: {
    camera: ShareCamera | PersistedViewState;
    layers: LayerId[];
    filters: Record<string, string[]>;
    openObjects: Array<[string, string]>;
    points: ReadonlyArray<readonly [string, number, number, number?]>;
  },
): string {
  const s = encodeShareState(state);
  const params = new URLSearchParams();
  params.set("s", s);
  return `${origin}${pathname}?${params.toString()}`;
}
