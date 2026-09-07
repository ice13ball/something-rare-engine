// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { DEEPDATA_CONTRACTOR_DEFS } from "../filterDefs";
import {
  LayerRow, SubGroup, CheckboxFilter,
} from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function AnalysisSection({ expandedFilter, setExpandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    deepdataStationContractorFilters, toggleDeepdataStationContractor,
    marineCarbonVariable, setMarineCarbonVariable,
    marineCarbonDepth, setMarineCarbonDepth,
    vmeView, setVmeView,
    acidificationVariable, setAcidificationVariable,
    acidificationDepth, setAcidificationDepth,
    acidificationDisplayMode, setAcidificationDisplayMode,
    chiDisplayMode, setChiDisplayMode,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  // Ambient field layers (WOA / Oxygen / Ocean Carbon / Surface CO₂) hide their
  // Field/Hexagons value-readout toggle behind the "+" expander, which only
  // appears once the layer is active — so it's easy to miss. Auto-expand the
  // controls the moment such a layer is switched on so the toggle is obvious;
  // collapse again when it's switched off (if it was the expanded one).
  const toggleFieldLayer = (id: LayerId) => {
    const wasActive = activeLayers.has(id);
    toggle(id);
    if (!wasActive) setExpandedFilter(id);
    else if (expandedFilter === id) setExpandedFilter(null);
  };

  // Ocean Acidification (GLODAP Ω) meta — Map3D.tsx already fetches its own copy for the
  // BitmapLayer/hex ramp; this is a second, independent fetch scoped to the controls row
  // (variable/depth options), same lazy-on-activation pattern as the field layers above.
  const [acidMeta, setAcidMeta] = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; center: number | null; vmax: number; cmap: string; kind: string; ramp?: Array<{ pos: number; hex: string }>; depths: number[] }>; depths: number[] } | null>(null);
  const acidMetaFetchedRef = useRef(false);
  useEffect(() => {
    if (!activeLayers.has("ocean-acidification") || acidMetaFetchedRef.current) return;
    acidMetaFetchedRef.current = true;
    const API = import.meta.env.VITE_API_BASE_URL ?? "";
    fetch(`${API}/api/v1/acidification/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => { if (m?.variables?.length) setAcidMeta(m); })
      .catch(() => { acidMetaFetchedRef.current = false; });
  }, [activeLayers]);

  // Cumulative Human Impact meta — single "impact" var, no depth; scoped to the controls
  // row for the colour-scale legend. Same lazy-on-activation pattern.
  const [chiMeta, setChiMeta] = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }> } | null>(null);
  const chiMetaFetchedRef = useRef(false);
  useEffect(() => {
    if (!activeLayers.has("cumulative-human-impact") || chiMetaFetchedRef.current) return;
    chiMetaFetchedRef.current = true;
    const API = import.meta.env.VITE_API_BASE_URL ?? "";
    fetch(`${API}/api/v1/chi/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => { if (m?.variables?.length) setChiMeta(m); })
      .catch(() => { chiMetaFetchedRef.current = false; });
  }, [activeLayers]);

  return (
            <SubGroup label={t("controls.subgroups.analysis")} storageKey="sea_analysis">
              <LayerRow
                id="monitoring-density"
                label={t("layers.monitoringDensity.toggle")}
                color="#ff7a00"
                active={activeLayers.has("monitoring-density")}
                onToggle={() => toggle("monitoring-density")}
                onLocate={() => flyToLayer?.("monitoring-density")}
              />
              <LayerRow
                id="deepdata-stations"
                label={t("layers.deepdataStations.toggle")}
                color="#f472b6"
                active={activeLayers.has("deepdata-stations")}
                onToggle={() => toggle("deepdata-stations")}
                onLocate={() => flyToLayer?.("deepdata-stations")}
                filterActive={deepdataStationContractorFilters.size > 0}
                expanded={expandedFilter === "deepdata-stations"}
                onExpandToggle={() => toggleExpand("deepdata-stations")}
                filterContent={
                  <CheckboxFilter
                    header={t("filters.deepdataStations.contractorHeading")}
                    defs={DEEPDATA_CONTRACTOR_DEFS}
                    activeSet={deepdataStationContractorFilters}
                    onToggle={toggleDeepdataStationContractor}
                    clearLabel={t("filters.deepdataStations.clearLabel")}
                  />
                }
              />

              {/* Marine Carbon (unified) — GLODAP + SOCAT + ISAS20 + WOA */}
              <LayerRow
                id="marine-carbon"
                label={t("layers.marineCarbon.toggle")}
                color="#6ee7b7"
                active={activeLayers.has("marine-carbon")}
                onToggle={() => toggleFieldLayer("marine-carbon")}
                onLocate={() => flyToLayer?.("marine-carbon")}
                expanded={expandedFilter === "marine-carbon"}
                onExpandToggle={() => toggleExpand("marine-carbon")}
                filterContent={
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
                      <select
                        value={marineCarbonVariable}
                        onChange={(e) => setMarineCarbonVariable(e.target.value)}
                        className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                      >
                        <option value="co2_fco2">{t("layers.marineCarbon.var.fco2")}</option>
                        <option value="dic">{t("layers.marineCarbon.var.dic")}</option>
                        <option value="o2_recent">{t("layers.marineCarbon.var.o2")}</option>
                        <option value="woa_temp">{t("layers.marineCarbon.var.temp")}</option>
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.depth")}</span>
                      <select
                        value={marineCarbonDepth}
                        onChange={(e) => setMarineCarbonDepth(Number(e.target.value))}
                        className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                      >
                        {[0, 100, 500, 1000, 2000].map((d) => (
                          <option key={d} value={d}>{d === 0 ? "Surface" : `${d} m`}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                }
              />

              {/* VME Suitability — modeled reef-forming coral habitat suitability */}
              <LayerRow
                id="vme-suitability"
                label={t("layers.vmeSuitability.toggle")}
                color="#a78bfa"
                active={activeLayers.has("vme-suitability")}
                onToggle={() => toggleFieldLayer("vme-suitability")}
                onLocate={() => flyToLayer?.("vme-suitability")}
                expanded={expandedFilter === "vme-suitability"}
                onExpandToggle={() => toggleExpand("vme-suitability")}
                filterContent={
                  <div className="flex flex-col gap-1">
                    <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
                    <select
                      value={vmeView}
                      onChange={(e) => setVmeView(e.target.value as "suitability" | "uncertainty")}
                      className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                    >
                      <option value="suitability">{t("layers.vmeSuitability.view.suitability")}</option>
                      <option value="uncertainty">{t("layers.vmeSuitability.view.uncertainty")}</option>
                    </select>
                  </div>
                }
              />

              {/* Ocean Acidification — modeled GLODAP OmegaA/OmegaC saturation state + platform-derived horizon depth */}
              <LayerRow
                id="ocean-acidification"
                label={t("layers.oceanAcidification.toggle")}
                color="#fb7185"
                active={activeLayers.has("ocean-acidification")}
                onToggle={() => toggleFieldLayer("ocean-acidification")}
                expanded={expandedFilter === "ocean-acidification"}
                onExpandToggle={() => toggleExpand("ocean-acidification")}
                filterContent={
                  acidMeta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              onClick={() => setAcidificationDisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${acidificationDisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
                            >
                              {m === "field" ? t("controls.fieldLayer.field") : t("controls.fieldLayer.hexagons")}
                            </button>
                          ))}
                        </div>
                        <span className="text-[10px] text-white/55 leading-snug">{t("controls.hexValueHint")}</span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
                        <select
                          value={acidificationVariable}
                          onChange={(e) => setAcidificationVariable(e.target.value as "aragonite" | "calcite" | "horizon" | "horizon-shift")}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {acidMeta.variables.map((v) => (
                            <option key={v.key} value={v.key}>
                              {v.label} ({v.units})
                            </option>
                          ))}
                        </select>
                      </div>
                      {acidificationVariable !== "horizon" && acidificationVariable !== "horizon-shift" && (
                        <div className="flex flex-col gap-1">
                          <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.depth")}</span>
                          <select
                            value={acidificationDepth}
                            onChange={(e) => setAcidificationDepth(Number(e.target.value))}
                            className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                          >
                            {acidMeta.depths.map((d) => (
                              <option key={d} value={d}>
                                {d === 0 ? "Surface" : `${d} m`}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                      {(() => {
                        const vm = acidMeta.variables.find((v) => v.key === acidificationVariable);
                        if (!vm) return null;
                        const stops = vm.ramp && vm.ramp.length
                          ? vm.ramp.map((s) => `${s.hex} ${Math.round(s.pos * 100)}%`).join(", ")
                          : "#222, #ccc";
                        const fmt = (n: number) => (Math.abs(n) >= 100 || Number.isInteger(n) ? n.toFixed(0) : n.toFixed(1));
                        return (
                          <div className="flex flex-col gap-1 mt-1">
                            <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.scale", { units: vm.units })}</span>
                            <div className="h-3 w-full rounded-sm border border-white/10" style={{ background: `linear-gradient(to right, ${stops})` }} />
                            <div className="flex justify-between text-[10px] font-mono text-white/75">
                              <span>{fmt(vm.vmin)}</span>
                              {vm.center != null && <span>{fmt(vm.center)}</span>}
                              <span>{fmt(vm.vmax)}</span>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ) : null
                }
              />

              {/* Coral Acidification Exposure — VME suitability × aragonite horizon crossing */}
              <LayerRow
                id="coral-acid-exposure"
                label={t("layers.coralAcidExposure.toggle")}
                color="#be1e5a"
                active={activeLayers.has("coral-acid-exposure")}
                onToggle={() => toggle("coral-acid-exposure")}
                onLocate={() => flyToLayer?.("coral-acid-exposure")}
              />

              {/* Cumulative Human Impact — modelled total human pressure (NCEAS/Halpern 2025) */}
              <LayerRow
                id="cumulative-human-impact"
                label={t("layers.cumulativeHumanImpact.toggle")}
                color="#f0be5a"
                active={activeLayers.has("cumulative-human-impact")}
                onToggle={() => toggleFieldLayer("cumulative-human-impact")}
                expanded={expandedFilter === "cumulative-human-impact"}
                onExpandToggle={() => toggleExpand("cumulative-human-impact")}
                filterContent={
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                      <div className="flex gap-1">
                        {(["field", "hexes"] as const).map((m) => (
                          <button
                            key={m}
                            onClick={() => setChiDisplayMode(m)}
                            className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${chiDisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
                          >
                            {m === "field" ? t("controls.fieldLayer.field") : t("controls.fieldLayer.hexagons")}
                          </button>
                        ))}
                      </div>
                      <span className="text-[10px] text-white/55 leading-snug">{t("controls.hexValueHint")}</span>
                    </div>
                    {(() => {
                      const vm = chiMeta?.variables.find((v) => v.key === "impact");
                      if (!vm) return null;
                      const stops = vm.ramp && vm.ramp.length
                        ? vm.ramp.map((s) => `${s.hex} ${Math.round(s.pos * 100)}%`).join(", ")
                        : "#214e64, #961c1c";
                      const fmt = (n: number) => (Math.abs(n) >= 100 || Number.isInteger(n) ? n.toFixed(0) : n.toFixed(1));
                      return (
                        <div className="flex flex-col gap-1 mt-1">
                          <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.scale", { units: vm.units })}</span>
                          <div className="h-3 w-full rounded-sm border border-white/10" style={{ background: `linear-gradient(to right, ${stops})` }} />
                          <div className="flex justify-between text-[10px] font-mono text-white/75">
                            <span>{fmt(vm.vmin)}</span>
                            <span>{fmt(vm.vmax)}</span>
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
