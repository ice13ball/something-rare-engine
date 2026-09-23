// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Row, Section, Badge, PanelHeader, HintText, SourceFooter } from "../shared/primitives";

/**
 * One MARHYS sample.
 *
 * ⛔ EVERYTHING HERE COMES FROM `properties`. No fetch on click: the layer's
 * GeoJSON already carries every named measurement and the sparse `params` tail
 * (8.7 MB, 0.67 MB gzipped, measured 2026-09-23), precisely so that opening a
 * sample never shows a spinner.
 */

/** The sample types MARHYS codes, and what each one actually is. */
const TYPE_META: Record<string, { color: string; key: string }> = {
  HF:  { color: "#fb923c", key: "hf" },
  EM:  { color: "#ef4444", key: "em" },
  SW:  { color: "#38bdf8", key: "sw" },
  STD: { color: "#94a3b8", key: "std" },
};

/**
 * The named measurements, in reading order, with the unit the SOURCE declares.
 *
 * ⭐ The unit is in the column name upstream (`fe_umol_kg`) and repeated here
 * rather than inferred. µmol/kg read as mmol/kg is a factor of 1000, and the
 * ingestion refuses to run if MARHYS ever republishes one of these under a
 * different unit — so what this table prints and what the database holds cannot
 * drift apart silently.
 */
const MEASUREMENTS: Array<{ field: string; label: string; unit: string }> = [
  { field: "temp_c",             label: "T",     unit: "°C" },
  { field: "ph",                 label: "pH",    unit: "" },
  { field: "depth_mbsl",         label: "Depth", unit: "m" },
  { field: "mg_mmol_kg",         label: "Mg",    unit: "mmol/kg" },
  { field: "cl_mmol_kg",         label: "Cl",    unit: "mmol/kg" },
  { field: "so4_mmol_kg",        label: "∑SO₄",  unit: "mmol/kg" },
  { field: "h2s_mmol_kg",        label: "∑H₂S",  unit: "mmol/kg" },
  { field: "ch4_umol_kg",        label: "CH₄",   unit: "µmol/kg" },
  { field: "h2_umol_kg",         label: "H₂",    unit: "µmol/kg" },
  { field: "co2_mmol_kg",        label: "∑CO₂",  unit: "mmol/kg" },
  { field: "si_mmol_kg",         label: "Si",    unit: "mmol/kg" },
  { field: "ca_mmol_kg",         label: "Ca",    unit: "mmol/kg" },
  { field: "k_mmol_kg",          label: "K",     unit: "mmol/kg" },
  { field: "na_mmol_kg",         label: "Na",    unit: "mmol/kg" },
  { field: "fe_umol_kg",         label: "Fe",    unit: "µmol/kg" },
  { field: "mn_umol_kg",         label: "Mn",    unit: "µmol/kg" },
  { field: "zn_umol_kg",         label: "Zn",    unit: "µmol/kg" },
  { field: "cu_umol_kg",         label: "Cu",    unit: "µmol/kg" },
  { field: "li_umol_kg",         label: "Li",    unit: "µmol/kg" },
  { field: "sr_umol_kg",         label: "Sr",    unit: "µmol/kg" },
  { field: "ba_umol_kg",         label: "Ba",    unit: "µmol/kg" },
  { field: "br_umol_kg",         label: "Br",    unit: "µmol/kg" },
  { field: "b_umol_kg",          label: "B",     unit: "µmol/kg" },
  { field: "rb_umol_kg",         label: "Rb",    unit: "µmol/kg" },
  { field: "cs_nmol_kg",         label: "Cs",    unit: "nmol/kg" },
  { field: "nh3_mmol_kg",        label: "∑NH₃",  unit: "mmol/kg" },
  { field: "alkalinity_mmol_kg", label: "Alk.",  unit: "mmol/kg" },
  { field: "salinity_g_kg",      label: "Sal.",  unit: "g/kg" },
];

/**
 * ⛔ `0` IS PRINTED, NOT HIDDEN. An end-member composition is defined by
 * extrapolation to zero magnesium — 1,252 of the 1,265 magnesium zeros in this
 * dataset sit on `EM` samples. A falsy check here would blank the single most
 * informative number on the sample.
 */
function fmt(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (n === 0) return "0";
  const abs = Math.abs(n);
  if (abs >= 1000) return n.toFixed(0);
  if (abs >= 1) return n.toFixed(2).replace(/\.?0+$/, "");
  return n.toPrecision(3);
}


/**
 * ⛔ Spelled out rather than built with `layers.marhys.types.${code}`. The
 * project type-checks every translation key against `en/panels.json`, and a
 * template literal over `string` defeats that check — the one guard standing
 * between a typo and a raw key rendered to a user.
 */
const TYPE_LABEL_KEY = {
  HF: "layers.marhys.types.HF",
  EM: "layers.marhys.types.EM",
  SW: "layers.marhys.types.SW",
  STD: "layers.marhys.types.STD",
} as const;

