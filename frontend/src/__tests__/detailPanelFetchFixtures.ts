// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Response fixtures for the "loaded" half of the fetch-on-mount panels in
// DetailPanel.tsx, used by detail-panel-matrix.test.tsx's per-URL fetch mock.
//
// Each shape is derived from the TS interface DetailPanel.tsx already declares
// for that endpoint's response (MiningDetail, VentDetail, MementoCastDetail,
// ...) — see the interface line-number comment on each block below. Values are
// synthetic and obviously so (round numbers, "TEST" strings), but arrays carry
// >=3 elements wherever a chart plots a series, so the chart component actually
// draws instead of hitting its own <2-point empty-state branch.
//
// WHY a fixtures file and not inline literals in the test: the router in the
// test file matches on URL only: keeping the payload shapes here (grouped by
// interface) makes it possible to skim this file against DetailPanel.tsx's
// interface block and see the contract is honoured, without wading through
// router/regex code.

// ---- MiningPanel — MiningDetail (DetailPanel.tsx:30) -----------------------
export const MINING_DETAIL = {
  isa_id: "TEST-ISA-1",
  contractor_name: "TEST Contractor",
  resource_type: "Polymetallic Manganese Nodules",
  area_km2: 12345,
  act_date: "2010-01-01T00:00:00Z",
  expiry_date: "2030-01-01T00:00:00Z",
  is_high_risk: false,
  jurisdiction_text: "TEST jurisdiction",
  nearest_eez_country: "TEST Country",
  nearest_eez_dist_km: 123.4,
  nearest_unesco_site: null,
  nearest_unesco_dist_km: null,
  centroid_lon: 4.56,
  centroid_lat: 1.23,
};

// ---- VentPanel — VentDetail (DetailPanel.tsx:47) ----------------------------
export const VENT_DETAIL_ACTIVE = {
  id: 1,
  name: "TEST Active Vent",
  status: "Active",
  depth_m: 2500,
  min_depth_m: 2400,
  max_temp_c: 350,
  temp_category: "high",
  ocean: "TEST Ocean",
  region: "TEST Region",
  jurisdiction: "TEST jurisdiction",
  tectonic_setting: "TEST setting",
  discovery_year: "1995",
  biology_notes: "TEST biology notes",
  latitude: 1.23,
  longitude: 4.56,
  source_url: "https://example.test/vent",
  created_at: "2020-01-01T00:00:00Z",
  chess_count: 2,
  chess_species: [
    { species: "Testus alpha", phylum: "Annelida", depth_m: 2500, institution: "TEST Inst" },
    { species: "Testus beta", phylum: "Mollusca", depth_m: 2510, institution: "TEST Inst" },
  ],
};

export const VENT_DETAIL_INACTIVE = {
  ...VENT_DETAIL_ACTIVE,
  id: 2,
  name: "TEST Inactive Vent",
  status: "Inactive",
  max_temp_c: null,
  temp_category: null,
  chess_count: 0,
  chess_species: [],
};

// ---- ArgoPanel's WoaSeasonalExplorer — /v1/woa/sample (DetailPanel.tsx:865) -
// Response is a bare Record<string, number|null>; only the 5 keys the
// component reads (see WoaSeasonalExplorer around DetailPanel.tsx:893).
export const WOA_SAMPLE = {
  woa_surface_temp_c: 14.2,
  woa_surface_sal: 34.6,
  woa_deep_temp_c: 3.4,
  woa_deep_sal: 34.9,
  woa_deep_oxygen_umol_kg: 205.1,
};

// ---- OncPanel — 4 parallel fetches (DetailPanel.tsx:1653-1659) -------------
// SparklineData (:1603) — keyed by sensor code; onc fixture's latest_sensors
// is {} so no sensor rows render regardless, but the endpoint itself must
// still resolve to a well-shaped object (empty map is valid — the panel reads
// it via `sparklineBySensor[key]` for keys that don't exist here).
export const ONC_SPARKLINES: Record<string, { unit: string; samples: [number, number][] }> = {};

