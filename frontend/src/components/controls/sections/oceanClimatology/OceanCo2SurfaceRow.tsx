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
  co2Meta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }>; decades: Array<{ index: number; label: string }> } | null;
}

export function OceanCo2SurfaceRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, co2Meta }: Props) {
  const {
    activeLayers,
    co2Variable, setCo2Variable,
    co2Decade, setCo2Decade,
    co2DisplayMode, setCo2DisplayMode,
  } = useMapStore();

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
                filterContent={
                  co2Meta ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
                        <div className="flex gap-1">
                          {(["field", "hexes"] as const).map((m) => (
                            <button
                              key={m}
                              onClick={() => setCo2DisplayMode(m)}
                              className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${co2DisplayMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
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
                    </div>
                  ) : null
                }
              />
  );
}
