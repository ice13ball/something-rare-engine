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

/** In situ Primary Production, Svalbard Fjords. */
export function SvalbardFjordsPpRow({ toggle, flyToLayer }: Props) {
  const activeLayers = useMapStore((s) => s.activeLayers);
  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="svalbard-fjords-primary-production"
                label={t("layers.svalbardFjordsPrimaryProduction.toggle" as any)}
                color="#6366f1"
                active={activeLayers.has("svalbard-fjords-primary-production")}
                onToggle={() => toggle("svalbard-fjords-primary-production")}
                onLocate={() => flyToLayer?.("svalbard-fjords-primary-production")}
              />
  );
}