// AdcpData (:1604) — 3 depth bins x 3 time buckets so AdcpHeatmap draws a
// real grid instead of its own empty-state.
export const ONC_ADCP = {
  device_code: "TEST-ADCP",
  bin_count: 3,
  window_start: "2020-06-14T00:00:00Z",
  window_end: "2020-06-15T00:00:00Z",
  variable: "meanBackscatter",
  units: "dB",
  depths: [10, 20, 30],
  strip: [
    [40, 41, 42],
    [43, 44, 45],
    [46, 47, 48],
  ],
};

// CtdCast (:1614) — >=3 depth points per profiled variable so ProfilePlot draws.
export const ONC_CTD: Array<{ device_code: string; cast_time: string; profile: Record<string, (number | null)[]> }> = [
  {
    device_code: "TEST-CTD",
    cast_time: "2020-06-15T00:00:00Z",
    profile: {
      depth: [10, 20, 30],
      temperature: [12.1, 10.4, 8.7],
      salinity: [34.1, 34.3, 34.5],
    },
  },
];

// EarthquakeRow (:1616) — 3 rows so the "N events total" list has real content.
export const ONC_EARTHQUAKES = [
  { usgs_id: "TEST-EQ-1", occurred_at: "2020-06-14T00:00:00Z", magnitude: 4.5, depth_km: 10, place: "TEST place 1", distance_km: 50 },
  { usgs_id: "TEST-EQ-2", occurred_at: "2020-06-13T00:00:00Z", magnitude: 3.2, depth_km: 5, place: "TEST place 2", distance_km: 80 },
  { usgs_id: "TEST-EQ-3", occurred_at: "2020-06-12T00:00:00Z", magnitude: 5.1, depth_km: 20, place: "TEST place 3", distance_km: 120 },
];

// ---- HydrophoneStationPanel — SoundscapeRow[] (DetailPanel.tsx:1803) -------
// 3 days so the broadband-SPL sparkline draws (needs >1 point) and the mean
// is computed over more than one sample.
export const HYDROPHONE_SOUNDSCAPE = [
  { day: "2020-06-13", broadband_spl_db: 110.2, spl_10hz_db: 90, spl_63hz_db: 95, spl_100hz_db: 98, spl_125hz_db: 99, spl_1khz_db: 100, spl_10khz_db: 80, l50_db: 105, l95_db: 115, n_minutes_recorded: 1440, source_url: null },
  { day: "2020-06-14", broadband_spl_db: 112.7, spl_10hz_db: 91, spl_63hz_db: 96, spl_100hz_db: 99, spl_125hz_db: 100, spl_1khz_db: 101, spl_10khz_db: 81, l50_db: 106, l95_db: 116, n_minutes_recorded: 1440, source_url: null },
  { day: "2020-06-15", broadband_spl_db: 108.9, spl_10hz_db: 89, spl_63hz_db: 94, spl_100hz_db: 97, spl_125hz_db: 98, spl_1khz_db: 99, spl_10khz_db: 79, l50_db: 104, l95_db: 114, n_minutes_recorded: 1440, source_url: null },
];

// ---- MonitoringDensityPanel — /v2/map/monitoring-density/cell -------------
// DensitySource[] (:2079), 3 sources so the breakdown list has real rows.
export const MONITORING_DENSITY_CELL = {
  distinct_species: 17,
  sources: [
    { src: "obis", count: 120, samples: [{ id: "s1", title: "TEST sample 1", year: 2015 }] },
    { src: "wod", count: 80, samples: [{ id: "s2", title: "TEST sample 2", year: 2016 }] },
    { src: "argo", count: 40, samples: [] },
  ],
};

// ---- WodOxygenPanel — WodByIdDetail (DetailPanel.tsx:3604) -----------------
// o2_profile needs >=2 points for WodO2Chart to draw (its own guard is `< 2`);
// 3 supplied for headroom.
export const WOD_BY_ID = {
  id: 1,
  wod_cast_id: "TEST-WOD-1",
  lat: 1.23,
  lon: 4.56,
  max_depth_m: 500,
  profile_date: "2020-06-15T00:00:00Z",
  decade: 2020,
  cruise: "TEST Cruise",
  dataset: "osd",
  country: "TEST Country",
  probe_type: "TEST probe",
  n_levels: 3,
  o2_units: "umol/kg",
  qc_flag: 0,
  qc_note: null,
  o2_profile: [[10, 220], [100, 180], [500, 90]] as [number, number][],
};

