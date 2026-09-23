// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Kept in its own module, free of side effects, so tests can load it without
// the dist/index.html that render-page.js reads at import time.
// ─────────────────────────────────────────────────────────────────────────────
// The consent banner for server-rendered pages.
//
// The React CookieBanner mounts only inside MapApp, i.e. on `/`. Every page
// built here — where search traffic lands — had no banner at all, so a visitor
// there could never grant or decline. This is the same banner in plain HTML and
// JS, outside #root so hydration cannot remove it, and it behaves like
// CookieBanner + analytics.updateConsent: shown to EVERY visitor without a
// stored decision (no automatic grant, whatever the browser language), and a
// choice updates Consent Mode and, if granted, re-runs `config` so GA4 starts a
// session with cookies.
//
// ⛔ Same storage key as src/utils/analytics.ts and the index.html bootstrap.
export const CONSENT_STORAGE_KEY = 'abyssal_consent_v2';

export const CONSENT_BANNER_HTML = `  <div id="consent-banner" hidden role="dialog" aria-label="Cookie consent" style="position:fixed;left:0;right:0;bottom:0;z-index:2147483000;padding:12px;display:flex;justify-content:center;pointer-events:none">
    <div style="pointer-events:auto;background:#111827;border:1px solid rgba(255,255,255,.15);border-radius:12px;padding:12px 16px;max-width:42rem;width:100%;box-shadow:0 25px 50px -12px rgba(0,0,0,.5);display:flex;flex-wrap:wrap;align-items:center;gap:12px;font:12px/1.6 system-ui,sans-serif">
      <p style="margin:0;flex:1;min-width:14rem;color:rgba(255,255,255,.8)">We use cookies for analytics. <a href="/privacy" style="color:rgba(255,255,255,.85)">Privacy Policy</a> · <a href="/terms" style="color:rgba(255,255,255,.85)">Terms of Use</a></p>
      <div style="display:flex;gap:8px">
        <button type="button" data-consent="denied" style="padding:6px 12px;font-size:12px;color:rgba(255,255,255,.7);background:transparent;border:1px solid rgba(255,255,255,.15);border-radius:8px;cursor:pointer">Decline</button>
        <button type="button" data-consent="granted" style="padding:6px 12px;font-size:12px;font-weight:500;color:#000;background:rgba(255,255,255,.9);border:0;border-radius:8px;cursor:pointer">Accept</button>
      </div>
    </div>
  </div>
  <script>
    (function () {
      var KEY = '${CONSENT_STORAGE_KEY}';
      var el = document.getElementById('consent-banner');
      var stored = null;
      try { stored = localStorage.getItem(KEY); } catch (e) {}
      if (stored !== null || !el) return;
      el.hidden = false;
      el.addEventListener('click', function (ev) {
        var btn = ev.target.closest && ev.target.closest('[data-consent]');
        if (!btn) return;
        var value = btn.getAttribute('data-consent');
        try { localStorage.setItem(KEY, value); } catch (e) {}
        if (typeof window.gtag === 'function') {
          window.gtag('consent', 'update', { analytics_storage: value, ad_storage: value, ad_user_data: value, ad_personalization: value });
          if (value === 'granted') window.gtag('config', 'G-S5HR4WT0ZG', { send_page_view: true });
          window.gtag('event', 'consent_decision', { granted: value === 'granted' ? 1 : 0, send_to: 'G-S5HR4WT0ZG' });
        }
        el.hidden = true;
      });
    })();
  </script>`;
