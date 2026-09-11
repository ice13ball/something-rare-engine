// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * The OceanSITES visibility rule — ONE definition, two call sites.
 *
 * ⛔ It lives here, outside Map3D, for two reasons. First, the features deck.gl
 * draws and the features `flyConfigs` cycles through must obey the SAME rule:
 * when those drifted apart on this layer, the zoom button landed on stations the
 * map was not drawing. Second, a rule written inline in a 4,900-line component
 * can only be guarded by grepping its source — and a grep is satisfied by a
 * dependency array that merely mentions the filter it no longer applies. That
 * happened while writing this: deleting the status check left the guard green.
 * A pure function can be CALLED, so the guard tests behaviour instead.
 *
 * Both Sets follow the convention used by every filter in this app: an empty Set
 * means "no filtering", not "hide everything".
 */
export interface OceansitesProps {
  network?: string | null;
  status?: string | null;
}

export function oceansitesPasses(
  props: OceansitesProps | null | undefined,
  networkFilters: Set<string>,
  statusFilters: Set<string>,
): boolean {
  const p = props ?? {};
  if (networkFilters.size > 0 && !networkFilters.has(p.network ?? "")) return false;
  if (statusFilters.size > 0 && !statusFilters.has(p.status ?? "")) return false;
  return true;
}