// ---- MementoPanel — MementoCastDetail (DetailPanel.tsx:4416) ---------------
// 3 samples with both ch4 and n2o so MementoDepthChart draws for either gas.
export const MEMENTO_CAST = {
  cast_id: "TEST-MEMENTO-1",
  set_name: "TEST Set",
  station: "TEST Station",
  sample_time: "2020-06-15T00:00:00Z",
  lat: 1.23,
  lon: 4.56,
  decade: 2020,
  n_samples: 3,
  min_depth_m: 3,
  max_depth_m: 500,
  has_ch4: true,
  has_n2o: true,
  ch4_surf: 5.5,
  n2o_surf: 12.1,
  samples: [
    { depth_m: 3, sample_time: "2020-06-15T00:00:00Z", ch4: 5.5, n2o: 12.1, n2o_perc: null, o2: 200, temp: 15, sal: 35, params: {}, ch4_is_atmospheric: false, n2o_is_atmospheric: false },
    { depth_m: 100, sample_time: "2020-06-15T00:00:00Z", ch4: 4.2, n2o: 11.4, n2o_perc: null, o2: 180, temp: 10, sal: 34.8, params: {}, ch4_is_atmospheric: false, n2o_is_atmospheric: false },
    { depth_m: 500, sample_time: "2020-06-15T00:00:00Z", ch4: 3.1, n2o: 10.8, n2o_perc: null, o2: 90, temp: 4, sal: 34.6, params: {}, ch4_is_atmospheric: false, n2o_is_atmospheric: false },
  ],
};

// ---- GeotracesStationPanel — GeotracesResponse (DetailPanel.tsx:4740) -----
// 3 samples with all 5 elements so GeotracesDepthChart draws for any selected element.
const GEOTRACES_SAMPLES = [
  { depth_m: 10, sample_time: "2020-06-15T00:00:00Z", mn_d: 1.1, fe_d: 0.9, co_d: 0.05, ni_d: 4.2, cu_d: 1.8, mn_d_qc: 1, fe_d_qc: 1, co_d_qc: 1, ni_d_qc: 1, cu_d_qc: 1, params: {} },
  { depth_m: 200, sample_time: "2020-06-15T00:00:00Z", mn_d: 0.8, fe_d: 0.7, co_d: 0.04, ni_d: 4.5, cu_d: 2.1, mn_d_qc: 1, fe_d_qc: 1, co_d_qc: 1, ni_d_qc: 1, cu_d_qc: 1, params: {} },
  { depth_m: 1000, sample_time: "2020-06-15T00:00:00Z", mn_d: 0.3, fe_d: 0.6, co_d: 0.03, ni_d: 5.1, cu_d: 2.6, mn_d_qc: 1, fe_d_qc: 1, co_d_qc: 1, ni_d_qc: 1, cu_d_qc: 1, params: {} },
];
export const GEOTRACES_RESPONSE = {
  station: {
    station_id: "TEST-GEOTRACES-1",
    cruise: "TEST Cruise",
    station: "TEST Station",
    sample_time: "2020-06-15T00:00:00Z",
    decade: 2020,
    lat: 1.23,
    lon: 4.56,
    n_samples: 3,
    min_depth_m: 10,
    max_depth_m: 1000,
    bottom_depth_m: 4000,
    samples: GEOTRACES_SAMPLES,
  },
  units: { mn: "nmol/kg", fe: "nmol/kg", co: "pmol/kg", ni: "nmol/kg", cu: "nmol/kg" },
  samples: GEOTRACES_SAMPLES,
};

