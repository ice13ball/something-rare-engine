// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { WOD_DECADES, wodDecadeHex } from "../../../../utils/wodDecades";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function MementoRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    mementoGas, setMementoGas,
    mementoDisplayMode, setMementoDisplayMode,
    mementoGasFilters, toggleMementoGasFilter,
    mementoDecadeFilters, toggleMementoDecadeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="memento"
                label={t("layers.memento.toggle")}
                color="#2dd4bf"
                active={activeLayers.has("memento")}
                onToggle={() => toggle("memento")}
                onLocate={() => flyToLayer?.("memento")}
                filterActive={mementoGasFilters.size > 0 || mementoDecadeFilters.size > 0}
                expanded={expandedFilter === "memento"}
                onExpandToggle={() => toggleExpand("memento")}
                filterContent={
                  <div className="flex flex-col gap-3">
                    {/* CH₄ / N₂O gas selector (display state — not a filter Set) */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">Show gas</span>
                      <div className="flex gap-1">
                        {(["ch4", "n2o"] as const).map((g) => (
                          <button
                            key={g}
                            onClick={() => setMementoGas(g)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              mementoGas === g
                                ? "bg-teal-500 border-teal-500 text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                          >
                            {g === "ch4" ? "CH₄" : "N₂O"}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Dots / Hexagons display mode toggle */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">View</span>
                      <div className="flex gap-1">
                        {(["dots", "hexes"] as const).map((m) => (
                          <button
                            key={m}
                            onClick={() => setMementoDisplayMode(m)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              mementoDisplayMode === m
                                ? "bg-teal-500 border-teal-500 text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                          >
                            {m === "dots" ? "Dots" : "Hexagons"}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Gas-presence filter */}
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">Has gas</span>
                        {mementoGasFilters.size > 0 && (
                          <FilterResetLink
                            show
                            onReset={() => mementoGasFilters.forEach(toggleMementoGasFilter)}
                          />
                        )}
                      </div>
                      <div className="flex gap-1">
                        {(["ch4", "n2o"] as const).map((g) => {
                          const active = mementoGasFilters.size === 0 || mementoGasFilters.has(g);
                          return (
                            <button
                              key={g}
                              onClick={() => toggleMementoGasFilter(g)}
                              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                                active
                                  ? "bg-teal-600 border-teal-600 text-white"
                                  : "border-white/20 text-white/65 bg-white/5"
                              }`}
                            >
                              {g === "ch4" ? "CH₄" : "N₂O"}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    {/* Decade filter — mirroring wod-oxygen */}
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">Decade</span>
                        {mementoDecadeFilters.size > 0 && (
                          <FilterResetLink
                            show
                            onReset={() => mementoDecadeFilters.forEach(toggleMementoDecadeFilter)}
                          />
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {WOD_DECADES.map((d) => {
                          const decade = String(d);
                          const color = wodDecadeHex(d);
                          const active = mementoDecadeFilters.size === 0 || mementoDecadeFilters.has(decade);
                          return (
                            <button
                              key={decade}
                              onClick={() => toggleMementoDecadeFilter(decade)}
                              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                                active
                                  ? "border-transparent text-white"
                                  : "border-white/20 text-white/65 bg-white/5"
                              }`}
                              style={active ? { backgroundColor: color, borderColor: color } : {}}
                            >
                              {decade}s
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                }
              />
  );
}
