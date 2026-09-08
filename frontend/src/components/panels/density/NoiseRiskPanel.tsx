// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, WarningBanner, SourceFooter } from "../shared/primitives";

// ── Noise risk panel ──────────────────────────────────────────────────────────

const NOISE_LEVEL_COLORS: Record<string, string> = {
  critical: "text-red-400",
  high:     "text-orange-400",
  moderate: "text-yellow-400",
  low:      "text-green-400",
  data_gap: "text-slate-400",
  minimal:  "text-white/65",
};

export function NoiseRiskPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const riskLevel = String(p.risk_level ?? "unknown");
  const dataGap = !!p.data_gap;
  return (
    <>
      <WarningBanner color="orange">
        {t("noiseRisk.derivedModelBanner")}
      </WarningBanner>

      <Badge label={`${t("noiseRisk.panelBadge")} (modeled)`} color="text-amber-300 border-amber-500/40" />
      <PanelHeader>
        <span className={NOISE_LEVEL_COLORS[riskLevel] ?? "text-white/65"}>
          {riskLevel.toUpperCase().replace("_", " ")}
          {dataGap && <span className="ml-2 text-xs font-normal text-slate-300">(data gap)</span>}
        </span>
      </PanelHeader>

      <Section title={t("noiseRisk.riskIndexSectionTitle")}>
        {p.risk_index    != null && <Row label={t("noiseRisk.impactRiskIndexLabel")} value={Number(p.risk_index).toFixed(3)} />}
        {p.pbd_norm      != null && <Row label={t("noiseRisk.pbdNormLabel")}         value={Number(p.pbd_norm).toFixed(3)} />}
        {p.spl_norm      != null && <Row label={t("noiseRisk.splNormLabel")}         value={Number(p.spl_norm).toFixed(3)} />}
        {p.cetacean_norm != null && <Row label={t("noiseRisk.noiseCetaceanNormLabel")} value={Number(p.cetacean_norm).toFixed(3)} />}
        {p.species_weight != null && <Row label={t("noiseRisk.speciesWeightLabel")} value={`×${Number(p.species_weight).toFixed(1)}`} />}
      </Section>

      <Section title={t("noiseRisk.cetaceansSectionTitle")}>
        {p.cetacean_count != null && <Row label={t("noiseRisk.cetaceanCountLabel")} value={String(p.cetacean_count)} />}
        <Row label={t("noiseRisk.threatenedSpeciesLabel")} value={String(p.max_species ?? t("noiseRisk.noneRecorded"))} />
      </Section>

      <Section title={t("noiseRisk.noiseSourceSectionTitle")}>
        <Row label={t("noiseRisk.dataSourceLabel")} value={String(p.noise_source ?? "—")} />
        {p.pbd_year != null && (
          <Row label={t("noiseRisk.pbdYearLabel")} value={String(p.pbd_year)} />
        )}
        {p.pbd_year_min != null && p.pbd_year_max != null && p.pbd_year_min !== p.pbd_year_max && (
          <Row
            label={t("noiseRisk.pbdYearSpanLabel")}
            value={`${p.pbd_year_min}–${p.pbd_year_max}`}
          />
        )}
      </Section>

      {dataGap && (
        <WarningBanner color="orange">
          {t("noiseRisk.dataGapWarning")}
        </WarningBanner>
      )}
      <SourceFooter>
        Sources: GFW shipping density · OBIS-SEAMAP cetacean records · derived layer (no single canonical citation)
      </SourceFooter>
    </>
  );
}