// ---- MosaicPanel — MosaicResponse (DetailPanel.tsx:4996) -------------------
// 3 samples with toc/tn/d13c/d14c so MosaicDepthChart draws for any selected variable.
export const MOSAIC_RESPONSE = {
  core: {
    core_id: 1,
    core_name: "TEST Core",
    latitude: 1.23,
    longitude: 4.56,
    water_depth_m: 500,
    sampling_year: 2015,
    decade: 2010,
    sampling_method: "TEST method",
    research_vessel: "TEST Vessel",
    seas: "TEST Sea",
    eez: "TEST EEZ",
    longhurst: "TEST Province",
    has_toc: true,
    has_tn: true,
    has_d13c: true,
    has_d14c: true,
    toc_surf: 1.5,
    tn_surf: 0.15,
    d13c_surf: -22.1,
    d14c_surf: -80,
    sampling_date: "2015-08-12",
    sampling_month: 8,
    sampling_day: 12,
    campaign_name: null,
    campaign_start: null,
    campaign_end: null,
    core_comment: "TEST core comment",
    date_precision: "day",
  },
  samples: [
    { sample_id: 1, depth_upper_cm: 0, depth_bottom_cm: 5, depth_avg_cm: 2.5, material_analyzed: "bulk", replicate: 1, toc: 1.5, tn: 0.15, d13c: -22.1, d14c: -80, fm14c: 0.9, provenance: null },
    { sample_id: 2, depth_upper_cm: 5, depth_bottom_cm: 15, depth_avg_cm: 10, material_analyzed: "bulk", replicate: 1, toc: 1.2, tn: 0.12, d13c: -22.5, d14c: -120, fm14c: 0.85, provenance: null },
    { sample_id: 3, depth_upper_cm: 15, depth_bottom_cm: 30, depth_avg_cm: 22.5, material_analyzed: "bulk", replicate: 1, toc: 0.9, tn: 0.1, d13c: -23, d14c: -200, fm14c: 0.78, provenance: null },
  ],
};

// ---- ArcticCatchmentPanel — ArcticCatchmentDetail (DetailPanel.tsx:5219) ---
export const ARCTIC_CATCHMENT_DETAIL = {
  gid: 1,
  name: "TEST Catchment",
  stream_order: 3,
  continent: "TEST Continent",
  area_km2: 1234.5,
  center_lat: 1.23,
  center_lon: 4.56,
  ocs_mean: 45.2,
  oc_tot: 12.3,
  runoff_mean: 1.4,
  pf_frac: 0.6,
  t_2m_mean: 268.5,
  params: {
    soc_depth: [10, 20, 15, 12, 8, 5],
    pf_classes: { cont: 0.4, disc: 0.3, isol: 0.2, spor: 0.1 },
    iwp_frac: 0.15,
    etot_mean: 300,
    ptot_mean: 350,
    total_prec: 400,
    t_2m_min: 250,
    t_2m_max: 285,
    ndvi_mean: 0.35,
  },
};

// ---- WoaPointPanel — WoaPointData (DetailPanel.tsx:5397) -------------------
export const WOA_POINT = {
  lat: 1.23,
  lon: 4.56,
  depth: 100,
  variables: [
    { key: "temperature", label: "Temperature", units: "°C", baseline: "1991-2020", value: 12.4 },
    { key: "salinity", label: "Salinity", units: "PSU", baseline: "1991-2020", value: 34.7 },
    { key: "oxygen", label: "Oxygen", units: "µmol/kg", baseline: "1971-2000", value: 210.5 },
  ],
};

// ---- CarbonPointPanel — CarbonPointData (DetailPanel.tsx:5497) -------------
export const CARBON_POINT = {
  lat: 1.23,
  lon: 4.56,
  depth_m: 100,
  variables: [
    { key: "dic", label: "DIC", units: "µmol/kg", value: 2100.5, n_observations: 42 },
    { key: "talk", label: "Total Alkalinity", units: "µmol/kg", value: 2300.2, n_observations: null },
    { key: "ph", label: "pH (in-situ)", units: "", value: 7.95 },
  ],
  citation: "TEST GLODAP citation",
};

// ---- AcidificationPointPanel — AcidificationPointData (DetailPanel.tsx:5596)
export const ACIDIFICATION_POINT = {
  lat: 1.23,
  lon: 4.56,
  depth_m: 100,
  aragonite: 1.8,
  calcite: 2.6,
  horizon_m: 2500,
  horizon_shift_m: 400,
  always_supersaturated: false,
  horizon_no_data: false,
  citation: "TEST GLODAP citation",
  qc: { n: 3000, median: 0.00167, iqr: [-0.0087, 0.0088] as [number, number], max_abs: 0.02 },
};

