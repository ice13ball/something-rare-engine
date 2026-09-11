// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { ALARM_DEFS } from "../../../utils/argoAlarms";
import { analytics } from "../../../utils/analytics";
import { ONC_EOV_ORDER, ONC_EOV_LABELS } from "../../../types/onc";
import { OCEANSITES_NETWORK_DEFS, OCEANSITES_STATUS_DEFS } from "../filterDefs";
import {
  LayerRow, SubGroup, CheckboxFilter, FilterResetLink,
} from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
  currentsMeta?: Record<string, import("../../CurrentsLayer").CurrentsMeta> | null;
  currentsDate?: string | null;
  setCurrentsDate?: (d: string | null) => void;
  currentsPlaying?: boolean;
  setCurrentsPlaying?: (b: boolean) => void;
}

export function SensorsSection({
  expandedFilter, toggleExpand, toggle, flyToLayer,
  currentsMeta, currentsDate, setCurrentsDate, currentsPlaying, setCurrentsPlaying,
}: Props) {
  const {
    activeLayers,
    argoAlarmFilters, toggleArgoAlarm,
    oceansitesNetworkFilters, toggleOceansitesNetworkFilter,
    oceansitesStatusFilters,  toggleOceansitesStatusFilter,
    oncEovFilters, toggleOncEovFilter,
    hydrophoneSourceFilters, toggleHydrophoneSourceFilter,
    hydrophoneStatusFilters, toggleHydrophoneStatusFilter,
    hydrophoneDepthFilters,  toggleHydrophoneDepthFilter,
    currentsDepth, setCurrentsDepth,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
            <SubGroup label={t("controls.subgroups.sensorsMonitoring")} storageKey="sea_sensors">
              <LayerRow
                id="argo" label={t("layers.argo.toggle")} color="#00e5ff"
                active={activeLayers.has("argo")}
                onToggle={() => toggle("argo")}
                onLocate={() => flyToLayer?.("argo")}
                filterActive={argoAlarmFilters.size > 0}
                expanded={expandedFilter === "argo"}
                onExpandToggle={() => toggleExpand("argo")}
                filterContent={
                  <CheckboxFilter
                    header={t("filters.argo.showOnlyFloatsWith")}
                    headerClassName="text-white/65 text-[13px] mb-0.5"
                    defs={ALARM_DEFS}
                    activeSet={argoAlarmFilters}
                    onToggle={(key) => { toggleArgoAlarm(key); analytics.toggleAlarmFilter(key, !argoAlarmFilters.has(key)); }}
                    clearLabel={t("filters.argo.clearLabel")}
                  />
                }
              />
              <LayerRow
                id="oceansites"
                label={t("layers.oceansites.toggle")}
                color="#00cfff"
                active={activeLayers.has("oceansites")}
                onToggle={() => toggle("oceansites")}
                onLocate={() => flyToLayer?.("oceansites")}
                filterContent={
                  <>
                    <div className="flex items-center justify-end pb-0.5">
                      <FilterResetLink
                        show={oceansitesNetworkFilters.size > 0 || oceansitesStatusFilters.size > 0}
                        onReset={() => {
                          oceansitesNetworkFilters.forEach(toggleOceansitesNetworkFilter);
                          oceansitesStatusFilters.forEach(toggleOceansitesStatusFilter);
                        }}
                      />
                    </div>
                    {/* Status first: 64 of 1,037 stations are OPERATIONAL, so this
                        is the filter that changes what the map shows most. The KEY
                        is OceanOPS's own word; only the gloss beside it is ours. */}
                    <CheckboxFilter
                      header={t("filters.oceansites.statusHeader")}
                      headerClassName="text-white/65 text-[13px] mb-0.5"
                      defs={OCEANSITES_STATUS_DEFS.map(({ key, labelKey, color }) => ({
                        key, color, label: t(labelKey),
                      }))}
                      activeSet={oceansitesStatusFilters}
                      onToggle={toggleOceansitesStatusFilter}
                    />
                    <p className="text-white/60 text-[10px] font-mono uppercase tracking-[0.12em] pt-1.5 pb-0.5">
                      {t("filters.oceansites.networkHeader")}
                    </p>
                    {OCEANSITES_NETWORK_DEFS.map(({ key, label, color }) => {
                      const active = oceansitesNetworkFilters.has(key);
                      return (
                        <button
                          key={key}
                          onClick={() => toggleOceansitesNetworkFilter(key)}
                          aria-label={`Filter by ${label} network`}
                          aria-pressed={oceansitesNetworkFilters.has(key)}
                          className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${
                            oceansitesNetworkFilters.size > 0 && !active ? "opacity-60" : "opacity-100"
                          }`}
                        >
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0 border"
                            style={{ backgroundColor: active ? color : "transparent", borderColor: color }}
                          />
                          <span className={active ? "text-white" : "text-white/70"}>{label}</span>
                        </button>
                      );
                    })}
                  </>
                }
                filterActive={oceansitesNetworkFilters.size > 0 || oceansitesStatusFilters.size > 0}
                expanded={expandedFilter === "oceansites"}
                onExpandToggle={() => toggleExpand("oceansites")}
              />
              <LayerRow
                id="onc"
                label={t("layers.onc.toggle")}
                color="#4db8a4"
                active={activeLayers.has("onc")}
                onToggle={() => toggle("onc")}
                onLocate={() => flyToLayer?.("onc")}
                filterActive={oncEovFilters.size > 0}
                expanded={expandedFilter === "onc"}
                onExpandToggle={() => toggleExpand("onc")}
                filterContent={
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-white/65 text-[11px] leading-tight">{t("filters.onc.eovFilterHint")}</p>
                      <FilterResetLink
                        show={oncEovFilters.size > 0}
                        onReset={() => oncEovFilters.forEach(toggleOncEovFilter)}
                      />
                    </div>
                    {ONC_EOV_ORDER.map(eov => (
                      <label key={eov} className="flex items-center gap-2 py-0.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={oncEovFilters.has(eov)}
                          onChange={() => toggleOncEovFilter(eov)}
                          className="accent-teal-400 w-3 h-3"
                        />
                        <span className="text-white/75 text-[13px]">{ONC_EOV_LABELS[eov]}</span>
                      </label>
                    ))}
                  </div>
                }
              />
              <LayerRow
                id="onc-instruments"
                label={t("layers.oncInstruments.toggle")}
                color="#a78bfa"
                active={activeLayers.has("onc-instruments")}
                onToggle={() => toggle("onc-instruments")}
                onLocate={() => flyToLayer?.("onc-instruments")}
              />
              <LayerRow
                id="hydrophone-stations"
                label={t("controls.layers.hydrophoneStations" as any)}
                color="#e879f9"
                active={activeLayers.has("hydrophone-stations")}
                onToggle={() => toggle("hydrophone-stations")}
                onLocate={() => flyToLayer?.("hydrophone-stations")}
                filterActive={
                  hydrophoneSourceFilters.size > 0 ||
                  hydrophoneStatusFilters.size > 0 ||
                  hydrophoneDepthFilters.size > 0
                }
                expanded={expandedFilter === "hydrophone-stations"}
                onExpandToggle={() => toggleExpand("hydrophone-stations")}
                filterContent={
                  <>
                    <div className="flex items-center justify-end -mt-0.5">
                      <FilterResetLink
                        show={
                          hydrophoneSourceFilters.size > 0 ||
                          hydrophoneStatusFilters.size > 0 ||
                          hydrophoneDepthFilters.size > 0
                        }
                        onReset={() => {
                          hydrophoneSourceFilters.forEach(toggleHydrophoneSourceFilter);
                          hydrophoneStatusFilters.forEach(toggleHydrophoneStatusFilter);
                          hydrophoneDepthFilters.forEach(toggleHydrophoneDepthFilter);
                        }}
                      />
                    </div>
                    <p className="text-white/70 text-[10px] uppercase tracking-wider mt-1 mb-1">
                      {t("controls.hydrophone.source" as any)}
                    </p>
                    {[
                      { key: "ooi",    label: "OOI",         color: "#e879f9" },
                      { key: "imos",   label: "IMOS",        color: "#22c55e" },
                      { key: "mars",   label: "MARS",        color: "#22d3ee" },
                      { key: "palaoa", label: "AWI PALAOA",  color: "#f8fafc" },
                      { key: "obsea",  label: "OBSEA",       color: "#facc15" },
                      { key: "km3net", label: "KM3NeT",      color: "#818cf8" },
                      { key: "nrs",        label: "NOAA NRS",        color: "#38bdf8" },
                      { key: "sanctsound", label: "NOAA SanctSound", color: "#fb923c" },
                      { key: "nefsc",      label: "NOAA NEFSC",      color: "#f472b6" },
                      // Phase 4 — 12 NOAA Passive Acoustic Archive programs
                      { key: "pifsc",  label: "PIFSC", color: "#0ea5e9" },
                      { key: "sefsc",  label: "SEFSC", color: "#fbbf24" },
                      { key: "onms",   label: "ONMS",  color: "#f97316" },
                      { key: "adeon",  label: "ADEON", color: "#8b5cf6" },
                      { key: "boem",   label: "BOEM",  color: "#4b5563" },
                      { key: "aeon",   label: "AEON",  color: "#a78bfa" },
                      { key: "navy",   label: "Navy",  color: "#1f2937" },
                      { key: "nps",    label: "NPS",   color: "#10b981" },
                      { key: "jasco",  label: "JASCO", color: "#d946ef" },
                      { key: "fram",   label: "FRAM",  color: "#e1d314" },
                      { key: "coastal_studies_institute", label: "CSI", color: "#0e7490" },
                      { key: "ioos",   label: "IOOS",  color: "#4f46e5" },
                      // Phase 3 — PANGAEA/Dryad
                      { key: "sambah", label: "SAMBAH", color: "#34d399" },
                      // Phase 4 — CTBTO IMS
                      { key: "ims", label: "CTBTO IMS", color: "#67e8f9" },
                    ].map(({ key, label, color }) => {
                      const disabled = hydrophoneSourceFilters.size > 0 && !hydrophoneSourceFilters.has(key);
                      return (
                        <button
                          key={key}
                          onClick={() => toggleHydrophoneSourceFilter(key)}
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
                    <p className="text-white/70 text-[10px] uppercase tracking-wider mt-2 mb-1">
                      {t("controls.hydrophone.status" as any)}
                    </p>
                    {([
                      { key: "active",  label: t("controls.hydrophone.active" as any) as string },
                      { key: "retired", label: t("controls.hydrophone.retired" as any) as string },
                    ] as const).map(({ key, label }) => (
                      <label key={key} className="flex items-center gap-2 py-0.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={hydrophoneStatusFilters.has(key)}
                          onChange={() => toggleHydrophoneStatusFilter(key)}
                          className="accent-fuchsia-400 w-3 h-3"
                        />
                        <span className="text-white/75 text-[13px]">{label}</span>
                      </label>
                    ))}
                    <p className="text-white/70 text-[10px] uppercase tracking-wider mt-2 mb-1">
                      {t("controls.hydrophone.depth" as any)}
                    </p>
                    {([
                      { key: "shallow", label: t("controls.hydrophone.shallow" as any) as string },
                      { key: "slope",   label: t("controls.hydrophone.slope" as any)   as string },
                      { key: "abyssal", label: t("controls.hydrophone.abyssal" as any) as string },
                    ] as const).map(({ key, label }) => (
                      <label key={key} className="flex items-center gap-2 py-0.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={hydrophoneDepthFilters.has(key)}
                          onChange={() => toggleHydrophoneDepthFilter(key)}
                          className="accent-fuchsia-400 w-3 h-3"
                        />
                        <span className="text-white/75 text-[13px]">{label}</span>
                      </label>
                    ))}
                  </>
                }
              />
              <LayerRow
                id="ocean-currents"
                label={t("controls.layers.oceanCurrents" as any)}
                color="#5eead4"
                active={activeLayers.has("ocean-currents")}
                onToggle={() => toggle("ocean-currents")}
                expanded={expandedFilter === "ocean-currents"}
                onExpandToggle={() => toggleExpand("ocean-currents")}
                filterContent={
                  <div className="flex flex-col gap-2">
                    <div className="flex gap-1">
                      {(["surface", "1000m"] as const).map((d) => (
                        <button
                          key={d}
                          onClick={() => setCurrentsDepth(d)}
                          className={
                            "px-2 py-0.5 rounded text-[11px] font-mono transition-colors " +
                            (currentsDepth === d
                              ? "bg-teal-400/20 text-teal-200 ring-1 ring-teal-400/40"
                              : "text-white/70 hover:text-white/90")
                          }
                        >
                          {d === "surface"
                            ? t("controls.layers.currentsSurface" as any)
                            : t("controls.layers.currents1000m" as any)}
                        </button>
                      ))}
                    </div>
                    {(() => {
                      const meta = currentsMeta?.[currentsDepth];
                      const dates = meta?.available_dates ?? [];
                      if (dates.length < 2) return null;
                      const cur = (currentsDate && dates.includes(currentsDate))
                        ? currentsDate : dates[dates.length - 1];
                      const idx = dates.indexOf(cur);
                      const atLatest = idx >= dates.length - 1;
                      return (
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => setCurrentsPlaying?.(!currentsPlaying)}
                              className="px-1.5 py-0.5 rounded text-[11px] bg-teal-400/15 text-teal-200 ring-1 ring-teal-400/30 hover:bg-teal-400/25"
                              aria-label={currentsPlaying
                                ? t("controls.layers.currentsPause" as any)
                                : t("controls.layers.currentsPlay" as any)}
                            >
                              {currentsPlaying ? "❚❚" : "▶"}
                            </button>
                            <input
                              type="range"
                              min={0}
                              max={dates.length - 1}
                              value={idx}
                              aria-label={t("controls.layers.currentsSlider" as any)}
                              onChange={(e) => {
                                setCurrentsPlaying?.(false);
                                setCurrentsDate?.(dates[Number(e.target.value)]);
                              }}
                              className="flex-1 accent-teal-400"
                            />
                          </div>
                          <div className="text-[11px] font-mono text-white/80 text-center">
                            {cur}{atLatest ? ` · ${t("controls.layers.currentsLatest" as any)}` : ""}
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                }
              />
            </SubGroup>
  );
}
