// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";

/** A hex or a radius holds many samples, so it has a span, not a date.
 *  Rendering a span through the single-date component is how the two quietly
 *  drift apart. */
export function SampleYearRange(p: {
  yearMin?: number | null; yearMax?: number | null;
  count?: number | null; nUndated?: number | null;
}) {
  const { t } = useTranslation("legend");
  if (p.yearMin == null || p.yearMax == null) {
    return <span className="text-white/60">{t("sampleDate.noDateAtSource")}</span>;
  }
  const span = p.yearMin === p.yearMax ? `${p.yearMin}` : `${p.yearMin} – ${p.yearMax}`;
  return (
    <span>
      <span className="font-mono">{span}</span>
      {p.nUndated ? (
        <span className="text-white/60 ml-1">({p.nUndated} {t("sampleDate.undatedSuffix")})</span>
      ) : null}
    </span>
  );
}
