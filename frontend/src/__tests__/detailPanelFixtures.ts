// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Fixture data for detail-panel-matrix.test.tsx.
//
// One entry per layer-id string literal PanelContent() dispatches on in
// DetailPanel.tsx. All 76 come from a straight read of that function — see the
// count assertion in the test file, which re-derives the count from the real
// source so a panel added/removed there fails this test instead of silently
// going unchecked.
//
// Property values are synthetic and obviously so (1.23, "TEST", 2020-01-01).
// Where a panel formats a field as a date or divides/toFixed()s it, a real
// parseable value is supplied instead of a string — an unparsable date would
// render "Invalid Date", which is a real DOM difference a refactor could
// silently reintroduce, so it must not appear in the baseline snapshot.

export interface LayerFixture {
  layer: string;
  id: string | number;
  properties: Record<string, unknown>;
}

const DATE = "2020-06-15T00:00:00Z";
const GEOM = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] };

export const LAYER_FIXTURES: LayerFixture[] = [
  {
    layer: "mining-contracts-mvt",
    id: "TEST-ISA-1",
    properties: {
      cell_key: "TEST", depth_m: 4321, location_code: "TESTLOC", max_species: 3,
      mining_zones: ["zone-a"], name: "TEST Contract", network: "TEST Net",
      platform_id: "TEST-P1", profile_id: "TEST-PR1", ref: "TEST-REF",
      risk_index: 0.5, risk_level: "low", surface_temp_c: 1.23,
    },
  },
  {
    layer: "hydrothermal-vents-active",
    id: 1,
    properties: {
      deep_pressure_m: 1234, deep_salinity: 34.5, deep_temp_c: 2.1, oxygen_qc: 1,
      oxygen_umol_kg: 200, ph: 7.9, ph_qc: 1, profile_date: DATE, sal_qc: 1,
      surface_salinity: 35, surface_temp_c: 15, temp_qc: 1,
      woa_deep_aou: 1, woa_deep_nitrate: 1, woa_deep_o2sat: 1, woa_deep_oxygen_umol_kg: 1,
      woa_deep_phosphate: 1, woa_deep_sal: 1, woa_deep_silicate: 1, woa_deep_temp_c: 1,
      woa_surface_sal: 1, woa_surface_temp_c: 1,
    },
  },
  {
    layer: "hydrothermal-vents-inactive",
    id: 2,
    properties: { deep_temp_c: 2.1, profile_date: DATE, surface_temp_c: 15 },
  },
  {
    layer: "argo-floats-3d",
    id: "TEST",
    properties: {
      deep_pressure_m: 1234, deep_salinity: 34.5, deep_temp_c: 2.1, max_depth_m: 2000,
      mining_dist_km: 12.3, mining_zone: "TEST zone", near_mining: true, oxygen_qc: 1,
      oxygen_umol_kg: 200, ph: 7.9, ph_qc: 1, platform_id: "TEST-P1", platform_number: 1234567,
      profile_date: DATE, profile_id: "TEST-PR1", sal_qc: 1, surface_salinity: 35,
      surface_temp_c: 15, temp_qc: 1,
    },
  },
  {
    layer: "argo-trail-dot",
    id: "TEST",
    properties: {
      deep_pressure_m: 1234, deep_salinity: 34.5, deep_temp_c: 2.1, max_depth_m: 2000,
      mining_dist_km: 12.3, mining_zone: "TEST zone", near_mining: true, oxygen_qc: 1,
      oxygen_umol_kg: 200, ph: 7.9, ph_qc: 1, platform_id: "TEST-P1", profile_date: DATE,
      profile_id: "TEST-PR1", sal_qc: 1, surface_salinity: 35, surface_temp_c: 15, temp_qc: 1,
    },
  },
  {
    layer: "seamounts",
    id: "TEST",
    properties: {
      area_km2: 12.3, height_m: 1234, in_2011: true, in_concession: false,
      overlapping_base: "TEST base", peak_id: "TEST-PEAK", summit_depth_m: 1500,
    },
  },
  // biodiversity-hotspots dispatches on properties.total_count at runtime — this
  // fixture deliberately omits it so the individual-record branch (BiodiversityPanel)
  // is what gets exercised; the two grid layer ids below cover the other branch.
  {
    layer: "biodiversity-hotspots",
    id: "TEST",
    properties: {
      aphia_id: 123456, class_name: "TEST class", depth: 1234, description: "TEST desc",
      family: "TEST family", image_url: null, is_endangered: false, obis_id: "TEST-OBIS",
      order_name: "TEST order", phylum: "TEST phylum", scientific_name: "Testus testicus",
      valid_name: "Testus testicus", vernacular_name: "Test creature", worms_is_marine: true,
      worms_url: "https://marinespecies.org/test", worms_verified: true,
    },
  },
  {
    layer: "biodiversity-hotspots-grid-coarse",
    id: "TEST",
    properties: {
      _lat: 1.23, _lon: 4.56, cr_en_count: 2, endangered_count: 5, species_count: 42,
      top_species: ["Testus testicus"], total_count: 100,
    },
  },
  {
    layer: "biodiversity-hotspots-grid-fine",
    id: "TEST",
    properties: {
      _lat: 1.23, _lon: 4.56, cr_en_count: 2, endangered_count: 5, species_count: 42,
      top_species: ["Testus testicus"], total_count: 100,
    },
  },
  {
    layer: "relinquished-areas",
    id: "TEST",
    properties: {
      AreaKM2: 12.3, AreaType: "TEST", ContractID: "TEST-C1", arcgis_id: 1,
      area_km2: 12.3, contractor_name: "TEST Contractor", isa_id: "TEST-ISA-2",
      resource_type: "Polymetallic Nodules",
    },
  },
  {
    layer: "reserved-areas",
    id: "TEST",
    properties: {
      AreaKM2: 12.3, AreaType: "TEST", ContractID: "TEST-C1", STATUS: "Active",
      Status: "Active", arcgis_id: 1, area_km2: 12.3, isa_id: "TEST-ISA-3",
    },
  },
  {
    layer: "apeis",
    id: "TEST",
    properties: {
      AreaKM2: 12.3, Area_km2: 12.3, NAME: "TEST APEI", Remarks: "TEST remark",
      STATUS: "Active", Shape__Area: 12.3, Status: "Active", arcgis_id: 1,
    },
  },
  {
    layer: "eez",
    id: "TEST",
    properties: {
      GEONAME: "TEST Sea", ISO_TER1: "TST", SOVEREIGN1: "Testland", area_km2: 12.3,
      geoname: "TEST Sea", iso_ter1: "TST", sovereign1: "Testland",
    },
  },
  {
    layer: "protected-marine-sites",
    id: "TEST",
    properties: { COUNTRY: "Testland", NAME: "TEST Site", area_km2: 12.3, country: "Testland", name: "TEST Site" },
  },
  {
    layer: "plume-origin",
    id: "TEST",
    properties: {
      contractor_name: "TEST Contractor", origin_lat: 1.23, origin_lon: 4.56,
      platform_id: "TEST-P1", profile_date: DATE, profile_id: "TEST-PR1",
      speed_cms: 1.23, steps_completed: 5,
    },
  },
  {
    layer: "monitoring-density",
    id: "TEST",
    properties: { centroid_lat: 1.23, centroid_lon: 4.56, point_count: 42, source_count: 3 },
  },
  {
    layer: "deepdata-stations",
    id: "TEST",
    properties: {
      archive_citation: "TEST citation", archive_license: "CC-BY 4.0",
      archive_pub_date: DATE, archive_rights_holder: "TEST Holder", archive_slug: "test-archive",
      archive_title: "TEST Archive", contractor_code: "TESTPMN", depth_m_max: 5000,
      depth_m_min: 4000, event_id_raw: "TEST-EVT-1", first_event_date: DATE,
      last_event_date: DATE, location_id: "TEST-LOC", occurrence_count: 42,
      sampling_protocol: "TEST protocol", sediment_horizons: ["0-1cm"], species_count: 7,
      station_id: "TEST-STN", top_phyla: ["TEST phylum"], top_species: ["Testus testicus"],
    },
  },
  {
    layer: "noise-risk",
    id: "TEST",
    properties: {
      cetacean_count: 3, cetacean_norm: 0.5, data_gap: false, max_species: 3,
      pbd_norm: 0.5, spl_norm: null, noise_source: "TEST source", risk_index: 0.5, risk_level: "low",
      species_weight: 0.5,
    },
  },
  {
    layer: "oceansites",
    id: "TEST",
    properties: {
      deploy_date: DATE, latest_obs: {}, name: "TEST Mooring", network: "TEST Net",
      obs_fetched_at: DATE, obs_source: "TEST", ref: "TEST-REF", status: "active",
    },
  },
  {
    layer: "onc",
    id: "TEST",
    properties: {
      depth_m: 1234, latest_sensors: {}, location_code: "TESTLOC", name: "TEST Observatory",
      sensors_fetched_at: DATE,
    },
  },
  {
    layer: "hydrophone-stations",
    id: "TEST",
    properties: {
      deploy_end: DATE, deploy_start: DATE, depth_m: 1234, hz_range_hi: 20000,
      hz_range_lo: 10, license: "CC-BY", model: "TEST model", name: "TEST Hydrophone",
      operator: "TEST Operator", portal_url: "https://example.test", source: "ooi",
      station_id: "TEST-STN",
    },
  },
  {
    layer: "chess",
    id: "TEST",
    properties: {
      depth_m: 1234, habitat_type: "TEST habitat", locality: "TEST Locality",
      phyla: ["TEST phylum"], species_count: 7, species_list: ["Testus testicus"],
    },
  },
  {
    layer: "submarine-cables",
    id: "TEST",
    properties: {
      cable_type: "TEST", inst_year: 2000, length_km: 123.4, location: "TEST",
      name: "TEST Cable", operator: "TEST Operator", source_layer: "pcablesnve",
      status: "active", voltage_kv: 220,
    },
  },
  {
    layer: "onc-cables",
    id: "TEST",
    properties: { comments: "TEST comment", ext_id: "TEST-EXT", length_m: 123400, status: "active" },
  },
  {
    layer: "ooi-cables",
    id: "TEST",
    properties: {
      commissioned: "2015", deepest_node_m: 2900, ext_id: "northern", length_m: 477000,
      line_name: "TEST Line", node_count: 5, operator: "TEST Operator", shallowest_node_m: 80,
    },
  },
  {
    layer: "noaa-cables",
    id: "TEST",
    properties: { cable_system: "TEST System", owner: "TEST Owner", region: "Gulf of America", short_name: "TEST", status: "active" },
  },
  {
    layer: "nz-cables",
    id: "TEST",
    properties: {
      burdep: 1.23, catcbl: "power", condtn: "good", datend: DATE, datsta: DATE,
      fidn: "TEST-FID", inform: "TEST info", objnam: null, status: "operational",
    },
  },
  {
    layer: "au-cables",
    id: "TEST",
    properties: { abbrev: "TST", cable: "TEST Cable" },
  },
  {
    layer: "onc-instruments",
    id: "TEST",
    properties: {
      data_products: [], deployment_end: DATE, deployment_start: DATE, depth_m: 1234,
      description: "TEST instrument", device_category: "Current Meter", device_code: "TEST-DEV",
      device_id: 1, device_link: "https://example.test", device_name: "TEST Device",
      image_url: null, latest_readings: [], location_code: "TESTLOC", location_name: "TEST Location",
      readings_at: DATE, site_name: "TEST Site", status: "active",
    },
  },
  {
    layer: "ports",
    id: "TEST",
    properties: { city: "TEST City", country: "Testland", state: null },
  },
  {
    layer: "tectonic-plates-fill",
    id: "TEST",
    properties: { PlateA: "TEST-A", PlateB: "TEST-B", PlateName: "TEST Plate", Type: "Convergent" },
  },
  {
    layer: "tectonic-plates-boundaries",
    id: "TEST",
    properties: { PlateA: "TEST-A", PlateB: "TEST-B", PlateName: "TEST Plate", Type: "Divergent" },
  },
  {
    layer: "mining-footprints",
    id: "TEST",
    properties: { area_km2: 12.3, country: "Testland", ftype: "open-pit", source: "TEST source" },
  },
  {
    layer: "mining-footprints-mvt",
    id: "TEST",
    properties: { area_km2: 12.3, country: "Testland", ftype: "open-pit", source: "TEST source" },
  },
  {
    layer: "tailings",
    id: "TEST",
    properties: {
      construction_year: 1990, country: "Testland", dam_name: "TEST Dam", data_source: "wapha",
      hazard_raw: "TEST", height_m: 45, latitude: 1.23, longitude: 4.56, mine_name: "TEST Mine",
      operator: "TEST Operator", owner_company: "TEST Owner", raise_type: "upstream",
      risk_class: "low", status: "active", volume_m3: 1234567,
    },
  },
  {
    layer: "fires",
    id: "TEST",
    properties: { acq_date: DATE, brightness: 320.5, confidence: "h", frp: 12.3, instrument: "VIIRS" },
  },
  {
    layer: "air-quality",
    id: "TEST",
    properties: {
      bc: 1.23, ch4: 1.23, city: "TEST City", co: 1.23, co2: 1.23, country: "Testland",
      coverage_pct: 80, datetime_first: DATE, humidity: 55, is_mobile: false, is_monitor: true,
      last_updated: DATE, locality: "TEST Locality", location_id: 1, name: "TEST Station",
      no: 1.23, no2: 1.23, nox: 1.23, o3: 1.23, owner: "TEST Owner", pm1: 1.23, pm10: 1.23,
      pm25: 1.23, pm4: 1.23, provider: "OpenAQ", so2: 1.23, temperature: 15, timezone: "UTC", ufp: 1.23,
      // ⛔ Deliberately MIXED, because OpenAQ's real answers are mixed: on
      // production 2026-09-10 ozone was ppb on 7 stations of 10,282 and µg/m³
      // or ppm on the rest. A fixture with one unit throughout would snapshot a
      // world where the bug could not have happened.
      units: {
        pm25: "µg/m³", pm10: "µg/m³", pm1: "µg/m³", pm4: "µg/m³", bc: "µg/m³",
        no2: "µg/m³", o3: "ppm", co: "ppm", so2: "ppb", no: "µg/m³", nox: "ppb",
        co2: "ppm", ch4: "ppb", ufp: "particles/cm³",
      },
    },
  },
  {
    layer: "landslides",
    id: "TEST",
    properties: {
      country: "Testland", event_date: DATE, event_type: "landslide", fatalities: 0,
      location: "TEST Location", source: "TEST source", trigger: "rain",
    },
  },
  {
    layer: "dams",
    id: "TEST",
    properties: { country: "Testland", dam_name: "TEST Dam", height_m: 45, purpose: "irrigation", river: "TEST River", volume_mcm: 12.3, year_built: 1990 },
  },
  { layer: "surface-water", id: "TEST", properties: {} },
  {
    layer: "water-risk",
    id: "TEST",
    properties: {
      area_km2: 12.3, bwd_score: 1.23, bws_label: "Low", bws_score: 1.23, drr_score: 1.23,
      name_0: "Testland", name_1: "TEST Region", rfr_score: 1.23, w_awr_min_tot_cat: 1,
      w_awr_min_tot_label: "Low", w_awr_min_tot_score: 1.23,
    },
  },
  {
    layer: "water-risk-mvt",
    id: "TEST",
    properties: {
      area_km2: 12.3, bwd_score: 1.23, bws_label: "Low", bws_score: 1.23, drr_score: 1.23,
      name_0: "Testland", name_1: "TEST Region", rfr_score: 1.23, w_awr_min_tot_cat: 1,
      w_awr_min_tot_label: "Low", w_awr_min_tot_score: 1.23,
    },
  },
  {
    layer: "offshore-activities",
    id: "TEST",
    properties: {
      _lat: 1.23, _lon: 4.56, activity_type: "oil_gas", area_km2: 12.3, awarded_date: DATE,
      basin: "TEST Basin", expires_date: DATE, geometry: GEOM, id: "TEST-OA-1",
      licence_holder: "TEST Holder", licence_type: "TEST type", licensing_round: "R1",
      name: "TEST Activity", operator: "TEST Operator", source: "emodnet", source_id: "TEST-SRC-1",
      sovereign: "Testland", status: "active", water_depth_m: 120, water_zone: null,
    },
  },
  {
    layer: "offshore-activities-mvt",
    id: "TEST",
    properties: {
      _lat: 1.23, _lon: 4.56, activity_type: "offshore_wind", area_km2: 12.3, awarded_date: DATE,
      basin: "TEST Basin", expires_date: DATE, geometry: GEOM, id: "TEST-OA-2",
      licence_holder: "TEST Holder", licence_type: "TEST type", licensing_round: "R1",
      name: "TEST Activity 2", operator: "TEST Operator", source: "boem", source_id: "TEST-SRC-2",
      sovereign: "Testland", status: "active", water_depth_m: 120, water_zone: null,
    },
  },
  {
    layer: "offshore-zones-mvt",
    id: "TEST",
    properties: {
      _lat: 1.23, _lon: 4.56, activity_type: "oil_gas", area_km2: 12.3, awarded_date: null,
      basin: "TEST Basin", expires_date: null, geometry: GEOM, id: "TEST-OA-3",
      licence_holder: null, licence_type: null, licensing_round: null,
      name: "TEST Zone", operator: null, source: "anh_co", source_id: "TEST-SRC-3",
      sovereign: "Testland", status: "sin asignar", water_depth_m: null, water_zone: "shelf",
    },
  },
  {
    layer: "vessel-events",
    id: "TEST",
    properties: {
      ais_gap_seconds: 3600, classification: "dark", contractor_name: "TEST Contractor",
      contractor_role: "operator", contractor_short: "TC", coverage_neighbors: 2,
      inside_polygon_id: "TEST-POLY", inside_polygon_name: "TEST Polygon",
      inside_polygon_type: "isa_concession", lat: 1.23, lon: 4.56, matched_mmsi: 123456789,
      s2_thumbnail_url: null, sar_detection_id: "TEST-DET", ts: DATE, vessel_name: "TEST Vessel",
    },
  },
  {
    layer: "ais-live",
    id: "TEST",
    properties: {
      mmsi: 123456789, name: "TEST Vessel", ship_type: 70, flag: "TST", imo: "1234567",
      callsign: "TESTCS", length_m: 100, sog_knots: 12.3, destination: "TEST Port", ts: DATE,
    },
  },
  {
    layer: "vessel-track-point",
    id: "TEST",
    properties: {
      ts: DATE, lat: 1.23, lon: 4.56, sog_knots: 12.3, cog_deg: 90, heading_deg: 91,
      destination: "TEST Port", vessel_name: "TEST Vessel", mmsi: 123456789,
    },
  },
  {
    layer: "sios-svalbard",
    id: "TEST",
    properties: {
      abstract: "TEST abstract", activity_type: "In Situ Land-based station", institution: "TEST Institution",
      iso_topic: "oceans", keywords: ["test"], license: "CC-BY 4.0", license_url: "https://example.test",
      pi_name: "Test PI", platform_long: "TEST Platform", platform_url: "https://example.test",
      series: ["TEST series"], series_long_name: "TEST series long", series_units: "m",
      series_var: "depth", time_end: DATE, time_start: DATE, title: "TEST Dataset",
      url_http: "https://example.test", url_landing: "https://example.test",
      url_opendap: "https://example.test", url_wms: "https://example.test",
    },
  },
  {
    layer: "methane-seeps",
    id: "TEST",
    properties: {
      depth_m: 1234, feature_types: ["gas_bubbles"], loc_uncert_m: 100, obs_year: 2015,
      pockmark_depth_m: 5, pockmark_radius_m: 50, source_ref: "TEST ref", source_url: "https://example.test",
      type_raw: { gas_bubbles: "Y" },
    },
  },
  {
    // Bulk-only shape (2026-09-08 split): authors/data_source_type/source_doi/
    // imagery moved to GET .../permafrost-thaw/by-id/{unique_id} — see
    // PERMAFROST_THAW_DETAIL in detailPanelFetchFixtures.ts for those.
    layer: "permafrost-thaw",
    id: "TEST",
    properties: {
      unique_id: "TEST-UID-1", feature_category: "thermokarst lake",
      feature_name: "TEST Feature", feature_type: "lake",
      source: "alaska_webb", thaw_type: "non-abrupt",
    },
  },
  {
    layer: "arctic-rivers",
    id: "TEST",
    properties: {
      annual_fluxes: null, biogeochem_monthly: [], citation: "TEST citation", discharge_monthly: [],
      lat: 1.23, lon: 4.56, record_end: DATE, record_start: DATE, river_name: "TEST River",
      site_label: "TEST Site", source: "arcticgro", summary_stats: {}, units: {},
    },
  },
  { layer: "wod-oxygen", id: "TEST-WOD-1", properties: {} },
  { layer: "memento", id: "TEST-MEMENTO-1", properties: {} },
  {
    layer: "memento-hexes",
    id: "TEST",
    properties: {
      count: 42, _lat: 1.23, _lon: 4.56,
      year_min: 1971, year_max: 2016, n_undated: 0,
      by_decade: { "1970": 5, "1980": 8, "1990": 10, "2000": 12, "2010": 7 },
    },
  },
  { layer: "geotraces", id: "TEST-GEOTRACES-1", properties: {} },
  {
    layer: "geotraces-hexes",
    id: "TEST",
    properties: {
      count: 42, _lat: 1.23, _lon: 4.56,
      year_min: 2005, year_max: 2023, n_undated: 0,
      by_decade: { "2000": 10, "2010": 22, "2020": 10 },
    },
  },
  { layer: "mosaic-sediment", id: "TEST-MOSAIC-1", properties: { core_id: "TEST-MOSAIC-1" } },
  {
    layer: "mosaic-hexes",
    id: "TEST",
    properties: {
      count: 42, _lat: 1.23, _lon: 4.56,
      year_min: 1990, year_max: 2010, n_undated: 3,
      by_decade: { "1990": 20, "2000": 19 },
    },
  },
  {
    layer: "arctic-catchments",
    id: "TEST",
    properties: {
      gid: 1, etot_mean: 1.23, iwp_frac: 0.1, ndvi_mean: 0.5, pf_classes: { cont: 0.5 },
      ptot_mean: 1.23, soc_depth: [1, 2, 3, 4, 5, 6], t_2m_max: 280, t_2m_min: 260,
    },
  },
  {
    layer: "woa-climatology",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56, depth: 100 },
  },
  {
    layer: "oxygen-deox",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56, depth: 100 },
  },
  {
    layer: "ocean-carbon",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56, depth: 100 },
  },
  {
    layer: "marine-carbon",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56, depth: 100 },
  },
  {
    layer: "vme-suitability",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56 },
  },
  {
    layer: "ocean-acidification",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56, depth: 100 },
  },
  {
    layer: "cumulative-human-impact",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56 },
  },
  {
    layer: "coral-acid-exposure",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56 },
  },
  {
    layer: "ocean-co2-surface",
    id: "TEST",
    properties: { _lat: 1.23, _lon: 4.56, decade: 5 },
  },
  {
    layer: "seabed-substrate",
    id: "TEST",
    properties: { class_code: 1, class_key: "silt", lat: 1.23, lon: 4.56 },
  },
  {
    layer: "arctic-sediment-carbon-stations",
    id: "TEST",
    properties: {
      d13c: -25.5, d14c: -100, expedition: "TEST Expedition", hmw_acids: 1.23, hmw_alkanes: 1.23,
      lignin: 1.23, oc_pct: 1.23, oc_tn: 12.3, station: "TEST Station", station_id: "TEST-STN",
      tn_pct: 0.5, water_depth_m: 100, year: 2005,
    },
  },
  {
    layer: "arctic-sediment-carbon",
    id: "TEST",
    properties: { unit: "%", value: 1.23, variable: "oc" },
  },
];

// A changed count means a panel branch was added or removed in PanelContent()
// — see detail-panel-matrix.test.tsx, which re-derives the real count from the
// source and fails loudly rather than silently under-covering the dispatcher.
// 74 -> 72 on 2026-09-03: the KBA withdrawal removed one branch carrying two
// literals (`layer === "kbas" || layer === "kbas-mvt"`), so the count drops
// by two for one layer. A drop of one here would mean something else was lost.
export const EXPECTED_LAYER_COUNT = 72;
