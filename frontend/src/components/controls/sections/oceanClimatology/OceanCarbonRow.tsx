// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { glodapWindowLabel } from "../../../../utils/glodapPoints";
import { LayerRow, FilterResetLink } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  // Year span of the GLODAPv3 cast document (null until it has loaded) and whether it is loading now.
  glodapYearBounds?: { min: number; max: number } | null;
  glodapLoading?: boolean;
  carbonMeta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null;
}

const SELECT_CLS =
  "bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40";

export function OceanCarbonRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, carbonMeta, glodapYearBounds, glodapLoading = false }: Props) {
  const {
    activeLayers,
    carbonVariable, setCarbonVariable,
    carbonDepth, setCarbonDepth,
    carbonDisplayMode, setCarbonDisplayMode,
    glodapYearRange, setGlodapYearRange,
    enabledLayerIds,
  } = useMapStore();

  // Measurements are the THIRD option of the display switch (Field / Hexagons / Measurements) and replace the
  // field. The store keeps the `glodap-points` layer id (share links, search, z-order) in step with the mode.
  const pointsOn = carbonDisplayMode === "points";
  // Offer the option only while the layer can be turned on: `enabledLayerIds` already folds in a layer disabled or
  // retired in layer_config AND one hidden per environment via HIDDEN_LAYERS (null = config not loaded: allow all).
  // Same rule as LayerRow, and the store would refuse to select it anyway: a visible dead option is the bug.
  const pointsAvailable = !enabledLayerIds || enabledLayerIds.has("glodap-points");
  const bounds = glodapYearBounds ?? null;
  // A stored range can outlive the data it was set on (a share link, a refreshed load); clamp for display only.
  const from = bounds ? Math.max(bounds.min, Math.min(glodapYearRange?.[0] ?? bounds.min, bounds.max)) : 0;
  const to = bounds ? Math.min(bounds.max, Math.max(glodapYearRange?.[1] ?? bounds.max, bounds.min)) : 0;
  const years = bounds ? Array.from({ length: bounds.max - bounds.min + 1 }, (_, i) => bounds.min + i) : [];
  // Both ends back at the bounds store null, so "all years" is one state and stays out of the share link.
  const update = (nextFrom: number, nextTo: number) => {
    if (!bounds) return;
    const a = Math.min(nextFrom, nextTo);
    const b = Math.max(nextFrom, nextTo);
    setGlodapYearRange(a <= bounds.min && b >= bounds.max ? null : [a, b]);
  };

  const { t } = useTranslation(["panels", "common"]);

  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  return (
              <LayerRow
                id="ocean-carbon"
                label={t("layers.oceanCarbon.toggle")}
                color="#34d399"
                active={activeLayers.has("ocean-carbon")}
                onToggle={() => toggleFieldLayer("ocean-carbon")}
                expanded={expandedFilter === "ocean-carbon"}
                onExpandToggle={() => toggleExpand("ocean-carbon")}
                filterActive={pointsOn && glodapYearRange !== null}
                filterContent={
                  carbonMeta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(pointsAvailable ? ["field", "hexes", "points"] as const : ["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              aria-pressed={carbonDisplayMode === m}
                              aria-describedby={m === "points" ? "glodap-version-note" : undefined}
                              onClick={() => setCarbonDisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${carbonDisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
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
                          value={carbonVariable}
                          onChange={(e) => setCarbonVariable(e.target.value)}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {carbonMeta.variables.map((v) => (
                            <option key={v.key} value={v.key}>
                              {v.label} ({v.units})
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.depth")}</span>
                        <select
                          value={carbonDepth}
                          onChange={(e) => setCarbonDepth(Number(e.target.value))}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {carbonMeta.depths.map((d) => (
                            <option key={d} value={d}>
                              {d === 0 ? "Surface" : `${d} m`}
                            </option>
                          ))}
                        </select>
                      </div>
                      {(() => {
                        const vm = carbonMeta.variables.find((v) => v.key === carbonVariable);
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
                          <p id="glodap-version-note" className="text-[11px] text-white/60 leading-snug">{t("layers.oceanCarbon.points.versionNote")}</p>
                          {pointsOn && (
                            <>
                              {carbonVariable === "cant"
                                ? <p className="text-[11px] text-amber-300/80">{t("layers.oceanCarbon.points.cantNote")}</p>
                                : <p className="text-[11px] text-white/60">{t("layers.oceanCarbon.points.greyNote", { window: glodapWindowLabel(carbonDepth) })}</p>}
                              {glodapLoading && <p className="text-[11px] text-white/50">{t("layers.oceanCarbon.points.loading")}</p>}
                              {bounds && (
                                <div className="flex items-center gap-2">
                                  <select
                                    aria-label={t("layers.oceanCarbon.points.yearFrom")}
                                    value={from}
                                    onChange={(e) => update(Number(e.target.value), to)}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <span className="text-white/50">–</span>
                                  <select
                                    aria-label={t("layers.oceanCarbon.points.yearTo")}
                                    value={to}
                                    onChange={(e) => update(from, Number(e.target.value))}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <FilterResetLink
                                    show={glodapYearRange !== null}
                                    onReset={() => setGlodapYearRange(null)}
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
