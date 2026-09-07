// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef, useState } from "react";
import { PRIVACY_POLICY, TERMS_OF_USE, ABOUT, type LegalDoc } from "../content/legalContent";

export type LegalTab = "privacy" | "terms" | "about";

interface LegalModalProps {
  initialTab?: LegalTab;
  onClose: () => void;
}

const TABS: { id: LegalTab; label: string }[] = [
  { id: "about", label: "About" },
];

const DOCS: Record<LegalTab, LegalDoc> = {
  about:   ABOUT,
  privacy: PRIVACY_POLICY,
  terms:   TERMS_OF_USE,
};

function DocRenderer({ doc }: { doc: LegalDoc }) {
  return (
    <div className="space-y-1">
      <p className="text-white/60 text-xs mb-4">Last updated: {doc.updated}</p>
      {doc.sections.map((section, i) => (
        <div key={i} className="mb-4">
          <h3 className="text-white/90 text-xs font-semibold uppercase tracking-wider mb-1.5">
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
      ))}
    </div>
  );
}

export function LegalModal({ initialTab = "about", onClose }: LegalModalProps) {
  const [tab, setTab] = useState<LegalTab>(initialTab);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [tab]);

  return (
    <div
      className="fixed inset-0 z-overlay flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <button className="absolute inset-0 bg-surface-overlay cursor-default" aria-label="Close modal" onClick={onClose} />
      <div className="relative bg-[#0d1117] border border-white/10 rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/10 flex-shrink-0">
          <div className="flex gap-1">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                  tab === t.id ? "bg-white/10 text-white" : "text-white/65 hover:text-white/85"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button
            onClick={onClose}
            className="text-white/60 hover:text-white text-xl leading-none ml-4"
            aria-label="Close"
          >×</button>
        </div>

        {/* Content */}
        <div ref={scrollRef} className="overflow-y-auto p-5 custom-scrollbar flex-1">
          <DocRenderer doc={DOCS[tab]} />
        </div>
      </div>
    </div>
  );
}
