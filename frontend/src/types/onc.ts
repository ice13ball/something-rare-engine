// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export type OncEov = "currents" | "ocean-sound" | "oxygen" | "particulate-matter";

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
  ],
  "ocean-sound": [
    "Hydrophone",
    "Acoustic Receiver",
    "Echosounder, Bioacoustic",
  ],
  "oxygen": [
    "Oxygen Sensor",
    "Conductivity Temperature Depth",
    "Integrated CTD pH O2 Instrument",
  ],
  "particulate-matter": [
    "Fluorometer",
    "Fluorometer Turbidity",
    "Turbidity Meter",
    "Coloured Dissolved Organic Matter",
  ],
};

export const ONC_EOV_LABELS: Record<OncEov, string> = {
  "currents":           "Currents",
  "ocean-sound":        "Ocean sound",
  "oxygen":             "Oxygen",
  "particulate-matter": "Particulate matter",
};

export const ONC_EOV_ORDER: OncEov[] = [
  "currents",
  "ocean-sound",
  "oxygen",
  "particulate-matter",
];
