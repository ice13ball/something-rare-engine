// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { centroid } from "@turf/turf";
import type { FeatureCollection, Feature } from "geojson";
import type { LayerId } from "../types/layers";
import { useMapStore } from "../store/mapStore";
import type { AssertComplete, AssertDisjoint } from "../types/layerRegistry";
import { isActiveVentStatus } from "../utils/ventStatus";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/* ── Per-layer search configuration ──────────────────────────────────────── */

interface SearchConfig {
  key: string;
  layerId: LayerId;
  label: string;
  fields: string[];
  display: (p: Record<string, unknown>) => { primary: string; secondary: string };
  color: string;
}

/**
 * Layers deliberately absent from global search, grouped by why.
 *
 * Adding a searchable layer and forgetting SEARCH_CONFIGS used to make it
 * silently unfindable; now the build fails unless the layer is either
 * configured above or listed here with a reason.
 */
const NO_SEARCH = [
  // Continuous fields and rasters: sampled from a grid, raster surface or
  // density aggregate, so a "feature" here is a probe point, pixel or cell —
  // not a discrete named thing. Verified per-id against Map3D.tsx: each of
  // these either renders a BitmapLayer raster tile or reads back only
  // lat/lon/depth/value (or a grid-cell stat like risk_index/point_count)
  // on click, with no name-shaped field anywhere in its properties.
  "bathymetry",
  "ocean-currents",
  "woa-climatology",
  "oxygen-deox",
  "ocean-carbon",
  "ocean-co2-surface",
  "marine-carbon",
  "seabed-substrate",
  "vme-suitability",
  "ocean-acidification",
  "coral-acid-exposure",
  "cumulative-human-impact",
  "forest-loss",
  "surface-water",
  "carbon-flux",
  "soil-carbon",
  "noise-risk",
  "monitoring-density",
  // Server-rendered tiles (vector MVT or point-queried raster): the client
  // only ever holds the current viewport, never the complete feature list
  // search needs to filter against — even where the underlying record DOES
  // carry a name. offshore-activities ships `name`, arctic_catchments has
  // `name` in Postgres (fetched only one row at a time via /by-point,
  // never as a list), and mosaic-sediment cores have `core_name` (fetched
  // only after a click, never as the upfront list search would need).
  "water-risk",
  "wod-oxygen",
  "offshore-activities",
  "mosaic-sediment",
  "arctic-catchments",
  // The client DOES hold the complete feature set for these (fetched once,
  // in full) — the gap is upstream: nothing in the data functions as a name.
  // Checked against production 2026-09-11: apeis ships AreaKM2/Remarks/
  // Status/arcgis_id only (the panel's `p.NAME` fallback is defensive code
  // for a field this source doesn't actually send); mining-footprints ships
  // area_km2/country/ftype/source only.
  "mining-footprints",
  "apeis",
] as const satisfies readonly LayerId[];

