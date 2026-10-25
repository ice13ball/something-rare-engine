// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Every visitor is ASKED before analytics runs. Nobody is granted consent
// automatically, and nothing reaches Google before a grant.
//
// Until 2026-09-23 a visitor whose browser language was not an EU one got
// consent stored as 'granted' on first load without seeing any banner. Language
// is not location. Since 2026-10-25 there is ONE decision for the atlas and
// tools.something-rare.com: the cookie `ac_consent` (granted|denied), written by
// the ga4-bootstrap block of index.html (window.acConsent), which also loads
// gtag.js and runs `config` ONLY after a grant. The legacy localStorage key
// `abyssal_consent_v2` is migrated into the cookie; v1 is discarded.
//
// These tests EXECUTE the three pieces: the bootstrap as shipped in index.html,
// the server-rendered banner from seo/consent-banner.js, and the React banner.
// jsdom does not expose cookie attributes (Domain, Secure), so only the value is
// asserted here; the attributes live in the bootstrap and are covered by review.
import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const INDEX_HTML = fs.readFileSync(path.resolve(__dirname, '../../index.html'), 'utf8');
const BOOTSTRAP = INDEX_HTML.match(/<!-- ga4-bootstrap:start[\s\S]*?-->([\s\S]*?)<!-- ga4-bootstrap:end -->/)![1];
const LEGACY_KEY = 'abyssal_consent_v2';
const ID = 'G-S5HR4WT0ZG';
const BANNER_EN =
  'With your consent we use Google Analytics to count visits to and use of the Abyssal Claims Atlas and Tools. One choice applies to both. We never send the contents of your files or the links you paste.';

type GtagCall = unknown[];
const w = window as unknown as Record<string, unknown> & { dataLayer: IArguments[] };

const calls = (): GtagCall[] => (w.dataLayer as IArguments[]).map((a) => Array.from(a));
const updates = (value?: string) =>
  calls().filter((c) => c[0] === 'consent' && c[1] === 'update' && (!value || (c[2] as { analytics_storage: string }).analytics_storage === value));
const configs = () => calls().filter((c) => c[0] === 'config');
const gtagScripts = () => document.head.querySelectorAll('script[src*="gtag/js"]');
const cookie = () => document.cookie.match(/(?:^|; )ac_consent=([^;]*)/)?.[1] ?? null;

function setLanguage(lang: string) {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: [lang], configurable: true });
}

function clearCookies() {
  for (const host of [location.hostname, '']) {
    document.cookie = `ac_consent=; Path=/; Max-Age=0${host ? `; Domain=${host}` : ''}`;
  }
  document.cookie = 'ac_consent=; Path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
}

