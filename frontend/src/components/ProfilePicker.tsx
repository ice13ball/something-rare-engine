// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { StartupProfile } from "../utils/startupProfiles";
import { pickLocale } from "../utils/startupProfiles";

interface Props {
  profiles: StartupProfile[] | null; // null = fetch failed → legacy fallback
  lang: string;
  onPickProfile: (p: StartupProfile) => void;
  onPickMode: (mode: "ocean" | "land") => void;
  onExploreAll: () => void;
  /** Optional guided-tour entry point (Step-1 only). Omitted by callers that
   *  want a profile-only picker (e.g. the reopenable Views switcher). */
  onGuided?: () => void;
  /** Restore the previous session's layer selection ("Continue where I left
   *  off"). Omitted when there is no saved selection (true first visit). */
  onContinue?: () => void;
}

/** Two-tier startup profile chooser. Step 1 picks a section (ocean/land) or
 *  explores everything; Step 2 shows that section's curated profiles plus an
 *  "all layers" power option. Falls back to the legacy 3-button set when the
 *  backend profile fetch failed (profiles === null), so the overlay never
 *  blanks on an outage. Reuses the button/card classes from the pre-existing
 *  WelcomeOverlay button block for visual consistency. */
export function ProfilePicker({ profiles, lang, onPickProfile, onPickMode, onExploreAll, onGuided, onContinue }: Props) {
  const { t } = useTranslation("tutorial");
  const [section, setSection] = useState<null | "ocean" | "land">(null);

  // Prominent "Continue where I left off" — only when a prior selection exists.
  // Rendered first so returning users can resume in one click.
  const continueBtn = onContinue ? (
    <button
      onClick={onContinue}
      className="flex items-center gap-3 bg-white/10 hover:bg-white/15 border border-white/25 text-white text-sm px-5 py-3 rounded-lg transition-colors text-left"
    >
      <svg aria-hidden="true" className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
      </svg>
      <span className="font-semibold">{t("welcome.continue")}</span>
    </button>
  ) : null;

  // Fallback: no profiles available → legacy three buttons.
  if (profiles === null) {
    return (
      <div className="grid grid-cols-1 gap-2.5">
        {continueBtn}
        <button
          onClick={() => onPickMode("ocean")}
          aria-label={t("welcome.ocean.ariaLabel")}
          className="flex items-center gap-3 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-sm px-5 py-3 rounded-lg transition-colors text-left"
        >
          <span className="font-semibold">{t("welcome.ocean.title")}</span>
        </button>
        <button
          onClick={() => onPickMode("land")}
          aria-label={t("welcome.land.ariaLabel")}
          className="flex items-center gap-3 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-sm px-5 py-3 rounded-lg transition-colors text-left"
        >
          <span className="font-semibold">{t("welcome.land.title")}</span>
        </button>
        <button
          onClick={onExploreAll}
          className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 border border-white/15 text-white/70 hover:text-white/85 text-sm px-5 py-2.5 rounded-lg transition-colors"
        >
          {t("welcome.continue")}
        </button>
      </div>
    );
  }

  if (section === null) {
    return (
      <div className="grid grid-cols-1 gap-2.5">
        {continueBtn}
        {onGuided && (
          <button
            onClick={onGuided}
            aria-label={t("welcome.guided.ariaLabel")}
            className="flex items-center gap-3 bg-violet-500/10 hover:bg-violet-500/20 border border-violet-500/30 text-violet-300 text-sm px-5 py-3 rounded-lg transition-colors text-left"
          >
            <svg aria-hidden="true" className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
            </svg>
            <div>
              <span className="font-semibold">{t("welcome.guided.title")}</span>
              <span className="block text-xs text-violet-400/50 mt-0.5">{t("welcome.guided.summary")}</span>
            </div>
          </button>
        )}

        <button
          onClick={() => setSection("ocean")}
          aria-label={t("welcome.ocean.ariaLabel")}
          className="flex items-center gap-3 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-sm px-5 py-3 rounded-lg transition-colors text-left"
        >
          <svg aria-hidden="true" className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M20.893 13.393l-1.135-1.135a2.252 2.252 0 01-.421-.585l-1.08-2.16a.414.414 0 00-.663-.107.827.827 0 01-.812.21l-1.273-.363a.89.89 0 00-.738 1.595l.587.39c.59.395.674 1.23.172 1.732l-.2.2c-.212.212-.33.498-.33.796v.41c0 .409-.11.809-.32 1.158l-1.315 2.191a2.11 2.11 0 01-1.81 1.025 1.055 1.055 0 01-1.055-1.055v-1.172c0-.92-.56-1.747-1.414-2.089l-.655-.261a2.25 2.25 0 01-1.383-2.46l.007-.042a2.25 2.25 0 01.29-.787l.09-.15a2.25 2.25 0 012.37-1.048l1.178.236a1.125 1.125 0 001.302-.795l.208-.73a1.125 1.125 0 00-.578-1.315l-.665-.332-.091.091a2.25 2.25 0 01-1.591.659h-.18c-.249 0-.487.1-.662.274a.931.931 0 01-1.458-1.137l1.411-2.353a2.25 2.25 0 00.286-.76M11.25 2.25c-.621 0-1.125.504-1.125 1.125v.008c0 .621.504 1.125 1.125 1.125h.008c.621 0 1.125-.504 1.125-1.125v-.008c0-.621-.504-1.125-1.125-1.125h-.008z" />
            <circle cx="12" cy="12" r="10" strokeWidth="1.5" />
          </svg>
          <div>
            <span className="font-semibold">{t("welcome.ocean.title")}</span>
            <span className="block text-xs text-cyan-400/50 mt-0.5">{t("welcome.ocean.summary")}</span>
          </div>
        </button>

        <button
          onClick={() => setSection("land")}
          aria-label={t("welcome.land.ariaLabel")}
          className="flex items-center gap-3 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-sm px-5 py-3 rounded-lg transition-colors text-left"
        >
          <svg aria-hidden="true" className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
          </svg>
          <div>
            <span className="font-semibold">{t("welcome.land.title")}</span>
            <span className="block text-xs text-emerald-400/50 mt-0.5">{t("welcome.land.summary")}</span>
          </div>
        </button>

        <button
          onClick={onExploreAll}
          className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 border border-white/15 text-white/70 hover:text-white/85 text-sm px-5 py-2.5 rounded-lg transition-colors"
        >
          {t("welcome.exploreAll")}
        </button>
      </div>
    );
  }

  const subs = profiles.filter((p) => p.section === section);
  const sectionColor = section === "ocean"
    ? { bg: "bg-cyan-500/10 hover:bg-cyan-500/20", border: "border-cyan-500/30", text: "text-cyan-300", summary: "text-cyan-400/50" }
    : { bg: "bg-emerald-500/10 hover:bg-emerald-500/20", border: "border-emerald-500/30", text: "text-emerald-300", summary: "text-emerald-400/50" };

  return (
    <div className="grid grid-cols-1 gap-2.5">
      <button
        onClick={() => setSection(null)}
        className="flex items-center gap-1.5 self-start text-white/50 hover:text-white/80 text-xs px-1 py-1 transition-colors"
      >
        <svg aria-hidden="true" className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
        </svg>
        {t("welcome.back")}
      </button>

      {subs.map((p) => (
        <button
          key={p.id}
          onClick={() => onPickProfile(p)}
          style={p.accent ? { borderColor: p.accent } : undefined}
          className={`flex items-center gap-3 ${sectionColor.bg} border ${sectionColor.border} ${sectionColor.text} text-sm px-5 py-3 rounded-lg transition-colors text-left`}
        >
          <div>
            <span className="font-semibold">{pickLocale(p.label, lang)}</span>
            <span className={`block text-xs ${sectionColor.summary} mt-0.5`}>{pickLocale(p.description, lang)}</span>
          </div>
        </button>
      ))}

      <button
        onClick={() => onPickMode(section)}
        className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 border border-white/15 text-white/70 hover:text-white/85 text-sm px-5 py-2.5 rounded-lg transition-colors"
      >
        {section === "ocean" ? t("welcome.allOcean") : t("welcome.allLand")}
      </button>
    </div>
  );
}
