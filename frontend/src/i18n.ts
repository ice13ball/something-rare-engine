// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import HttpBackend from "i18next-http-backend";

// Eagerly bundle English so first paint always works without HTTP.
import en_common from "../public/locales/en/common.json";
import en_panels from "../public/locales/en/panels.json";
import en_enums from "../public/locales/en/enums.json";
import en_tutorial from "../public/locales/en/tutorial.json";
// Note: en_legend is intentionally NOT bundled here. It is large and
// only needed when LegendPanel mounts. The HTTP backend will fetch it
// on demand for all locales (including en).

export const SUPPORTED_LOCALES = ["en", "pl", "fr", "de"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

// ── ?lang= on arrival (contract §2: tools.something-rare.com links carry it) ──
// Runs at import time, BEFORE init (so the detector sees the stored value) and
// before App's module graph loads (main.tsx imports "./i18n" first), so nothing
// has read location.search yet. ⛔ Only `lang` is removed from the URL: `?s=`
// (share state) and every other param plus the hash must survive untouched.
// An unknown value is ignored but still stripped.
try {
  const { search, pathname, hash } = window.location;
  // Hand-filtered, not URLSearchParams.toString(): that re-encodes every other
  // param (`,` → %2C, `~` → %7E…), and `?s=` must stay byte-for-byte.
  const pairs = search.replace(/^\?/, "").split("&").filter(Boolean);
  const langPair = pairs.find((p) => p === "lang" || p.startsWith("lang="));
  if (langPair !== undefined) {
    const requested = decodeURIComponent(langPair.slice(5)).trim();
    if ((SUPPORTED_LOCALES as readonly string[]).includes(requested)) {
      try { localStorage.setItem("abyssal_lang", requested); } catch {}
    }
    const rest = pairs.filter((p) => !(p === "lang" || p.startsWith("lang=")));
    window.history.replaceState(window.history.state, "", pathname + (rest.length ? "?" + rest.join("&") : "") + hash);
  }
} catch {}

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: "en",
    supportedLngs: SUPPORTED_LOCALES as unknown as string[],
    ns: ["common", "panels", "legend", "enums", "tutorial"],
    defaultNS: "common",
    resources: {
      en: {
        common: en_common,
        panels: en_panels,
        enums: en_enums,
        tutorial: en_tutorial,
      },
    },
    partialBundledLanguages: true, // legend ns + non-en locales come from HTTP
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "abyssal_lang",
      caches: ["localStorage"],
    },
    backend: {
      loadPath: "/locales/{{lng}}/{{ns}}.json",
    },
    interpolation: {
      escapeValue: false, // React already escapes
    },
    react: {
      useSuspense: false, // avoid showing a fallback when switching locales
    },
  });

// <html lang> follows the UI language (contract §2), on init and on every switch.
const syncHtmlLang = (lng?: string) => { if (lng) document.documentElement.lang = lng; };
i18n.on("initialized", () => syncHtmlLang(i18n.resolvedLanguage || i18n.language));
i18n.on("languageChanged", () => syncHtmlLang(i18n.resolvedLanguage || i18n.language));
syncHtmlLang(i18n.resolvedLanguage || i18n.language);

export default i18n;
