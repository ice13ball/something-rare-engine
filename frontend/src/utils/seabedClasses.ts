// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/seabedClasses.ts
// Single source of truth for seabed-substrate colours — MUST match backend CPT_RGB.
// Dutkiewicz et al. 2015 official CPT palette.
export interface SeabedClass { key: string; name: string; rgb: [number, number, number]; }

export const SEABED_CLASSES: Record<number, SeabedClass> = {
  1:  { key: "gravel",            name: "Gravel and coarser",               rgb: [128,130,132] },
  2:  { key: "sand",              name: "Sand",                             rgb: [255,241,0]   },
  3:  { key: "silt",              name: "Silt",                             rgb: [250,169,25]  },
  4:  { key: "clay",              name: "Clay",                             rgb: [112,75,42]   },
  5:  { key: "calcareous_ooze",   name: "Calcareous ooze",                  rgb: [14,145,207]  },
  6:  { key: "radiolarian_ooze",  name: "Radiolarian ooze",                 rgb: [13,150,71]   },
  7:  { key: "diatom_ooze",       name: "Diatom ooze",                      rgb: [190,215,83]  },
  8:  { key: "sponge_spicules",   name: "Sponge spicules",                  rgb: [85,147,141]  },
  9:  { key: "mixed_ooze",        name: "Mixed calcareous/siliceous ooze",  rgb: [131,112,178] },
  10: { key: "shells_coral",      name: "Shells and coral fragments",       rgb: [247,187,213] },
  11: { key: "ash_volcanic",      name: "Ash and volcanic sand/gravel",     rgb: [234,27,27]   },
  12: { key: "siliceous_mud",     name: "Siliceous mud",                    rgb: [195,154,107] },
  13: { key: "fine_calcareous",   name: "Fine-grained calcareous sediment", rgb: [0,46,167]    },
};

export const SEABED_FILL_ALPHA = 180;
export function seabedColor(code: number | null | undefined): [number, number, number, number] {
  const c = code != null ? SEABED_CLASSES[code] : undefined;
  return c ? [c.rgb[0], c.rgb[1], c.rgb[2], SEABED_FILL_ALPHA] : [0, 0, 0, 0];
}
