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
  flyToLayer: ((id: LayerId) => void) | null;
}

export function SeabedSubstrateRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    seabedDisplayMode, setSeabedDisplayMode,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  return (
              <LayerRow
                id="seabed-substrate"
                label={t("layers.seabedSubstrate.toggle")}
                color="#9a6b3a"
                active={activeLayers.has("seabed-substrate")}
                onToggle={() => toggleFieldLayer("seabed-substrate")}
                onLocate={() => flyToLayer?.("seabed-substrate")}
                expanded={expandedFilter === "seabed-substrate"}
                onExpandToggle={() => toggleExpand("seabed-substrate")}
                filterContent={
                  <div className="flex flex-col gap-2">
                    <span className="text-[11px] uppercase tracking-wide text-white/50">
                      {t("controls.fieldLayer.display")}
                    </span>
                    <div className="flex gap-1">
                      {(["field", "hexes"] as const).map((m) => (
                        <button key={m} onClick={() => setSeabedDisplayMode(m)}
                          className={`px-2 py-1 rounded text-xs border ${seabedDisplayMode === m
                            ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300"
                            : "bg-white/5 border-white/10 text-white/60"}`}>
                          {m === "field" ? t("controls.fieldLayer.field") : t("controls.fieldLayer.hexagons")}
                        </button>
                      ))}
                    </div>
                  </div>
                }
              />
  );
}
