// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { LayerRow } from "../rows";

interface Props {
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

/** IMOS zooplankton abundance (AusCPR + NRS). No filters: the default view is the total of copepods per m³. */
export function ImosZooplanktonRow({ toggle, flyToLayer }: Props) {
  const activeLayers = useMapStore((s) => s.activeLayers);
  const { t } = useTranslation(["panels", "common"]);
  return (
    <LayerRow
      id="imos-zooplankton"
      label={t("layers.imosZooplankton.toggle" as any)}
      color="#c026d3"
      active={activeLayers.has("imos-zooplankton")}
      onToggle={() => toggle("imos-zooplankton")}
      onLocate={() => flyToLayer?.("imos-zooplankton")}
    />
  );
}
