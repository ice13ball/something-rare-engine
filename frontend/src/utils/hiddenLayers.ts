// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Per-environment list of layer ids hidden in the UI.
 *
 * Dev and prod share one backend and one `layer_config` table, so `status`
 * cannot differ per environment. The BFF (server.js) reads the HIDDEN_LAYERS env
 * var and writes `<meta name="abyssal-hidden-layers" content="a,b">` into every
 * HTML shell that boots the SPA; this module reads it. No tag = nothing hidden =
 * behaviour identical to before this existed.
 */

export const HIDDEN_LAYERS_META_NAME = "abyssal-hidden-layers";

// Mirrors seo/hidden-layers.js. Unknown-but-well-formed ids are kept (they match
// no layer, so they hide nothing); malformed ones are dropped.
const LAYER_ID = /^[a-z0-9-]+$/;

export function parseHiddenLayers(raw: string | null | undefined): string[] {
  if (!raw) return [];
  const out: string[] = [];
  for (const part of raw.split(",")) {
    const id = part.trim();
    if (id && LAYER_ID.test(id) && !out.includes(id)) out.push(id);
  }
  return out;
}

let cached: ReadonlySet<string> | undefined;

/** Read once per page load: the tag is written by the server and never changes. */
export function getHiddenLayers(): ReadonlySet<string> {
  if (cached === undefined) {
    let raw: string | null = null;
    try {
      raw = document.querySelector(`meta[name="${HIDDEN_LAYERS_META_NAME}"]`)?.getAttribute("content") ?? null;
    } catch { /* no DOM (SSR/tests without jsdom): nothing hidden */ }
    cached = new Set(parseHiddenLayers(raw));
  }
  return cached;
}

export function isLayerHidden(id: string): boolean {
  return getHiddenLayers().has(id);
}

/** Test seam: forget the cached read so the next call re-reads the document. */
export function resetHiddenLayersCache(): void {
  cached = undefined;
}

/**
 * Apply the hidden list to an enabled-id set.
 *  - nothing hidden: returned as is (including null = allow-all), so the
 *    no-env-var path is unchanged;
 *  - null (config unknown / fetch failed) with something hidden: allow-all can
 *    no longer be expressed as null, so it becomes "every known id minus hidden".
 */
export function applyHiddenLayers(
  enabled: Set<string> | null,
  allKnownIds: Iterable<string>,
): Set<string> | null {
  const hidden = getHiddenLayers();
  if (hidden.size === 0) return enabled;
  const base = enabled ?? new Set(allKnownIds);
  return new Set([...base].filter((id) => !hidden.has(id)));
}
