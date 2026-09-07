// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import React from "react";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LOCALES, type SupportedLocale } from "../i18n";

const LOCALE_CODE_LABEL: Record<SupportedLocale, string> = {
  en: "EN",
  pl: "PL",
  fr: "FR",
  de: "DE",
};

const LOCALE_NATIVE_NAME: Record<SupportedLocale, string> = {
  en: "English",
  pl: "Polski",
  fr: "Français",
  de: "Deutsch",
};

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const current = (i18n.resolvedLanguage ?? "en") as SupportedLocale;

  const onChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value as SupportedLocale;
    i18n.changeLanguage(next);
  };

  return (
    <div className="relative inline-flex items-center gap-1.5 bg-black/40 rounded border border-white/15 px-2 py-0.5 cursor-pointer hover:border-white/40 focus-within:border-white/60">
      {/* Visible trigger — globe (signals "language") + always-on current code.
          These are real elements so the active language is never hidden by
          platform-specific <select> rendering. */}
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
        className="w-3.5 h-3.5 text-white/80 shrink-0"
      >
        <circle cx="12" cy="12" r="9" />
        <path strokeLinecap="round" d="M3 12h18M12 3c2.6 2.7 2.6 15.3 0 18M12 3c-2.6 2.7-2.6 15.3 0 18" />
      </svg>
      <span className="text-sm font-semibold leading-none text-white/95 tracking-wide">{LOCALE_CODE_LABEL[current]}</span>
      {/* Transparent select on top: captures clicks, shows the native dropdown,
          and carries the accessible label. opacity-0 hides its own value text. */}
      <select
        aria-label={`Language: ${LOCALE_NATIVE_NAME[current]}`}
        title={LOCALE_NATIVE_NAME[current]}
        value={current}
        onChange={onChange}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
      >
        {SUPPORTED_LOCALES.map((code) => (
          <option key={code} value={code}>
            {LOCALE_NATIVE_NAME[code]}
          </option>
        ))}
      </select>
    </div>
  );
}