const SEARCH_CONFIGS = [
  {
    key: "claims", layerId: "contracts", label: "Mining Concessions",
    fields: ["isa_id", "contractor_name", "resource_type", "nearest_eez_country"],
    display: p => ({ primary: String(p.contractor_name ?? p.isa_id ?? ""), secondary: String(p.isa_id ? `${p.isa_id} · ${p.resource_type ?? ""}` : p.resource_type ?? "") }),
    color: "#00f2ff",
  },
  {
    key: "reserved", layerId: "reserved-areas", label: "Reserved Areas",
    fields: ["contractor_name"],
    display: p => ({ primary: String(p.contractor_name ?? ""), secondary: "Reserved Area" }),
    color: "#00ff9f",
  },
  {
    key: "relinquished", layerId: "relinquished-areas", label: "Relinquished",
    fields: ["contractor_name"],
    display: p => ({ primary: String(p.contractor_name ?? ""), secondary: "Relinquished" }),
    color: "#ff4466",
  },
  {
    key: "vents", layerId: "hydrothermal-vents", label: "Hydrothermal Vents",
    fields: ["name", "name_aliases", "status", "region", "ocean"],
    display: p => ({
      primary: String(p.name ?? ""),
      secondary: [p.status, p.region, p.ocean ? `${p.ocean} Ocean` : ""].filter(Boolean).join(" · "),
    }),
    color: "#ff4400",
  },
  {
    key: "argo", layerId: "argo", label: "Argo Floats",
    fields: ["platform_id", "mining_zone"],
    display: p => ({ primary: `Float ${p.platform_id ?? ""}`, secondary: String(p.mining_zone ?? "Open ocean") }),
    color: "#00e5ff",
  },
  {
    key: "eez", layerId: "eez", label: "EEZ Boundaries",
    fields: ["geoname", "sovereign1"],
    display: p => ({ primary: String(p.geoname ?? ""), secondary: String(p.sovereign1 ?? "") }),
    color: "#ffd700",
  },
  {
    key: "protectedSites", layerId: "protected-marine-sites", label: "UNESCO Sites",
    fields: ["name", "country"],
    display: p => ({ primary: String(p.name ?? ""), secondary: String(p.country ?? "") }),
    color: "#00e676",
  },
  {
    key: "hotspots", layerId: "biodiversity-hotspots", label: "Species",
    fields: ["scientific_name", "vernacular_name", "valid_name"],
    display: p => ({
      primary: String(p.scientific_name ?? ""),
      secondary: String(
        p.valid_name && p.valid_name !== p.scientific_name
          ? `→ ${p.valid_name}`
          : (p.vernacular_name || p.iucn_category || "")
      ),
    }),
    color: "#ff9f00",
  },
  {
    key: "seamounts", layerId: "seamounts", label: "Seamounts",
    fields: ["peak_id"],
    display: p => ({
      primary: `Seamount #${p.peak_id ?? ""}`,
      secondary: `${p.height_m ?? "?"}m tall · ${p.summit_depth_m ?? "?"}m depth${p.in_concession ? " · In concession" : ""}`,
    }),
    color: "#7eb8f7",
  },
  {
    key: "oceansites", layerId: "oceansites", label: "OceanSITES Moorings",
    fields: ["ref", "name", "network"],
    display: p => ({ primary: String(p.name ?? p.ref ?? ""), secondary: String(p.network ?? p.ref ?? "") }),
    color: "#00cfff",
  },
  {
    key: "onc", layerId: "onc", label: "ONC Observatories",
    fields: ["location_code", "name"],
    display: p => ({ primary: String(p.name ?? ""), secondary: String(p.location_code ?? "") }),
    color: "#4db8a4",
  },
  {
    key: "chess", layerId: "chess", label: "Chemosynthetic Sites",
    fields: ["locality"],
    display: p => ({
      primary: String(p.locality ?? ""),
      secondary: "",
    }),
    color: "#00c896",
  },
  {
    key: "cables", layerId: "submarine-cables", label: "Submarine Cables",
    fields: ["name", "status", "location"],
    display: p => ({ primary: String(p.name ?? ""), secondary: [p.status, p.inst_year ? `${p.inst_year}` : ""].filter(Boolean).join(" · ") }),
    color: "#fbbf24",
  },
  {
    key: "oncInstruments", layerId: "onc-instruments", label: "ONC Instruments",
    fields: ["device_name", "device_code", "device_category", "location_name", "site_name"],
    display: p => ({
      primary: String(p.device_name ?? p.device_code ?? ""),
      secondary: [p.device_category, p.location_name].filter(Boolean).join(" · "),
    }),
    color: "#a78bfa",
  },
  {
    key: "ports", layerId: "ports", label: "Port Locations",
    fields: ["city", "country", "state"],
    display: p => ({ primary: String(p.city ?? ""), secondary: [p.state, p.country].filter(Boolean).join(", ") }),
    color: "#60a5fa",
  },
  {
    key: "tectonic", layerId: "tectonic-plates", label: "Tectonic Boundaries",
    fields: ["Name", "PlateA", "PlateB", "Type"],
    display: p => ({ primary: `${p.PlateA ?? ""}–${p.PlateB ?? ""} boundary`, secondary: [p.Type, p.Name].filter(Boolean).join(" · ") }),
    color: "#c9956e",
  },
  {
    key: "aisLive",
    layerId: "ais-live",
    label: "Live Vessels (AIS)",
    fields: ["name", "mmsi", "imo", "callsign", "flag", "destination"],
    display: (p: Record<string, unknown>) => ({
      primary: String(p.name ?? `MMSI ${p.mmsi}`),
      secondary: [
        p.flag ? String(p.flag) : "",
        p.length_m != null ? `${p.length_m} m` : "",
        p.destination ? `→ ${String(p.destination)}` : "",
      ].filter(Boolean).join(" · "),
    }),
    color: "#22d3ee",
  },
  {
    key: "vessels",
    layerId: "vessel-events",
    label: "Dark Vessels",
    fields: ["vessel_name", "matched_mmsi", "sar_detection_id", "contractor_name", "contractor_short"],
    display: (p: Record<string, unknown>) => ({
      primary: String(p.vessel_name ?? (p.classification === "dark" ? "Dark vessel (no AIS)" : `MMSI ${p.matched_mmsi ?? ""}`)),
      secondary: [
        p.classification ? String(p.classification) : "",
        p.contractor_short ?? p.contractor_name ?? "",
      ].filter(Boolean).join(" · "),
    }),
    color: "#f59e0b",
  },
  // Land layers
  {
    key: "fires", layerId: "fires", label: "Active Fires",
    fields: ["acq_date", "instrument"],
    display: p => ({ primary: `Fire ${String(p.acq_date ?? "")}`, secondary: [p.confidence ? `${p.confidence} conf` : "", p.instrument].filter(Boolean).join(" · ") }),
    color: "#ff6b00",
  },
  {
    key: "tailings", layerId: "tailings", label: "Tailings Dams",
    fields: ["dam_name", "mine_name", "country"],
    display: p => ({ primary: String(p.dam_name ?? p.mine_name ?? ""), secondary: String(p.country ?? "") }),
    color: "#dc2626",
  },
  {
    key: "airQuality", layerId: "air-quality", label: "Air Quality Stations",
    fields: ["name", "city", "country"],
    display: p => ({ primary: String(p.name ?? p.city ?? ""), secondary: String(p.country ?? "") }),
    color: "#7c9bb5",
  },
  {
    key: "landslides", layerId: "landslides", label: "Landslide Catalog",
    fields: ["location", "country", "event_type"],
    display: p => ({ primary: String(p.location ?? p.event_type ?? ""), secondary: [p.event_date, p.country].filter(Boolean).join(" · ") }),
    color: "#92400e",
  },
  {
    key: "dams", layerId: "dams", label: "Global Dams",
    fields: ["dam_name", "river", "country"],
    display: p => ({ primary: String(p.dam_name ?? ""), secondary: [p.river, p.country].filter(Boolean).join(" · ") }),
    color: "#5e8ab4",
  },
  {
    key: "deepdataStations", layerId: "deepdata-stations", label: "Contractor Sampling Stations",
    fields: ["location_id", "event_id_raw", "contractor_code", "sampling_protocol"],
    display: p => ({
      primary: String(p.location_id ?? p.event_id_raw ?? p.station_id ?? ""),
      secondary: [p.contractor_code, p.sampling_protocol].filter(Boolean).join(" · "),
    }),
    color: "#f472b6",
  },
  {
    key: "hydrophones", layerId: "hydrophone-stations", label: "Hydrophone Stations",
    fields: ["name", "station_id", "operator", "source"],
    display: p => ({
      primary: String(p.name ?? p.station_id ?? ""),
      secondary: [p.source, p.operator].filter(Boolean).join(" · "),
    }),
    color: "#22d3ee",
  },
  {
    key: "marhys", layerId: "marhys", label: "Vent Fluid Chemistry",
    // ⛔ `sample_id` is searchable but is NOT an identifier — 6788 rows carry
    // 6108 distinct labels. Searching it is fine; routing on it is not, which
    // is why the openable registry keys on `source_row` instead.
    fields: ["sample_id", "vent_site", "vent_area", "region_large"],
    display: p => ({
      primary: String(p.sample_id ?? p.vent_site ?? p.vent_area ?? ""),
      secondary: [p.vent_area, p.region_large, p.date_raw].filter(Boolean).join(" · "),
    }),
    color: "#fb923c",
  },
  {
    key: "arcticRivers", layerId: "arctic-rivers", label: "Arctic Rivers",
    fields: ["river_name", "site_label", "source"],
    display: p => ({
      primary: `${String(p.river_name ?? "")} River`,
      secondary: String(p.site_label ?? p.source ?? ""),
    }),
    color: "#38bdf8",
  },
  {
    key: "memento", layerId: "memento", label: "CH₄/N₂O Casts (MEMENTO)",
    fields: ["set_name", "cruise", "cast_id"],
    display: p => ({
      primary: String(p.set_name ?? p.cruise ?? p.cast_id ?? ""),
      secondary: [p.cruise, p.cast_id].filter(Boolean).join(" · "),
    }),
    color: "#2dd4bf",
  },
  {
    key: "geotraces", layerId: "geotraces", label: "Trace Metals (GEOTRACES)",
    fields: ["cruise", "station", "station_id"],
    display: p => ({
      primary: String(p.cruise ?? p.station ?? p.station_id ?? ""),
      secondary: [p.station, p.station_id].filter(Boolean).join(" · "),
    }),
    color: "#f97316",
  },
  {
    key: "methaneSeeps",
    layerId: "methane-seeps",
    label: "Methane Seeps",
    fields: ["ext_id", "primary_type", "source_ref"],
    display: p => ({
      primary: `Seep ${String(p.ext_id ?? "")}`,
      secondary: String(p.primary_type ?? p.source_ref ?? ""),
    }),
    color: "#ef4444",
  },
  {
    key: "permafrostThaw",
    layerId: "permafrost-thaw",
    label: "Permafrost Thaw",
    fields: ["feature_name", "feature_type", "authors"],
    display: p => ({
      primary: String(p.feature_name || p.feature_type || "Thaw feature"),
      secondary: String(p.feature_category ?? p.thaw_type ?? ""),
    }),
    color: "#38bdf8",
  },
  {
    key: "sios",
    layerId: "sios-svalbard",
    label: "SIOS Svalbard",
    fields: ["title", "platform_long", "keywords"],
    display: p => ({
      primary:   String(p.title         ?? ""),
      secondary: String(p.platform_long ?? ""),
    }),
    color: "#5ec8d8",
  },
  {
    key: "arcticSedimentCarbon", layerId: "arctic-sediment-carbon", label: "Arctic Sediment Carbon",
    fields: ["station", "expedition"],
    display: p => ({ primary: `Station ${String(p.station ?? p.station_id ?? "")}`,
                     secondary: String(p.expedition ?? "") }),
    color: "#d4a373",
  },
] as const satisfies readonly SearchConfig[];

