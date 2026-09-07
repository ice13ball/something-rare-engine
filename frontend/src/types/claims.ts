// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { Feature, FeatureCollection, MultiPolygon } from "geojson";

export type ResourceType =
  | "Polymetallic Nodules"
  | "Polymetallic Sulphides"
  | "Cobalt-rich Ferromanganese Crusts";

export interface ClaimProperties {
  id: string;
  contractor_name: string;
  resource_type: ResourceType;
  area_km2: number | null;
  expiry_date: string | null;
  region: string | null;
  isa_id: string | null;
  is_high_risk: boolean;
  // Maritime boundary enrichment (may be null if enrichment hasn't run yet)
  jurisdiction_text: string | null;
  nearest_eez_country: string | null;
  nearest_eez_dist_km: number | null;
  nearest_unesco_site: string | null;
  nearest_unesco_dist_km: number | null;
}

export type ClaimFeature = Feature<MultiPolygon, ClaimProperties>;
export type ClaimFeatureCollection = FeatureCollection<MultiPolygon, ClaimProperties>;
