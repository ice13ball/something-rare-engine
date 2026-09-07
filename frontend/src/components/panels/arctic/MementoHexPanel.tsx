// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Row } from "../shared/primitives";
import { SampleYearRange } from "../shared/SampleYearRange";
import { HexSampleSummary } from "../shared/HexSampleSummary";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";

export function MementoHexPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("legend");
  const selected = useMapStore((s) => s.mementoDecadeFilters);
  const count = Number(properties?.count ?? 0);
  const yearMin = properties?.year_min as number | null | undefined;
  const yearMax = properties?.year_max as number | null | undefined;
  const nUndated = properties?.n_undated as number | null | undefined;
  return (
    <div className="space-y-2 text-sm">
      <HexSampleSummary
        properties={properties}
        selected={selected}
        nounOne="cast"
        nounMany="casts"
        numberClass="text-teal-300"
      />
      <Row
        label={t("sampleDate.range")}
        value={<SampleYearRange yearMin={yearMin} yearMax={yearMax} count={count} nUndated={nUndated} />}
      />
      <p className="text-white/60 text-xs">
        Density view — switch this layer to <span className="text-white/80">Dots</span> and click an
        individual location to open its CH₄/N₂O depth profile.
      </p>
    </div>
  );
}