// Run the single inline <script> of the bootstrap, as a page load would.
function runBootstrap() {
  const inline = [...BOOTSTRAP.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  expect(inline).toHaveLength(1);
  w.dataLayer = [] as unknown as IArguments[];
  // eslint-disable-next-line no-new-func
  new Function(inline[0] + '\nwindow.gtag = gtag;')();
}

beforeEach(() => {
  localStorage.clear();
  clearCookies();
  document.body.innerHTML = '';
  document.head.querySelectorAll('script[src*="gtag/js"]').forEach((n) => n.remove());
  delete w.acConsent;
  delete w[`ga-disable-${ID}`];
  setLanguage('en-US');
});

describe('index.html bootstrap: no automatic grant, nothing before a grant', () => {
  it.each(['en-US', 'ja-JP', 'pt-BR', 'pl-PL'])('%s, first visit: consent stays denied, no cookie, no gtag.js, no config', (lang) => {
    setLanguage(lang);
    runBootstrap();
    const c = calls();
    expect(c[0][0]).toBe('consent');
    expect(c[0][1]).toBe('default');
    expect((c[0][2] as { analytics_storage: string }).analytics_storage).toBe('denied');
    expect(updates()).toHaveLength(0);
    expect(configs()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
    expect(cookie()).toBeNull();
  });

  it('a v1 "granted" (possibly automatic) is discarded, not honoured', () => {
    localStorage.setItem('abyssal_consent', 'granted');
    runBootstrap();
    expect(updates()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
    expect(cookie()).toBeNull();
    expect(localStorage.getItem('abyssal_consent')).toBeNull();
  });

  it('the visitor\'s own cookie "granted" is restored: analytics only, one config, one gtag.js', () => {
    document.cookie = 'ac_consent=granted; Path=/';
    runBootstrap();
    expect(updates()).toHaveLength(1);
    // Analytics only: no ads run on the site, so ad_* are never granted.
    expect(updates()[0][2]).toEqual({ analytics_storage: 'granted' });
    expect(configs()).toEqual([['config', ID]]);
    expect(gtagScripts()).toHaveLength(1);
  });

  it('a cookie "denied" loads nothing', () => {
    document.cookie = 'ac_consent=denied; Path=/';
    runBootstrap();
    expect(updates()).toHaveLength(0);
    expect(configs()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
  });

  it.each(['granted', 'denied'])('legacy abyssal_consent_v2=%s becomes the cookie and the key is removed', (v) => {
    localStorage.setItem(LEGACY_KEY, v);
    runBootstrap();
    expect(cookie()).toBe(v);
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull();
    expect(window.acConsent!.get()).toBe(v);
    expect(configs()).toHaveLength(v === 'granted' ? 1 : 0);
    expect(gtagScripts()).toHaveLength(v === 'granted' ? 1 : 0);
  });

  it('a legacy value does not overwrite a cookie that already exists', () => {
    document.cookie = 'ac_consent=denied; Path=/';
    localStorage.setItem(LEGACY_KEY, 'granted');
    runBootstrap();
    expect(cookie()).toBe('denied');
    expect(gtagScripts()).toHaveLength(0);
  });

  it('acConsent.set("granted"): cookie, consent update, exactly one config and one gtag.js even when repeated', () => {
    runBootstrap();
    window.acConsent!.set('granted');
    window.acConsent!.set('granted');
    expect(cookie()).toBe('granted');
    expect(updates('granted')).toHaveLength(2);
    expect(configs()).toHaveLength(1);
    expect(gtagScripts()).toHaveLength(1);
  });

  it('acConsent.set("denied"): cookie, consent update denied, no config, ga-disable set, _ga* cookies deleted', () => {
    document.cookie = '_ga=GA1.1.1.1; Path=/';
    document.cookie = `_ga_${ID.slice(2)}=GS2.1.x; Path=/`;
    runBootstrap();
    window.acConsent!.set('denied');
    expect(cookie()).toBe('denied');
    expect(updates('denied')).toHaveLength(1);
    expect(configs()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
    expect(w[`ga-disable-${ID}`]).toBe(true);
    expect(document.cookie).not.toMatch(/(?:^|; )_ga/);
  });
});

describe('server-rendered banner (seo/consent-banner.js)', () => {
  async function mountBanner() {
    const { CONSENT_BANNER_HTML } = await import('../../seo/consent-banner.js');
    runBootstrap();
    document.body.innerHTML = CONSENT_BANNER_HTML;
    const script = document.body.querySelector('script')!;
    // eslint-disable-next-line no-new-func
    new Function(script.textContent!)();
    return document.getElementById('consent-banner')!;
  }

  it('is shown to a visitor with no ac_consent cookie, whatever the language, with the contract text', async () => {
    const el = await mountBanner();
    expect(el.hidden).toBe(false);
    expect(el.textContent).toContain(BANNER_EN);
    // No ads run on the site (AdSense removed 2026-04-11), so the banner names analytics only.
    expect(el.textContent).not.toMatch(/advertis/i);
    expect(gtagScripts()).toHaveLength(0);
    expect(configs()).toHaveLength(0);
  });

  it.each(['granted', 'denied'])('stays hidden when the cookie is already %s', async (v) => {
    document.cookie = `ac_consent=${v}; Path=/`;
    const el = await mountBanner();
    expect(el.hidden).toBe(true);
  });

  it('stays hidden for a visitor with a legacy v2 answer (migrated, not asked again)', async () => {
    localStorage.setItem(LEGACY_KEY, 'denied');
    const el = await mountBanner();
    expect(el.hidden).toBe(true);
    expect(cookie()).toBe('denied');
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull();
  });

  it('ignores a v1 value and still asks', async () => {
    localStorage.setItem('abyssal_consent', 'granted');
    const el = await mountBanner();
    expect(el.hidden).toBe(false);
    expect(gtagScripts()).toHaveLength(0);
  });

  it('Accept: cookie granted, consent update granted, one config, one gtag.js, banner hidden', async () => {
    const el = await mountBanner();
    (el.querySelector('[data-consent="granted"]') as HTMLButtonElement).click();
    expect(cookie()).toBe('granted');
    expect(updates('granted')).toHaveLength(1);
    expect(configs()).toEqual([['config', ID]]);
    expect(gtagScripts()).toHaveLength(1);
    expect(el.hidden).toBe(true);
  });

  it('Decline: cookie denied, consent update denied, no config, no gtag.js, ga-disable set', async () => {
    const el = await mountBanner();
    (el.querySelector('[data-consent="denied"]') as HTMLButtonElement).click();
    expect(cookie()).toBe('denied');
    expect(updates('denied')).toHaveLength(1);
    expect(updates('granted')).toHaveLength(0);
    expect(configs()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
    expect(w[`ga-disable-${ID}`]).toBe(true);
    expect(el.hidden).toBe(true);
  });
});

describe('React CookieBanner on /', () => {
  async function mountReact() {
    runBootstrap();
    const { CookieBanner } = await import('../components/CookieBanner');
    return render(<MemoryRouter><CookieBanner /></MemoryRouter>);
  }

  it.each(['en-US', 'de-DE'])('%s, no cookie: the banner is shown with the contract text and nothing is granted', async (lang) => {
    setLanguage(lang);
    await mountReact();
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeTruthy();
    expect(document.body.textContent).toContain(BANNER_EN);
    expect(document.body.textContent).not.toMatch(/advertis/i);
    expect(cookie()).toBeNull();
    expect(updates()).toHaveLength(0);
    expect(configs()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
  });

  it.each(['granted', 'denied'])('cookie %s: no banner', async (v) => {
    document.cookie = `ac_consent=${v}; Path=/`;
    await mountReact();
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('legacy v2 answer: no banner, cookie written, key removed', async () => {
    localStorage.setItem(LEGACY_KEY, 'granted');
    await mountReact();
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(cookie()).toBe('granted');
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull();
  });

  it('Accept: cookie granted, consent update granted, exactly one config, one gtag.js', async () => {
    await mountReact();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    expect(cookie()).toBe('granted');
    expect(updates('granted')).toHaveLength(1);
    expect(configs()).toHaveLength(1);
    expect(gtagScripts()).toHaveLength(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('Decline: cookie denied, consent update denied, no config, ga-disable set', async () => {
    await mountReact();
    fireEvent.click(await screen.findByRole('button', { name: 'Decline' }));
    expect(cookie()).toBe('denied');
    expect(updates('denied')).toHaveLength(1);
    expect(updates('granted')).toHaveLength(0);
    expect(configs()).toHaveLength(0);
    expect(gtagScripts()).toHaveLength(0);
    expect(w[`ga-disable-${ID}`]).toBe(true);
  });
});

describe('no advertising anywhere: the site runs no ads', () => {
  it('React updateConsent(true) grants analytics only', async () => {
    runBootstrap();
    const { updateConsent } = await import('../utils/analytics');
    updateConsent(true);
    expect(updates()).toEqual([['consent', 'update', { analytics_storage: 'granted' }]]);
    expect(cookie()).toBe('granted');
  });

  it('the privacy policy, terms and about pages never mention advertising', async () => {
    const legal = await import('../content/legalContent');
    const text = JSON.stringify([legal.PRIVACY_POLICY, legal.TERMS_OF_USE, legal.ABOUT]);
    expect(text).not.toMatch(/advertis/i);
  });
});
