// Augments the i18next module so that t('namespace:key.path') is
// type-checked against the en/*.json shapes at compile time.
// English is the single source of truth for the schema.

import "i18next";
import en_common from "../../public/locales/en/common.json";
import en_panels from "../../public/locales/en/panels.json";
import en_legend from "../../public/locales/en/legend.json";
import en_enums from "../../public/locales/en/enums.json";
import en_tutorial from "../../public/locales/en/tutorial.json";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common";
    resources: {
      common: typeof en_common;
      panels: typeof en_panels;
      legend: typeof en_legend;
      enums: typeof en_enums;
      tutorial: typeof en_tutorial;
    };
  }
}