export const _searchIsComplete: AssertComplete<
  (typeof SEARCH_CONFIGS)[number]["layerId"],
  (typeof NO_SEARCH)[number]
> = true;

// Completeness alone would pass even if a layer sat in BOTH SEARCH_CONFIGS and
// NO_SEARCH — e.g. someone silencing a completeness error by adding a working,
// searchable layer to the opt-out list. Disjointness catches that lie.
export const _searchIsDisjoint: AssertDisjoint<
  (typeof SEARCH_CONFIGS)[number]["layerId"],
  (typeof NO_SEARCH)[number]
> = true;

// Maps logical LayerId → deck.gl layer ID that PanelContent dispatches on.
// Only entries where they differ are needed.
const DECK_LAYER_ID: Partial<Record<string, (p: Record<string, unknown>) => string>> = {
  "contracts":           () => "mining-contracts-mvt",
  "hydrothermal-vents":  (p) => isActiveVentStatus(p.status) ? "hydrothermal-vents-active" : "hydrothermal-vents-inactive",
  "argo":                () => "argo-floats-3d",
  "tectonic-plates":     () => "tectonic-plates-boundaries",
  "offshore-activities": () => "offshore-activities-mvt",
  "arctic-sediment-carbon": () => "arctic-sediment-carbon-stations",
};

