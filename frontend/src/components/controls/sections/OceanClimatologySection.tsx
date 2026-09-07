// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import type { LayerId } from "../../../types/layers";
import { SubGroup } from "../rows";
import { WoaClimatologyRow } from "./oceanClimatology/WoaClimatologyRow";
import { OceanCarbonRow } from "./oceanClimatology/OceanCarbonRow";
import { OceanCo2SurfaceRow } from "./oceanClimatology/OceanCo2SurfaceRow";
import { WodOxygenRow } from "./oceanClimatology/WodOxygenRow";
import { MementoRow } from "./oceanClimatology/MementoRow";
import { GeotracesRow } from "./oceanClimatology/GeotracesRow";
import { MosaicSedimentRow } from "./oceanClimatology/MosaicSedimentRow";
import { MethaneSeepsRow } from "./oceanClimatology/MethaneSeepsRow";
import { OxygenDeoxRow } from "./oceanClimatology/OxygenDeoxRow";
import { ArcticRiversRow } from "./oceanClimatology/ArcticRiversRow";
import { ArcticCatchmentsRow } from "./oceanClimatology/ArcticCatchmentsRow";
import { ArcticSedimentCarbonRow } from "./oceanClimatology/ArcticSedimentCarbonRow";
import { PermafrostThawRow } from "./oceanClimatology/PermafrostThawRow";
import { SiosSvalbardRow } from "./oceanClimatology/SiosSvalbardRow";
import { SeabedSubstrateRow } from "./oceanClimatology/SeabedSubstrateRow";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
  woaMeta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null;
  oxygenMeta?: { views: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp: Array<{ pos: number; hex: string }>; depths: number[]; diverging: boolean }>; depths: number[]; attribution: string } | null;
  carbonMeta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null;
  co2Meta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }>; decades: Array<{ index: number; label: string }> } | null;
}

export function OceanClimatologySection({ expandedFilter, setExpandedFilter, toggleExpand, toggle, flyToLayer, woaMeta, oxygenMeta, carbonMeta, co2Meta }: Props) {
  const { t } = useTranslation(["panels", "common"]);

  return (
            <SubGroup label={t("controls.subgroups.oceanClimatology")} storageKey="sea_woa">
              <WoaClimatologyRow
                expandedFilter={expandedFilter}
                setExpandedFilter={setExpandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                woaMeta={woaMeta}
              />

              <OceanCarbonRow
                expandedFilter={expandedFilter}
                setExpandedFilter={setExpandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                carbonMeta={carbonMeta}
              />

              <OceanCo2SurfaceRow
                expandedFilter={expandedFilter}
                setExpandedFilter={setExpandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                co2Meta={co2Meta}
              />

              <WodOxygenRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <MementoRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <GeotracesRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <MosaicSedimentRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <MethaneSeepsRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <OxygenDeoxRow
                expandedFilter={expandedFilter}
                setExpandedFilter={setExpandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                oxygenMeta={oxygenMeta}
              />
              <ArcticRiversRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <ArcticCatchmentsRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <ArcticSedimentCarbonRow
                expandedFilter={expandedFilter}
                setExpandedFilter={setExpandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <PermafrostThawRow
                expandedFilter={expandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <SiosSvalbardRow
                toggle={toggle}
                flyToLayer={flyToLayer}
              />

              <SeabedSubstrateRow
                expandedFilter={expandedFilter}
                setExpandedFilter={setExpandedFilter}
                toggleExpand={toggleExpand}
                toggle={toggle}
                flyToLayer={flyToLayer}
              />
            </SubGroup>
  );
}
