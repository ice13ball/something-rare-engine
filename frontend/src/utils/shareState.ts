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
export interface ShareState {
  camera: ShareCamera | null;
  layers: LayerId[] | null;
  filters: Record<string, string[]> | null;
}

interface ShareEnvelope {
  v: number;
  c?: [number, number, number, number, number];
  l?: string[];
  f?: Record<string, string[]>;
}

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

export function encodeShareState(state: {
  camera: ShareCamera | PersistedViewState;
  layers: LayerId[];
  filters: Record<string, string[]>;
}): string {
  const envelope: ShareEnvelope = { v: SHARE_STATE_VERSION };
  const { longitude, latitude, zoom, pitch, bearing } = state.camera;
  envelope.c = [longitude, latitude, zoom, pitch, bearing];
  if (state.layers.length > 0) envelope.l = state.layers;
  if (Object.keys(state.filters).length > 0) envelope.f = state.filters;
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

  return {
    camera: validateCamera(envelope.c),
    layers: validateLayers(envelope.l),
    filters: validateFilters(envelope.f),
  };
}

export function buildShareUrl(
  origin: string,
  pathname: string,
  state: {
    camera: ShareCamera | PersistedViewState;
    layers: LayerId[];
    filters: Record<string, string[]>;
  },
): string {
  const s = encodeShareState(state);
  const params = new URLSearchParams();
  params.set("s", s);
  return `${origin}${pathname}?${params.toString()}`;
}
