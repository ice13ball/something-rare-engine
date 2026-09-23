// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

declare global {
  interface Window {
    gtag: (command: string, targetId: string, config?: Record<string, unknown>) => void;
    dataLayer: unknown[];
  }
}

const MEASUREMENT_ID = "G-S5HR4WT0ZG";
// v2 since 2026-09-23: v1 values include automatic grants made without asking
// (see the ga4-bootstrap block in index.html), so none of them is carried over.
// seo/render-page.js (server-rendered banner) uses the same key.
const CONSENT_KEY = "abyssal_consent_v2";

// ── Consent helpers ────────────────────────────────────────────────────────

export function getStoredConsent(): "granted" | "denied" | null {
  try {
    const v = localStorage.getItem(CONSENT_KEY);
    if (v === "granted" || v === "denied") return v;
  } catch {}
  return null;
}

export function updateConsent(granted: boolean): void {
  const value = granted ? "granted" : "denied";
  try { localStorage.setItem(CONSENT_KEY, value); } catch {}
  if (typeof window !== "undefined" && window.gtag) {
    window.gtag("consent", "update", {
      analytics_storage: value,
      ad_storage: value,
      ad_user_data: value,
      ad_personalization: value,
    });
    // Re-trigger config so GA4 creates a proper session with cookies
    // (the initial config fired with consent denied, so no session was started)
    if (granted) {
      window.gtag("config", MEASUREMENT_ID, { send_page_view: true });
    }
  }
}

export function clearStoredConsent(): void {
  try { localStorage.removeItem(CONSENT_KEY); } catch {}
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
  if (typeof window !== "undefined" && window.gtag) {
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
