// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ── Shared panel primitives (centralised sizes/spacing) ──────────────────────
// Change font sizes here to update ALL popups at once.

export const API = import.meta.env.VITE_API_BASE_URL ?? "";

export const T = {
  header:    "text-white text-sm font-semibold font-sans leading-tight mb-1",
  subtitle:  "text-[14px] font-sans",
  rowLabel:  "text-white/70 text-[14px] shrink-0",
  rowValue:  "text-white/90 text-[14px] text-right font-mono",
  sectionH:  "text-white/65 text-[13px] uppercase tracking-widest mb-1.5 font-sans",
  badge:     "text-[14px] font-mono",
  body:      "text-white/70 text-[14px] leading-relaxed",
  hint:      "text-white/70 text-[14px] leading-relaxed",
  warning:   "text-[14px] font-sans",
  source:    "text-white/65 text-[14px] mt-2 uppercase tracking-wider",
  expand:    "text-[13px] uppercase tracking-wider flex items-center gap-1 mb-1",
} as const;
