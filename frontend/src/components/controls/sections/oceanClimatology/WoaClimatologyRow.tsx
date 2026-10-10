// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow, FilterResetLink } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";
import { WOD_PICK_VARS, wodWindowLabel } from "../../../../utils/wodCasts";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  woaMeta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null;
  // Year span of the WOD casts (from /v1/wod/meta; null until loaded) and whether it is loading now.
  wodYearBounds?: { min: number; max: number } | null;
  wodLoading?: boolean;
}

const SELECT_CLS =
  "bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40";

export function WoaClimatologyRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, woaMeta, wodYearBounds, wodLoading = false }: Props) {
  const {
    activeLayers,
    woaVariable, setWoaVariable,
    woaDepth, setWoaDepth,
    woaDisplayMode, setWoaDisplayMode,
    wodYearRange, setWodYearRange,
    enabledLayerIds,
  } = useMapStore();

  // Measurements are the THIRD option of the display switch (Field / Hexagons / Measurements) and REPLACE the field
  // (Michal's standing ruling, as for SOCAT). The store keeps the `wod-casts` layer id (share links, z-order) in step.
  const pointsOn = woaDisplayMode === "points";
  // Offered only while the layer can be turned on (same rule as OceanCo2SurfaceRow): a visible dead option is the bug.
  const pointsAvailable = !enabledLayerIds || enabledLayerIds.has("wod-casts");
  const bounds = wodYearBounds ?? null;
  // A stored range can outlive the data it was set on (a share link, a refreshed load); clamp for display only.
  const from = bounds ? Math.max(bounds.min, Math.min(wodYearRange?.[0] ?? bounds.min, bounds.max)) : 0;
  const to = bounds ? Math.min(bounds.max, Math.max(wodYearRange?.[1] ?? bounds.max, bounds.min)) : 0;
  const years = bounds ? Array.from({ length: bounds.max - bounds.min + 1 }, (_, i) => bounds.min + i) : [];
  // Both ends back at the bounds store null, so "all years" is one state and stays out of the share link.
  const update = (nextFrom: number, nextTo: number) => {
    if (!bounds) return;
    const a = Math.min(nextFrom, nextTo);
    const b = Math.max(nextFrom, nextTo);
    setWodYearRange(a <= bounds.min && b >= bounds.max ? null : [a, b]);
  };

  const { t } = useTranslation(["panels", "common"]);

  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  return (
              <LayerRow
                id="woa-climatology"
                label={t("layers.woaClimatology.toggle")}
                color="#50aac8"
                active={activeLayers.has("woa-climatology")}
                onToggle={() => toggleFieldLayer("woa-climatology")}
                expanded={expandedFilter === "woa-climatology"}
                onExpandToggle={() => toggleExpand("woa-climatology")}
                filterActive={pointsOn && wodYearRange !== null}
                filterContent={
                  woaMeta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(pointsAvailable ? ["field", "hexes", "points"] as const : ["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              aria-pressed={woaDisplayMode === m}
                              aria-describedby={m === "points" ? "wod-product-note" : undefined}
                              onClick={() => setWoaDisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${woaDisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
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
                          value={woaVariable}
                          onChange={(e) => setWoaVariable(e.target.value)}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {woaMeta.variables.map((v) => (
                            <option key={v.key} value={v.key}>
                              {v.label} ({v.units})
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.depth")}</span>
                        <select
                          value={woaDepth}
                          onChange={(e) => setWoaDepth(Number(e.target.value))}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {woaMeta.depths.map((d) => (
                            <option key={d} value={d}>
                              {d === 0 ? "Surface" : `${d} m`}
                            </option>
                          ))}
                        </select>
                      </div>
                      {(() => {
                        const vm = woaMeta.variables.find((v) => v.key === woaVariable);
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
                            {vm.key === "nstar" && (
                              <span className="text-[10px] text-white/55 leading-snug">{t("woaPoint.nstarHint")}</span>
                            )}
                          </div>
                        );
                      })()}
                      {pointsAvailable && (
                        <div className="flex flex-col gap-1 border-t border-white/10 pt-2">
                          <p id="wod-product-note" className="text-[11px] text-white/60 leading-snug">{t("layers.woaClimatology.points.productNote")}</p>
                          {pointsOn && (
                            <>
                              <p className="text-[11px] text-white/60">{t("layers.woaClimatology.points.greyNote", { window: wodWindowLabel(woaDepth) })}</p>
                              {!(WOD_PICK_VARS as readonly string[]).includes(woaVariable) && (
                                <p className="text-[11px] text-white/60">{t("layers.woaClimatology.points.derivedNote")}</p>)}
                              {woaVariable === "nstar" && (
                                <p className="text-[11px] text-white/60">{t("layers.woaClimatology.points.nstarNote")}</p>)}
                              {wodLoading && <p className="text-[11px] text-white/50">{t("layers.woaClimatology.points.loading")}</p>}
                              {bounds && (
                                <div className="flex items-center gap-2">
                                  <select
                                    aria-label={t("layers.woaClimatology.points.yearFrom")}
                                    value={from}
                                    onChange={(e) => update(Number(e.target.value), to)}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <span className="text-white/50">–</span>
                                  <select
                                    aria-label={t("layers.woaClimatology.points.yearTo")}
                                    value={to}
                                    onChange={(e) => update(from, Number(e.target.value))}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <FilterResetLink
                                    show={wodYearRange !== null}
                                    onReset={() => setWodYearRange(null)}
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
