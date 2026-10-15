// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/** The SSR cruise page of an EXPOCODE. Same key rule as backend/domains/seo_cruises.CRUISE_KEY_RE: a key that can
 *  never have a page gets no link (a visible link to a 404 is the bug). */
export const CRUISE_KEY_RE = /^[A-Za-z0-9_-]{4,32}$/;

export function cruisePageHref(expocode: string | null | undefined): string | null {
  return expocode && CRUISE_KEY_RE.test(expocode) ? `/cruise/${encodeURIComponent(expocode)}` : null;
}
