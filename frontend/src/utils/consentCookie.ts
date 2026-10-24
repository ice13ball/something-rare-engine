// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The shared consent cookie `ac_consent` (atlas + tools.something-rare.com).
// The real implementation is the inline `ga4-bootstrap` block in index.html,
// which exposes window.acConsent so React and the server-rendered banner share
// one copy. ⛔ The cookie attributes live THERE; the fallback below exists only
// for contexts without the block (unit tests, a page served without it).

export type ConsentValue = "granted" | "denied";

declare global {
  interface Window {
    acConsent?: { get: () => ConsentValue | null; set: (v: ConsentValue) => void };
  }
}

export function readConsent(): ConsentValue | null {
  if (typeof document === "undefined") return null;
  if (window.acConsent) return window.acConsent.get();
  const m = document.cookie.match(/(?:^|; )ac_consent=(granted|denied)(?:;|$)/);
  return m ? (m[1] as ConsentValue) : null;
}

export function writeConsent(v: ConsentValue): void {
  if (typeof document === "undefined") return;
  if (window.acConsent) { window.acConsent.set(v); return; }
  const h = location.hostname;
  const shared = h === "something-rare.com" || h.endsWith(".something-rare.com");
  document.cookie = `ac_consent=${v}${shared ? "; Domain=something-rare.com" : ""}; Path=/` +
    `${location.protocol === "https:" ? "; Secure" : ""}; SameSite=Lax; Max-Age=15552000`;
}
