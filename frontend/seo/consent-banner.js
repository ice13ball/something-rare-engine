// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Kept in its own module, free of side effects, so tests can load it without
// the dist/index.html that render-page.js reads at import time.
// ─────────────────────────────────────────────────────────────────────────────
// The consent banner for server-rendered pages.
//
// The React CookieBanner mounts only inside MapApp, i.e. on `/`. Every page
// built here — where search traffic lands — has no React banner, so this is the
// same banner in plain HTML and JS, outside #root so hydration cannot remove it.
// It is shown to EVERY visitor without a stored decision (no automatic grant).
//
// ⛔ The decision lives in the shared cookie `ac_consent`, owned by the
// ga4-bootstrap block (index.html → window.acConsent: get / set, which also
// loads gtag.js after 'granted'). This script re-types neither the cookie nor
// the loader, so there is no second copy to drift. The text is the contract
// wording of ekosystem-wspolne-ustalenia §3, copied verbatim; there is no i18n
// runtime here, so the 4 languages are embedded and picked by localStorage
// `abyssal_lang`, then navigator.language, else en.
//
// CONSENT_STORAGE_KEY is the LEGACY localStorage key, migrated away by the
// bootstrap; it is exported only for the tests that still import it.
export const CONSENT_STORAGE_KEY = 'abyssal_consent_v2';

const BANNER_TEXT = {
  pl: {
    text: 'Za Twoją zgodą używamy Google Analytics, żeby liczyć odwiedziny i użycie Atlasu i Narzędzi Abyssal Claims. Jedna decyzja obowiązuje w obu. Nigdy nie wysyłamy treści Twoich plików ani wklejonych linków.',
    decline: 'Odrzucam', accept: 'Akceptuję', privacy: 'Prywatność', label: 'Zgoda na pliki cookie',
  },
  en: {
    text: 'With your consent we use Google Analytics to count visits to and use of the Abyssal Claims Atlas and Tools. One choice applies to both. We never send the contents of your files or the links you paste.',
    decline: 'Decline', accept: 'Accept', privacy: 'Privacy', label: 'Cookie consent',
  },
  de: {
    text: 'Mit Ihrer Einwilligung nutzen wir Google Analytics, um die Besuche und die Nutzung des Atlas und der Werkzeuge von Abyssal Claims zu zählen. Eine Entscheidung gilt für beide. Wir senden niemals den Inhalt Ihrer Dateien oder die von Ihnen eingefügten Links.',
    decline: 'Ablehnen', accept: 'Akzeptieren', privacy: 'Datenschutz', label: 'Cookie-Einwilligung',
  },
  fr: {
    text: "Avec votre accord, nous utilisons Google Analytics pour compter les visites et l'utilisation de l'Atlas et des Outils d'Abyssal Claims. Un seul choix vaut pour les deux. Nous n'envoyons jamais le contenu de vos fichiers ni les liens que vous collez.",
    decline: 'Refuser', accept: 'Accepter', privacy: 'Confidentialité', label: 'Consentement aux cookies',
  },
};

export const CONSENT_BANNER_HTML = `  <div id="consent-banner" hidden role="dialog" aria-label="Cookie consent" style="position:fixed;left:0;right:0;bottom:0;z-index:2147483000;padding:12px;display:flex;justify-content:center;pointer-events:none">
    <div style="pointer-events:auto;background:#111827;border:1px solid rgba(255,255,255,.15);border-radius:12px;padding:12px 16px;max-width:42rem;width:100%;box-shadow:0 25px 50px -12px rgba(0,0,0,.5);display:flex;flex-wrap:wrap;align-items:center;gap:12px;font:12px/1.6 system-ui,sans-serif">
      <p style="margin:0;flex:1;min-width:14rem;color:rgba(255,255,255,.8)"><span data-ct>${BANNER_TEXT.en.text}</span> <a data-cp href="/privacy" style="color:rgba(255,255,255,.85)">${BANNER_TEXT.en.privacy}</a></p>
      <div style="display:flex;gap:8px">
        <button type="button" data-consent="denied" style="padding:6px 12px;font-size:12px;color:rgba(255,255,255,.7);background:transparent;border:1px solid rgba(255,255,255,.15);border-radius:8px;cursor:pointer">${BANNER_TEXT.en.decline}</button>
        <button type="button" data-consent="granted" style="padding:6px 12px;font-size:12px;font-weight:500;color:#000;background:rgba(255,255,255,.9);border:0;border-radius:8px;cursor:pointer">${BANNER_TEXT.en.accept}</button>
      </div>
    </div>
  </div>
  <script>
    (function () {
      var el = document.getElementById('consent-banner');
      var ac = window.acConsent;
      // No bootstrap (it logs loudly at build time) or a decision already stored
      // (the bootstrap has migrated abyssal_consent_v2 by now): stay hidden.
      if (!el || !ac || ac.get() !== null) return;
      var T = ${JSON.stringify(BANNER_TEXT)};
      var lang = 'en';
      try {
        var cand = [localStorage.getItem('abyssal_lang'), navigator.language];
        for (var i = 0; i < cand.length; i++) {
          var l = String(cand[i] || '').slice(0, 2).toLowerCase();
          if (T[l]) { lang = l; break; }
        }
      } catch (e) {}
      var t = T[lang];
      el.setAttribute('aria-label', t.label);
      el.querySelector('[data-ct]').textContent = t.text;
      el.querySelector('[data-cp]').textContent = t.privacy;
      el.querySelector('[data-consent="denied"]').textContent = t.decline;
      el.querySelector('[data-consent="granted"]').textContent = t.accept;
      el.hidden = false;
      el.addEventListener('click', function (ev) {
        var btn = ev.target.closest && ev.target.closest('[data-consent]');
        if (!btn) return;
        var value = btn.getAttribute('data-consent');
        ac.set(value);
        // consent_decision only after a grant: a denied one must send nothing to Google.
        if (value === 'granted') window.gtag('event', 'consent_decision', { granted: 1, send_to: 'G-S5HR4WT0ZG' });
        el.hidden = true;
      });
    })();
  </script>`;