/* ── Types ───────────────────────────────────────────────────────────────── */

interface SearchResult {
  layerId: LayerId;
  label: string;
  color: string;
  primary: string;
  secondary: string;
  coords: [number, number] | null;
  featureId: string | number;
  properties: Record<string, unknown>;
  isCoordinate?: boolean;
  isServerSpecies?: boolean;
}

export interface SearchBarProps {
  dataRef: React.RefObject<Record<string, FeatureCollection | null>>;
  dataVersion: number;
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function getCoords(feature: Feature): [number, number] | null {
  const g = feature.geometry;
  if (!g) return null;
  if (g.type === "Point") return g.coordinates as [number, number];
  try {
    const c = centroid(feature as Parameters<typeof centroid>[0]);
    return c.geometry.coordinates as [number, number];
  } catch {
    return null;
  }
}

/**
 * ⚠️ THIS CHAIN IS A HAND-COPIED TWIN of `ID_CHAIN` in `types/openableRegistry.ts`,
 * and on 2026-09-23 the two had already drifted: `source_row` was added there for
 * MARHYS and missed here, so selecting a MARHYS sample from search produced a
 * share link carrying `["marhys", ""]` — an empty id that reopens nothing. The
 * failure is silent: the camera still flies to the right spot, so nothing looks
 * wrong until someone follows the link. Keep the two lists in the same order.
 */
export function featureId(p: Record<string, unknown>): string | number {
  return (p.mmsi ?? p.vessel_id ?? p.event_id ?? p.isa_id ?? p.id ?? p.platform_id ?? p.peak_id ?? p.mrgid ?? p.site_id ?? p.device_id ?? p.device_code ?? p.city ?? p.dam_name ?? p.site_name ?? p.station_id ?? p.cast_id ?? p.ext_id ?? p.metadata_id ?? p.unique_id ?? p.source_row ?? "") as string | number;
}

/**
 * Parse a free-text coordinate into GeoJSON [lon, lat], or null if the query
 * isn't a coordinate. Accepts forms like:
 *   "46.97°N,154.55°E"  "46.97 N 154.55 E"  "-46.97, 154.55"  "154.55E 46.97N"
 * Hemisphere letters (N/S→lat, E/W→lon) win regardless of token order; with no
 * letters it assumes lat,lon order. Ranges are validated.
 */
function parseCoordinates(raw: string): [number, number] | null {
  const s = raw.replace(/[°º]/g, " ").replace(/,/g, " ").trim();
  if (!/\d/.test(s)) return null;
  const matches = [...s.matchAll(/(-?\d{1,3}(?:\.\d+)?)\s*([NSEWnsew])?/g)];
  const tokens = matches
    .filter(m => m[0].trim() !== "")
    .map(m => ({ value: parseFloat(m[1]), hemi: m[2] ? m[2].toUpperCase() : null }));
  if (tokens.length !== 2) return null;

  let lat: number | null = null;
  let lon: number | null = null;
  for (const tk of tokens) {
    const v = tk.hemi === "S" || tk.hemi === "W" ? -Math.abs(tk.value)
            : tk.hemi === "N" || tk.hemi === "E" ?  Math.abs(tk.value)
            : tk.value;
    if (tk.hemi === "N" || tk.hemi === "S") lat = v;
    else if (tk.hemi === "E" || tk.hemi === "W") lon = v;
  }
  // No hemispheres at all → assume lat,lon order.
  if (lat === null && lon === null) { lat = tokens[0].value; lon = tokens[1].value; }
  // Exactly one hemisphere is ambiguous — refuse rather than guess.
  if (lat === null || lon === null) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return [lon, lat];
}

function fmtLatLon(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? "E" : "W"}`;
}

function search(
  data: Record<string, FeatureCollection | null>,
  query: string,
  enabledLayerIds: Set<string> | null,
  maxPerGroup = 5,
): SearchResult[] {
  const q = query.toLowerCase().trim();
  if (q.length < 2) return [];
  const results: SearchResult[] = [];

  for (const cfg of SEARCH_CONFIGS) {
    if (enabledLayerIds && !enabledLayerIds.has(cfg.layerId)) continue; // hide disabled layers from search
    const fc = data[cfg.key];
    if (!fc?.features) continue;
    let count = 0;
    for (const f of fc.features) {
      if (count >= maxPerGroup) break;
      const props = (f.properties ?? {}) as Record<string, unknown>;
      const match = cfg.fields.some(field => {
        const val = props[field];
        return val != null && String(val).toLowerCase().includes(q);
      });
      if (!match) continue;
      const { primary, secondary } = cfg.display(props);
      results.push({
        layerId: cfg.layerId,
        label: cfg.label,
        color: cfg.color,
        primary,
        secondary,
        coords: getCoords(f),
        featureId: featureId(props),
        properties: props,
      });
      count++;
    }
  }
  return results;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export function SearchBar({ dataRef, dataVersion }: SearchBarProps) {
  const { t } = useTranslation("common");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const flyTo = useMapStore(s => s.flyTo);
  const setSelectedFeature = useMapStore(s => s.setSelectedFeature);
  const activeLayers = useMapStore(s => s.activeLayers);
  const toggleLayer = useMapStore(s => s.toggleLayer);
  const enabledLayerIds = useMapStore((s) => s.enabledLayerIds);

  // Debounced search
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 200);
    return () => clearTimeout(t);
  }, [query]);

  // Server-side species search — the biodiversity-hotspots layer is ~700K
  // occurrences fetched per-viewport-tile, so the client only holds a viewport
  // sample. Name search must hit the DB to find a species anywhere on the globe.
  const [speciesResults, setSpeciesResults] = useState<SearchResult[]>([]);
  useEffect(() => {
    const q = debouncedQuery.trim();
    if (q.length < 2 || parseCoordinates(q)) { setSpeciesResults([]); return; }
    let cancelled = false;
    fetch(`${API}/api/v1/search/species?q=${encodeURIComponent(q)}`)
      .then(r => (r.ok ? r.json() : []))
      .then((rows: Array<Record<string, unknown> & { scientific_name: string; vernacular_name: string | null; iucn_category: string | null; lat: number; lon: number }>) => {
        if (cancelled) return;
        setSpeciesResults(
          rows.map(s => ({
            layerId: "biodiversity-hotspots" as LayerId,
            label: "Species",
            color: "#ff9f00",
            primary: s.scientific_name,
            secondary: s.vernacular_name || s.iucn_category || "",
            coords: [s.lon, s.lat] as [number, number],
            featureId: s.scientific_name,
            // Full row → BiodiversityPanel renders a complete popup on select.
            properties: { ...s },
            isServerSpecies: true,
          })),
        );
      })
      .catch(() => { if (!cancelled) setSpeciesResults([]); });
    return () => { cancelled = true; };
  }, [debouncedQuery]);

  const results = useMemo(() => {
    const base = search(dataRef.current ?? {}, debouncedQuery, enabledLayerIds);
    // Drop server species already present in the loaded-viewport client results.
    const seen = new Set(
      base.filter(r => r.layerId === "biodiversity-hotspots").map(r => String(r.primary).toLowerCase()),
    );
    const species = speciesResults.filter(r => !seen.has(String(r.primary).toLowerCase()));
    const coord = parseCoordinates(debouncedQuery);
    const coordResults: SearchResult[] = coord
      ? [{
          layerId: "" as LayerId,
          label: t("search.coordinateLabel"),
          color: "#22d3ee",
          primary: fmtLatLon(coord[1], coord[0]),
          secondary: t("search.coordinateAction"),
          coords: coord,
          featureId: "coordinate",
          properties: {},
          isCoordinate: true,
        }]
      : [];
    return [...coordResults, ...base, ...species];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery, dataVersion, speciesResults, t, enabledLayerIds]);

  // Reset highlight when results change
  useEffect(() => setHighlight(0), [results]);

  // Ctrl+K / Cmd+K to focus
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectResult = useCallback(
    (r: SearchResult) => {
      setOpen(false);
      setQuery("");
      if (!r.coords) return;
      // Coordinate jump: just fly there — no layer to toggle, no popup to open.
      if (r.isCoordinate) {
        flyTo?.(r.coords[0], r.coords[1]);
        return;
      }
      // Server species: enable the hotspots layer + fly to a representative
      // occurrence, then open the popup. The DetailPanel renders purely from
      // the passed properties (a floating panel, not anchored to a loaded dot),
      // so the full record from /v1/search/species drives a complete panel.
      if (r.isServerSpecies) {
        if (!activeLayers.has(r.layerId)) toggleLayer(r.layerId);
        flyTo?.(r.coords[0], r.coords[1]);
        setTimeout(() => {
          setSelectedFeature({
            id: r.featureId,
            layer: "biodiversity-hotspots",
            properties: r.properties,
          });
        }, 800);
        return;
      }
      // Ensure layer is active
      if (!activeLayers.has(r.layerId)) toggleLayer(r.layerId);
      // Fly to the feature
      flyTo?.(r.coords[0], r.coords[1]);
      // Open popup after fly animation settles
      setTimeout(() => {
        const deckLayer = DECK_LAYER_ID[r.layerId]?.(r.properties) ?? r.layerId;
        setSelectedFeature({
          id: r.featureId,
          layer: deckLayer,
          properties: r.properties,
        });
      }, 800);
    },
    [flyTo, setSelectedFeature, activeLayers, toggleLayer],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); inputRef.current?.blur(); }
    if (e.key === "ArrowDown") { e.preventDefault(); setHighlight(h => Math.min(h + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)); }
    if (e.key === "Enter" && results[highlight]) { selectResult(results[highlight]); }
  };

  // Group results by label for visual separation
  const grouped = useMemo(() => {
    const groups: { label: string; items: (SearchResult & { globalIdx: number })[] }[] = [];
    let idx = 0;
    const seen = new Map<string, (typeof groups)[0]>();
    for (const r of results) {
      let group = seen.get(r.label);
      if (!group) {
        group = { label: r.label, items: [] };
        groups.push(group);
        seen.set(r.label, group);
      }
      group.items.push({ ...r, globalIdx: idx++ });
    }
    return groups;
  }, [results]);

  const showResults = open && debouncedQuery.length >= 2;
  const [mobileExpanded, setMobileExpanded] = useState(false);
  const [layersPanelOpen, setLayersPanelOpen] = useState(false);

  // Detect layers panel open/close to hide the mobile search icon behind it
  useEffect(() => {
    const check = () => setLayersPanelOpen(!!document.querySelector('[data-panel="layers"]'));
    const obs = new MutationObserver(check);
    obs.observe(document.body, { childList: true, subtree: true });
    check();
    return () => obs.disconnect();
  }, []);

  // Close mobile search when clicking outside
  useEffect(() => {
    if (!mobileExpanded) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setMobileExpanded(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [mobileExpanded]);

  return (
    <>
      {/* Mobile search icon — visible only below sm, hidden when expanded or layers panel open */}
      {!mobileExpanded && !layersPanelOpen && (
        <button
          onClick={() => { setMobileExpanded(true); setTimeout(() => inputRef.current?.focus(), 100); }}
          className="fixed bottom-4 left-1/2 ml-1.5 z-10 sm:hidden bg-[rgba(10,14,20,0.92)] border border-white/[0.08] text-white/70 hover:text-white rounded px-3 py-2 min-h-[44px] transition-colors pointer-events-auto"
          title={t("actions.search")}
        >
          <svg aria-hidden="true" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
        </button>
      )}

      <div
        ref={containerRef}
        className={`absolute top-3 pointer-events-auto sm:left-1/2 sm:right-auto sm:-translate-x-1/2 sm:w-80 sm:z-overlay max-w-sm ${
          mobileExpanded ? "left-4 right-4 z-overlay" : "hidden sm:block"
        }`}
      >
        {/* Input */}
        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/65 pointer-events-none"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => { setQuery(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            placeholder={t("search.placeholder")}
            className="w-full bg-[rgba(10,14,20,0.95)] border border-white/[0.12] rounded pl-9 pr-16 py-2 text-[13px] font-medium text-white/90 placeholder:text-white/60 focus:outline-none focus:border-white/25 focus-visible:ring-1 focus-visible:ring-white/20 transition-colors"
          />
          <kbd className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono text-white/50 bg-white/[0.04] border border-white/[0.06] rounded px-1.5 py-0.5 pointer-events-none hidden sm:block">
            {navigator.platform.includes("Mac") ? "⌘K" : "Ctrl K"}
          </kbd>
        </div>

      {/* Results dropdown */}
      {showResults && results.length > 0 && (
        <div className="mt-1 bg-[rgba(10,14,20,0.97)] border border-white/[0.08] rounded overflow-hidden max-h-80 overflow-y-auto">
          {grouped.map(group => (
            <div key={group.label}>
              <div className="px-3 py-1 text-[10px] font-mono text-white/60 uppercase tracking-[0.12em] bg-white/[0.03]">
                {group.label}
              </div>
              {group.items.map(r => (
                <button
                  key={`${r.layerId}-${r.featureId}-${r.globalIdx}`}
                  className={`w-full text-left px-3 py-1.5 flex items-center gap-2.5 transition-colors ${
                    r.globalIdx === highlight ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"
                  }`}
                  onMouseEnter={() => setHighlight(r.globalIdx)}
                  onClick={() => selectResult(r)}
                >
                  <span
                    className="w-2 h-2 rounded-sm shrink-0"
                    style={{ backgroundColor: r.color }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-white/90 truncate">{r.primary}</span>
                    {r.secondary && (
                      <span className="block text-xs font-mono text-white/60 truncate">{r.secondary}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* No results */}
      {showResults && results.length === 0 && (
        <div className="mt-1 bg-[rgba(10,14,20,0.97)] border border-white/[0.08] rounded px-3 py-2.5 text-xs font-mono text-white/60 text-center">
          {t("search.noResults", { query: debouncedQuery })}
        </div>
      )}
    </div>
    </>
  );
}
