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
// Raw InterRidge status values since 2026-09-21 (see ventStatus.ts) — not the
// platform-invented "Active"/"Inactive"/"Extinct" these fixtures used before.
export const VENT_DETAIL_ACTIVE = {
  id: 1,
  name: "TEST Active Vent",
  status: "active, confirmed",
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
  status: "inactive",
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
// ⛔ The span fields are ONC's own and must be present here, or the matrix
// snapshot records the pre-2026-09-10 shape as if it were current: no caption,
// no depth range, no sample count — exactly the state we just left behind.
export const ONC_CTD: Array<{
  device_code: string;
  cast_time: string;
  sample_start: string;
  sample_end: string;
  n_samples: number;
  depth_min_m: number;
  depth_max_m: number;
  profile: Record<string, (number | null)[]>;
}> = [
  {
    device_code: "TEST-CTD",
    cast_time: "2020-06-15T00:00:00Z",
    sample_start: "2020-06-15T00:00:00Z",
    sample_end: "2020-06-22T00:00:00Z",
    n_samples: 10080,
    depth_min_m: 10,
    depth_max_m: 30,
    profile: {
      depth: [10, 20, 30],
      temperature: [12.1, 10.4, 8.7],
      salinity: [34.1, 34.3, 34.5],
    },
  },
];

// EarthquakeRow (:1616) — 3 rows so the "N events total" list has real content.
// ⛔ mag_type and status must be here, and MIXED. USGS labels every event with
// the scale it used (mb 1,048 · ml 328 · mww 96 of 1,577 measured 2026-09-10)
// and marks the rare unreviewed one. A fixture without them snapshots the old
// bare-"M" world in which the defect could not be seen.
export const ONC_EARTHQUAKES = [
  { usgs_id: "TEST-EQ-1", occurred_at: "2020-06-14T00:00:00Z", magnitude: 4.5, depth_km: 10, place: "TEST place 1", distance_km: 50, mag_type: "mb", status: "reviewed" },
  { usgs_id: "TEST-EQ-2", occurred_at: "2020-06-13T00:00:00Z", magnitude: 3.2, depth_km: 5, place: "TEST place 2", distance_km: 80, mag_type: "ml", status: "automatic" },
  { usgs_id: "TEST-EQ-3", occurred_at: "2020-06-12T00:00:00Z", magnitude: 5.1, depth_km: 20, place: "TEST place 3", distance_km: 120, mag_type: null, status: "reviewed" },
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
// sample_id here mirrors what /v2/spatial/geotraces/by-id actually returns
// post-DEFECT-1-fix: the geotraces_samples.sample_id BIGSERIAL PK (NOT the
// CSV's "GEOTRACES Sample ID", which is unkeyable — see 2026-09-08 audit).
// `measurements` below is keyed by this same sample_id, as the by-id
// endpoint does — GeotracesStationPanel joins on String(sample.sample_id).
const GEOTRACES_SAMPLES = [
  { sample_id: 1, depth_m: 10, sample_time: "2020-06-15T00:00:00Z", mn_d: 1.1, fe_d: 0.9, co_d: 0.05, ni_d: 4.2, cu_d: 1.8, mn_d_qc: 1, fe_d_qc: 1, co_d_qc: 1, ni_d_qc: 1, cu_d_qc: 1, params: {} },
  { sample_id: 2, depth_m: 200, sample_time: "2020-06-15T00:00:00Z", mn_d: 0.8, fe_d: 0.7, co_d: 0.04, ni_d: 4.5, cu_d: 2.1, mn_d_qc: 1, fe_d_qc: 1, co_d_qc: 1, ni_d_qc: 1, cu_d_qc: 1, params: {} },
  { sample_id: 3, depth_m: 1000, sample_time: "2020-06-15T00:00:00Z", mn_d: 0.3, fe_d: 0.6, co_d: 0.03, ni_d: 5.1, cu_d: 2.6, mn_d_qc: 1, fe_d_qc: 1, co_d_qc: 1, ni_d_qc: 1, cu_d_qc: 1, params: {} },
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
  measurements: {
    // Keyed on sample_id 2 (depth_m 200) — the plain assertion in
    // detail-panel-matrix.test.tsx checks this row renders depth "200",
    // not an em-dash from a failed String(sample.sample_id) join.
    "2": [
      { param_code: "Zn_D_CONC_BOTTLE", value: 3.4, stddev: 0.1, qc_flag: 1 },
      { param_code: "Cd_D_CONC_BOTTLE", value: 0.6, stddev: 0.02, qc_flag: 1 },
    ],
  },
  params: [
    { param_code: "Zn_D_CONC_BOTTLE", label: "Dissolved Zn", unit: "nmol/kg", family: "trace metal", n_values: 50 },
    { param_code: "Cd_D_CONC_BOTTLE", label: "Dissolved Cd", unit: "nmol/kg", family: "trace metal", n_values: 40 },
  ],
  truncated: false,
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

// ---- PermafrostThawPanel — GET .../permafrost-thaw/by-id/{unique_id} ------
// (DetailPanel.tsx / panels/arctic/PermafrostThawPanel.tsx). Detail-only
// fields split off the bulk GeoJSON 2026-09-08; see that file's header comment.
export const PERMAFROST_THAW_DETAIL = {
  imagery: "TEST imagery",
  authors: "Test Author",
  source_doi: "10.5281/zenodo.16996415",
  data_source_type: "satellite imagery",
  obs_start: "1985-06-01",
  obs_end: "2015-08-15",
};

// ---- CoastdomPanel — /v1/map/coastdom/samples ------------------------------
export const COASTDOM_SAMPLES = {
  lat: 1.23, lon: 4.56, n_samples: 2,
  samples: [
    { version_id: 1, row_no: 1, location: "TEST estuary", sample_id: "TEST-1", sample_date: "2017-04-15",
      depth_m: 0, doc_umol_l: 100, doc_method: "TEST method", qf_doc: 2, ref_1: "doi:TEST", pi: "TEST PI",
      institution: "TEST Institution" },
    { version_id: 1, row_no: 2, location: "TEST estuary", sample_id: "TEST-2", sample_date: null,
      depth_m: 4, doc_umol_l: 120, doc_method: "TEST method", qf_doc: 6 },
  ],
};

// ---- CoastdomPanel / GreenlandPrimaryProductionPanel — /v1/pangaea-water/meta
export const PANGAEA_WATER_META = {
  versions: [
    { version_id: 1, layer_id: "coastdom", is_current: true, doi: "10.1594/PANGAEA.964012",
      date_published: "2023-12-12", sha256: "0123456789abcdef0123", rows_in_source: 3, rows_unmappable: 1,
      data_points: 30, citation: "TEST citation [dataset]. PANGAEA", related_citation: "TEST related",
      license: "https://creativecommons.org/licenses/by/4.0/", ingested_at: "2026-09-25T00:00:00Z",
      units: { doc_umol_l: "DOC [µmol/l]", qf_doc: "QF DOC", depth_m: "Depth water [m]" } },
    { version_id: 2, layer_id: "greenland-primary-production", is_current: true, doi: "10.1594/PANGAEA.965985",
      date_published: "2025-04-07", sha256: "fedcba9876543210fedc", rows_in_source: 12, rows_unmappable: 0,
      data_points: 12, citation: "TEST citation [dataset]. PANGAEA", related_citation: null,
      license: "https://creativecommons.org/licenses/by/4.0/", ingested_at: "2026-09-25T00:00:00Z",
      units: { gpp_c_mg_m2_day: "GPP C [mg/m**2/day]" } },
  ],
};

// ---- AocPocPanel — /v1/map/aoc2025-poc/samples -----------------------------
export const AOC_POC_SAMPLES = {
  station: "TEST", n_samples: 1,
  samples: [
    { version_id: 1, row_no: 1, cruise_id: "AOC2025", station: "TEST", sample_date: "2025-05-19T04:30:00Z",
      lat: 73.02205, lon: -5.362583333, prespr01_db: 5, pressure_db: 4.652, activity: "9", sample_id: "TEST-1",
      salinity: 34.5031, temp_c: 0.4349, d15n_permil: 3.421, d13c_permil: -22.321,
      poc_mg_dm3: 0.500199883, pn_mg_dm3: 0.085944997 },
  ],
  units: {
    prespr01_db: "db (SeaDataNet P01 PRESPR01, profiling pressure sensor)", pressure_db: "db",
    salinity: "PSU", temp_c: "°C",
    d15n_permil: "‰ (SeaDataNet P01 D15NEAM1)", d13c_permil: "‰ (SeaDataNet P01 D13CMOP11)",
    poc_mg_dm3: "mg dm-3 (from the dataset abstract; not in the data file)",
    pn_mg_dm3: "mg dm-3 (from the dataset abstract; not in the data file)",
  },
};

// ---- AocPocPanel — /v1/map/aoc2025-poc/meta --------------------------------
export const AOC_POC_META = {
  version: {
    version_id: 1, doi: "10.48457/IOPAN.2026.571",
    source_url: "https://opendap.iopan.pl/opendap/data/csv/SeaQuester/AOC2025/2025_AOC_POC.csv",
    sha256: "0123456789abcdef0123", rows_in_source: 94,
    citation: "Kowalczuk, P. (2026). Particulate organic carbon concentrations in water samples collected in the Greenland Sea, during Atlantic-Arctic Ocean Change cruise (AOC2025) between 19-31 May 2025. Institute of Oceanology Polish Academy of Sciences. https://doi.org/10.48457/IOPAN.2026.571",
    license: "CC-BY 4.0", fetched_at: "2026-09-25T00:00:00Z",
    units: {
      prespr01_db: "db (SeaDataNet P01 PRESPR01, profiling pressure sensor)", pressure_db: "db",
      salinity: "PSU", temp_c: "°C",
      d15n_permil: "‰ (SeaDataNet P01 D15NEAM1)", d13c_permil: "‰ (SeaDataNet P01 D13CMOP11)",
      poc_mg_dm3: "mg dm-3 (from the dataset abstract; not in the data file)",
      pn_mg_dm3: "mg dm-3 (from the dataset abstract; not in the data file)",
    },
    metadata_url: "https://geonetwork.iopan.pl/geonetwork/srv/eng/catalog.search#/metadata/a5efb78a-cc02-4839-9c94-18730e470eb4",
    temporal_extent_discrepancy: "The dataset's ISO metadata states a temporal extent of 2024-07-24..2024-08-09; the title and every sample date in the data itself are 19-31 May 2025. This platform uses the dates in the data.",
  },
};

// ---- SvalbardFjordsPpPanel — /v1/map/svalbard-fjords-pp/samples ------------
export const SVALBARD_FJORDS_PP_SAMPLES = {
  position_id: "K:TEST:78.97:11.74", station: "TEST", region_code: "K", region_name: "Kongsfjorden",
  expositions: [
    { exposition_no: "1", date: "2010-07-01", fjord_part: "Inner", pi_mgc_m2_day: 123.4,
      samples: [
        { depth_m: 0, temperature_degc: 2.1, salinity: 33.5, ca_mg_m3: 1.2, pe_mgc_m3_h: 0.5, water_mass: "SW" },
        { depth_m: 10, temperature_degc: 1.4, salinity: 34.1, ca_mg_m3: null, pe_mgc_m3_h: 0.3, water_mass: "AW" },
      ] },
  ],
};

// ---- SvalbardFjordsPpPanel — /v1/map/svalbard-fjords-pp/meta ---------------
export const SVALBARD_FJORDS_PP_META = {
  version: {
    version_id: 1, doi: "10.48457/iopan-2024-198",
    source_url: "https://opendap.iopan.pl/opendap/data/csv/Primary_production_in_Kongsfjorden_and_Hornsund_in_the_period_1994-2019.csv",
    metadata_url: "https://geonetwork.iopan.pl/geonetwork/srv/api/records/5a2ef3d9-02ea-4b9c-acef-10e9b1968458/formatters/xml",
    sha256: "0123456789abcdef0123", rows_in_source: 369,
    citation: "Institute of Oceanology Polish Academy of Sciences (2024). In situ primary production, Kongsfjorden & Hornsund (Svalbard), 1994-2019. https://doi.org/10.48457/iopan-2024-198",
    licence: "© Institute of Oceanology PAS (IO PAN). Used with permission; the source publishes no open licence.",
    fetched_at: "2026-09-26T00:00:00Z",
    units: {
      depth_m: "m", temperature_degc: "°C", salinity: "no unit stated in the source",
      ca_mg_m3: "mg m⁻³ (Not defined in the source record; in primary-production data this usually denotes chlorophyll a.)",
      pe_mgc_m3_h: "mgC m⁻³ h⁻¹",
      pi_mgc_m2_day: "mgC m⁻² day⁻¹ (daily water-column-integrated production of the whole profile)",
    },
    counts: {
      rows: 369, expositions: 45, positions: 43, named_stations: 29,
      per_region: { K: { rows: 232, expositions: 28 }, H: { rows: 137, expositions: 17 } },
    },
    date_range: { first_date: "1994-07-05", last_date: "2019-08-11" },
    column_notes: {
      ca_mg_m3: "Not defined in the source record; in primary-production data this usually denotes chlorophyll a.",
      water_mass: {
        expansions: { AW: "Atlantic Water", TAW: "Transformed Atlantic Water", IW: "Intermediate Water", SW: "Surface Water", LW: "Local Water" },
        attribution: "Cottier et al. 2005, standard Svalbard fjord classification",
      },
      salinity: "unit not stated in the source",
    },
    discrepancies: [
      { key: "incubation_total", metadata_says: "348 incubation levels (137 Hornsund + 232 Kongsfjorden)", data_shows: "369 rows (137 Hornsund + 232 Kongsfjorden)" },
      { key: "station_counts", metadata_says: "28 measurement stations in Kongsfjorden and 17 in Hornsund", data_shows: "those numbers equal the per-fjord exposition (station-visit) counts (28 Kongsfjorden + 17 Hornsund), while named stations are 22 Kongsfjorden + 7 Hornsund (29 total) and distinct positions 43" },
      { key: "bbox_west", metadata_says: "west bound 11.0308°E", data_shows: "positions west of it (EB2-13bis 2.50°E, EB2-GL 9.45°E; 20 rows)" },
      { key: "station_name_reuse", metadata_says: null, data_shows: "K2 (2 positions)" },
    ],
  },
};

// GLODAPv3 bottle cast — shape of `/api/v1/glodap/cast/{cast_key}` (backend/domains/glodap_points.py
// `get_cast_payload`). One flag-0 sample (205 m, interpolated) and one flag-9 sample with no value (1000 m).
const GLODAP_NVS_CREDIT =
  "Ship names: The NERC Vocabulary Server (NVS), National Oceanography Centre - British Oceanographic Data Centre (BODC), "
  + "collection C17 (ICES platform codes), https://vocab.nerc.ac.uk/collection/C17/current/ - CC BY 4.0, https://vocab.nerc.ac.uk/about";
export const GLODAP_CAST = {
  cast_key: "49UF20150620_4511_1", expocode: "49UF20150620", station: "4511", cast_no: 1,
  ship_name: "TEST Ship", platform_code: "49UF", lat: 1.23, lon: 4.56,
  obs_date: "2015-06-20", obs_time: "2015-06-20T12:34:00+00:00", time_precision: "minute",
  year: 2015, region: 1, doi: "10.1234/test-cruise", bottom_depth_m: 4100, pos_spread_km: 0.5,
  depth_m: [5, 200, 205, 1000, 4000],
  variables: {
    tco2: { values: [2050, 2150, 2155, null, 2250], flags: [2, 2, 0, 9, 2], qc: 1, units: "µmol/kg" },
    talk: { values: [2300, 2310, null, null, 2330], flags: [2, 2, 9, 9, 2], qc: null, units: "µmol/kg" },
    temperature: { values: [20, 10, 9, 4, 1.5], flags: [2, 2, 2, 2, 2], qc: 1, units: "°C" },
  },
  levels: { dic: { "0": [2050, 5], "200": [2150, 200], "4000": [2250, 4000] }, talk: { "0": [2300, 5] } },
  field: {
    dic: { "0": 2040.5, "200": 2140.2, "500": null, "1000": 2190, "2000": 2220, "3000": 2240, "4000": 2260 },
    talk: { "0": 2299.9, "200": 2309.9 },
    ph: { "0": 8.101, "200": 7.9 },
    cant: { "0": 55.4, "200": 30.1 },
  },
  citations: [
    "Lange, N., et al. (2026). The Global Ocean Data Analysis Project version 3 (GLODAPv3). NOAA NCEI. https://doi.org/10.25921/m6tp-mj50",
    "Lange et al., ESSD preprint, https://doi.org/10.5194/essd-2026-496",
    GLODAP_NVS_CREDIT,
  ],
  citation: "dataset — and — paper — and — ship names",
  source_url: "https://doi.org/10.25921/m6tp-mj50",
  product: "GLODAPv3 (2026)",
  field_product: "GLODAPv2.2016b mapped climatology (TCO2 and pH normalised to 2002)",
};

// BGC-Argo DOXY profile — shape of `/api/v1/argo-oxygen/profile/{key}` (backend/domains/argo_oxygen_points.py
// `get_profile_payload`). Level 2 (60 m) carries an adjusted value flagged 3 (counted, never charted); level 4
// (2000 m) has a raw value only (QC 4). Citations are the backend's CITATIONS verbatim.
export const ARGO_OXYGEN_ACKNOWLEDGEMENT =
  "These data were collected and made freely available by the International Argo Program and the national programs "
  + "that contribute to it. (https://argo.ucsd.edu, https://www.ocean-ops.org). The Argo Program is part of the Global Ocean Observing System.";
export const ARGO_OXYGEN_PROFILE = {
  profile_key: "aoml_1900722_001", argo_profile_id: "1900722_001", dac: "aoml", platform_number: "1900722",
  cycle_number: 1, direction: "A", lat: -40.316, lon: 73.389, position_qc: 1,
  profile_time: "2006-10-22T02:16:24+00:00", juld_qc: 1, year: 2006, doxy_mode: "D", pres_source: "adjusted",
  n_levels_source: 71, n_levels: 4, n_good: 70, drawable: true, units: "µmol/kg",
  levels: {
    pres_dbar: [6, 60, 500, 2000], depth_m: [5.9, 59.5, 495.8, 1974.3],
    doxy_adj: [259.6, 255.0, 200.1, null], doxy_adj_qc: [1, 3, 1, null],
    doxy_raw: [230.9, 228.0, 178.0, 146.2], doxy_raw_qc: [3, 3, 3, 4],
  },
  at_depth: { "0": [259.6, 5.9], "500": [200.1, 495.8], "2000": null },
  depth_windows: { "0": [0, 10], "500": [450, 550], "2000": [1900, 2100] },
  field_recent: { "0": 250.0, "500": 205.0, "2000": 180.0 },
  field_product: "ISAS20 BGC-Argo 2014–2018 mean (SEANOE doi:10.17882/52367), built from an older Argo snapshot",
  product: "BGC-Argo DOXY, Argo GDAC synthetic profiles (current)",
  good_qc: [1, 2], source_url: "https://data-argo.ifremer.fr/dac/aoml/1900722/profiles/SD1900722_001.nc",
  float_url: "https://fleetmonitoring.euro-argo.eu/float/1900722", source_home: "https://doi.org/10.17882/42182",
  citations: [
    ARGO_OXYGEN_ACKNOWLEDGEMENT,
    "Argo (2000). Argo float data and metadata from Global Data Assembly Centre (Argo GDAC). SEANOE. https://doi.org/10.17882/42182",
  ],
  citation: "",
};

// SOCAT v2026 observation — shape of `/api/v1/socat/obs/{obs_key}` (backend/domains/socat_points.py `get_obs_payload`).
// Three observations in the segment; the selected one (index 1) has no salinity (null, never 0). Citations and the
// acknowledgement are the backend's verbatim; the cruise is the fixture-style 33GC20040908 (QC C).
export const SOCAT_OBS = {
  obs_key: "33GC20040908~1", expocode: "33GC20040908", ordinal: 1,
  time: "2004-09-08T10:20:30Z", lon: -70.5, lat: 42.9,
  fco2_uatm: 365.4, sst_c: 0, sal_pss78: null, fco2_src: 4,
  fco2_src_note: "fCO2rec_src is the SOCAT algorithm code (0 not generated, 1-14) that produced the recomputed fCO2; see the SOCAT data documentation for the meaning of each code.",
  fco2_flag: 2,
  segment: {
    ord0: 0, n_obs: 3, index: 1,
    time: ["2004-09-08T10:00:00Z", "2004-09-08T10:20:30Z", "2004-09-08T10:40:00Z"],
    lon: [-70.4, -70.5, -70.6], lat: [42.8, 42.9, 43.0],
    fco2_uatm: [360.2, 365.4, 370.1], sst_c: [0.5, 0, -0.5], sal_pss78: [31.2, null, 31.4],
    fco2_flag: [2, 2, 2],
  },
  field: { fco2_decadal_uatm: 372.3 },
  cruise: {
    expocode: "33GC20040908", platform_name: "Gulf Challenger", dataset_name: "33GC20040908",
    pis: "Vandemark, D.", qc_flag: "C", version: "3.0U", source_doi: "10.3334/CDIAC/otg.TSM_UNH_GOM",
    source_reference: "https://accession.nodc.noaa.gov/0073808", metadata_docs: "33GC20040908/README",
    first_time: "2004-09-08T10:00:00Z", last_time: "2004-09-08T10:40:00Z", n_obs: 3,
    west: -70.6, east: -70.4, south: 42.8, north: 43.0, crosses_antimeridian: false,
  },
  citations: [
    "Bakker, D. C. E., Alin, S. R., Bates, N., et al. (2026). Surface Ocean CO2 Atlas Database Version 2026 (SOCATv2026) (NCEI Accession 0315110). NOAA NCEI. https://doi.org/10.25921/8dba-fr90",
    "Bakker, D. C. E., et al. (2016). A multi-decade record of high-quality fCO2 data in version 3 of the Surface Ocean CO2 Atlas (SOCAT). Earth System Science Data 8, 383-413. https://doi.org/10.5194/essd-8-383-2016",
  ],
  citation: "dataset — and — paper",
  acknowledgement: "The Surface Ocean CO2 Atlas (SOCAT) is an international effort, endorsed by the SCOR Infrastructural Project International Ocean Carbon Coordination Project (IOCCP) and the Surface Ocean Lower-Atmosphere Study (SOLAS), to deliver a uniform, quality-controlled surface ocean CO2 database. The many researchers and funding agencies responsible for the collection of data and quality control are thanked for their contributions to SOCAT.",
  source_url: "https://doi.org/10.25921/8dba-fr90",
  metadata_url: "https://www.ncei.noaa.gov/data/oceans/ncei/ocads/metadata/0315110.html",
  licence: "CC BY 4.0", product: "SOCAT v2026 (Surface Ocean CO2 Atlas)",
};

// WOD23 cast — shape of `/api/v1/wod/cast/{cast_id}?var=&depth=` (backend/domains/wod_casts.py `_cast_payload`).
// A CTD cast with temperature and oxygen on four levels; the 0 m temperature is 0 °C (a value, never "no value"),
// one oxygen level carries flag 1 (listed, never plotted), time_precision "day" (no time of day recorded).
// `picks` are the server's 8 display-depth values (depths 0, 50, 100, 200, 500, 1000, 1500, 2000); `field.values`
// the WOA23 oxygen field at the cast's cell (the matrix store default is woaVariable "oxygen", woaDepth 500).
export const WOD_CAST = {
  cast_id: 9000001, instrument: "ctd", dataset: "XCTD", cruise: "TEST-CRUISE-1", orig_cruise: "TEST-ORIG-1",
  platform: "TEST Vessel", vehicle: null, wmo_id: null, institute: "TEST Institute", project: "TEST Project",
  country: "TEST Country", t_instrument: "TEST thermometer", o2_instrument: null, real_time: null,
  date: "2004-09-08", time: null, time_precision: "day", lat: 42.9, lon: -70.5,
  access_no: 12345, accession_url: "https://www.ncei.noaa.gov/archive/accession/12345",
  source_file_url: "https://www.ncei.noaa.gov/data/oceans/ncei/wod/2004/wod_ctd_2004.nc",
  levels: {
    t: [[0, 0, 0], [50, 4.5, 0], [100, 6.25, 0], [200, 8.5, 0]],
    o: [[0, 300, 0], [50, 280, 0], [100, 250, 1], [200, 220, 0]],
  },
  depth_flag: [0, 0, 0, 0], pflag: [0, 255, 0, 255, 255, 255], n_src: [4, 0, 4, 0, 0, 0],
  picks: {
    temperature: [0, 4.5, 6.25, 8.5, null, null, null, null],
    oxygen: [300, 280, null, 220, null, null, null, null],
  },
  field: { variable: "oxygen", selected_depth: 500, values: { "0": 310, "50": 290, "100": 260, "200": 230, "500": 150 } },
  flag_meanings: { Temperature: { "0": "accepted_value", "1": "range_outlier" }, Oxygen: { "0": "accepted_value", "1": "range_outlier" } },
  product: "World Ocean Database 2023 (WOD23) — OSD, CTD, PFL", licence: "Public use without restriction (NOAA NCEI)",
  citation: "TEST WOD23 citation", source_url: "https://www.ncei.noaa.gov/products/world-ocean-database",
};

// Plankton place — shape of `/api/v1/plankton/site/{site_key}` (backend/domains/plankton.py plankton_site).
export const PLANKTON_SITE = {
  site_key: "10.200000,50.200000", lon: 10.2, lat: 50.2, total: 6,
  groups: [{ taxon_group: "copepoda", n: 3 }, { taxon_group: "diatoms", n: 2 }, { taxon_group: "dinoflagellates", n: 1 }],
  top_species: [
    { scientific_name: "Calanus finmarchicus", taxon_group: "copepoda", n: 3 },
    { scientific_name: "Chaetoceros", taxon_group: "diatoms", n: 2 },
  ],
  years: { min: 1995, max: 2015, undated: 1 },
  depth: { min_m: 50, max_m: 1500, no_depth: 2 },
  edna: { n: 1, share: 0.1667 },
  licences: [{ licence: "cc-by", n: 4 }, { licence: "cc-by-nc", n: 2 }],
  datasets: [
    { dataset_id: "00000000-0000-0000-0000-0000000000aa", title: "Synthetic CC-BY dataset",
      citation: "Synthetic citation A", url: "https://example.org/a", licence: "cc-by", n: 4,
      obis_url: "https://obis.org/dataset/00000000-0000-0000-0000-0000000000aa" },
    { dataset_id: "00000000-0000-0000-0000-0000000000ab", title: "Synthetic CC-BY-NC dataset",
      citation: "Synthetic citation B", url: "https://example.org/b", licence: "cc-by-nc", n: 2,
      obis_url: "https://obis.org/dataset/00000000-0000-0000-0000-0000000000ab" },
  ],
  datasets_total: 2,
};