// ---- ChiPanel — ChiPointData (DetailPanel.tsx:5722) ------------------------
export const CHI_POINT = {
  lat: 1.23,
  lon: 4.56,
  impact: 0.42,
  citation: "TEST NCEA/Halpern citation",
};

// ---- UnifiedCarbonPanel — UnifiedCarbonData + nearest-obs (DetailPanel.tsx:5806-5823)
export const UNIFIED_CARBON_POINT = {
  lat: 1.23,
  lon: 4.56,
  depth_m: 100,
  decade: 2020,
  groups: [
    {
      group: "Surface CO2 (SOCAT)",
      variables: [
        { key: "fco2", label: "fCO2", units: "µatm", value: 400.1 },
      ],
    },
    {
      group: "Interior carbon (GLODAP)",
      variables: [
        { key: "dic", label: "DIC", units: "µmol/kg", value: 2100.5 },
      ],
    },
  ],
  citations: ["TEST GLODAP citation", "TEST SOCAT citation"],
};

// nearest-obs is wrapped: { observations: NearestObsRow[] } — see the panel's
// `Array.isArray(d?.observations) ? d.observations : []` unwrap.
export const UNIFIED_CARBON_NEAREST_OBS = {
  observations: [
    { source: "argo", label: "Argo float", id: "TEST-P1", distance_km: 12.3, summary: "TEST summary", lat: 1.24, lon: 4.57, deck_layer_id: "argo-floats-3d" },
  ],
};

// ---- VmeSuitabilityPanel — VmePointData (DetailPanel.tsx:5972) -------------
export const VME_POINT = {
  lat: 1.23,
  lon: 4.56,
  suitability: 0.62,
  uncertainty: 0.08,
  extrapolated: false,
  top_predictors: [
    { key: "depth", label: "Depth", value: 2500, units: "m" },
    { key: "temp", label: "Temperature", value: 3.1, units: "°C" },
    { key: "substrate", label: "Substrate", value: 1, units: null },
  ],
  citation: "TEST VME citation",
};

// ---- CoralExposurePanel — point + summary (DetailPanel.tsx:6091-6109) -----
export const CORAL_EXPOSURE_POINT = {
  found: true,
  cell_id: "TEST-CELL-1",
  taxon_set: "reef_scleractinia_v1",
  suitability: 0.55,
  uncertainty: 0.1,
  seafloor_m: 2500,
  horizon_today_m: 2400,
  horizon_pi_m: 3200,
  state: "newly_corrosive",
  citation: "TEST citation",
};

export const CORAL_EXPOSURE_SUMMARY = {
  weighted: { exposed: 0.31, newly: 0.22, total_weight: 3837 },
  thresholds: [
    { cutoff: 0.3, n_cells: 1200, exposed_pct: 0.28, newly_pct: 0.2 },
    { cutoff: 0.5, n_cells: 800, exposed_pct: 0.31, newly_pct: 0.22 },
    { cutoff: 0.7, n_cells: 400, exposed_pct: 0.35, newly_pct: 0.25 },
  ],
  counts: { newly_corrosive: 900, corrosive_preindustrial: 300, supersaturated: 2400, no_data: 237 },
  citation: "TEST citation",
};

// ---- Co2PointPanel — Co2PointData (DetailPanel.tsx:6290) ------------------
export const CO2_POINT = {
  lat: 1.23,
  lon: 4.56,
  decade: 5,
  decade_label: "2020s",
  variables: [
    { key: "fco2", label: "fCO2", units: "µatm", value: 405.2 },
    { key: "density", label: "Observation density", units: "count", value: 12 },
    { key: "sst", label: "SST", units: "°C", value: 14.1 },
  ],
  citation: "TEST SOCAT citation",
};

// ---- OxygenPointPanel — OxygenPointData (DetailPanel.tsx:6389) -------------
export const OXYGEN_POINT = {
  lat: 1.23,
  lon: 4.56,
  depth: 100,
  recent_o2: 195.4,
  baseline_o2: 210.1,
  delta_o2: -14.7,
  units: "µmol/kg",
};
