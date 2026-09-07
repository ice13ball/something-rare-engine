// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { T } from "../shared/tokens";
import { Row, Section, SourceAttribution } from "../shared/primitives";

export function BiodiversityGridPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const flyTo = useMapStore((s) => s.flyTo);
  const topSpecies = (p.top_species as { name: string; iucn?: string; records?: number }[]) ?? [];
  const hasCoords = typeof p._lon === "number" && typeof p._lat === "number";
  return (
    <>
      <h2 className={T.header}>{t("biodiversityGrid.panelTitle")}</h2>
      <Section title={t("biodiversityGrid.summarySectionTitle")}>
        <Row label={t("biodiversityGrid.observationsLabel")} value={Number(p.total_count).toLocaleString()} />
        {p.species_count != null && <Row label={t("biodiversityGrid.speciesLabel")} value={String(p.species_count)} />}
        {Number(p.endangered_count) > 0 && <Row label={t("biodiversityGrid.threatenedLabel")} value={String(p.endangered_count)} />}
        {Number(p.cr_en_count) > 0 && <Row label={t("biodiversityGrid.crEnLabel")} value={String(p.cr_en_count)} />}
      </Section>
      {topSpecies.length > 0 && (
        <Section title={t("biodiversityGrid.topSpeciesSectionTitle")}>
          {topSpecies.map((sp, i) => (
            <div key={i} className="flex items-center justify-between text-[14px] py-0.5">
              <span className="text-white/80 italic truncate mr-2">{sp.name}</span>
              <div className="flex items-center gap-1.5">
                {sp.iucn && <span className="text-white/65 font-mono">{sp.iucn}</span>}
                {sp.records != null && <span className="text-white/55">{sp.records}</span>}
              </div>
            </div>
          ))}
        </Section>
      )}
      {hasCoords && flyTo && (
        <button
          onClick={() => flyTo(p._lon as number, p._lat as number)}
          className="w-full mt-2 py-1.5 text-[14px] font-medium rounded-lg
                     bg-emerald-500/20 text-emerald-300 border border-emerald-500/30
                     hover:bg-emerald-500/30 transition-colors"
        >
          {t("biodiversityGrid.zoomToSpeciesButton")}
        </button>
      )}
      <SourceAttribution link={sourceLinkFor("obis-occurrence", p)} />
    </>
  );
}

