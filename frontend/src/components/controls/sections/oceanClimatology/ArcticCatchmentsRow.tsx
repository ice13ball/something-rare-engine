// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore, type ArcticCatchmentVariable } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function ArcticCatchmentsRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    arcticCatchmentsVariable, setArcticCatchmentsVariable,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="arctic-catchments"
                label={t("layers.arcticCatchments.toggle")}
                color="#7dd3fc"
                active={activeLayers.has("arctic-catchments")}
                onToggle={() => toggle("arctic-catchments")}
                onLocate={() => flyToLayer?.("arctic-catchments")}
                expanded={expandedFilter === "arctic-catchments"}
                onExpandToggle={() => toggleExpand("arctic-catchments")}
                filterContent={
                  <div className="flex flex-col gap-2">
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
                      <select
                        value={arcticCatchmentsVariable}
                        onChange={(e) => setArcticCatchmentsVariable(e.target.value as ArcticCatchmentVariable)}
                        className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                      >
                        <option value="ocs_mean">{t("layers.arcticCatchments.var.ocs")}</option>
                        <option value="oc_tot">{t("layers.arcticCatchments.var.octot")}</option>
                        <option value="runoff_mean">{t("layers.arcticCatchments.var.runoff")}</option>
                        <option value="pf_frac">{t("layers.arcticCatchments.var.pf")}</option>
                        <option value="t_2m_mean">{t("layers.arcticCatchments.var.temp")}</option>
                      </select>
                    </div>
                  </div>
                }
              />
  );
}
