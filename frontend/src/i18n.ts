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

export default i18n;
