// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  oxygenMeta?: { views: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp: Array<{ pos: number; hex: string }>; depths: number[]; diverging: boolean }>; depths: number[]; attribution: string } | null;
}

export function OxygenDeoxRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, oxygenMeta }: Props) {
  const {
    activeLayers,
    oxygenView, setOxygenView,
    oxygenDepth, setOxygenDepth,
    oxygenDisplayMode, setOxygenDisplayMode,
  } = useMapStore();

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
                filterContent={
                  oxygenMeta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              onClick={() => setOxygenDisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${oxygenDisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
                            >
                              {m === "field" ? t("controls.fieldLayer.field") : t("controls.fieldLayer.hexagons")}
                            </button>
                          ))}
                        </div>
                        <span className="text-[10px] text-white/55 leading-snug">{t("controls.hexValueHint")}</span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.view")}</span>
                        <select
                          value={oxygenView}
                          onChange={(e) => setOxygenView(e.target.value as "recent" | "change")}
                          className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                        >
                          {oxygenMeta.views.map((v) => (
                            <option key={v.key} value={v.key}>
                              {v.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      {(() => {
                        const activeView = oxygenMeta.views.find((v) => v.key === oxygenView);
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
                    </div>
                  ) : null
                }
              />
  );
}
