// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Per-environment "hide these layers in the UI", set by the HIDDEN_LAYERS env var
// (comma-separated layer ids) on the Cloud Run service. Dev and prod share ONE
// backend and ONE layer_config table, so layer_config.status cannot differ per
// environment; this is the only per-environment switch.
//
// Delivered to the SPA as <meta name="abyssal-hidden-layers" content="a,b"> rather
// than an inline script: a meta tag is inert data, needs no CSP allowance and no
// nonce. The client reads it in src/utils/hiddenLayers.ts. Unset or empty = no tag
// at all, so the served HTML is byte-identical to before this existed.

export const HIDDEN_LAYERS_META_NAME = 'abyssal-hidden-layers';

// Same pattern the client applies. Layer ids are lowercase dash-ids; anything else
// (typos, quotes, angle brackets) is dropped, never escaped-and-kept.
const LAYER_ID = /^[a-z0-9-]+$/;

export function parseHiddenLayers(raw) {
  if (typeof raw !== 'string') return [];
  const out = [];
  for (const part of raw.split(',')) {
    const id = part.trim();
    if (id && LAYER_ID.test(id) && !out.includes(id)) out.push(id);
  }
  return out;
}

const escapeAttr = (s) => s
  .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');

export function hiddenLayersMetaTag(ids) {
  if (!ids || ids.length === 0) return '';
  return `<meta name="${HIDDEN_LAYERS_META_NAME}" content="${escapeAttr(ids.join(','))}" />`;
}

/** Read once at startup: a change of the env var means a new Cloud Run revision. */
export const HIDDEN_LAYER_IDS = parseHiddenLayers(process.env.HIDDEN_LAYERS);

/**
 * Insert the meta tag right after the opening <head>. No ids, or no <head> to
 * anchor on: the HTML comes back untouched.
 */
export function injectHiddenLayersMeta(html, ids = HIDDEN_LAYER_IDS) {
  const tag = hiddenLayersMetaTag(ids);
  if (!tag) return html;
  return html.replace(/<head(\s[^>]*)?>/i, (open) => `${open}\n  ${tag}`);
}
