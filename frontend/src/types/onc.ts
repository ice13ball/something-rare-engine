// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export type OncEov =
  | "currents"
  | "ocean-sound"
  | "oxygen"
  | "particulate-matter"
  | "chemistry"
  | "biology";

// ⚠️ TWO NAMING FORMS ARRIVE HERE, from two independent backend sources — see
// rules/layers/onc-observatory.md and backend/domains/onc.py::get_onc().
//   - LONG human names (e.g. "Conductivity Temperature Depth") come from the
//     ArcGIS `ONC_Instruments` WFS feed via the `onc_instruments` table —
//     this is the original, small set of ~20 curated categories.
//   - SHORT API codes (e.g. "CTD", "FLUOROMETER") come from the Oceans 3.0
//     `deviceCategoryCode` used by `onc_ingest.py` / `onc_location_categories`
//     — this is the full 129-category breadth measured 2026-09-08
//     (docs/audits/2026-09-08-geotraces-onc-pelne-pobranie.md). Verified via
//     `get_onc()`'s SQL, which now unions both sources into one
//     `device_categories` array per location — so BOTH forms can appear side
//     by side on the same feature. Both forms must be listed for a bucket to
//     actually catch every location, not just the legacy-instrument ones.
export const ONC_EOV_CATEGORIES: Record<OncEov, string[]> = {
  "currents": [
    "Acoustic Doppler Current Profiler 150 kHz",
    "Acoustic Doppler Current Profiler 2 MHz",
    "Acoustic Doppler Current Profiler 300 kHz",
    "Acoustic Doppler Current Profiler 400 kHz",
    "Acoustic Doppler Current Profiler 55 kHz",
    "Acoustic Doppler Current Profiler 600 kHz",
    "Acoustic Doppler Current Profiler 75 kHz",
    "Current Meter",
    "ADCP1200KHZ", "ADCP2MHZ", "ADCP300KHZ", "ADCP400KHZ", "ADCP55KHZ",
    "ADCP600KHZ", "ADCP75KHZ", "CURRENTMETER",
  ],
  "ocean-sound": [
    "Hydrophone",
    "Acoustic Receiver",
    "Echosounder, Bioacoustic",
    "HYDROPHONE", "ACOUSTICRECEIVER", "HYDROPHONEARRAY",
  ],
  "oxygen": [
    "Oxygen Sensor",
    "Conductivity Temperature Depth",
    "Integrated CTD pH O2 Instrument",
    "CTD", "OXYSENSOR",
  ],
  "particulate-matter": [
    "Fluorometer",
    "Fluorometer Turbidity",
    "Turbidity Meter",
    "Coloured Dissolved Organic Matter",
    "FLUOROMETER", "CDOM", "TURBIDITYMETER", "TURBCHLFL",
    "CRUDEOILFLUOROMETER", "REFINEDFUELSFLUOROMETER",
    "TRANSMISSOMETER", "PARTANALYZER",
  ],
  "chemistry": [
    "PHSENSOR", "CO2SENSOR", "NITRATESENSOR", "METHSENSOR",
    "CHEMINI", "GTD", "UCRDS", "UURS", "UWVOLTAMMETRICSYSTEM",
  ],
  "biology": [
    "SEDTRAP", "PLANKTONSAMPLER", "WATERSAMPLER", "WETLABS_WQM",
    "BIOSPECTROMETER", "MBIOSENSOR", "PLANKTONCAMSYSTEM", "BARS", "BBES",
  ],
};

export const ONC_EOV_LABELS: Record<OncEov, string> = {
  "currents":           "Currents",
  "ocean-sound":        "Ocean sound",
  "oxygen":             "Oxygen",
  "particulate-matter": "Particulate matter",
  "chemistry":          "Chemistry",
  "biology":            "Biology & sampling",
};

export const ONC_EOV_ORDER: OncEov[] = [
  "currents",
  "ocean-sound",
  "oxygen",
  "particulate-matter",
  "chemistry",
  "biology",
];

/** Every category string ONC_EOV_CATEGORIES knows about, across all buckets —
 *  used to distinguish "known category not in the active filter" (hide) from
 *  "category we haven't catalogued yet" (never silently hide, see filters.ts). */
export const ONC_ALL_KNOWN_CATEGORIES: Set<string> = new Set(
  Object.values(ONC_EOV_CATEGORIES).flat()
);
