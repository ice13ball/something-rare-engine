// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { MOSAIC_VARS, MOSAIC_DECADES, mosaicDecadeHex, MOSAIC_UNDATED_HEX } from "../../../../utils/mosaicVars";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function MosaicSedimentRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    mosaicVariable, setMosaicVariable,
    mosaicDisplayMode, setMosaicDisplayMode,
    mosaicDecadeFilters, toggleMosaicDecadeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common", "legend"]);

  return (
              <LayerRow
                id="mosaic-sediment"
                label={t("layers.mosaicSediment.toggle")}
                color="#22c55e"
                active={activeLayers.has("mosaic-sediment")}
                onToggle={() => toggle("mosaic-sediment")}
                onLocate={() => flyToLayer?.("mosaic-sediment")}
                filterActive={mosaicDecadeFilters.size > 0}
                expanded={expandedFilter === "mosaic-sediment"}
                onExpandToggle={() => toggleExpand("mosaic-sediment")}
                filterContent={
                  <div className="flex flex-col gap-3">
                    {/* Variable selector (display state — not a filter Set) */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("layers.mosaicSediment.variableLabel")}</span>
                      <div className="flex gap-1 flex-wrap">
                        {MOSAIC_VARS.map((v) => (
                          <button
                            key={v.key}
                            onClick={() => setMosaicVariable(v.key)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              mosaicVariable === v.key
                                ? "bg-emerald-500 border-emerald-500 text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                          >
                            {t(`layers.mosaicSediment.variables.${v.key}`)}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Dots / Hexagons display mode toggle */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("layers.mosaicSediment.view")}</span>
                      <div className="flex gap-1">
                        {(["dots", "hexes"] as const).map((m) => (
                          <button
                            key={m}
                            onClick={() => setMosaicDisplayMode(m)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              mosaicDisplayMode === m
                                ? "bg-emerald-500 border-emerald-500 text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                          >
                            {m === "dots" ? t("layers.mosaicSediment.dots") : t("layers.mosaicSediment.hexes")}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Decade filter — chips covering the MOSAIC compilation range */}
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("layers.mosaicSediment.decade")}</span>
                        {mosaicDecadeFilters.size > 0 && (
                          <FilterResetLink
                            show
                            onReset={() => mosaicDecadeFilters.forEach(toggleMosaicDecadeFilter)}
                          />
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {MOSAIC_DECADES.map((d) => {
                          const decade = String(d);
                          const color = mosaicDecadeHex(d);
                          const active = mosaicDecadeFilters.size === 0 || mosaicDecadeFilters.has(decade);
                          return (
                            <button
                              key={decade}
                              onClick={() => toggleMosaicDecadeFilter(decade)}
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
                        {(() => {
                          const active = mosaicDecadeFilters.size === 0 || mosaicDecadeFilters.has("undated");
                          return (
                            <button
                              key="undated"
                              onClick={() => toggleMosaicDecadeFilter("undated")}
                              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                                active
                                  ? "border-transparent text-white"
                                  : "border-white/20 text-white/65 bg-white/5"
                              }`}
                              style={active ? { backgroundColor: MOSAIC_UNDATED_HEX, borderColor: MOSAIC_UNDATED_HEX } : {}}
                            >
                              {t("sampleDate.undatedSuffix", { ns: "legend" })}
                            </button>
                          );
                        })()}
                      </div>
                    </div>
                  </div>
                }
              />
  );
}
