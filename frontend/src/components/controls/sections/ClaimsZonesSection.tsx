// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { FeatureCollection } from "geojson";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { RISK_FILTERS } from "../filterDefs";
import {
  LayerRow, SubGroup, FilterResetLink,
} from "../rows";

interface Props {
  claimsData: FeatureCollection | null;
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function ClaimsZonesSection({ claimsData, expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    hiddenContractors, toggleContractor,
    claimRiskFilters, toggleClaimRisk,
    offshoreActivityFilters, toggleOffshoreActivityFilter,
    offshoreActivityCountryFilters, toggleOffshoreActivityCountryFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  // Fetch the list of countries (sovereigns) with offshore-activity coverage
  // — populated lazily only when the user opens the filter chevron.
  const [offshoreCountries, setOffshoreCountries] = useState<{ sovereign: string; count: number }[] | null>(null);
  useEffect(() => {
    if (expandedFilter !== "offshore-activities" || offshoreCountries !== null) return;
    const API = import.meta.env.VITE_API_BASE_URL ?? "";
    fetch(`${API}/api/v2/spatial/offshore-activities/countries`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: { sovereign: string; count: number }[]) => setOffshoreCountries(rows ?? []))
      .catch(() => setOffshoreCountries([]));
  }, [expandedFilter, offshoreCountries]);

  const contractorKeys = (() => {
    if (!claimsData) return [] as string[];
    const seen = new Set<string>();
    for (const f of claimsData.features) {
      const key = `${f.properties?.contractor_name}::${f.properties?.resource_type}`;
      seen.add(key);
    }
    return [...seen].sort();
  })();

  return (
    <SubGroup label={t("controls.subgroups.claimsZones")} storageKey="sea_claims" defaultExpanded>
      <LayerRow
        id="contracts" label={t("layers.contracts.toggle")} color="#00f2ff"
        active={activeLayers.has("contracts")}
        onToggle={() => toggle("contracts")}
        onLocate={() => flyToLayer?.("contracts")}
        locateDataAttr="locate-btn"
        filterActive={claimRiskFilters.size > 0 || hiddenContractors.size > 0}
        expanded={expandedFilter === "contracts"}
        onExpandToggle={() => toggleExpand("contracts")}
        filterContent={
          <>
            <div className="flex items-center justify-between pb-0.5">
              <p className="text-white/60 text-[10px] font-mono uppercase tracking-[0.12em]">{t("filters.contracts.riskFiltersHeading")}</p>
              <FilterResetLink
                show={claimRiskFilters.size > 0}
                onReset={() => claimRiskFilters.forEach(toggleClaimRisk)}
              />
            </div>
            {RISK_FILTERS.map(r => (
              <label key={r.key} className="flex items-center gap-2 py-0.5 cursor-pointer">
                <input type="checkbox" checked={claimRiskFilters.has(r.key)} onChange={() => toggleClaimRisk(r.key)} className="accent-red-400 w-3 h-3" />
                <span className="text-white/75 text-[13px]">{t(`filters.contracts.risk.${r.key}` as any)}</span>
              </label>
            ))}
            {contractorKeys.length > 0 && (
              <>
                <div className="flex items-center gap-1.5 pt-1.5 pb-0.5">
                  <p className="text-white/60 text-[10px] font-mono uppercase tracking-[0.12em] flex-1">
                    {t("filters.contracts.contractorsHeading", { visible: contractorKeys.length - hiddenContractors.size, total: contractorKeys.length })}
                  </p>
                  <button onClick={() => { for (const k of contractorKeys) { if (hiddenContractors.has(k)) toggleContractor(k); } }} aria-label={t("common:actions.all")} className="text-xs text-white/70 hover:text-white/90 transition-colors">{t("common:actions.all")}</button>
                  <span className="text-white/45 text-xs">·</span>
                  <button onClick={() => { for (const k of contractorKeys) { if (!hiddenContractors.has(k)) toggleContractor(k); } }} aria-label={t("common:actions.none")} className="text-xs text-white/70 hover:text-white/90 transition-colors">{t("common:actions.none")}</button>
                </div>
                {contractorKeys.map(key => {
                  const [name, resource] = key.split("::");
                  const visible = !hiddenContractors.has(key);
                  return (
                    <label key={key} className="flex items-center gap-2 py-0.5 cursor-pointer">
                      <input type="checkbox" checked={visible} onChange={() => toggleContractor(key)} className="accent-white/70 w-3 h-3" />
                      <span className={`text-[13px] truncate ${visible ? "text-white/75" : "text-white/50"}`}>
                        {name}
                        {resource && <span className="text-white/70 ml-1">· {resource.replace("Polymetallic ", "")}</span>}
                      </span>
                    </label>
                  );
                })}
              </>
            )}
          </>
        }
      />
      {([
        { id: "reserved-areas",        label: t("layers.reservedAreas.toggle"),       color: "#00ff9f" },
        { id: "relinquished-areas",    label: t("layers.relinquishedAreas.toggle"),   color: "#ff4466" },
        { id: "apeis",                 label: t("layers.apeis.toggle"), color: "#bf5fff" },
        { id: "protected-marine-sites", label: t("layers.protectedMarineSites.toggle"), color: "#00e676" },
        { id: "eez",                   label: t("layers.eez.toggle"),       color: "#ffd700" },
      ] as { id: LayerId; label: string; color: string }[]).map(cfg => (
        <LayerRow
          key={cfg.id}
          id={cfg.id} label={cfg.label} color={cfg.color}
          active={activeLayers.has(cfg.id)}
          onToggle={() => toggle(cfg.id)}
          onLocate={() => flyToLayer?.(cfg.id)}
        />
      ))}
      <LayerRow
        id="offshore-activities"
        label={t("layers.offshoreActivities.toggle")}
        color="#dc2626"
        active={activeLayers.has("offshore-activities")}
        onToggle={() => toggle("offshore-activities")}
        onLocate={() => flyToLayer?.("offshore-activities")}
        filterActive={offshoreActivityFilters.size > 0 || offshoreActivityCountryFilters.size > 0}
        expanded={expandedFilter === "offshore-activities"}
        onExpandToggle={() => toggleExpand("offshore-activities")}
        filterContent={
          <>
            <div className="text-white/65 text-[13px] mb-0.5 flex items-center justify-between">
              <span>{t("filters.offshoreActivities.activityTypeHeading")}</span>
              <FilterResetLink
                show={offshoreActivityFilters.size > 0}
                onReset={() => offshoreActivityFilters.forEach(toggleOffshoreActivityFilter)}
              />
            </div>
            {[
              { key: "oil_gas",        label: t("filters.offshoreActivities.activityTypes.oil_gas"),      color: "#dc2626" },
              { key: "offshore_wind",  label: t("filters.offshoreActivities.activityTypes.offshore_wind"),  color: "#38bdf8" },
              { key: "seabed_mining",  label: t("filters.offshoreActivities.activityTypes.seabed_mining"),  color: "#d946ef" },
              { key: "ccs_storage",    label: t("filters.offshoreActivities.activityTypes.ccs_storage"),    color: "#10b981" },
            ].map(({ key, label, color }) => {
              const disabled = offshoreActivityFilters.size > 0 && !offshoreActivityFilters.has(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleOffshoreActivityFilter(key)}
                  aria-label={`Toggle ${label}`}
                  aria-pressed={!disabled}
                  className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${disabled ? "opacity-60" : "opacity-100"}`}
                >
                  <span
                    className="w-2 h-2 rounded-full flex-shrink-0 border"
                    style={{ backgroundColor: disabled ? "transparent" : color, borderColor: color }}
                  />
                  <span className={disabled ? "text-white/70" : "text-white"}>{label}</span>
                </button>
              );
            })}
            <div className="text-white/65 text-[13px] mt-1.5 mb-0.5 flex items-center justify-between">
              <span>{t("filters.offshoreActivities.countryHeading")}</span>
              {offshoreActivityCountryFilters.size > 0 && (
                <button
                  onClick={() => offshoreActivityCountryFilters.forEach(toggleOffshoreActivityCountryFilter)}
                  className="text-white/65 hover:text-white text-[11px]"
                >
                  {t("filters.offshoreActivities.clearCount", { count: offshoreActivityCountryFilters.size })}
                </button>
              )}
            </div>
            {offshoreCountries === null ? (
              <div className="text-white/60 text-[11px]">{t("common:actions.loading")}</div>
            ) : (
              <div className="max-h-44 overflow-y-auto pr-1 -mr-1">
                {offshoreCountries.map(({ sovereign, count }) => {
                  const active = offshoreActivityCountryFilters.has(sovereign);
                  const dimmed = offshoreActivityCountryFilters.size > 0 && !active;
                  return (
                    <button
                      key={sovereign}
                      onClick={() => toggleOffshoreActivityCountryFilter(sovereign)}
                      aria-pressed={active}
                      className={`flex items-center justify-between w-full text-left text-[13px] py-0.5 transition-opacity ${dimmed ? "opacity-60" : "opacity-100"}`}
                    >
                      <span className={dimmed ? "text-white/70" : "text-white"}>{sovereign}</span>
                      <span className="text-white/60 text-[11px] tabular-nums">{count.toLocaleString()}</span>
                    </button>
                  );
                })}
              </div>
            )}
            <div className="text-white/60 text-[11px] mt-1 leading-snug">
              {t("filters.offshoreActivities.sourcesNote")}
            </div>
          </>
        }
      />
    </SubGroup>
  );
}
