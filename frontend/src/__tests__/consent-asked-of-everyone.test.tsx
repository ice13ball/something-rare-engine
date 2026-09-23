// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Every visitor is ASKED before analytics cookies are used. Nobody is granted
// consent automatically.
//
// Until 2026-09-23 a visitor whose browser language was not an EU one got
// consent stored as 'granted' on first load without seeing any banner — in the
// index.html bootstrap and again in CookieBanner. Language is not location: an
// English-language browser in Warsaw was treated as outside the GDPR. On top of
// that, server-rendered pages (where search traffic lands) had no banner at all.
//
// These tests EXECUTE the three pieces: the bootstrap as shipped in index.html,
// the server-rendered banner from seo/render-page.js, and the React banner.
import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const INDEX_HTML = fs.readFileSync(path.resolve(__dirname, '../../index.html'), 'utf8');
const BOOTSTRAP = INDEX_HTML.match(/<!-- ga4-bootstrap:start[\s\S]*?-->([\s\S]*?)<!-- ga4-bootstrap:end -->/)![1];
const KEY = 'abyssal_consent_v2';

type GtagCall = unknown[];
let calls: GtagCall[];

function setLanguage(lang: string) {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: [lang], configurable: true });
}

// Run the inline <script> blocks of the bootstrap (not the async gtag.js loader).
function runBootstrap() {
  const inline = [...BOOTSTRAP.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  expect(inline.length).toBeGreaterThanOrEqual(2);
  const w = window as unknown as { dataLayer: unknown[] };
  w.dataLayer = [];
  // eslint-disable-next-line no-new-func
  new Function(inline[0] + '\nwindow.gtag = gtag;')();
  calls = (w.dataLayer as IArguments[]).map((a) => Array.from(a));
}

beforeEach(() => {
  localStorage.clear();
  document.body.innerHTML = '';
  calls = [];
});

describe('index.html bootstrap: no automatic grant', () => {
  it.each(['en-US', 'ja-JP', 'pt-BR', 'pl-PL'])('%s, first visit: consent stays denied and nothing is stored', (lang) => {
    setLanguage(lang);
    runBootstrap();
    expect(calls[0][0]).toBe('consent');
    expect(calls[0][1]).toBe('default');
    expect(calls.filter((c) => c[0] === 'consent' && c[1] === 'update')).toHaveLength(0);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('a v1 "granted" (possibly automatic) is discarded, not honoured', () => {
    setLanguage('en-US');
    localStorage.setItem('abyssal_consent', 'granted');
    runBootstrap();
    expect(calls.filter((c) => c[1] === 'update')).toHaveLength(0);
    expect(localStorage.getItem('abyssal_consent')).toBeNull();
  });

  it('the visitor\'s own v2 "granted" is restored', () => {
    localStorage.setItem(KEY, 'granted');
    runBootstrap();
    const upd = calls.filter((c) => c[0] === 'consent' && c[1] === 'update');
    expect(upd).toHaveLength(1);
    expect((upd[0][2] as Record<string, string>).analytics_storage).toBe('granted');
  });
});

describe('server-rendered banner (seo/render-page.js)', () => {
  async function mountBanner(gtag = vi.fn()) {
    const { CONSENT_BANNER_HTML } = await import('../../seo/consent-banner.js');
    (window as unknown as { gtag: unknown }).gtag = gtag;
    document.body.innerHTML = CONSENT_BANNER_HTML;
    const script = document.body.querySelector('script')!;
    // eslint-disable-next-line no-new-func
    new Function(script.textContent!)();
    return { el: document.getElementById('consent-banner')!, gtag };
  }

  it('is shown to a visitor with no decision, whatever the language', async () => {
    setLanguage('en-US');
    const { el } = await mountBanner();
    expect(el.hidden).toBe(false);
  });

  it('stays hidden once the visitor has decided', async () => {
    localStorage.setItem(KEY, 'denied');
    const { el } = await mountBanner();
    expect(el.hidden).toBe(true);
  });

  it('Accept stores the choice, grants consent and re-runs config', async () => {
    const { el, gtag } = await mountBanner();
    (el.querySelector('[data-consent="granted"]') as HTMLButtonElement).click();
    expect(localStorage.getItem(KEY)).toBe('granted');
    expect(gtag).toHaveBeenCalledWith('consent', 'update', expect.objectContaining({ analytics_storage: 'granted' }));
    expect(gtag).toHaveBeenCalledWith('config', 'G-S5HR4WT0ZG', { send_page_view: true });
    expect(el.hidden).toBe(true);
  });

  it('Decline stores the refusal and never runs config', async () => {
    const { el, gtag } = await mountBanner();
    (el.querySelector('[data-consent="denied"]') as HTMLButtonElement).click();
    expect(localStorage.getItem(KEY)).toBe('denied');
    expect(gtag).toHaveBeenCalledWith('consent', 'update', expect.objectContaining({ analytics_storage: 'denied' }));
    expect(gtag).not.toHaveBeenCalledWith('config', expect.anything(), expect.anything());
  });
});

describe('React CookieBanner on /', () => {
  it.each(['en-US', 'de-DE'])('%s, no decision: the banner is shown and nothing is granted', async (lang) => {
    setLanguage(lang);
    const gtag = vi.fn();
    (window as unknown as { gtag: unknown }).gtag = gtag;
    const { CookieBanner } = await import('../components/CookieBanner');
    render(<MemoryRouter><CookieBanner /></MemoryRouter>);
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeTruthy();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(gtag).not.toHaveBeenCalled();
  });
});
