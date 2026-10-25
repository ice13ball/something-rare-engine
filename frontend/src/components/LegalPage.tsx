// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { useTranslation } from "react-i18next";
import { TERMS_OF_USE, ABOUT, TOOLS_URL, type LegalDoc } from "../content/legalContent";
import { PRIVACY_BY_LANG, type PolicyLang } from "../content/privacyTranslations";
import type { LegalTab } from "./LegalModal";

function slugify(s: string): string {
  return s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// Only the privacy policy is translated; About and Terms stay English.
const DOCS: Record<LegalTab, LegalDoc> = {
  about:   ABOUT,
  privacy: PRIVACY_BY_LANG.en,
  terms:   TERMS_OF_USE,
};

// Chrome strings of this page, kept here rather than in the locale JSON.
// "Atlas" / the tools name follow the ecosystem contract (AI-Wall
// ekosystem-wspolne-ustalenia.md §1).
export const CHROME: Record<PolicyLang, { atlas: string; tools: string; updated: string; privacyDescription: string }> = {
  en: { atlas: "Atlas", tools: "Tools",      updated: "Last updated",           privacyDescription: "Privacy policy for Abyssal Claims — how we collect, use, and protect your data." },
  pl: { atlas: "Atlas", tools: "Narzędzia",  updated: "Ostatnia aktualizacja",  privacyDescription: "Polityka prywatności Abyssal Claims — jak zbieramy, wykorzystujemy i chronimy Twoje dane." },
  de: { atlas: "Atlas", tools: "Werkzeuge",  updated: "Zuletzt aktualisiert",   privacyDescription: "Datenschutzerklärung von Abyssal Claims — wie wir Ihre Daten erheben, verwenden und schützen." },
  fr: { atlas: "Atlas", tools: "Outils",     updated: "Dernière mise à jour",   privacyDescription: "Politique de confidentialité d'Abyssal Claims — comment nous collectons, utilisons et protégeons vos données." },
};

export function pickLang(resolved: string | undefined): PolicyLang {
  const l = (resolved ?? "en").slice(0, 2);
  return l === "pl" || l === "de" || l === "fr" ? l : "en";
}

// Bare URLs in the privacy text become links (same tab). About and Terms keep
// their text exactly as written, so they are not linkified.
function Linkified({ text, links }: { text: string; links: boolean }) {
  if (!links) return <>{text}</>;
  return (
    <>
      {text.split(/(https:\/\/[^\s]*[^\s.,;:)])/g).map((part, i) =>
        /^https:\/\//.test(part)
          ? <a key={i} href={part} className="text-[#22d3ee] hover:underline">{part}</a>
          : part,
      )}
    </>
  );
}

const TITLES: Record<LegalTab, string> = {
  about:   "About",
  privacy: "Privacy Policy",
  terms:   "Terms of Use",
};

const DESCRIPTIONS: Record<LegalTab, string> = {
  about:   "Abyssal Claims is a deep-sea mining transparency platform visualising ISA concession data, environmental risks, and ocean monitoring on an interactive 3D map.",
  privacy: "Privacy policy for Abyssal Claims — how we collect, use, and protect your data.",
  terms:   "Terms of use for Abyssal Claims, the deep-sea mining transparency platform.",
};

function DocRenderer({ doc, updatedLabel, links }: { doc: LegalDoc; updatedLabel: string; links: boolean }) {
  return (
    <div className="space-y-1">
      <p className="text-white/60 text-xs mb-4">{updatedLabel}: {doc.updated}</p>
      {doc.sections.map((section, i) => {
        const id = section.id ?? slugify(section.heading);
        return (
          <div key={i} className="mb-4">
            <h3 id={id} className="text-white/90 text-xs font-semibold uppercase tracking-wider mb-1.5 scroll-mt-12">
              {section.heading}
            </h3>
            {section.paragraphs.map((p, j) => {
              if (typeof p === "string") {
                return <p key={j} className="text-white/75 text-xs leading-relaxed mb-2"><Linkified text={p} links={links} /></p>;
              }
              if ("code" in p) {
                return (
                  <pre key={j} className="text-white/75 text-[11px] leading-relaxed mb-2 p-3 bg-white/5 border border-white/10 rounded overflow-x-auto font-mono whitespace-pre">
                    {p.code}
                  </pre>
                );
              }
              return (
                <ul key={j} className="mb-2 space-y-1 ml-3">
                  {p.list.map((item, k) => (
                    <li key={k} className="text-white/75 text-xs leading-relaxed flex gap-2">
                      <span className="text-white/60 flex-shrink-0">—</span>
                      <span><Linkified text={item} links={links} /></span>
                    </li>
                  ))}
                </ul>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

export function LegalPage() {
  const { pathname, hash } = useLocation();
  const navigate = useNavigate();
  const { i18n } = useTranslation();
  const lang = pickLang(i18n.resolvedLanguage);
  const chrome = CHROME[lang];
  const legalTab = pathname.slice(1) as LegalTab;
  const isPrivacy = legalTab === "privacy";
  const doc = isPrivacy ? PRIVACY_BY_LANG[lang] : DOCS[legalTab];

  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash, doc]);

  if (!doc) {
    navigate("/", { replace: true });
    return null;
  }

  const pageName = isPrivacy ? doc.title : TITLES[legalTab];
  const title = `${pageName} — Abyssal Claims`;
  const description = isPrivacy ? chrome.privacyDescription : DESCRIPTIONS[legalTab];
  const canonical = `https://something-rare.com/${legalTab}`;

  return (
    <>
    <Helmet>
      <title>{title}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={canonical} />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      <meta property="og:url" content={canonical} />
      <meta property="og:type" content="website" />
      <meta property="og:image" content="https://something-rare.com/og.jpg" />
      <meta name="twitter:card" content="summary" />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
    </Helmet>
    <div className="min-h-screen bg-[#0a0e14] flex flex-col items-center px-4 py-12">
      <div className="w-full max-w-2xl">
        <div className="flex items-center justify-between mb-8 text-xs">
          <button
            onClick={() => navigate("/")}
            className="text-white/60 hover:text-white/85 flex items-center gap-1 transition-colors"
          >
            ← {chrome.atlas}
          </button>
          {/* Same tab, current language in the URL (ecosystem contract §2). */}
          <a href={`${TOOLS_URL}/?lang=${lang}`} className="text-[#22d3ee] hover:underline">
            {chrome.tools} →
          </a>
        </div>
        <h1 className="text-white text-sm font-semibold mb-6">{pageName}</h1>
        <DocRenderer doc={doc} updatedLabel={isPrivacy ? chrome.updated : CHROME.en.updated} links={isPrivacy} />
      </div>
    </div>
    </>
  );
}
