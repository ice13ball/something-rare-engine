// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { readConsent, writeConsent } from "./consentCookie";

declare global {
  interface Window {
    gtag: (command: string, targetId: string, config?: Record<string, unknown>) => void;
    dataLayer: unknown[];
  }
}

const MEASUREMENT_ID = "G-S5HR4WT0ZG";

// ── Consent helpers ────────────────────────────────────────────────────────
// The decision is the shared cookie `ac_consent` (see utils/consentCookie.ts and
// the ga4-bootstrap block in index.html, which also loads gtag.js — and only
// after 'granted').

export function getStoredConsent(): "granted" | "denied" | null {
  return readConsent();
}

export function updateConsent(granted: boolean): void {
  // writeConsent → window.acConsent.set: rewrites the cookie, then either loads
  // gtag.js + config once (granted) or flips Consent Mode to denied.
  writeConsent(granted ? "granted" : "denied");
}

// ── Cookieless page-view beacon ───────────────────────────────────────────
// Fires on every route change regardless of consent — no cookies, no personal
// data, just a date+path counter in Postgres. GDPR-exempt by design.

const API = import.meta.env.VITE_API_URL ?? "";

// ⛔ Fire-and-forget, and bounded. Nothing here is awaited and every failure is
// swallowed, so a counter can never delay or break a page — that part was
// already true. What was missing is the deadline: on 2026-09-18 the backend
// was saturated and Cloud Run logged 504s on /api/v1/pageview, each one an
// open proxy socket held for as long as the BFF would wait (then 120 s). A
// beacon that outlives the page view it describes is pure cost.
//
// 3 s is chosen against the beacon's own worth: a page view recorded later
// than that is still recorded, and one lost is one row in a counter table.
const PAGEVIEW_TIMEOUT_MS = 3000;

export function sendPageView(path: string): void {
  fetch(`${API}/api/v1/pageview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
    keepalive: true,
    signal: AbortSignal.timeout(PAGEVIEW_TIMEOUT_MS),
  }).catch(() => {});
}

// ── Event tracking ─────────────────────────────────────────────────────────

export const trackEvent = (eventName: string, eventParams?: Record<string, unknown>) => {
  // ⛔ Without consent nothing may enter dataLayer: gtag.js flushes the queue
  // when it loads after Accept, so a pre-consent event would reach Google then.
  if (typeof window !== "undefined" && window.gtag && readConsent() === "granted") {
    window.gtag("event", eventName, { ...eventParams, send_to: MEASUREMENT_ID });
  }
};

export const analytics = {
  trackEvent,
  selectConcession: (id: string, contractor: string) =>
    trackEvent("select_concession", { concession_id: id, contractor }),
  toggleLayer: (layerName: string, isVisible: boolean) =>
    trackEvent("toggle_layer", { layer_id: layerName, visible: isVisible ? 1 : 0 }),
  clickExternalLink: (linkName: string, url: string) =>
    trackEvent("click_external_link", { link_name: linkName, url }),
  toggleIucnFilter: (cat: string, active: boolean) =>
    trackEvent("toggle_iucn_filter", { iucn_category: cat, active: active ? 1 : 0 }),
  toggleAlarmFilter: (alarm: string, active: boolean) =>
    trackEvent("toggle_alarm_filter", { alarm_type: alarm, active: active ? 1 : 0 }),
  openLegendTab: (tab: string) =>
    trackEvent("open_legend_tab", { tab }),
  clickAtRiskClaim: (isa_id: string, contractor: string) =>
    trackEvent("click_at_risk_claim", { concession_id: isa_id, contractor }),
  consentDecision: (granted: boolean) =>
    trackEvent("consent_decision", { granted: granted ? 1 : 0 }),
};
