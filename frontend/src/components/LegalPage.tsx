// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { PRIVACY_POLICY, TERMS_OF_USE, ABOUT, type LegalDoc } from "../content/legalContent";
import type { LegalTab } from "./LegalModal";

function slugify(s: string): string {
  return s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const DOCS: Record<LegalTab, LegalDoc> = {
  about:   ABOUT,
  privacy: PRIVACY_POLICY,
  terms:   TERMS_OF_USE,
};

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

function DocRenderer({ doc }: { doc: LegalDoc }) {
  return (
    <div className="space-y-1">
      <p className="text-white/60 text-xs mb-4">Last updated: {doc.updated}</p>
      {doc.sections.map((section, i) => {
        const id = section.id ?? slugify(section.heading);
        return (
          <div key={i} className="mb-4">
            <h3 id={id} className="text-white/90 text-xs font-semibold uppercase tracking-wider mb-1.5 scroll-mt-12">
              {section.heading}
            </h3>
            {section.paragraphs.map((p, j) => {
              if (typeof p === "string") {
                return <p key={j} className="text-white/75 text-xs leading-relaxed mb-2">{p}</p>;
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
                      <span>{item}</span>
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
  const legalTab = pathname.slice(1) as LegalTab;
  const doc = DOCS[legalTab];

  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash, doc]);

  if (!doc) {
    navigate("/", { replace: true });
    return null;
  }

  const title = `${TITLES[legalTab]} | Abyssal Claims`;
  const description = DESCRIPTIONS[legalTab];
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
    <div className="min-h-screen bg-[#0d1117] flex flex-col items-center px-4 py-12">
      <div className="w-full max-w-2xl">
        <button
          onClick={() => navigate("/")}
          className="text-white/60 hover:text-white/85 text-xs mb-8 flex items-center gap-1 transition-colors"
        >
          ← Back to map
        </button>
        <h1 className="text-white text-sm font-semibold mb-6">{TITLES[legalTab]}</h1>
        <DocRenderer doc={doc} />
      </div>
    </div>
    </>
  );
}
