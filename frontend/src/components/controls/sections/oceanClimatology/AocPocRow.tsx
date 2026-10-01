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

/** AOC2025 POC, Greenland Sea. */
export function AocPocRow({ toggle, flyToLayer }: Props) {
  const activeLayers = useMapStore((s) => s.activeLayers);
  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="greenland-sea-poc-aoc2025"
                label={t("layers.greenlandSeaPocAoc2025.toggle" as any)}
                color="#f59e0b"
                active={activeLayers.has("greenland-sea-poc-aoc2025")}
                onToggle={() => toggle("greenland-sea-poc-aoc2025")}
                onLocate={() => flyToLayer?.("greenland-sea-poc-aoc2025")}
              />
  );
}
