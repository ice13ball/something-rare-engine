// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow, FilterResetLink } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  // Year span of the SOCAT observations (from /v1/socat/meta; null until loaded) and whether it is loading now.
  socatYearBounds?: { min: number; max: number } | null;
  socatLoading?: boolean;
  co2Meta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }>; decades: Array<{ index: number; label: string }> } | null;
}

const SELECT_CLS =
  "bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40";

export function OceanCo2SurfaceRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, co2Meta, socatYearBounds, socatLoading = false }: Props) {
  const {
    activeLayers,
    co2Variable, setCo2Variable,
    co2Decade, setCo2Decade,
    co2DisplayMode, setCo2DisplayMode,
    socatYearRange, setSocatYearRange,
    enabledLayerIds,
  } = useMapStore();

  // Measurements are the THIRD option of the display switch (Field / Hexagons / Measurements) and REPLACE the field
  // (Michal, 2026-10-09). The store keeps the `socat-points` layer id (share links, z-order) in step with the mode.
  const pointsOn = co2DisplayMode === "points";
  // Offered only while the layer can be turned on (same rule as OceanCarbonRow): a visible dead option is the bug.
  const pointsAvailable = !enabledLayerIds || enabledLayerIds.has("socat-points");
  const bounds = socatYearBounds ?? null;
  // A stored range can outlive the data it was set on (a share link, a refreshed load); clamp for display only.
  const from = bounds ? Math.max(bounds.min, Math.min(socatYearRange?.[0] ?? bounds.min, bounds.max)) : 0;
  const to = bounds ? Math.min(bounds.max, Math.max(socatYearRange?.[1] ?? bounds.max, bounds.min)) : 0;
  const years = bounds ? Array.from({ length: bounds.max - bounds.min + 1 }, (_, i) => bounds.min + i) : [];
  // Both ends back at the bounds store null, so "all years" is one state and stays out of the share link.
  const update = (nextFrom: number, nextTo: number) => {
    if (!bounds) return;
    const a = Math.min(nextFrom, nextTo);
    const b = Math.max(nextFrom, nextTo);
    setSocatYearRange(a <= bounds.min && b >= bounds.max ? null : [a, b]);
  };

  const { t } = useTranslation(["panels", "common"]);

  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  return (
              <LayerRow
                id="ocean-co2-surface"
                label={t("layers.oceanCo2Surface.toggle")}
                color="#38bdf8"
                active={activeLayers.has("ocean-co2-surface")}
                onToggle={() => toggleFieldLayer("ocean-co2-surface")}
                expanded={expandedFilter === "ocean-co2-surface"}
                onExpandToggle={() => toggleExpand("ocean-co2-surface")}
                filterActive={pointsOn && socatYearRange !== null}
                filterContent={
                  co2Meta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(pointsAvailable ? ["field", "hexes", "points"] as const : ["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              aria-pressed={co2DisplayMode === m}
                              aria-describedby={m === "points" ? "socat-version-note" : undefined}
                              onClick={() => setCo2DisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${co2DisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
                            >
                              {m === "field" ? t("controls.fieldLayer.field") : m === "hexes" ? t("controls.fieldLayer.hexagons") : t("controls.fieldLayer.measurements")}
                            </button>
                          ))}
                        </div>
                        <span className="text-[10px] text-white/55 leading-snug">{t("controls.hexValueHint")}</span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
                        <select
                          value={co2Variable}
                          onChange={(e) => setCo2Variable(e.target.value)}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {co2Meta.variables.map((v) => (
                            <option key={v.key} value={v.key}>
                              {v.label} ({v.units})
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.decade")}</span>
                        <select
                          value={co2Decade}
                          onChange={(e) => setCo2Decade(Number(e.target.value))}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {co2Meta.decades.map((d) => (
                            <option key={d.index} value={d.index}>
                              {d.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      {(() => {
                        const vm = co2Meta.variables.find((v) => v.key === co2Variable);
                        if (!vm) return null;
                        const stops = vm.ramp && vm.ramp.length
                          ? vm.ramp.map((s) => `${s.hex} ${Math.round(s.pos * 100)}%`).join(", ")
                          : "#222, #ccc";
                        const mid = (vm.vmin + vm.vmax) / 2;
                        const fmt = (n: number) => (Math.abs(n) >= 100 || Number.isInteger(n) ? n.toFixed(0) : n.toFixed(1));
                        return (
                          <div className="flex flex-col gap-1 mt-1">
                            <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.scale", { units: vm.units })}</span>
                            <div className="h-3 w-full rounded-sm border border-white/10" style={{ background: `linear-gradient(to right, ${stops})` }} />
                            <div className="flex justify-between text-[10px] font-mono text-white/75">
                              <span>{fmt(vm.vmin)}</span>
                              <span>{fmt(mid)}</span>
                              <span>{fmt(vm.vmax)}</span>
                            </div>
                          </div>
                        );
                      })()}
                      {pointsAvailable && (
                        <div className="flex flex-col gap-1 border-t border-white/10 pt-2">
                          <p id="socat-version-note" className="text-[11px] text-white/60 leading-snug">{t("layers.oceanCo2Surface.points.versionNote")}</p>
                          {pointsOn && (
                            <>
                              <p className="text-[11px] text-white/60">{t("layers.oceanCo2Surface.points.greyNote")}</p>
                              {co2Variable === "density" && <p className="text-[11px] text-white/60">{t("layers.oceanCo2Surface.points.densityNote")}</p>}
                              {socatLoading && <p className="text-[11px] text-white/50">{t("layers.oceanCo2Surface.points.loading")}</p>}
                              {bounds && (
                                <div className="flex items-center gap-2">
                                  <select
                                    aria-label={t("layers.oceanCo2Surface.points.yearFrom")}
                                    value={from}
                                    onChange={(e) => update(Number(e.target.value), to)}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <span className="text-white/50">–</span>
                                  <select
                                    aria-label={t("layers.oceanCo2Surface.points.yearTo")}
                                    value={to}
                                    onChange={(e) => update(from, Number(e.target.value))}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <FilterResetLink
                                    show={socatYearRange !== null}
                                    onReset={() => setSocatYearRange(null)}
                                    label={t("common:actions.reset")}
                                  />
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  ) : null
                }
              />
  );
}
