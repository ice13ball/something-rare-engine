// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * MEMENTO parameter registry.
 *
 * Units are VERBATIM from the MEMENTO portal parameter list
 * (portal.geomar.de/memento). Never infer a unit — note that `o2` is µmol/l,
 * while `o2_kg` is µmol/kg.
 *
 * MEMENTO declares `CH4` as BOTH `Methane_Ocean [nmol/l]` and
 * `Methane_Atmosphere [ppb]`, distinguished by a `parameterType` the CSV export
 * omits. Values that are atmospheric are marked by the backend's
 * platform-derived `ch4_is_atmospheric` / `n2o_is_atmospheric` columns.
 *
 * Several entries are the SAME measurement in different units (ch4, ch4_kg,
 * ch4_nl_l, ch4_ml, ch4_natm). They are listed flat, each with its explicit
 * unit; the panel prints a footnote saying so.
 */
export type MementoSphere = "ocean" | "atmosphere" | "both";

export interface MementoParam {
  key: string;
  label: string;
  unit: string;
  sphere: MementoSphere;
}

export const MEMENTO_PARAM_META: readonly MementoParam[] = [
  // Dissolved gases (first-class table columns)
  { key: "ch4",       label: "Methane",              unit: "nmol/l",   sphere: "both" },
  { key: "n2o",       label: "Nitrous oxide",        unit: "nmol/l",   sphere: "both" },
  { key: "n2o_perc",  label: "N₂O saturation",       unit: "%",        sphere: "ocean" },
  { key: "o2",        label: "Oxygen",               unit: "µmol/l",   sphere: "ocean" },
  { key: "temp",      label: "Temperature",          unit: "°C",       sphere: "ocean" },
  { key: "sal",       label: "Salinity",             unit: "PSU",      sphere: "ocean" },
  // Nutrients
  { key: "no3",       label: "Nitrate",              unit: "µmol/l",   sphere: "ocean" },
  { key: "no2",       label: "Nitrite",              unit: "µmol/l",   sphere: "ocean" },
  { key: "po4",       label: "Phosphate",            unit: "µmol/l",   sphere: "ocean" },
  { key: "sio4",      label: "Silicate",             unit: "µmol/l",   sphere: "ocean" },
  { key: "nh4",       label: "Ammonium",             unit: "µmol L⁻¹", sphere: "ocean" },
  // Ancillary / atmosphere
  { key: "airpress",  label: "Air pressure",         unit: "mbar",     sphere: "atmosphere" },
  { key: "airtemp",   label: "Air temperature",      unit: "°C",       sphere: "atmosphere" },
  { key: "ch4_ppb",   label: "CH₄ (mole fraction)",  unit: "ppb",      sphere: "ocean" },
  { key: "n2o_ppb",   label: "N₂O (mole fraction)",  unit: "ppb",      sphere: "ocean" },
  // Partial pressures
  { key: "ch4_natm",  label: "CH₄ partial pressure", unit: "natm",     sphere: "both" },
  { key: "n2o_natm",  label: "N₂O partial pressure", unit: "natm",     sphere: "both" },
  // Unit variants of the gases above
  { key: "ch4_kg",    label: "Methane",              unit: "nmol/kg",  sphere: "ocean" },
  { key: "ch4_nl_l",  label: "Methane",              unit: "nl/l",     sphere: "ocean" },
  { key: "ch4_ml",    label: "Methane",              unit: "mL L⁻¹",   sphere: "ocean" },
  { key: "n2o_kg",    label: "Nitrous oxide",        unit: "nmol/kg",  sphere: "ocean" },
  { key: "n2o_nl_l",  label: "Nitrous oxide",        unit: "nl/l",     sphere: "ocean" },
  { key: "o2_kg",     label: "Oxygen",               unit: "µmol/kg",  sphere: "ocean" },
  { key: "o2_ml_l-1", label: "Oxygen",               unit: "ml/l",     sphere: "ocean" },
] as const;

/** Keys that already have dedicated table columns / chart series. */
export const MEMENTO_FIRST_CLASS: ReadonlySet<string> = new Set([
  "ch4", "n2o", "n2o_perc", "o2", "temp", "sal",
]);
