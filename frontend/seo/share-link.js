// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// "Open on the map" links built on the server. ⛔ Must stay byte-compatible with encodeShareState() in
// src/utils/shareState.ts: envelope {v, c:[lon,lat,zoom,pitch,bearing], l, d}, JSON, base64url without padding.
// A version mismatch makes decodeShareState() return null, i.e. the link silently opens the default map.
const SHARE_STATE_VERSION = 1;

export function shareLinkHref({ layers, display, camera }) {
  const [lon, lat, zoom] = camera;
  const env = { v: SHARE_STATE_VERSION, c: [lon, lat, zoom, 0, 0], l: layers };
  if (display && Object.keys(display).length > 0) env.d = display;
  return `/?s=${Buffer.from(JSON.stringify(env), 'utf8').toString('base64url')}`;
}
