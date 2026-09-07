// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow } from "../../rows";

interface Props {
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function SiosSvalbardRow({ toggle, flyToLayer }: Props) {
  const { activeLayers } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="sios-svalbard"
                label={t("layers.siosSvalbard.toggle")}
                color="#a78bfa"
                active={activeLayers.has("sios-svalbard")}
                onToggle={() => toggle("sios-svalbard")}
                onLocate={() => flyToLayer?.("sios-svalbard")}
              />
  );
}
