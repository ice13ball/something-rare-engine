// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { ARGO_POINTS_VIEW, argoWindowLabel } from "../../../../utils/argoOxygenPoints";
import { ARGO_POINT_MIN_ZOOM } from "../../../../utils/argoOxygenTiles";
import { LayerRow, FilterResetLink } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  // BGC-Argo O₂ Measurements (points): year span (from /meta), still loading, nothing in the year window.
  argoYearBounds?: { min: number; max: number } | null;
  argoLoading?: boolean;
  argoEmpty?: boolean;
  oxygenMeta?: { views: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp: Array<{ pos: number; hex: string }>; depths: number[]; diverging: boolean }>; depths: number[]; attribution: string } | null;
}

const SELECT_CLS =
  "bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40";

export function OxygenDeoxRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, oxygenMeta, argoYearBounds, argoLoading = false, argoEmpty = false }: Props) {
  const {
    activeLayers,
    oxygenView, setOxygenView,
    oxygenDepth, setOxygenDepth,
    oxygenDisplayMode, setOxygenDisplayMode,
    argoOxygenYearRange, setArgoOxygenYearRange,
    enabledLayerIds,
  } = useMapStore();

  // Measurements are the THIRD option of the display switch (Field / Hexagons / Measurements) and replace the
  // field. The store keeps the `argo-oxygen-points` layer id (share links, search, z-order) in step with the mode.
  const pointsOn = oxygenDisplayMode === "points";
  // Offer the option only while the layer can be turned on: `enabledLayerIds` already folds in a layer disabled or
  // retired in layer_config AND one hidden per environment via HIDDEN_LAYERS (null = config not loaded: allow all).
  const pointsAvailable = !enabledLayerIds || enabledLayerIds.has("argo-oxygen-points");
  const bounds = argoYearBounds ?? null;
  // A stored range can outlive the data it was set on (a share link, a refreshed load); clamp for display only.
  const from = bounds ? Math.max(bounds.min, Math.min(argoOxygenYearRange?.[0] ?? bounds.min, bounds.max)) : 0;
  const to = bounds ? Math.min(bounds.max, Math.max(argoOxygenYearRange?.[1] ?? bounds.max, bounds.min)) : 0;
  const years = bounds ? Array.from({ length: bounds.max - bounds.min + 1 }, (_, i) => bounds.min + i) : [];
  // Both ends back at the bounds store null, so "all years" is one state and stays out of the share link.
  const update = (nextFrom: number, nextTo: number) => {
    if (!bounds) return;
    const a = Math.min(nextFrom, nextTo);
    const b = Math.max(nextFrom, nextTo);
    setArgoOxygenYearRange(a <= bounds.min && b >= bounds.max ? null : [a, b]);
  };
  // ⛔ Points are absolute O₂: their scale is ALWAYS the Recent view's, whatever `oxygenView` says. `oxygenView`
  // itself is never written here, so the user's field view is still there when they leave Measurements.
  const scaleView = oxygenMeta?.views.find((v) => v.key === (pointsOn ? ARGO_POINTS_VIEW : oxygenView));

  const { t } = useTranslation(["panels", "common"]);

  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  return (
              <LayerRow
                id="oxygen-deox"
                label={t("layers.oxygenDeox.toggle")}
                color="#3b82f6"
                active={activeLayers.has("oxygen-deox")}
                onToggle={() => toggleFieldLayer("oxygen-deox")}
                expanded={expandedFilter === "oxygen-deox"}
                onExpandToggle={() => toggleExpand("oxygen-deox")}
                filterActive={pointsOn && argoOxygenYearRange !== null}
                filterContent={
                  oxygenMeta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(pointsAvailable ? ["field", "hexes", "points"] as const : ["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              aria-pressed={oxygenDisplayMode === m}
                              aria-describedby={m === "points" ? "argo-version-note" : undefined}
                              onClick={() => setOxygenDisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${oxygenDisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
                            >
                              {m === "field" ? t("controls.fieldLayer.field") : m === "hexes" ? t("controls.fieldLayer.hexagons") : t("controls.fieldLayer.measurements")}
                            </button>
                          ))}
                        </div>
                        <span className="text-[10px] text-white/55 leading-snug">{t("controls.hexValueHint")}</span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.view")}</span>
                        <select
                          aria-label={t("controls.fieldLayer.view")}
                          aria-describedby={pointsOn ? "argo-recent-note" : undefined}
                          value={scaleView?.key ?? oxygenView}
                          disabled={pointsOn}
                          onChange={(e) => setOxygenView(e.target.value as "recent" | "change")}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40 disabled:opacity-60"
                        >
                          {oxygenMeta.views.map((v) => (
                            <option key={v.key} value={v.key}>
                              {t(v.key === "recent" ? "oxygen.viewRecent" : v.key === "change" ? "oxygen.viewChange" : "", { defaultValue: v.label })}
                            </option>
                          ))}
                        </select>
                        {pointsOn && (
                          <p id="argo-recent-note" className="text-[10px] text-white/55 leading-snug">{t("layers.oxygenDeox.points.recentScaleNote")}</p>
                        )}
                      </div>
                      {(() => {
                        const activeView = scaleView;
                        if (!activeView) return null;
                        return (
                          <>
                            <div className="flex flex-col gap-1">
                              <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.depth")}</span>
                              <select
                                value={oxygenDepth}
                                onChange={(e) => setOxygenDepth(Number(e.target.value))}
                                className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                              >
                                {activeView.depths.map((d) => (
                                  <option key={d} value={d}>
                                    {d === 0 ? "Surface" : `${d} m`}
                                  </option>
                                ))}
                              </select>
                            </div>
                            {(() => {
                              const stops = activeView.ramp.length
                                ? activeView.ramp.map((s) => `${s.hex} ${Math.round(s.pos * 100)}%`).join(", ")
                                : "#222, #ccc";
                              const mid = (activeView.vmin + activeView.vmax) / 2;
                              const fmt = (n: number) => (Math.abs(n) >= 100 || Number.isInteger(n) ? n.toFixed(0) : n.toFixed(1));
                              return (
                                <div className="flex flex-col gap-1 mt-1">
                                  <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.scale", { units: activeView.units })}</span>
                                  <div className="h-3 w-full rounded-sm border border-white/10" style={{ background: `linear-gradient(to right, ${stops})` }} />
                                  <div className="flex justify-between text-[10px] font-mono text-white/75">
                                    <span>{fmt(activeView.vmin)}</span>
                                    <span>{fmt(mid)}</span>
                                    <span>{fmt(activeView.vmax)}</span>
                                  </div>
                                </div>
                              );
                            })()}
                          </>
                        );
                      })()}
                      {pointsAvailable && (
                        <div className="flex flex-col gap-1 border-t border-white/10 pt-2">
                          <p id="argo-version-note" className="text-[11px] text-white/60 leading-snug">{t("layers.oxygenDeox.points.versionNote")}</p>
                          {pointsOn && (
                            <>
                              <p className="text-[11px] text-white/60">{t("layers.oxygenDeox.points.greyNote", { window: argoWindowLabel(oxygenDepth) })}</p>
                              <p className="text-[11px] text-white/60 leading-snug">{t("layers.oxygenDeox.points.cellNote", { zoom: ARGO_POINT_MIN_ZOOM })}</p>
                              {argoLoading && <p className="text-[11px] text-white/50">{t("layers.oxygenDeox.points.loading")}</p>}
                              {argoEmpty && <p className="text-[11px] text-white/60">{t("layers.oxygenDeox.points.empty")}</p>}
                              {bounds && (
                                <div className="flex items-center gap-2">
                                  <select
                                    aria-label={t("layers.oxygenDeox.points.yearFrom")}
                                    value={from}
                                    onChange={(e) => update(Number(e.target.value), to)}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <span className="text-white/50">–</span>
                                  <select
                                    aria-label={t("layers.oxygenDeox.points.yearTo")}
                                    value={to}
                                    onChange={(e) => update(from, Number(e.target.value))}
                                    className={SELECT_CLS}
                                  >
                                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                                  </select>
                                  <FilterResetLink
                                    show={argoOxygenYearRange !== null}
                                    onReset={() => setArgoOxygenYearRange(null)}
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