export function MarhysPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "common"]);
  const [showAll, setShowAll] = useState(false);

  const p = properties ?? {};
  const type = String(p.sample_type ?? "");
  const typeMeta = TYPE_META[type];

  const measured = useMemo(
    () => MEASUREMENTS.map(m => ({ ...m, text: fmt(p[m.field]) })).filter(m => m.text !== null),
    [p],
  );

  // The sparse tail: ~149 source columns, almost all empty on any one sample.
  const params = (p.params && typeof p.params === "object" ? p.params : {}) as Record<string, unknown>;
  const extra = useMemo(
    () => Object.entries(params)
      .map(([k, v]) => ({ k, text: fmt(v) }))
      .filter(e => e.text !== null)
      .sort((a, b) => a.k.localeCompare(b.k)),
    [params],
  );

  // ⚠️ Deduplicated. The source often repeats one name across the three scales —
  // `Menez Gwen` is its own site AND its own area — and joining them blind
  // rendered "Menez Gwen · Menez Gwen · Mid-Atlantic Ridge".
  const place = [...new Set(
    [p.vent_site, p.vent_area, p.region_large]
      .map(v => (v ? String(v).trim() : ""))
      .filter(Boolean),
  )];

  return (
    <div className="flex flex-col gap-3">
      <PanelHeader>
        {String(p.sample_id ?? t("layers.marhys.unnamedSample"))}
      </PanelHeader>

      {typeMeta && (
        <div className="flex items-center gap-2">
          <Badge label={type} color={typeMeta.color} />
          <HintText>
            {TYPE_LABEL_KEY[type as keyof typeof TYPE_LABEL_KEY]
              ? t(TYPE_LABEL_KEY[type as keyof typeof TYPE_LABEL_KEY])
              : type}
          </HintText>
        </div>
      )}

      <Section title={t("layers.marhys.sections.sample")}>
        {place.length > 0 && <Row label={t("layers.marhys.fields.place")} value={place.join(" · ")} />}
        {/* ⭐ Verbatim, always. The source's date column is free text in eight
            formats — "1977", "March 1979 - May 1979", ordinal dates. Michal's
            instruction 2026-09-22: show it exactly as the source writes it.
            Reformatting a range into a single day would invent precision. */}
        {p.date_raw ? <Row label={t("layers.marhys.fields.collected")} value={String(p.date_raw)} /> : null}
        {p.expedition ? <Row label={t("layers.marhys.fields.expedition")} value={String(p.expedition)} /> : null}
        {p.vessel ? <Row label={t("layers.marhys.fields.vessel")} value={String(p.vessel)} /> : null}
        {p.sampler_type ? <Row label={t("layers.marhys.fields.sampler")} value={String(p.sampler_type)} /> : null}
        {p.geologic_setting ? <Row label={t("layers.marhys.fields.setting")} value={String(p.geologic_setting)} /> : null}
        {p.rock_type_primary ? <Row label={t("layers.marhys.fields.rock")} value={String(p.rock_type_primary)} /> : null}
      </Section>

      {p.coord_status === "out_of_range" && (
        <HintText className="text-amber-300/80">
          {t("layers.marhys.outOfRange")}
        </HintText>
      )}

      {measured.length > 0 && (
        <Section title={t("layers.marhys.sections.composition")}>
          {measured.map(m => (
            <Row
              key={m.field}
              label={m.label}
              value={`${m.text}${m.unit ? ` ${m.unit}` : ""}`}
            />
          ))}
        </Section>
      )}

      {extra.length > 0 && (
        <Section title={t("layers.marhys.sections.more", { count: extra.length })}>
          {(showAll ? extra : extra.slice(0, 6)).map(e => (
            <Row key={e.k} label={e.k} value={e.text!} />
          ))}
          {extra.length > 6 && (
            <button
              onClick={() => setShowAll(v => !v)}
              className="mt-1 text-[11px] font-mono text-cyan-300/80 hover:text-cyan-200 transition-colors"
            >
              {showAll
                ? t("common:showLess", "Show less")
                : t("layers.marhys.showAllParams", { count: extra.length - 6 })}
            </button>
          )}
        </Section>
      )}

      {measured.length === 0 && extra.length === 0 && (
        <HintText>{t("layers.marhys.noChemistry")}</HintText>
      )}

      <SourceFooter>
        MARHYS Database 4.0 —{" "}
        <a
          href="https://doi.org/10.1594/PANGAEA.972999"
          target="_blank"
          rel="noopener noreferrer"
          className="text-cyan-400 hover:text-cyan-300"
        >
          Diehl &amp; Bach (2024), PANGAEA
        </a>{" "}
        (CC-BY-4.0).{" "}
        {/* ⭐ Not optional politeness — the dataset's own header states: "Please
            always cite the base publication (Diehl & Bach, 2020) along with this
            dataset." Dropping it would breach the terms we are using it under. */}
        <a
          href="https://doi.org/10.1029/2020GC009385"
          target="_blank"
          rel="noopener noreferrer"
          className="text-cyan-400 hover:text-cyan-300"
        >
          Diehl &amp; Bach (2020)
        </a>
      </SourceFooter>
    </div>
  );
}
