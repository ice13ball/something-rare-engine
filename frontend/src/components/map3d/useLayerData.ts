// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef, useState, type MutableRefObject } from "react";
import type { FeatureCollection } from "geojson";
import type { LayerId } from "../../types/layers";

type Guarded = (
  ref: MutableRefObject<boolean>,
  path: string,
  setter: (d: FeatureCollection) => void,
  name: string,
) => void;

/**
 * The 30 lazy-fetch-on-first-activation layers extracted verbatim from
 * Map3D.tsx's two "Lazy … fetch when toggled on" effects (the ones whose
 * body is exactly `fetchGuarded(ref, path, setter, name)`).
 *
 * Deliberately NOT moved (left in Map3D.tsx): argo trails, tectonic plates,
 * vent-mining conflicts, fires-near-mining, biodiversity hotspots, noise
 * risk, ocean currents, WOA/oxygen/carbon/acid/CHI/CO2 hex layers — each of
 * those has bespoke logic (baking, retry-reset tied to different state,
 * cross-layer dependencies) beyond the plain fetchGuarded pattern, so moving
 * them risks silently changing firing order/dependencies. See task note.
 */
export function useLayerData(activeLayers: Set<LayerId>, fetchGuarded: Guarded) {
  const [eezData, setEezData] = useState<FeatureCollection | null>(null);
  const [protectedSitesData, setProtectedSitesData] = useState<FeatureCollection | null>(null);
  const [seamountsData, setSeamountsData] = useState<FeatureCollection | null>(null);
  const [oceansitesData, setOceansitesData] = useState<FeatureCollection | null>(null);
  const [oncData, setOncData] = useState<FeatureCollection | null>(null);
  const [chessData, setChessData] = useState<FeatureCollection | null>(null);
  const [cablesData, setCablesData] = useState<FeatureCollection | null>(null);
  const [oncCablesData, setOncCablesData] = useState<FeatureCollection | null>(null);
  const [ooiCablesData, setOoiCablesData] = useState<FeatureCollection | null>(null);
  const [noaaCablesData, setNoaaCablesData] = useState<FeatureCollection | null>(null);
  const [nzCablesData, setNzCablesData] = useState<FeatureCollection | null>(null);
  const [auCablesData, setAuCablesData] = useState<FeatureCollection | null>(null);
  const [oncInstrumentsData, setOncInstrumentsData] = useState<FeatureCollection | null>(null);
  const [deepdataStationsData, setDeepdataStationsData] = useState<FeatureCollection | null>(null);
  const [hydrophoneData, setHydrophoneData] = useState<FeatureCollection | null>(null);
  const [portsData, setPortsData] = useState<FeatureCollection | null>(null);
  const [miningFootprintsData, setMiningFootprintsData] = useState<FeatureCollection | null>(null);
  const [tailingsData, setTailingsData] = useState<FeatureCollection | null>(null);
  const [firesData, setFiresData] = useState<FeatureCollection | null>(null);
  const [airQualityData, setAirQualityData] = useState<FeatureCollection | null>(null);
  const [landslidesData, setLandslidesData] = useState<FeatureCollection | null>(null);
  const [damsData, setDamsData] = useState<FeatureCollection | null>(null);
  const [vesselEventsData, setVesselEventsData] = useState<FeatureCollection | null>(null);
  const [aisLiveData, setAisLiveData] = useState<FeatureCollection | null>(null);
  const [arcticRiversData, setArcticRiversData] = useState<FeatureCollection | null>(null);
  const [siosData, setSiosData] = useState<FeatureCollection | null>(null);
  const [methaneSeepsData, setMethaneSeepsData] = useState<FeatureCollection | null>(null);
  const [permafrostThawData, setPermafrostThawData] = useState<FeatureCollection | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [cascadeStationsData, setCascadeStationsData] = useState<any>(null);
  const [monitoringDensityData, setMonitoringDensityData] = useState<FeatureCollection | null>(null);

  const eezFetchedRef = useRef(false);
  const unescoFetchedRef = useRef(false);
  const seamountsFetchedRef = useRef(false);
  const oceansitesFetchedRef = useRef(false);
  const oncFetchedRef = useRef(false);
  const chessFetchedRef = useRef(false);
  const cablesFetchedRef = useRef(false);
  const oncCablesFetchedRef = useRef(false);
  const ooiCablesFetchedRef = useRef(false);
  const noaaCablesFetchedRef = useRef(false);
  const nzCablesFetchedRef = useRef(false);
  const auCablesFetchedRef = useRef(false);
  const oncInstrumentsFetchedRef = useRef(false);
  const deepdataStationsFetchedRef = useRef(false);
  const hydrophoneFetchedRef = useRef(false);
  const portsFetchedRef = useRef(false);
  const miningFootprintsFetchedRef = useRef(false);
  const tailingsFetchedRef = useRef(false);
  const firesFetchedRef = useRef(false);
  const airQualityFetchedRef = useRef(false);
  const landslidesFetchedRef = useRef(false);
  const damsFetchedRef = useRef(false);
  const vesselEventsFetchedRef = useRef(false);
  const aisLiveFetchedRef = useRef(false);
  const arcticRiversFetchedRef = useRef(false);
  const siosFetchedRef = useRef(false);
  const methaneSeepsFetchedRef = useRef(false);
  const permafrostThawFetchedRef = useRef(false);
  const cascadeStationsFetchedRef = useRef(false);
  const monitoringDensityFetchedRef = useRef(false);

  // ── Lazy EEZ / UNESCO fetch when toggled on ─────────────────────────────
  useEffect(() => {
    if (activeLayers.has("eez"))
      fetchGuarded(eezFetchedRef, "/api/v1/map/eez", setEezData, "EEZ Boundaries");
    if (activeLayers.has("protected-marine-sites"))
      fetchGuarded(unescoFetchedRef, "/api/v1/map/protected-marine-sites", setProtectedSitesData, "UNESCO Marine Heritage");
  }, [activeLayers, fetchGuarded]);

  // ── Lazy remaining registry/land layers ─────────────────────────────────
  useEffect(() => {
    if (activeLayers.has("seamounts"))
      fetchGuarded(seamountsFetchedRef, "/api/v1/map/seamounts", setSeamountsData, "Seamounts");
    if (activeLayers.has("oceansites"))
      fetchGuarded(oceansitesFetchedRef, "/api/v1/map/oceansites", setOceansitesData, "OceanSITES Moorings");
    if (activeLayers.has("onc"))
      fetchGuarded(oncFetchedRef, "/api/v1/map/onc", setOncData, "ONC Observatories");
    if (activeLayers.has("chess"))
      fetchGuarded(chessFetchedRef, "/api/v1/map/chess", setChessData, "Chemosynthetic Sites");
    if (activeLayers.has("submarine-cables")) {
      fetchGuarded(cablesFetchedRef, "/api/v1/map/cables", setCablesData, "Submarine Cables");
      fetchGuarded(oncCablesFetchedRef, "/api/v1/map/onc-cables", setOncCablesData, "ONC Cables");
      fetchGuarded(ooiCablesFetchedRef, "/api/v1/map/ooi-cables", setOoiCablesData, "OOI Cables");
      fetchGuarded(noaaCablesFetchedRef, "/api/v1/map/noaa-cables", setNoaaCablesData, "NOAA Cables");
      fetchGuarded(nzCablesFetchedRef, "/api/v1/map/nz-cables", setNzCablesData, "NZ LINZ Cables");
      fetchGuarded(auCablesFetchedRef, "/api/v1/map/au-cables", setAuCablesData, "AU ACMA Cables");
    }
    if (activeLayers.has("onc-instruments"))
      fetchGuarded(oncInstrumentsFetchedRef, "/api/v1/map/onc-instruments", setOncInstrumentsData, "ONC Instruments");
    if (activeLayers.has("deepdata-stations"))
      fetchGuarded(deepdataStationsFetchedRef, "/api/v2/map/deepdata-stations", setDeepdataStationsData, "Contractor Sampling Stations");
    if (activeLayers.has("hydrophone-stations"))
      fetchGuarded(hydrophoneFetchedRef, "/api/v1/map/hydrophones", setHydrophoneData, "Hydrophone Stations");
    if (activeLayers.has("ports"))
      fetchGuarded(portsFetchedRef, "/api/v1/map/ports", setPortsData, "Port Locations");

    // ── Land layer lazy fetches (/v2/map/*) ─────────────────────────────────
    // kbas, wdpa: withdrawn 2026-09-03 — no fetch, no tile layer, nothing to load.
    // mining-footprints: ~3 MB gzipped GeoJSON, simplified server-side (ST_Simplify 0.001).
    // Cheaper UX than MVT here because the dataset is small and panning/zooming
    // becomes instant once loaded — same approach as the ISA contracts layer.
    if (activeLayers.has("mining-footprints"))
      fetchGuarded(miningFootprintsFetchedRef, "/api/v2/map/mining-footprints", setMiningFootprintsData, "Mining Footprints");
    if (activeLayers.has("tailings"))
      fetchGuarded(tailingsFetchedRef, "/api/v2/map/tailings", setTailingsData, "Tailings Dams");
    if (activeLayers.has("fires"))
      fetchGuarded(firesFetchedRef, "/api/v2/map/fires", setFiresData, "Active Fires");
    if (activeLayers.has("air-quality"))
      fetchGuarded(airQualityFetchedRef, "/api/v2/map/air-quality", setAirQualityData, "Air Quality Stations");
    if (activeLayers.has("landslides"))
      fetchGuarded(landslidesFetchedRef, "/api/v2/map/landslides", setLandslidesData, "Landslide Catalog");
    if (activeLayers.has("dams"))
      fetchGuarded(damsFetchedRef, "/api/v2/map/dams", setDamsData, "Global Dams");
    if (activeLayers.has("vessel-events"))
      fetchGuarded(vesselEventsFetchedRef, "/api/v2/map/vessel-events", setVesselEventsData, "vessel-events");
    if (activeLayers.has("ais-live"))
      // Phase 0: whole-world fetch (backend caps at 20k).
      // Later: bbox-driven refetch on viewport change.
      fetchGuarded(aisLiveFetchedRef, "/api/v2/vessels/live?max_age_min=60&limit=20000", setAisLiveData, "ais-live");
    if (activeLayers.has("arctic-rivers"))
      fetchGuarded(arcticRiversFetchedRef, "/api/v2/map/arctic-rivers", setArcticRiversData, "Arctic River Inputs");
    if (activeLayers.has("sios-svalbard"))
      fetchGuarded(siosFetchedRef, "/api/v1/map/sios", setSiosData, "SIOS Svalbard");
    if (activeLayers.has("methane-seeps"))
      fetchGuarded(methaneSeepsFetchedRef, "/api/v1/map/methane-seeps", setMethaneSeepsData, "Methane Seeps (SEAFLEA)");
    if (activeLayers.has("permafrost-thaw"))
      fetchGuarded(permafrostThawFetchedRef, "/api/v2/map/permafrost-thaw", setPermafrostThawData, "Permafrost Thaw");
    if (activeLayers.has("arctic-sediment-carbon"))
      fetchGuarded(cascadeStationsFetchedRef, "/api/v1/map/cascade/stations", setCascadeStationsData, "Arctic Sediment Carbon");
    if (activeLayers.has("monitoring-density"))
      fetchGuarded(monitoringDensityFetchedRef, "/api/v2/map/monitoring-density", setMonitoringDensityData, "Baseline Monitoring Density");
  }, [activeLayers, fetchGuarded]);

  return {
    eezData, protectedSitesData, seamountsData, oceansitesData, oncData, chessData,
    cablesData, oncCablesData, ooiCablesData, noaaCablesData, nzCablesData, auCablesData,
    oncInstrumentsData, deepdataStationsData, hydrophoneData, portsData,
    miningFootprintsData, tailingsData, firesData, airQualityData, landslidesData,
    damsData, vesselEventsData, aisLiveData, arcticRiversData, siosData,
    methaneSeepsData, permafrostThawData, cascadeStationsData, monitoringDensityData,
  };
}
