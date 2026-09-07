// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { hexFilteredCount, type HexDecadeProps } from "../../map3d/hexDecadeFilter";

/**
 * The map colours a hex by the FILTERED count, but the panel used to always
 * report the unfiltered total — a hex shaded for 3 points next to a panel
 * saying "42 casts". Show both numbers when a decade filter is active so
 * nothing is hidden; fall back to the old single-number rendering when it
 * is not (selected.size === 0 means "no filter", not "nothing selected").
 */
export function HexSampleSummary(p: {
  properties: Record<string, unknown>;
  selected: Set<string>;
  nounOne: string;
  nounMany: string;
  numberClass: string;
}) {
  const { t } = useTranslation("legend");
  const total = Number(p.properties?.count ?? 0);
  const shown = hexFilteredCount(p.properties as HexDecadeProps, p.selected);

  if (p.selected.size === 0) {
    const noun = total === 1 ? p.nounOne : p.nounMany;
    return (
      <div className="text-white/90">
        <span className={"text-2xl font-semibold " + p.numberClass}>{total.toLocaleString()}</span>{" "}
        <span className="text-white/70">{noun} in this grid cell</span>
      </div>
    );
  }

  const noun = shown === 1 ? p.nounOne : p.nounMany;
  const labels = [
    ...Array.from(p.selected)
      .filter((d) => d !== "undated")
      .map(Number)
      .filter((d) => Number.isFinite(d))
      .sort((a, b) => a - b)
      .map((d) => `${d}s`),
    ...(p.selected.has("undated") ? [t("sampleDate.undatedSuffix")] : []),
  ];

  return (
    <div className="text-white/90">
      <div>
        <span className={"text-2xl font-semibold " + p.numberClass}>{shown.toLocaleString()}</span>{" "}
        <span className="text-white/70">{t("sampleDate.ofTotal", { total: total.toLocaleString() })}</span>{" "}
        <span className="text-white/70">{noun} in this grid cell</span>
      </div>
      <div className="text-white/60 text-xs">
        {t("sampleDate.decadesShown")}: {labels.join(", ")}
      </div>
    </div>
  );
}
