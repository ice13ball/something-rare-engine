// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * "Graphics" display preference: enhanced (3D models for seamounts and vents) or simple (columns).
 *
 * A personal display preference, not map state: it changes no data, so it lives in localStorage
 * and is deliberately NOT in share links (see DISPLAY_OPT_OUT_FIELDS). Kept free of deck.gl
 * imports so the store can use it without pulling in anything heavy.
 */
export type GraphicsMode = "enhanced" | "simple";

/**
 * Desktop default when the user has not chosen. ROLLBACK to columns-by-default = change this one
 * word to "simple" (phones are already simple; stored user choices still win).
 */
export const DESKTOP_DEFAULT_GRAPHICS: GraphicsMode = "enhanced";

export const GRAPHICS_STORAGE_KEY = "abyssal_graphics";

/**
 * Phone detection for the default. `(pointer: coarse) and (hover: none)` is a touch-first device
 * (phones, most tablets) whatever its width; the 768 px test additionally catches a narrow desktop
 * window or a device that reports a fine pointer. Either one means "simple": the lighter path is
 * the safe default where GPU and bandwidth are scarce. The user can always override it.
 */
function isPhoneLike(): boolean {
  if (typeof window === "undefined") return false;
  const touchFirst = typeof window.matchMedia === "function"
    && window.matchMedia("(pointer: coarse) and (hover: none)").matches;
  return touchFirst || window.innerWidth < 768;
}

/** Stored choice, else (temporary testing override) ?models=1|0, else the device default
 * (simple on phones and under prefers-reduced-motion, DESKTOP_DEFAULT_GRAPHICS elsewhere). */
export function readGraphicsMode(): GraphicsMode {
  try {
    const stored = window.localStorage.getItem(GRAPHICS_STORAGE_KEY);
    if (stored === "enhanced" || stored === "simple") return stored;
  } catch { /* storage blocked — fall through to the default */ }
  try {
    // Testing override only; never persisted, and an explicit user choice (above) wins.
    const flag = new URLSearchParams(window.location.search).get("models");
    if (flag === "1") return "enhanced";
    if (flag === "0") return "simple";
  } catch { /* SSR */ }
  return isPhoneLike() || prefersReducedMotion() ? "simple" : DESKTOP_DEFAULT_GRAPHICS;
}

/**
 * A system request for reduced motion also starts on simple graphics (Michal, 29.10.2026): the
 * models' plume is animated. The user can still pick enhanced, and then the plume stays still.
 */
function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function persistGraphicsMode(mode: GraphicsMode): void {
  try { window.localStorage.setItem(GRAPHICS_STORAGE_KEY, mode); } catch { /* quota/blocked — non-fatal */ }
}
