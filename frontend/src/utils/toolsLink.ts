// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

const SUPPORTED = ["en", "pl", "fr", "de"];

/** Link to tools.something-rare.com carrying the current UI language (contract §2).
 *  Compute it at render from i18n.resolvedLanguage so it follows a language switch. */
export function toolsUrl(lang: string | undefined): string {
  const l = lang && SUPPORTED.includes(lang) ? lang : "en";
  return `https://tools.something-rare.com/?lang=${l}`;
}
